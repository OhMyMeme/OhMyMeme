"""设置窗口桥接所有权。"""

from ..window_manager import SettingsApi
from .handlers import WindowSettingsHandler


def create_settings_api(webui, settings):
    """创建设置窗口既有 ABI 的桥接对象。"""
    return SettingsApi(webui, settings)


__all__ = ["WindowSettingsHandler", "create_settings_api"]
