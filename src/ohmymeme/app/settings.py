"""设置应用用例。"""


class Settings:
    """协调配置与平台设置副作用，不依赖桌面 UI。"""

    def __init__(self, config, is_auto_start_enabled, set_auto_start):
        self._config = config
        self._is_auto_start_enabled = is_auto_start_enabled
        self._set_auto_start = set_auto_start

    def get_settings(self):
        data = self._config.to_dict()
        return data | {"auto_start": self._is_auto_start_enabled()}

    def save_settings(self, settings):
        if not isinstance(settings, dict):
            return None
        if "auto_start" in settings:
            self._set_auto_start(settings["auto_start"])
        self._config.update_from_dict(settings)
        self._config.save()
        return settings.get("hotkey")

    def reset_settings(self):
        cache_dir = self._config.get("cache_dir", "")
        self._config.reset()
        if cache_dir:
            self._config.set("cache_dir", cache_dir)
        self._config.save()
        self._set_auto_start(False)
        return self.get_settings()
