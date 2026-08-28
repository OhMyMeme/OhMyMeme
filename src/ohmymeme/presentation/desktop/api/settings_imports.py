"""Settings-window importer orchestration and file-dialog operations."""

import os
import shutil

from ohmymeme.integrations.imports import adb_qq, telegram


class SettingsImportHandler:
    """Owns settings-window importer orchestration for one WebUI graph."""

    def __init__(self, webui, context):
        self.webui = webui
        self.config = webui._cfg
        self.library = webui._container.library
        self.job_manager = getattr(webui._container, "job_manager", None)
        self.context = context

    def start_qq_import(self):
        started = adb_qq.start_qq_import(self.job_manager)
        return {"ok": started, **({} if started else {"error": "已有导入任务正在进行"})}

    def get_qq_import_progress(self):
        return adb_qq.get_qq_progress()

    def save_qq_zip(self):
        state = adb_qq.get_qq_progress()
        if state["status"] != "done" or not state["zip_path"]:
            return {"ok": False, "error": "no zip ready"}
        try:
            result = (
                self.context.webview()
                .windows[0]
                .create_file_dialog(
                    self.context.webview().FileDialog.SAVE,
                    allow_multiple=False,
                    file_types=("ZIP 文件 (*.zip)",),
                )
            )
        except Exception:
            return {"ok": False, "error": "dialog failed"}
        if not result:
            return {"ok": False, "error": "cancelled"}
        destination = result[0] if isinstance(result, (tuple, list)) else result
        if not destination.lower().endswith(".zip"):
            destination += ".zip"
        shutil.copy2(state["zip_path"], destination)
        try:
            os.unlink(state["zip_path"])
        except OSError:
            pass
        adb_qq.reset_qq_import()
        return {"ok": True, "path": destination}

    def open_adb_folder(self):
        try:
            adb_qq.open_adb_folder()
            return True
        except Exception:
            return False

    def open_adb_help(self):
        try:
            adb_qq.open_adb_help()
            return True
        except Exception:
            return False

    def cancel_qq_import(self):
        adb_qq.cancel_qq_import()

    def pick_tg_tdata(self):
        try:
            result = (
                self.context.webview()
                .windows[0]
                .create_file_dialog(
                    self.context.webview().FileDialog.FOLDER, allow_multiple=False
                )
            )
        except Exception:
            return {"ok": False, "error": "无法打开目录选择对话框"}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        if not telegram.is_valid_tdata(path):
            return {
                "ok": False,
                "error": "所选目录不是有效的 tdata 目录（未找到 key_datas）",
            }
        self.config.set("tg_tdata_path", path)
        self.config.save()
        return {"ok": True, "path": path}

    def start_tg_import(self, tdata_path=None, passcode="", convert_webm=True):
        from ohmymeme.integrations.imports import telegram as telegram_module

        path = tdata_path or self.config.get("tg_tdata_path", "") or None
        started = telegram_module.start_tg_import(
            self.library.import_paths,
            path,
            passcode,
            convert_webm,
            self.job_manager,
        )
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_tg_import_progress(self):
        return telegram.get_tg_progress()

    def cancel_tg_import(self):
        telegram.cancel_tg_import()

    def start_douyin_import(self, cookie):
        try:
            from ohmymeme.integrations.imports import douyin
        except ImportError as error:
            return {"ok": False, "error": f"缺少依赖: {error}"}
        started = douyin.start_douyin_import(
            self.library.import_paths, cookie, self.job_manager
        )
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_douyin_import_progress(self):
        from ohmymeme.integrations.imports import douyin

        return douyin.get_douyin_progress()

    def cancel_douyin_import(self):
        from ohmymeme.integrations.imports import douyin

        douyin.cancel_douyin_import()

    def pick_wechat_root(self):
        try:
            result = (
                self.context.webview()
                .windows[0]
                .create_file_dialog(
                    self.context.webview().FileDialog.FOLDER, allow_multiple=False
                )
            )
        except Exception:
            return {"ok": False, "error": "无法打开目录选择对话框"}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        if not os.path.isdir(path):
            return {"ok": False, "error": "所选目录不存在"}
        return {"ok": True, "path": path}

    def inspect_wechat_environment(self, user_root=None):
        from ohmymeme.integrations.imports import wechat

        return wechat.inspect_wechat_environment(user_root)

    def list_wechat_stickers(self, user_root, account_path=None):
        from ohmymeme.integrations.imports import wechat

        return wechat.list_wechat_stickers(user_root, account_path)

    def start_wechat_import(self, user_root=None, download=True, account_path=None):
        from ohmymeme.integrations.imports import wechat

        started = wechat.start_wechat_import(
            self.library.import_paths,
            user_root,
            download,
            account_path,
            self.job_manager,
        )
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_wechat_import_progress(self):
        from ohmymeme.integrations.imports import wechat

        return wechat.get_wechat_progress()

    def cancel_wechat_import(self):
        from ohmymeme.integrations.imports import wechat

        wechat.cancel_wechat_import()

    def qqnt_pick_ini(self):
        try:
            result = (
                self.context.webview()
                .windows[0]
                .create_file_dialog(
                    self.context.webview().FileDialog.OPEN,
                    allow_multiple=False,
                    file_types=("INI Files (*.ini);;All Files (*)",),
                )
            )
        except Exception:
            return {"ok": False}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        self.config.set("qqnt_ini_path", path)
        self.config.set("qqnt_userdata_path", "")
        self.config.save()
        return self._qqnt_check_env()

    def qqnt_pick_userdata(self):
        try:
            result = (
                self.context.webview()
                .windows[0]
                .create_file_dialog(
                    self.context.webview().FileDialog.FOLDER, allow_multiple=False
                )
            )
        except Exception:
            return {"ok": False}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        self.config.set("qqnt_userdata_path", path)
        self.config.save()
        return self._qqnt_check_env()

    def qqnt_pick_base(self):
        try:
            result = (
                self.context.webview()
                .windows[0]
                .create_file_dialog(
                    self.context.webview().FileDialog.FOLDER, allow_multiple=False
                )
            )
        except Exception:
            return {"ok": False}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        return {"ok": True, "base": path}

    def qqnt_start(self, qq_number, output_dir, image_only=False, overwrite=False):
        ok = self.context.qqnt_start(
            qq_number,
            output_dir,
            image_only=image_only,
            overwrite=overwrite,
            ini_path=self.config.get("qqnt_ini_path") or None,
            userdata_save_path=self.config.get("qqnt_userdata_path") or None,
            job_manager=self.job_manager,
            import_callback=self.library.import_paths,
        )
        return {"ok": ok}

    def qqnt_get_progress(self):
        return self.context.qqnt_progress()

    def qqnt_cancel(self):
        return self.context.qqnt_cancel()

    def _qqnt_check_env(self):
        from ohmymeme.integrations.imports import qqnt

        return qqnt.get_extract_status(
            ini_path=self.config.get("qqnt_ini_path") or qqnt.DEFAULT_INI_PATH,
            userdata_save_path=self.config.get("qqnt_userdata_path") or None,
            fetch_nicknames=True,
        )

    def qqnt_open_dir(self, path):
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
