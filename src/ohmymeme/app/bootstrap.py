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
from ohmymeme.services.lifecycle import LifecycleResources, LifecycleService
from ohmymeme.services.sync import cleanup_stale_temp_files

from .container import Container
from .ports import DesktopFactoryPort, LifecycleOwnerPort

logger = logging.getLogger(__name__)


def _ensure_vue_frontend():
    """源码运行且产物缺失时构建 Vue 前端。"""
    if getattr(sys, "frozen", False):
        return
    root = Path(__file__).resolve().parents[3]
    dist_js = root / "src" / "webui" / "dist" / "ohmymeme.js"
    settings_js = root / "src" / "webui" / "dist" / "settings-vue.js"
    if not (root / "package.json").exists():
        return
    if dist_js.exists() and settings_js.exists():
        return
    try:
        npx = "npx.cmd" if os.name == "nt" else "npx"
        if not dist_js.exists():
            subprocess.run([npx, "vite", "build"], cwd=str(root), check=False, timeout=600)
        if not settings_js.exists():
            subprocess.run(
                [npx, "vite", "build", "--config", "vite.settings.config.ts"],
                cwd=str(root),
                check=False,
                timeout=600,
            )
    except OSError:
        logger.warning("Vue 自动编译失败")


class OhMyMemeApp:
    """桌面应用生命周期协调器。"""

    def __init__(self, container):
        self._container = container
        self._factory: DesktopFactoryPort = container
        self._cfg = self._container.config
        self._db = self._container.db
        self._tray = None
        self._hotkey = None
        self._webui = None
        self._lifecycle = None
        self._lifecycle_lock = threading.Lock()
        self._running = False
        self._hotkey_str = self._cfg.get("hotkey", "Ctrl+Alt+N")

    def run(self):
        self._running = True
        try:
            _ensure_vue_frontend()
            cleanup_stale_temp_files()
            self._webui = self._factory.create_webui(
                getattr(self, "_update_debug", False),
                getattr(self, "_silent_start", False),
            )
            self._webui.set_on_hotkey_change(self._on_hotkey_change)
            self._register_hotkey()
            if platform.system() not in ("Linux", "Darwin"):
                self._tray = self._factory.create_tray(
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
            self._lifecycle_service().mark_running()
            self._webui.start()
        except Exception:
            self._lifecycle_service().mark_failed()
            raise
        finally:
            self.shutdown()

    def _register_hotkey(self):
        self._hotkey = self._factory.create_hotkey()
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

    def _lifecycle_service(self):
        with self._lifecycle_lock:
            if self._lifecycle is None:
                owner: LifecycleOwnerPort = self._container
                lan_service = getattr(self._container, "lan", None)
                lan_stop = lan_service.stop if lan_service is not None else lan.stop
                self._lifecycle = LifecycleService(
                    LifecycleResources(
                        self._hotkey,
                        self._tray,
                        lan_stop,
                        self._webui,
                        owner.db,
                        owner.config,
                    )
                )
            return self._lifecycle

    def shutdown(self):
        self._running = False
        closer = getattr(self._container, "close", None)
        if closer is None:
            return self._lifecycle_service().close()
        lan_service = getattr(self._container, "lan", None)
        lan_stop = lan_service.stop if lan_service is not None else lan.stop
        return closer(
            self._hotkey,
            self._tray,
            lan_stop,
            self._webui,
            self._lifecycle_service(),
        )


def compose_app(args=None, container_factory=Container):
    """Construct the only desktop object graph used by the package entrypoint."""
    container = container_factory()
    try:
        app = OhMyMemeApp(container)
    except Exception:
        owner: LifecycleOwnerPort = container
        LifecycleService(
            LifecycleResources(None, None, None, None, owner.db, owner.config)
        ).close()
        raise
    if args is not None:
        app._update_debug = args.update_debug
        app._silent_start = args.silent
    return app


def main():
    """保留既有 CLI flags 的包入口。"""
    if "--plugin-worker" in sys.argv[1:]:
        from ohmymeme.core.plugins.runtime.worker import main as worker_main

        raise SystemExit(worker_main(sys.argv[1:]))
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
    app = None
    try:
        app = compose_app(args)
        app.run()
    except Exception:
        logger.exception("启动失败")
        if app is not None:
            app.shutdown()
        sys.exit(1)
