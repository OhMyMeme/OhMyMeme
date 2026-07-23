"""OhMyMeme 主程序入口 - WebView UI + 托盘 + 全局快捷键"""

import logging
import os
import signal
import sys
import threading

from . import __app_name__, __version__
from .config import get_config
from .database import get_db
from .hotkey import GlobalHotkey
from .platform_util import set_auto_start
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
        self._webui = WebUI()
        self._webui.set_on_hotkey_change(self._on_hotkey_change)

        # 2. 注册全局快捷键
        self._register_hotkey()

        # 3. 启动系统托盘（在后台线程）
        self._tray = TrayManager(
            on_show=self._on_hotkey,
            on_quit=self._on_quit,
        )
        try:
            self._tray.start()
        except Exception as e:
            logger.warning(f"托盘启动失败: {e}")

        # 4. 开机自启
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
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(name)s: %(message)s",
    )

    if os.name != "nt":
        signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))

    app = OhMyMemeApp()
    try:
        app.run()
    except Exception as e:
        logger.exception(f"启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
