"""Desktop bridge WindowSettingsHandler implementation."""

import platform


class WindowSettingsHandler:
    """Owns shared settings dependencies without constructing a second graph."""

    def __init__(self, webui, settings, context):
        from .settings_imports import SettingsImportHandler

        self.webui = webui
        self.settings = settings
        self.config = webui._cfg
        self.imports = SettingsImportHandler(webui, context)
        self.context = context

    def get_settings(self):
        return self.settings.get_settings()

    def save_settings(self, settings):
        hotkey = self.settings.save_settings(settings)
        if hotkey:
            self.webui._on_hotkey_change(hotkey)

    def reset_settings(self):
        result = self.settings.reset_settings()
        self.webui._on_hotkey_change(result["hotkey"])
        return result

    def move_window(self, dx, dy):
        window = self.webui._settings_window
        if window:
            try:
                window.move(window.x + dx, window.y + dy)
            except Exception:
                pass

    def move_main_window(self, dx, dy):
        window = self.webui._window
        if window:
            try:
                window.move(window.x + dx, window.y + dy)
            except Exception:
                pass

    def start_window_drag(self, button, root_x, root_y):
        if platform.system() != "Linux":
            return False
        window = self.webui._settings_window
        if not window:
            return False
        try:
            from gi.repository import Gdk, GLib

            native = getattr(window, "native", None)
            if native is None:
                return False
            GLib.idle_add(
                native.begin_move_drag, button, root_x, root_y, Gdk.CURRENT_TIME
            )
            return True
        except Exception:
            return False

    def start_lan(self, port, secret):
        from ohmymeme.services import lan

        current_port = int(port or self.config.get("lan_port", 17852))
        current_secret = (
            secret if secret is not None else self.config.get("lan_secret", "")
        )
        ok = self.webui._container.start_lan(current_port, current_secret)
        return {"ok": ok, "status": lan.get_status()}

    def stop_lan(self):
        from ohmymeme.services import lan

        self.webui._container.stop_lan()
        return {"ok": True, "status": lan.get_status()}

    def lan_status(self):
        from ohmymeme.services import lan

        return lan.get_status()

    def lan_ip(self):
        from ohmymeme.services import lan

        return lan.get_lan_ip()

    def allow_secret_config(self, enabled):
        from ohmymeme.services import lan

        lan.set_allow_secret_config(bool(enabled))
        return {
            "ok": True,
            "allow_secret_config": lan.get_status()["allow_secret_config"],
        }

    def storage_info(self):
        return self.webui._container.library.storage_info()

    def pick_storage_dir(self):
        import webview

        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER, allow_multiple=False
            )
        except Exception:
            return {"ok": False, "error": "dialog failed"}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        return {"ok": True, "path": path}

    def apply_storage_dir(self, path, move_files=False):
        import webview

        try:
            result = self.webui._container.library.apply_storage_dir(path, move_files)
        except Exception as error:
            return {"ok": False, "error": str(error)}
        if not result.get("ok"):
            return result
        file_cache = getattr(self.webui, "_file_cache", None)
        if file_cache is not None:
            file_cache.clear()
        try:
            if webview.windows:
                webview.windows[0].evaluate_js("refreshMemes();")
        except Exception:
            pass
        return result

    def open_directory(self, path):
        import os
        import platform
        import subprocess

        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except Exception:
            return False

    def qqnt_check_env(self):
        from ohmymeme.integrations.imports import qqnt

        return qqnt.get_extract_status(
            ini_path=self.config.get("qqnt_ini_path") or qqnt.DEFAULT_INI_PATH,
            userdata_save_path=self.config.get("qqnt_userdata_path") or None,
            fetch_nicknames=True,
        )

    def qqnt_default_dir(self, base, qq_number):
        from ohmymeme.integrations.imports import qqnt

        try:
            directory = qqnt.get_default_output_dir(
                base, qq_number, fetch_nickname=True
            )
        except Exception:
            return {"ok": False}
        return {"ok": True, "dir": directory}

    def start_qq_import(self):
        return self.imports.start_qq_import()

    def get_qq_import_progress(self):
        return self.imports.get_qq_import_progress()

    def save_qq_zip(self):
        return self.imports.save_qq_zip()

    def open_adb_folder(self):
        return self.imports.open_adb_folder()

    def open_adb_help(self):
        return self.imports.open_adb_help()

    def export_logs(self):
        from .logs import export_logs

        return export_logs(
            self.webui,
            self.context,
            self.context.log_lock,
            self.context.log_buffer,
        )

    def cancel_qq_import(self):
        return self.imports.cancel_qq_import()

    def pick_tg_tdata(self):
        return self.imports.pick_tg_tdata()

    def start_tg_import(self, tdata_path=None, passcode="", convert_webm=True):
        return self.imports.start_tg_import(tdata_path, passcode, convert_webm)

    def get_tg_import_progress(self):
        return self.imports.get_tg_import_progress()

    def cancel_tg_import(self):
        return self.imports.cancel_tg_import()

    def start_douyin_import(self, cookie):
        return self.imports.start_douyin_import(cookie)

    def get_douyin_import_progress(self):
        return self.imports.get_douyin_import_progress()

    def cancel_douyin_import(self):
        return self.imports.cancel_douyin_import()

    def pick_wechat_root(self):
        return self.imports.pick_wechat_root()

    def inspect_wechat_environment(self, user_root=None):
        return self.imports.inspect_wechat_environment(user_root)

    def list_wechat_stickers(self, user_root, account_path=None):
        return self.imports.list_wechat_stickers(user_root, account_path)

    def start_wechat_import(self, user_root=None, download=True, account_path=None):
        return self.imports.start_wechat_import(user_root, download, account_path)

    def get_wechat_import_progress(self):
        return self.imports.get_wechat_import_progress()

    def cancel_wechat_import(self):
        return self.imports.cancel_wechat_import()

    def qqnt_pick_ini(self):
        return self.imports.qqnt_pick_ini()

    def qqnt_pick_userdata(self):
        return self.imports.qqnt_pick_userdata()

    def qqnt_pick_base(self):
        return self.imports.qqnt_pick_base()

    def qqnt_start(self, qq_number, output_dir, image_only=False, overwrite=False):
        return self.imports.qqnt_start(qq_number, output_dir, image_only, overwrite)

    def qqnt_get_progress(self):
        return self.imports.qqnt_get_progress()

    def qqnt_cancel(self):
        return self.imports.qqnt_cancel()

    def qqnt_open_dir(self, path):
        return self.imports.qqnt_open_dir(path)
