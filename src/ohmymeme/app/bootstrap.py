"""桌面应用启动编排。"""

import argparse
import logging
import os
import platform
import signal
import subprocess
import sys
import threading
from pathlib import Path

from ohmymeme import __app_name__, __version__
from ohmymeme.integrations.imports.adb_qq import init_background as _adb_init
from ohmymeme.integrations.platform.system import (
    _startup_folder_path,
    is_auto_start_enabled,
    set_auto_start,
)
from ohmymeme.services.lan import server as lan
from ohmymeme.services.sync import cleanup_stale_temp_files

from .container import Container

logger = logging.getLogger(__name__)


def _ensure_vue_frontend():
    """源码运行且产物缺失时构建 Vue 前端。"""
    if getattr(sys, "frozen", False):
        return
    root = Path(__file__).resolve().parents[3]
    dist_js = root / "src" / "webui" / "dist" / "ohmymeme.js"
    if dist_js.exists() or not (root / "package.json").exists():
        return
    try:
        npx = "npx.cmd" if os.name == "nt" else "npx"
        subprocess.run([npx, "vite", "build"], cwd=str(root), check=False, timeout=600)
    except OSError:
        logger.warning("Vue 自动编译失败")


class OhMyMemeApp:
    """桌面应用生命周期协调器。"""

    def __init__(self, container=None):
        self._container = container or Container()
        self._cfg = self._container.config
        self._db = self._container.db
        self._tray = None
        self._hotkey = None
        self._webui = None
        self._running = False
        self._hotkey_str = self._cfg.get("hotkey", "Ctrl+Alt+N")

    def run(self):
        self._running = True
        _ensure_vue_frontend()
        cleanup_stale_temp_files()
        self._webui = self._container.create_webui(
            getattr(self, "_update_debug", False),
            getattr(self, "_silent_start", False),
        )
        self._webui.set_on_hotkey_change(self._on_hotkey_change)
        self._register_hotkey()
        if platform.system() not in ("Linux", "Darwin"):
            self._tray = self._container.create_tray(
                self._on_tray_show,
                self._on_quit,
                not getattr(sys, "frozen", False),
            )
            self._tray.start()
        if getattr(sys, "frozen", False) and is_auto_start_enabled():
            self._cfg.set("auto_start", True)
        if getattr(sys, "frozen", False) and self._cfg.get("auto_start", False):
            set_auto_start(True)
        threading.Thread(target=_adb_init, daemon=True).start()
        logger.info("%s v%s 已启动", __app_name__, __version__)
        try:
            self._webui.start()
        finally:
            self.shutdown()

    def _register_hotkey(self):
        self._hotkey = self._container.create_hotkey()
        try:
            self._hotkey.register(self._hotkey_str, self._on_hotkey)
        except Exception:
            logger.warning("快捷键注册失败")

    def _on_hotkey(self):
        if self._webui:
            self._webui.toggle_hotkey_safe()

    def _on_tray_show(self):
        if self._webui:
            self._webui.toggle_safe()

    def _on_hotkey_change(self, new_hotkey):
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
        self._container.close(self._hotkey, self._tray, lan.stop, self._webui)


def main():
    """保留既有 CLI flags 的包入口。"""
    parser = argparse.ArgumentParser(description="OhMyMeme")
    parser.add_argument("--debug-update", action="store_true", dest="update_debug")
    parser.add_argument("--silent", action="store_true", dest="silent")
    parser.add_argument("--debug-startup", action="store_true", dest="startup_debug")
    parser.add_argument("--debug-adb", action="store_true", dest="adb_debug")
    parser.add_argument("--debug", action="store_true", dest="debug")
    args, _ = parser.parse_known_args()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if args.debug else logging.INFO)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(console)
    if args.startup_debug:
        logger.info("Startup folder: %s", _startup_folder_path())
        logger.info("is_auto_start_enabled() == %s", is_auto_start_enabled())
    if os.name != "nt":
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    app = OhMyMemeApp()
    app._update_debug = args.update_debug
    app._silent_start = args.silent
    try:
        app.run()
    except Exception:
        logger.exception("启动失败")
        app.shutdown()
        sys.exit(1)
