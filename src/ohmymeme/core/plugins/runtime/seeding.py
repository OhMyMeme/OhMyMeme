# pyright: basic

"""官方插件种子：把随包分发的九个包复制到用户插件目录。"""

import hashlib
import importlib.util
import json
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from ohmymeme import __version__
from ohmymeme.core.plugins.manifest import CANONICAL_PROVIDERS

logger = logging.getLogger(__name__)

STATE_SCHEMA_VERSION = 1
STATE_FILENAME = "installed.json"
PLUGIN_META_FILENAME = "plugin.json"
_SKIP_PARTS = {"__pycache__"}
_SKIP_SUFFIXES = {".pyc", ".pyo"}
OFFICIAL_IDS = frozenset(provider for provider, _, _ in CANONICAL_PROVIDERS)


class PluginSeedError(RuntimeError):
    def __init__(self, reason, message=""):
        text = "%s: %s" % (reason, message) if message else reason
        super().__init__(text)
        self.reason = reason


# 用户插件根目录
def plugins_dir(data_dir):
    return Path(data_dir) / "plugins"


# 读取插件状态；缺失或损坏时返回空状态
def read_state(data_dir):
    path = plugins_dir(data_dir) / STATE_FILENAME
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": STATE_SCHEMA_VERSION, "plugins": {}}
    if not isinstance(value, dict) or not isinstance(value.get("plugins"), dict):
        return {"schema_version": STATE_SCHEMA_VERSION, "plugins": {}}
    return value


# 原子写入插件状态并回读
def write_state(data_dir, state):
    root = plugins_dir(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / STATE_FILENAME
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", delete=False, dir=str(root)
    )
    temp_path = handle.name
    try:
        with handle:
            json.dump(
                state,
                handle,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return json.loads(path.read_text(encoding="utf-8"))


# 仓库内官方插件源码根（源码运行时）
def _repo_plugins_root():
    import ohmymeme

    return Path(ohmymeme.__file__).resolve().parents[2] / "plugins"


# 定位官方包目录：源码优先仓库路径，冻结包用已收集模块
def _locate_package(provider_id, package_root):
    if not getattr(sys, "frozen", False):
        candidate = _repo_plugins_root() / provider_id / "src" / package_root
        if candidate.is_dir():
            return candidate
    try:
        spec = importlib.util.find_spec(package_root)
    except (ImportError, ValueError):
        return None
    locations = getattr(spec, "submodule_search_locations", None)
    if locations:
        candidate = Path(next(iter(locations)))
        if candidate.is_dir():
            return candidate
    return None


# 计算包目录内容指纹（跳过缓存文件）
def _tree_fingerprint(root):
    digest = hashlib.sha256()
    for file in sorted(root.rglob("*")):
        if not file.is_file() or file.suffix in _SKIP_SUFFIXES:
            continue
        relative = file.relative_to(root)
        if any(part in _SKIP_PARTS for part in relative.parts):
            continue
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\x00")
        digest.update(file.read_bytes())
    return digest.hexdigest()[:16]


# 复制包目录到目标版本目录
def _copy_tree(source, target):
    shutil.copytree(
        source,
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )


# 由 provider ID 前缀得到插件种类
def _kind_for(provider_id):
    return provider_id.split(".", 1)[0]


# 写入版本目录内的插件元数据
def _write_plugin_meta(version_dir, meta):
    path = version_dir / PLUGIN_META_FILENAME
    path.write_text(
        json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


# 只保留当前版本与最近一个旧版本
def _prune_versions(root, active):
    versions = [path for path in root.iterdir() if path.is_dir()]
    others = sorted(
        (path for path in versions if path.name != active),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale in others[1:]:
        shutil.rmtree(stale, ignore_errors=True)


# 把官方九包种子到用户插件目录，返回最新状态
def seed_official_plugins(data_dir, locate=None):
    locate = locate or _locate_package
    state = read_state(data_dir)
    entries = dict(state.get("plugins") or {})
    for provider_id, package_root, capabilities in CANONICAL_PROVIDERS:
        source = locate(provider_id, package_root)
        if source is None:
            logger.warning("official plugin package missing: %s", provider_id)
            continue
        fingerprint = _tree_fingerprint(source)
        root = plugins_dir(data_dir) / provider_id
        version_dir = root / fingerprint
        if not version_dir.is_dir():
            temp_dir = root / (fingerprint + ".tmp")
            shutil.rmtree(temp_dir, ignore_errors=True)
            temp_dir.parent.mkdir(parents=True, exist_ok=True)
            _copy_tree(source, temp_dir)
            _write_plugin_meta(
                temp_dir,
                {
                    "id": provider_id,
                    "origin": "bundled",
                    "package_root": package_root,
                    "version": __version__,
                    "entry": "%s:create_plugin" % package_root,
                    "kind": _kind_for(provider_id),
                    "capabilities": list(capabilities),
                },
            )
            shutil.rmtree(version_dir, ignore_errors=True)
            os.replace(temp_dir, version_dir)
            _prune_versions(root, fingerprint)
        record = dict(entries.get(provider_id) or {})
        versions = dict(record.get("versions") or {})
        versions[fingerprint] = {
            "version": __version__,
            "entry": "%s:create_plugin" % package_root,
            "kind": _kind_for(provider_id),
            "package_root": package_root,
            "capabilities": list(capabilities),
            "origin": "bundled",
        }
        record.update(
            {"origin": "bundled", "active": fingerprint, "versions": versions}
        )
        entries[provider_id] = record
    return write_state(
        data_dir, {"schema_version": STATE_SCHEMA_VERSION, "plugins": entries}
    )


# 解析一个插件的活动版本信息
def resolve_plugin(data_dir, plugin_id):
    state = read_state(data_dir)
    record = (state.get("plugins") or {}).get(plugin_id)
    if not isinstance(record, dict):
        raise PluginSeedError("plugin_missing", str(plugin_id))
    active = record.get("active")
    version = (record.get("versions") or {}).get(active)
    if not isinstance(version, dict):
        raise PluginSeedError("plugin_missing", str(plugin_id))
    package_dir = plugins_dir(data_dir) / plugin_id / str(active)
    if not package_dir.is_dir():
        raise PluginSeedError("plugin_storage_missing", str(plugin_id))
    return {
        "id": plugin_id,
        "origin": record.get("origin", "installed"),
        "version": version.get("version", ""),
        "active": active,
        "entry": version.get("entry", ""),
        "kind": version.get("kind", _kind_for(plugin_id)),
        "package_root": version.get("package_root", ""),
        "capabilities": tuple(version.get("capabilities") or ()),
        "package_dir": str(package_dir),
    }


# 读取并解析包内 plugin.json
def _read_plugin_meta(zip_file):
    try:
        raw = zip_file.read(PLUGIN_META_FILENAME)
    except KeyError as error:
        raise PluginSeedError("invalid_package", "missing plugin.json") from error
    try:
        meta = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PluginSeedError("invalid_package", "invalid plugin.json") from error
    if not isinstance(meta, dict):
        raise PluginSeedError("invalid_package", "plugin.json must be an object")
    return meta


# version 直接作为目录名，仅拒绝路径语义
def _valid_version(version):
    return (
        isinstance(version, str)
        and bool(version)
        and version not in (".", "..")
        and "/" not in version
        and "\\" not in version
        and not version.startswith(".")
    )


# 校验并归一化最小 meta：id/version/entry 必填，name 可选
def _validate_meta(meta):
    plugin_id = meta.get("id")
    version = meta.get("version")
    entry = meta.get("entry")
    # 官方 ID 是分发身份，第三方不得占用（正确性约束，非安全校验）
    if not isinstance(plugin_id, str) or not plugin_id or plugin_id in OFFICIAL_IDS:
        raise PluginSeedError("invalid_plugin_id", str(plugin_id))
    if not _valid_version(version):
        raise PluginSeedError("invalid_version", str(version))
    if not isinstance(entry, str) or ":" not in entry:
        raise PluginSeedError("invalid_entry", str(entry))
    return {
        "id": plugin_id,
        "name": str(meta.get("name") or plugin_id),
        "version": version,
        "entry": entry,
    }


# 安装或更新第三方 ZIP 包，返回解析后的版本信息
def install_plugin(data_dir, archive_path):
    archive = Path(archive_path)
    try:
        zip_file = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as error:
        raise PluginSeedError("invalid_package", str(error)) from error
    with zip_file:
        meta = _validate_meta(_read_plugin_meta(zip_file))
        plugin_id = meta["id"]
        version = meta["version"]
        root = plugins_dir(data_dir) / plugin_id
        target = root / version
        temp_dir = root / (version + ".tmp")
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            zip_file.extractall(temp_dir)
        except (OSError, zipfile.BadZipFile) as error:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise PluginSeedError("invalid_package", str(error)) from error
        (temp_dir / PLUGIN_META_FILENAME).write_text(
            json.dumps(meta, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        shutil.rmtree(target, ignore_errors=True)
        os.replace(temp_dir, target)
    state = read_state(data_dir)
    entries = dict(state.get("plugins") or {})
    record = dict(entries.get(plugin_id) or {})
    if record.get("origin") == "bundled":
        raise PluginSeedError("official_plugin", plugin_id)
    versions = dict(record.get("versions") or {})
    versions[version] = {
        "version": version,
        "entry": meta["entry"],
        "origin": "installed",
        "name": meta["name"],
    }
    record.update({"origin": "installed", "active": version, "versions": versions})
    entries[plugin_id] = record
    write_state(data_dir, {"schema_version": STATE_SCHEMA_VERSION, "plugins": entries})
    return resolve_plugin(data_dir, plugin_id)


# 卸载第三方插件并移除其目录
def uninstall_plugin(data_dir, plugin_id):
    if plugin_id in OFFICIAL_IDS:
        raise PluginSeedError("official_plugin", str(plugin_id))
    state = read_state(data_dir)
    entries = dict(state.get("plugins") or {})
    record = entries.pop(plugin_id, None)
    if not isinstance(record, dict):
        raise PluginSeedError("plugin_missing", str(plugin_id))
    shutil.rmtree(plugins_dir(data_dir) / plugin_id, ignore_errors=True)
    write_state(data_dir, {"schema_version": STATE_SCHEMA_VERSION, "plugins": entries})
    return True


# 切换活动版本（回滚/前进）；版本必须已安装
def activate_version(data_dir, plugin_id, version):
    if not _valid_version(version):
        raise PluginSeedError("invalid_version", str(version))
    state = read_state(data_dir)
    entries = dict(state.get("plugins") or {})
    record = dict(entries.get(plugin_id) or {})
    versions = dict(record.get("versions") or {})
    if version not in versions:
        raise PluginSeedError("plugin_missing", str(version))
    if not (plugins_dir(data_dir) / plugin_id / version).is_dir():
        raise PluginSeedError("plugin_storage_missing", str(version))
    record["active"] = version
    entries[plugin_id] = record
    write_state(data_dir, {"schema_version": STATE_SCHEMA_VERSION, "plugins": entries})
    return resolve_plugin(data_dir, plugin_id)


# 返回状态中全部非官方插件条目
def installed_plugins(data_dir):
    state = read_state(data_dir)
    rows = []
    for plugin_id, record in (state.get("plugins") or {}).items():
        if plugin_id in OFFICIAL_IDS or not isinstance(record, dict):
            continue
        active = record.get("active")
        versions = dict(record.get("versions") or {})
        version = versions.get(active) or {}
        rows.append(
            {
                "id": plugin_id,
                "name": version.get("name") or plugin_id,
                "kind": version.get("kind", plugin_id.split(".", 1)[0]),
                "origin": "installed",
                "version": version.get("version", ""),
                "versions": sorted(versions.keys()),
            }
        )
    return rows
