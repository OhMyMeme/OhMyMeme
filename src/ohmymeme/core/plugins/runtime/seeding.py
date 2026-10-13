# pyright: basic

"""插件状态与安装事务：官方与第三方包共用校验、暂存与原子切换。"""

import hashlib
import json
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from ohmymeme.core.plugins.manifest import (
    CANONICAL_BY_ID,
    CANONICAL_PROVIDERS,
    PLUGIN_API_VERSION,
)

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


# 计算包目录内容指纹（跳过缓存文件）
def tree_fingerprint(root):
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


# 校验并归一化最小 meta：id/version/entry 必填，官方 ID 追加身份契约
def _validate_meta(meta):
    plugin_id = meta.get("id")
    version = meta.get("version")
    entry = meta.get("entry")
    if not isinstance(plugin_id, str) or not plugin_id:
        raise PluginSeedError("invalid_plugin_id", str(plugin_id))
    if not _valid_version(version):
        raise PluginSeedError("invalid_version", str(version))
    if not isinstance(entry, str) or ":" not in entry:
        raise PluginSeedError("invalid_entry", str(entry))
    result = {
        "id": plugin_id,
        "name": str(meta.get("name") or plugin_id),
        "version": version,
        "entry": entry,
    }
    if plugin_id in OFFICIAL_IDS:
        _, package_root, capabilities = CANONICAL_BY_ID[plugin_id]
        mismatches = []
        if entry != "%s:create_plugin" % package_root:
            mismatches.append("entry")
        if "api_version" in meta and (
            type(meta.get("api_version")) is not int
            or meta.get("api_version") != PLUGIN_API_VERSION
        ):
            mismatches.append("api_version")
        if "package_root" in meta and meta.get("package_root") != package_root:
            mismatches.append("package_root")
        if "capabilities" in meta and list(meta.get("capabilities") or ()) != list(
            capabilities
        ):
            mismatches.append("capabilities")
        if mismatches:
            raise PluginSeedError(
                "official_identity_mismatch",
                "%s: %s" % (plugin_id, ", ".join(mismatches)),
            )
        result["kind"] = _kind_for(plugin_id)
        result["package_root"] = package_root
        result["capabilities"] = list(capabilities)
    elif "api_version" in meta and meta.get("api_version") != PLUGIN_API_VERSION:
        raise PluginSeedError("invalid_api_version", str(meta.get("api_version")))
    return result


# 把暂存目录原子切换为版本目录并写入状态记录
def _commit_version(data_dir, meta, temp_dir, version_key, source=None):
    plugin_id = meta["id"]
    state = read_state(data_dir)
    entries = dict(state.get("plugins") or {})
    record = dict(entries.get(plugin_id) or {})
    if record.get("origin") == "bundled":
        raise PluginSeedError("official_plugin", plugin_id)
    _write_plugin_meta(temp_dir, meta)
    root = plugins_dir(data_dir) / plugin_id
    root.mkdir(parents=True, exist_ok=True)
    target = root / version_key
    shutil.rmtree(target, ignore_errors=True)
    os.replace(temp_dir, target)
    versions = dict(record.get("versions") or {})
    version_record = {
        "version": meta["version"],
        "entry": meta["entry"],
        "origin": "installed",
        "name": meta["name"],
    }
    if plugin_id in OFFICIAL_IDS:
        version_record["kind"] = meta["kind"]
        version_record["package_root"] = meta["package_root"]
        version_record["capabilities"] = list(meta["capabilities"])
    if source is not None:
        version_record["source"] = source
    versions[version_key] = version_record
    record.update({"origin": "installed", "active": version_key, "versions": versions})
    entries[plugin_id] = record
    write_state(data_dir, {"schema_version": STATE_SCHEMA_VERSION, "plugins": entries})
    return resolve_plugin(data_dir, plugin_id)


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


# 安装或更新插件 ZIP 包，返回解析后的版本信息
def install_plugin(data_dir, archive_path):
    archive = Path(archive_path)
    try:
        zip_file = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as error:
        raise PluginSeedError("invalid_package", str(error)) from error
    with zip_file:
        meta = _validate_meta(_read_plugin_meta(zip_file))
        version = meta["version"]
        root = plugins_dir(data_dir) / meta["id"]
        temp_dir = root / (version + ".tmp")
        shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)
        try:
            zip_file.extractall(temp_dir)
        except (OSError, zipfile.BadZipFile) as error:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise PluginSeedError("invalid_package", str(error)) from error
        try:
            return _commit_version(data_dir, meta, temp_dir, version)
        except BaseException:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise


# 用 populate 回调填充暂存目录并提交为指定版本
def install_prepared(data_dir, meta, populate, version_key, source=None):
    normalized = _validate_meta(meta)
    if not _valid_version(version_key):
        raise PluginSeedError("invalid_version", str(version_key))
    root = plugins_dir(data_dir) / normalized["id"]
    temp_dir = root / (version_key + ".tmp")
    shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        populate(temp_dir)
        return _commit_version(
            data_dir, normalized, temp_dir, version_key, source=source
        )
    except BaseException:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


# 清理旧版平铺种子记录与其目录，返回被清理的插件 ID
def purge_legacy_bundled(data_dir):
    state = read_state(data_dir)
    entries = dict(state.get("plugins") or {})
    purged = [
        plugin_id
        for plugin_id, record in entries.items()
        if isinstance(record, dict) and record.get("origin") == "bundled"
    ]
    if not purged:
        return []
    for plugin_id in purged:
        entries.pop(plugin_id, None)
        shutil.rmtree(plugins_dir(data_dir) / plugin_id, ignore_errors=True)
    write_state(data_dir, {"schema_version": STATE_SCHEMA_VERSION, "plugins": entries})
    logger.info("purged legacy bundled plugins: %s", ", ".join(purged))
    return purged


# 卸载插件并移除其目录
def uninstall_plugin(data_dir, plugin_id):
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
