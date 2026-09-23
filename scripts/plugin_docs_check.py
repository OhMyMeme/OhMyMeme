# pyright: basic

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT_GROUP = "ohmymeme.plugins.v1"
PROVIDERS = (
    ("source.qqnt", "ohmymeme_plugin_qqnt:create_plugin"),
    ("source.telegram", "ohmymeme_plugin_telegram:create_plugin"),
    ("source.douyin", "ohmymeme_plugin_douyin:create_plugin"),
    ("source.wechat", "ohmymeme_plugin_wechat:create_plugin"),
    ("sync.ftp", "ohmymeme_plugin_sync_ftp:create_plugin"),
    ("sync.s3", "ohmymeme_plugin_sync_s3:create_plugin"),
    ("sync.r2", "ohmymeme_plugin_sync_r2:create_plugin"),
    ("sync.webdav", "ohmymeme_plugin_sync_webdav:create_plugin"),
    ("transport.lan", "ohmymeme_plugin_lan:create_plugin"),
)
DOCUMENT_NAMES = ("README.md", "AGENTS.md", "project-structure.md")
INVENTORY_INPUTS = (
    "README.md",
    "fixtures/plugin-parity/baseline.json",
    "docs/plugin-provider-matrix.json",
)
DOCUMENT_FACTS = (
    ("canonical manifest", "唯一的 canonical 清单"),
    ("provider creation", "零参数 `create_plugin()` 每次都返回独立状态实例"),
    (
        "host boundary",
        "宿主拥有 SQLite、缓存、manifest、Config、UI、原生能力与 LAN 安全边界",
    ),
    (
        "config and storage boundary",
        "插件仅接收窄配置、限域密钥和 operation 临时目录，"
        "不接收持久 Config、缓存或存储路径",
    ),
    ("lifecycle", "OperationCoordinator 管理 provider 的启动、取消和资源回收"),
    (
        "source/frozen staging scope",
        "source/frozen staging 一致性只覆盖源码、入口元数据与 staging",
    ),
    ("license mapping", "docs/plugin-license-matrix.json"),
    (
        "parity variance",
        "九个 provider 的 parity 基线只允许 ids、timestamps、"
        "temporary paths、thread ordering 差异",
    ),
    (
        "external helper release scope",
        "外部下载的微信 helper 及其 CMake/OpenSSL 输入不随制品交付",
    ),
    (
        "external helper reproducibility scope",
        "不构成外部 helper EXE 的来源到二进制可复现性证明",
    ),
    (
        "unsupported extension features",
        "不提供 marketplace 或不受信任插件沙箱",
    ),
    (
        "plugin ui injections",
        "声明式 UI 注入白名单",
    ),
)
UNSUPPORTED_EXTENSION_FEATURES = (
    "marketplace",
    "不受信任插件沙箱",
)
AFFIRMATIVE_EXTENSION_CLAIM = re.compile(r"(?<!不)(?:提供|支持|允许|开放)")
FIXED_PATHS = (
    "config/plugin-manifest.json",
    "scripts/plugin_packaging.py",
    "scripts/plugin_docs_check.py",
    "docs/plugin-license-matrix.json",
)
FIXED_LINKS = {
    "README.md": "[`docs/project-structure.md`](docs/project-structure.md)",
    "AGENTS.md": "[`docs/project-structure.md`](docs/project-structure.md)",
}


# 拒绝重复 JSON 键，避免后续字段悄悄覆盖前值。
def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


# 读取固定的 JSON 证据文件。
def _load_json(path):
    value = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates
    )
    if not isinstance(value, dict):
        raise ValueError(f"inventory: expected object in {path}")
    return value


# 计算实际读取文件的 SHA-256。
def _sha256(path):
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
    elif path.is_dir():
        children = sorted(
            child
            for child in path.rglob("*")
            if child.is_file()
            and "__pycache__" not in child.parts
            and child.suffix != ".pyc"
        )
        for child in children:
            digest.update(child.relative_to(path).as_posix().encode("utf-8"))
            digest.update(child.read_bytes())
    else:
        raise ValueError(f"hash input does not exist: {path}")
    return digest.hexdigest()


# 将路径稳定地显示为工作树相对路径。
def _display_path(path):
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


# 校验 Todo1 清单的固定 provider 身份和新鲜输入哈希。
def _validate_inventory(path):
    value = _load_json(path)
    errors = []
    expected_ids = [provider_id for provider_id, _entry_point in PROVIDERS]
    if type(value.get("schema_version")) is not int or value.get("schema_version") != 1:
        errors.append("inventory.schema_version: expected 1")
    if value.get("verdict") != "pass":
        errors.append("inventory.verdict: expected pass")
    if type(value.get("provider_count")) is not int or value.get(
        "provider_count"
    ) != len(PROVIDERS):
        errors.append(f"inventory.provider_count: expected {len(PROVIDERS)}")
    provider_ids = value.get("provider_ids")
    if not isinstance(provider_ids, list) or not all(
        isinstance(item, str) for item in provider_ids
    ):
        errors.append("inventory.provider_ids: expected string array")
    else:
        for provider_id in expected_ids:
            if provider_id not in provider_ids:
                errors.append(f"inventory.provider_ids: missing provider {provider_id}")
        if provider_ids != expected_ids and set(provider_ids) == set(expected_ids):
            errors.append("inventory.provider_ids: canonical order mismatch")
        for provider_id in provider_ids:
            if provider_id not in expected_ids:
                errors.append(f"inventory.provider_ids: unknown provider {provider_id}")
    if value.get("errors") != []:
        errors.append("inventory.errors: expected empty array")
    if not isinstance(value.get("input_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", value.get("input_sha256", "")
    ):
        errors.append("inventory.input_sha256: expected SHA-256")
    input_hashes = value.get("input_hashes")
    if not isinstance(input_hashes, dict):
        errors.append("inventory.input_hashes: expected object")
    else:
        for relative_path in INVENTORY_INPUTS:
            expected_hash = input_hashes.get(relative_path)
            if not isinstance(expected_hash, str):
                errors.append(
                    f"inventory.input_hashes.{relative_path}: missing SHA-256"
                )
        for relative_path, expected_hash in sorted(input_hashes.items()):
            if (
                not isinstance(relative_path, str)
                or not relative_path
                or "\\" in relative_path
                or Path(relative_path).is_absolute()
            ):
                errors.append(f"inventory.input_hashes: unsafe path {relative_path!r}")
                continue
            actual_path = (ROOT / relative_path).resolve()
            if not actual_path.is_relative_to(ROOT) or not actual_path.exists():
                errors.append(
                    f"inventory.input_hashes.{relative_path}: missing repository input"
                )
            elif not isinstance(expected_hash, str) or not re.fullmatch(
                r"[0-9a-f]{64}", expected_hash
            ):
                errors.append(
                    f"inventory.input_hashes.{relative_path}: invalid SHA-256"
                )
            elif expected_hash != _sha256(actual_path):
                errors.append(f"inventory.input_hashes.{relative_path}: stale evidence")
    return value, errors


# 校验 canonical manifest 仍是文档声明的九个入口点。
def _validate_manifest():
    value = _load_json(ROOT / "config/plugin-manifest.json")
    errors = []
    if value.get("entry_point_group") != ENTRY_POINT_GROUP:
        errors.append(f"manifest.entry_point_group: expected {ENTRY_POINT_GROUP}")
    if type(value.get("api_version")) is not int or value.get("api_version") != 1:
        errors.append("manifest.api_version: expected 1")
    plugins = value.get("plugins")
    if not isinstance(plugins, list):
        return errors + ["manifest.plugins: expected array"]
    actual_ids = [
        item.get("id") if isinstance(item, dict) else None for item in plugins
    ]
    expected_ids = [provider_id for provider_id, _entry_point in PROVIDERS]
    if actual_ids != expected_ids:
        errors.append("manifest.plugins: canonical provider IDs/order mismatch")
    for index, (provider_id, entry_point) in enumerate(PROVIDERS):
        if index >= len(plugins) or not isinstance(plugins[index], dict):
            continue
        descriptor = plugins[index]
        actual_entry = descriptor.get("entry_point")
        expected_entry = {
            "group": ENTRY_POINT_GROUP,
            "name": provider_id,
            "value": entry_point,
        }
        if actual_entry != expected_entry:
            errors.append(
                f"manifest.plugins[{index}].entry_point: expected {provider_id}"
            )
    return value, errors


# 读取三份固定架构文档，拒绝替换、重复和缺失文档。
def _load_documents(paths):
    documents, errors = {}, []
    for path in paths:
        name = path.name
        if name not in DOCUMENT_NAMES:
            errors.append(f"docs: unexpected document {path}")
            continue
        if name in documents:
            errors.append(f"docs: duplicate document {name}")
            continue
        try:
            documents[name] = path.read_text(encoding="utf-8")
        except OSError as error:
            errors.append(f"docs: cannot read {path}: {error}")
    for name in DOCUMENT_NAMES:
        if name not in documents:
            errors.append(f"docs: missing document {name}")
    return documents, errors


# 核对固定事实、入口点和已知文档路径，而非泛化扫描文档。
def _validate_documents(documents):
    errors = []
    contents = "\n".join(documents.values())
    for provider_id, entry_point in PROVIDERS:
        if provider_id not in contents:
            errors.append(f"docs: missing provider {provider_id}")
        rendered_entry_point = f"{ENTRY_POINT_GROUP}:{provider_id} = {entry_point}"
        if rendered_entry_point not in contents:
            errors.append(f"docs: missing entry point {rendered_entry_point}")
    for name, marker in DOCUMENT_FACTS:
        if marker not in contents:
            errors.append(f"docs: missing {name}: {marker}")
    for line in contents.splitlines():
        if AFFIRMATIVE_EXTENSION_CLAIM.search(line):
            for feature in UNSUPPORTED_EXTENSION_FEATURES:
                if feature in line:
                    errors.append(
                        f"docs: unsupported extension feature is claimed: {feature}"
                    )
    for relative_path in FIXED_PATHS:
        if not (ROOT / relative_path).is_file():
            errors.append(f"docs: missing repository path {relative_path}")
        elif relative_path not in contents:
            errors.append(f"docs: missing path reference {relative_path}")
    for document_name, link in FIXED_LINKS.items():
        if link not in documents.get(document_name, ""):
            errors.append(f"docs: missing fixed link in {document_name}: {link}")
    return errors


# 写入离线校验报告。
def _write_report(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


# 运行固定的 Todo16 文档校验。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--docs", required=True, nargs="+", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    arguments = parser.parse_args(argv)
    inventory, manifest = {}, {}
    errors = []
    try:
        inventory, inventory_errors = _validate_inventory(arguments.inventory)
        manifest, manifest_errors = _validate_manifest()
        documents, document_errors = _load_documents(arguments.docs)
        errors.extend(inventory_errors)
        errors.extend(manifest_errors)
        errors.extend(document_errors)
        if not document_errors:
            errors.extend(_validate_documents(documents))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        errors.append(str(error))
        documents = {}
    report = {
        "schema_version": 1,
        "status": "PASS" if not errors else "REJECTED",
        "inventory": _display_path(arguments.inventory),
        "inventory_sha256": (
            _sha256(arguments.inventory) if arguments.inventory.is_file() else ""
        ),
        "manifest": "config/plugin-manifest.json",
        "manifest_sha256": _sha256(ROOT / "config/plugin-manifest.json"),
        "provider_ids": inventory.get("provider_ids", []),
        "manifest_provider_ids": [
            item.get("id")
            for item in manifest.get("plugins", [])
            if isinstance(item, dict)
        ],
        "docs": [_display_path(path) for path in arguments.docs],
        "doc_sha256": {
            _display_path(path): _sha256(path)
            for path in arguments.docs
            if path.is_file()
        },
        "errors": errors,
    }
    _write_report(arguments.report, report)
    if errors:
        for error in errors:
            print(f"REJECTED: {error}", file=sys.stderr)
        return 1
    print(f"PASS: validated {len(PROVIDERS)} documented providers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
