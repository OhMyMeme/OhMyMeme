# pyright: basic

"""插件 ui.json 声明式 UI 贡献的宿主校验与读取。"""

import json
from pathlib import Path

from ohmymeme.core.plugins.runtime import seeding

INJECTION_POINTS = ("imports.row", "plugin_detail.panel", "plugin_detail.iframe")
FIELD_TYPES = ("string", "int", "bool", "enum", "path_dir", "path_file", "secret")
ACTION_KINDS = ("import", "query", "config")
ICONS = ("generic", "qq", "telegram", "douyin", "wechat")
UI_FILENAME = "ui.json"
_KEY_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


# 构造统一的非法贡献错误
def _invalid(detail):
    return seeding.PluginSeedError("invalid_ui", detail)


# 标识符：小写字母开头，仅字母数字下划线
def _valid_key(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 64
        and value[0].islower()
        and all(char in _KEY_CHARS for char in value)
    )


# 展示文本：非空且长度有界
def _valid_label(value):
    return isinstance(value, str) and 0 < len(value) <= 120


# 归一化字段声明，字段类型与键集合都受白名单约束
def _normalize_field(value, index):
    if not isinstance(value, dict):
        raise _invalid(f"fields[{index}]")
    if not _valid_key(value.get("key")):
        raise _invalid(f"fields[{index}].key")
    if value.get("type") not in FIELD_TYPES:
        raise _invalid(f"fields[{index}].type")
    if not _valid_label(value.get("label")):
        raise _invalid(f"fields[{index}].label")
    extra = set(value) - {
        "key",
        "type",
        "label",
        "required",
        "default",
        "options",
        "placeholder",
    }
    if extra:
        raise _invalid(f"fields[{index}] extra")
    normalized = {
        "key": value["key"],
        "type": value["type"],
        "label": value["label"],
        "required": value.get("required") is True,
    }
    if "default" in value:
        normalized["default"] = value["default"]
    if "placeholder" in value:
        if not isinstance(value["placeholder"], str):
            raise _invalid(f"fields[{index}].placeholder")
        normalized["placeholder"] = value["placeholder"]
    if value["type"] == "enum":
        options = value.get("options")
        if (
            not isinstance(options, list)
            or not options
            or any(not isinstance(item, str) or not item for item in options)
        ):
            raise _invalid(f"fields[{index}].options")
        normalized["options"] = list(options)
    elif "options" in value:
        raise _invalid(f"fields[{index}].options")
    return normalized


# 归一化动作声明：名字即 worker RPC 的 allowlist
def _normalize_action(value, index):
    if not isinstance(value, dict):
        raise _invalid(f"actions[{index}]")
    if not _valid_key(value.get("name")):
        raise _invalid(f"actions[{index}].name")
    if not _valid_label(value.get("label")):
        raise _invalid(f"actions[{index}].label")
    if value.get("kind") not in ACTION_KINDS:
        raise _invalid(f"actions[{index}].kind")
    if set(value) - {"name", "label", "kind"}:
        raise _invalid(f"actions[{index}] extra")
    return {"name": value["name"], "label": value["label"], "kind": value["kind"]}


# 归一化单条注入声明（不接收 HTML/CSS/脚本）
def _normalize_injection(value, index):
    if not isinstance(value, dict):
        raise _invalid(f"injections[{index}]")
    point = value.get("point")
    if point not in INJECTION_POINTS:
        raise _invalid(f"injections[{index}].point")
    if point == "plugin_detail.iframe":
        entry = value.get("entry")
        candidate = Path(entry) if isinstance(entry, str) else None
        if (
            not entry
            or candidate is None
            or candidate.is_absolute()
            or ".." in candidate.parts
            or entry.startswith(("/", "\\", "."))
        ):
            raise _invalid(f"injections[{index}].entry")
        height = value.get("height", 360)
        if type(height) is not int or not 160 <= height <= 1200:
            raise _invalid(f"injections[{index}].height")
        if set(value) - {"point", "entry", "height", "label"}:
            raise _invalid(f"injections[{index}] extra")
        result = {"point": point, "entry": entry, "height": height}
        if "label" in value:
            if not _valid_label(value["label"]):
                raise _invalid(f"injections[{index}].label")
            result["label"] = value["label"]
        return result
    if not _valid_label(value.get("label")):
        raise _invalid(f"injections[{index}].label")
    fields = value.get("fields", [])
    if not isinstance(fields, list):
        raise _invalid(f"injections[{index}].fields")
    actions = value.get("actions")
    if not isinstance(actions, list) or not actions:
        raise _invalid(f"injections[{index}].actions")
    if set(value) - {"point", "label", "description", "icon", "fields", "actions"}:
        raise _invalid(f"injections[{index}] extra")
    result = {
        "point": point,
        "label": value["label"],
        "fields": [
            _normalize_field(item, position) for position, item in enumerate(fields)
        ],
        "actions": [
            _normalize_action(item, position) for position, item in enumerate(actions)
        ],
    }
    if "description" in value:
        if not isinstance(value["description"], str) or len(value["description"]) > 300:
            raise _invalid(f"injections[{index}].description")
        result["description"] = value["description"]
    if "icon" in value:
        if value["icon"] not in ICONS:
            raise _invalid(f"injections[{index}].icon")
        result["icon"] = value["icon"]
    return result


# 解析 ui.json 文本，整份无效即拒绝
def parse_document(text):
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        raise _invalid("document") from error
    if (
        not isinstance(value, dict)
        or value.get("version") != 1
        or not isinstance(value.get("injections"), list)
    ):
        raise _invalid("document")
    if set(value) - {"version", "injections"}:
        raise _invalid("document extra")
    return [
        _normalize_injection(item, index)
        for index, item in enumerate(value["injections"])
    ]


# 从插件版本目录读取并校验贡献
def load_contributions(package_dir):
    path = Path(package_dir) / UI_FILENAME
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise _invalid(str(error)) from error
    return parse_document(text)


# worker 侧只需动作 allowlist
def load_ui_actions(package_dir):
    names = set()
    for injection in load_contributions(package_dir):
        for action in injection.get("actions", ()):
            names.add(action["name"])
    return frozenset(names)


# 宿主目录：解析插件活动版本并读取贡献
def read_contributions(data_dir, plugin_id):
    entry = seeding.resolve_plugin(data_dir, plugin_id)
    return load_contributions(entry["package_dir"])


# 解析 iframe 静态资源；越界或不存在返回 None
def resolve_asset(package_dir, relative):
    if not isinstance(relative, str) or not relative:
        return None
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or relative.startswith(("/", "\\", "."))
    ):
        return None
    root = Path(package_dir).resolve()
    target = (root / candidate).resolve()
    if target != root and root not in target.parents:
        return None
    if not target.is_file():
        return None
    return target
