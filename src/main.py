"""OhMyMeme 主程序入口 - WebView UI + 托盘 + 全局快捷键"""

import logging
import os
import signal
import sys

from . import __app_name__, __version__
from .config import get_config
from .database import get_db
from .hotkey import GlobalHotkey
from .platform_util import (
    _startup_folder_path,
    is_auto_start_enabled,
    is_wsl,
    set_auto_start,
)
from .tray import TrayManager
from .webui import WebUI

logger = logging.getLogger(__name__)


class OhMyMemeApp:
    def __init__(self):
        self._cfg = get_config()
        self._db = get_db()
        self._tray = None
        self._hotkey = None
        self._webui = None
        self._running = False
        self._hotkey_str = self._cfg.get("hotkey", "Ctrl+Alt+M")

    def run(self):
        self._running = True

        # 1. 创建 WebUI（先不启动 GUI 循环）
        self._webui = WebUI(
            update_debug=getattr(self, "_update_debug", False),
            silent_start=getattr(self, "_silent_start", False),
        )
        self._webui.set_on_hotkey_change(self._on_hotkey_change)

        # 2. 注册全局快捷键
        self._register_hotkey()

        # 3. 启动系统托盘（WSL 环境下跳过，避免 GTK 线程冲突）
        if is_wsl():
            logger.warning("WSL 环境：跳过系统托盘（缺少 DBus，存在 GTK 线程冲突）")
        else:
            self._tray = TrayManager(
                on_show=self._on_hotkey,
                on_quit=self._on_quit,
            )
            try:
                self._tray.start()
            except Exception as e:
                logger.warning(f"托盘启动失败: {e}")

        # 4. 开机自启
        is_frozen = getattr(sys, "frozen", False)
        if not is_frozen:
            # 源码运行时：仅清理指向 python.exe 的开机自启项，不误删发行版
            try:
                import winreg

                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_QUERY_VALUE
                ) as key:
                    val, _ = winreg.QueryValueEx(key, "OhMyMeme")
                    if "python" in val.lower():
                        set_auto_start(False)
                        self._cfg.set("auto_start", False)
                        logger.info("已清理源码运行残留的开机自启项")
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(f"查询开机自启失败: {e}")
        else:
            if is_auto_start_enabled():
                self._cfg.set("auto_start", True)
            if self._cfg.get("auto_start", False):
                try:
                    set_auto_start(True)
                except Exception as e:
                    logger.warning(f"开机自启失败: {e}")

        logger.info(f"{__app_name__} v{__version__} 已启动")

        # 5. 启动 WebView GUI 循环（阻塞主线程）
        try:
            self._webui.start()
        except Exception as e:
            logger.exception(f"UI 启动失败: {e}")

        self.shutdown()

    def _register_hotkey(self):
        self._hotkey = GlobalHotkey()
        try:
            self._hotkey.register(self._hotkey_str, self._on_hotkey)
        except Exception as e:
            logger.warning(f"快捷键注册失败: {e}")

    def _on_hotkey(self):
        if self._webui:
            self._webui.toggle_safe()

    def _on_hotkey_change(self, new_hotkey: str):
        self._hotkey_str = new_hotkey
        if self._hotkey:
            try:
                self._hotkey.unregister()
            except Exception:
                pass
        self._register_hotkey()

    def _on_quit(self):
        self.shutdown()

    def shutdown(self):
        self._running = False
        if self._hotkey:
            try:
                self._hotkey.unregister()
            except Exception:
                pass
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        if self._webui:
            try:
                self._webui.stop()
            except Exception:
                pass
        if self._db:
            try:
                self._db.close()
            except Exception:
                pass
        self._cfg.save()
        logger.info("OhMyMeme 已退出")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="OhMyMeme")
    parser.add_argument(
        "--update-debug",
        action="store_true",
        dest="update_debug",
        help="Force show update dialog for testing",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        dest="silent",
        help="Start minimized to tray",
    )
    parser.add_argument(
        "--startup-debug",
        action="store_true",
        dest="startup_debug",
        help="Print auto-start detection details",
    )
    args, _ = parser.parse_known_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    if args.startup_debug:
        logger.info("=== startup-debug ===")
        if os.name == "nt":
            try:
                import winreg

                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_QUERY_VALUE
                    ) as key:
                        val, typ = winreg.QueryValueEx(key, "OhMyMeme")
                        logger.info("  Registry Run key: exists -> %s", val)
                except FileNotFoundError:
                    logger.info("  Registry Run key: not found")
                except OSError as e:
                    logger.info("  Registry Run key: error -> %s", e)
            except Exception as e:
                logger.info("  Registry Run key: import error -> %s", e)
            sp = _startup_folder_path()
            logger.info("  Startup folder: %s", sp)
            shortcut = sp / "OhMyMeme.lnk"
            logger.info("  Shortcut exists: %s", shortcut.exists())
        else:
            logger.info("  (non-Windows, skipped registry/startup-folder checks)")
        logger.info("  is_auto_start_enabled() == %s", is_auto_start_enabled())
        logger.info("====================")

    if os.name != "nt":
        signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))

    app = OhMyMemeApp()
    app._update_debug = args.update_debug
    app._silent_start = args.silent or (
        getattr(sys, "frozen", False) and get_config().get("silent_start", False)
    )
    try:
        app.run()
    except Exception as e:
        logger.exception(f"启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
