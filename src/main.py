"""OhMyMeme 主程序入口 - WebView UI + 托盘 + 全局快捷键"""

import logging
import os
import platform
import signal
import subprocess
import sys
import threading
from pathlib import Path

from . import __app_name__, __version__
from .config import get_config
from .database import get_db
from .hotkey import GlobalHotkey
from .platform_util import (
    _startup_folder_path,
    is_auto_start_enabled,
    set_auto_start,
)
from .tray import TrayManager
from .webui import WebUI

logger = logging.getLogger(__name__)
_SINGLE_INSTANCE_HANDLE = None


def _acquire_single_instance() -> bool:
    """Windows 使用命名互斥体阻止第二个进程初始化。"""
    global _SINGLE_INSTANCE_HANDLE
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_bool,
            ctypes.c_wchar_p,
        ]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        ctypes.set_last_error(0)
        mutex = kernel32.CreateMutexW(None, False, "Local\\OhMyMeme.Singleton")
        if not mutex:
            logger.warning("无法创建单实例锁，继续启动")
            return True
        if ctypes.get_last_error() == 183:
            kernel32.CloseHandle(mutex)
            return False
        _SINGLE_INSTANCE_HANDLE = mutex
        return True
    except Exception as e:
        logger.warning("单实例检查失败，继续启动: %s", e)
        return True


def _ensure_vue_frontend():
    """源码运行且 Vue 构建产物缺失时自动编译一次前端（打包环境跳过）"""
    if getattr(sys, "frozen", False):
        return
    root = Path(__file__).resolve().parent.parent
    dist_js = root / "src" / "webui" / "dist" / "ohmymeme.js"
    if dist_js.exists():
        return
    if not (root / "package.json").exists():
        return
    logger.info("Vue 构建产物缺失，自动编译前端（npx vite build）...")
    try:
        npx = "npx.cmd" if os.name == "nt" else "npx"
        result = subprocess.run(
            [npx, "vite", "build"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
        )
        if result.returncode == 0:
            logger.info("Vue 前端编译完成 -> %s", dist_js)
        else:
            logger.warning(
                "Vue 自动编译失败: %s",
                (result.stderr or result.stdout).strip()[-500:],
            )
    except Exception as e:
        logger.warning("Vue 自动编译失败: %s", e)


class OhMyMemeApp:
    def __init__(self):
        self._cfg = get_config()
        self._db = get_db()
        self._tray = None
        self._hotkey = None
        self._webui = None
        self._running = False
        self._hotkey_str = self._cfg.get("hotkey", "Ctrl+Alt+N")

    def run(self):
        self._running = True

        # 0. 源码运行且 Vue 产物缺失时自动编译一次前端
        _ensure_vue_frontend()

        # 1. 清理中断遗留的临时文件（.remote-* / *.tmp）
        try:
            from .sync import cleanup_stale_temp_files

            cleanup_stale_temp_files()
        except Exception as e:
            logger.debug("cleanup stale temp files: %s", e)

        # 1. 创建 WebUI（先不启动 GUI 循环）
        self._webui = WebUI(
            update_debug=getattr(self, "_update_debug", False),
            silent_start=getattr(self, "_silent_start", False),
        )
        self._webui.set_on_hotkey_change(self._on_hotkey_change)

        # 2. 注册全局快捷键
        self._register_hotkey()

        # 3. 启动系统托盘
        if platform.system() in ("Linux", "Darwin"):
            # Linux: GTK 线程冲突；macOS: pystray 抢占 NSApplication
            # runloop 与 webview 主循环冲突（窗口无法启动/段错误）
            logger.warning(
                f"{platform.system()} 环境：跳过系统托盘（与 WebView 主循环冲突）"
            )
        else:
            self._tray = TrayManager(
                on_show=self._on_tray_show,
                on_quit=self._on_quit,
                source_mode=not getattr(sys, "frozen", False),
            )
            try:
                self._tray.start()
            except Exception as e:
                logger.warning(f"托盘启动失败: {e}")

        # 4. 开机自启
        if getattr(sys, "frozen", False):
            if is_auto_start_enabled():
                self._cfg.set("auto_start", True)
            if self._cfg.get("auto_start", False):
                try:
                    set_auto_start(True)
                except Exception as e:
                    logger.warning(f"开机自启失败: {e}")

        # 5. 后台检测 ADB（不阻塞启动）
        try:
            from .adb_util import init_background as _adb_init

            threading.Thread(target=_adb_init, daemon=True).start()
        except Exception as e:
            logger.debug("ADB init: %s", e)

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
            self._webui.toggle_hotkey_safe()

    def _on_tray_show(self):
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
        try:
            from . import lan

            lan.stop()
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
        # 强制退出，避免残留的非 daemon 线程阻止解释器正常退出
        os._exit(0)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="OhMyMeme")
    parser.add_argument(
        "--debug-update",
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
        "--debug-startup",
        action="store_true",
        dest="startup_debug",
        help="Print auto-start detection details",
    )
    parser.add_argument(
        "--debug-adb",
        action="store_true",
        dest="adb_debug",
        help="Print ADB detection details",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        dest="debug",
        help="Print all debug logs",
    )
    args, _ = parser.parse_known_args()

    # 根 logger 固定 DEBUG（内存缓冲始终收集）；控制台级别按 --debug 调整
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if args.debug else logging.INFO)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(console)

    if args.startup_debug:
        logger.info("=== debug-startup ===")
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

    if args.adb_debug:
        from .adb_util import (
            _adb_binary_name,
            _get_adb_dir,
            _migrate_adb,
            detect_adb,
            set_adb_debug,
        )

        set_adb_debug()
        logger.info("=== debug-adb ===")
        _migrate_adb()
        adb_dir = _get_adb_dir()
        logger.info("  .adb dir: %s", adb_dir)
        binary = _adb_binary_name()
        logger.info("  binary name: %s", binary)
        candidate = adb_dir / "platform-tools" / binary
        logger.info("  local path exists: %s", candidate.exists())
        result = detect_adb()
        logger.info("  detect_adb(): %s", result)
        if result:
            try:
                which_cmd = "where.exe" if os.name == "nt" else "which"
                r = subprocess.run(
                    [which_cmd, "adb"],
                    capture_output=True,
                    timeout=5,
                    text=True,
                    shell=False,
                )
                path = r.stdout.splitlines()[0].strip() if r.stdout else ""
                logger.info("  adb path: %s", path or result)
            except Exception:
                pass
        logger.info("================")

    if os.name != "nt":
        signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))

    if not _acquire_single_instance():
        logger.info("OhMyMeme 已在运行，忽略重复启动")
        return

    app = OhMyMemeApp()
    app._update_debug = args.update_debug
    app._silent_start = args.silent
    try:
        app.run()
    except Exception as e:
        logger.exception(f"启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
