"""pywebview 桥接 API。"""


def __getattr__(name):
    if name in {"JsApi", "SettingsApi"}:
        from ..window_manager import JsApi, SettingsApi

        return {"JsApi": JsApi, "SettingsApi": SettingsApi}[name]
    raise AttributeError(name)


__all__ = ["JsApi", "SettingsApi"]
