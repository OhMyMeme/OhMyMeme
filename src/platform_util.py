"""平台工具 - 开机自启、系统相关"""

import os
import platform
import subprocess
import sys
from pathlib import Path

from .config import get_config

APP_NAME = "OhMyMeme"


def set_auto_start(enabled: bool) -> bool:
    """设置开机自启"""
    system = platform.system()

    if system == "Windows":
        return _set_auto_start_windows(enabled)
    elif system == "Darwin":
        return _set_auto_start_macos(enabled)
    elif system == "Linux":
        return _set_auto_start_linux(enabled)
    return False


def _get_executable_path() -> str:
    """获取当前可执行文件路径（兼容PyInstaller打包）"""
    if getattr(sys, "frozen", False):
        return sys.executable
    # 开发模式：使用python运行
    return sys.executable


def _set_auto_start_windows(enabled: bool) -> bool:
    """Windows: 使用注册表 Run 键"""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as key:
            if enabled:
                exe = _get_executable_path()
                # 如果是开发模式，加参数
                if not getattr(sys, "frozen", False):
                    args = f'"{exe}" -m src.main'
                else:
                    args = f'"{exe}"'
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, args)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def _set_auto_start_macos(enabled: bool) -> bool:
    """macOS: 使用 LaunchAgents plist"""
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / f"com.{APP_NAME.lower()}.plist"

    if enabled:
        exe = _get_executable_path()
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.{APP_NAME.lower()}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>"""
        plist_path.write_text(plist_content, encoding="utf-8")
        subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, timeout=10)
    else:
        if plist_path.exists():
            subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True, timeout=10)
            plist_path.unlink(missing_ok=True)
    return True


def _set_auto_start_linux(enabled: bool) -> bool:
    """Linux: 使用 .desktop autostart"""
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    desktop_path = autostart_dir / f"{APP_NAME.lower()}.desktop"

    if enabled:
        exe = _get_executable_path()
        desktop_content = f"""[Desktop Entry]
Type=Application
Name={APP_NAME}
Exec={exe}
Terminal=false
X-GNOME-Autostart-enabled=true
"""
        desktop_path.write_text(desktop_content, encoding="utf-8")
    else:
        desktop_path.unlink(missing_ok=True)
    return True


def is_auto_start_enabled() -> bool:
    """检查开机自启状态"""
    system = platform.system()
    if system == "Windows":
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                                winreg.KEY_QUERY_VALUE) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except (FileNotFoundError, OSError):
            return False
    elif system == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"com.{APP_NAME.lower()}.plist"
        return plist_path.exists()
    elif system == "Linux":
        desktop_path = Path.home() / ".config" / "autostart" / f"{APP_NAME.lower()}.desktop"
        return desktop_path.exists()
    return False
