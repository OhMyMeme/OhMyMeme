# pyright: basic

"""声明式面板字段与 plugins.<id> 配置命名空间的读写。"""

PANEL_POINT = "plugin_detail.panel"


# 收集声明中的全部字段（后声明覆盖同名键）
def panel_fields(injections, point=PANEL_POINT):
    fields = {}
    for item in injections:
        if item.get("point") != point:
            continue
        for field in item.get("fields", ()):
            fields[field["key"]] = field
    return fields


# 读取当前值；secret 只返回是否已配置
def read_values(cfg, provider_id, injections, point=PANEL_POINT):
    values = {}
    for key, field in panel_fields(injections, point).items():
        secret = field["type"] == "secret"
        value = cfg.get_plugin_value(provider_id, key, None, default="", secret=secret)
        if secret:
            values[key] = {"configured": bool(value)}
        else:
            values[key] = "" if value is None else value
    return values


# 写入声明过的字段；空 secret 表示保持不变
def apply_values(cfg, provider_id, injections, payload, point=PANEL_POINT):
    fields = panel_fields(injections, point)
    unknown = set(payload) - set(fields)
    if unknown:
        raise ValueError("unknown config key")
    for key, raw in payload.items():
        field = fields[key]
        value = _coerce(field, raw)
        if field["type"] == "secret" and value == "":
            continue
        cfg.set_plugin_value(provider_id, key, value, secret=field["type"] == "secret")
    return read_values(cfg, provider_id, injections, point)


# 严格按字段声明转换输入类型
def _coerce(field, raw):
    kind = field["type"]
    if kind == "bool":
        if type(raw) is not bool:
            raise ValueError("expected bool")
        return raw
    if kind == "int":
        if type(raw) is not int:
            raise ValueError("expected int")
        return raw
    if kind in ("path_dir", "path_file", "secret", "string", "enum"):
        if not isinstance(raw, str):
            raise ValueError("expected string")
        if kind == "enum" and raw not in (field.get("options") or ()):
            raise ValueError("expected enum option")
        return raw
    raise ValueError("unsupported type")
