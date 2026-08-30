"""平台工具 - 开机自启、单实例、系统相关"""

import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

APP_NAME = "OhMyMeme"

_single_instance_handle = None


def acquire_single_instance() -> bool:
    """单实例互斥（Windows 命名 mutex / POSIX flock 锁文件），已有实例返回 False"""
    global _single_instance_handle
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.CreateMutexW.argtypes = [
                wintypes.LPCWSTR,
                wintypes.BOOL,
                wintypes.LPCWSTR,
            ]
            handle = kernel32.CreateMutexW(None, False, APP_NAME + "_SingleInstance")
            if not handle:
                return True
            _single_instance_handle = handle
            return ctypes.get_last_error() != 183
        import fcntl

        uid = os.getuid() if hasattr(os, "getuid") else 0
        lock_path = Path(tempfile.gettempdir()) / f"{APP_NAME.lower()}-{uid}.lock"
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        _single_instance_handle = fd
        return True
    except Exception:
        return True


def is_wsl() -> bool:
    """检测是否运行在 WSL 环境"""
    if platform.system() != "Linux":
        return False
    try:
        with open("/proc/version", "r", encoding="utf-8") as f:
            return "microsoft" in f.read().lower()
    except Exception:
        return False


def is_integrated_gpu() -> bool:
    """DXGI 检测主 GPU 是否为核显（专用显存 < 1GB 视为核显）"""
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        class DXGI_ADAPTER_DESC(ctypes.Structure):
            _fields_ = [
                ("Description", ctypes.c_wchar * 128),
                ("VendorId", wintypes.UINT),
                ("DeviceId", wintypes.UINT),
                ("SubSysId", wintypes.UINT),
                ("Revision", wintypes.UINT),
                ("DedicatedVideoMemory", ctypes.c_size_t),
                ("DedicatedSystemMemory", ctypes.c_size_t),
                ("SharedSystemMemory", ctypes.c_size_t),
                ("AdapterLuid", ctypes.c_uint64),
            ]

        dxgi = ctypes.WinDLL("dxgi.dll")
        create = dxgi.CreateDXGIFactory1
        create.restype = ctypes.HRESULT
        create.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]

        iid = GUID(
            0x770AAE78,
            0xF26F,
            0x4DBA,
            (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87),
        )
        factory = ctypes.c_void_p()
        if create(ctypes.byref(iid), ctypes.byref(factory)) < 0 or not factory.value:
            return False

        vtbl = ctypes.cast(
            ctypes.cast(factory, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        EnumAdapters = ctypes.WINFUNCTYPE(
            ctypes.HRESULT,
            ctypes.c_void_p,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
        )(vtbl[7])
        adapter = ctypes.c_void_p()
        if EnumAdapters(factory, 0, ctypes.byref(adapter)) < 0 or not adapter.value:
            return False

        vtbl2 = ctypes.cast(
            ctypes.cast(adapter, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        GetDesc = ctypes.WINFUNCTYPE(
            ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(DXGI_ADAPTER_DESC)
        )(vtbl2[8])
        desc = DXGI_ADAPTER_DESC()
        if GetDesc(adapter, ctypes.byref(desc)) < 0:
            return False
        return desc.DedicatedVideoMemory < 1024 * 1024 * 1024
    except Exception:
        return False


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
    """Windows: 仅使用注册表 Run 键"""
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path,
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        ) as key:
            if enabled:
                exe = _get_executable_path()
                if not getattr(sys, "frozen", False):
                    args = f'"{exe}" -m src.main --silent'
                else:
                    args = f'"{exe}" --silent'
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
        <string>--silent</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>"""
        plist_path.write_text(plist_content, encoding="utf-8")
        subprocess.run(
            ["launchctl", "load", str(plist_path)], capture_output=True, timeout=10
        )
    else:
        if plist_path.exists():
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True,
                timeout=10,
            )
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
Exec={exe} --silent
Terminal=false
X-GNOME-Autostart-enabled=true
"""
        desktop_path.write_text(desktop_content, encoding="utf-8")
    else:
        desktop_path.unlink(missing_ok=True)
    return True


def _startup_folder_path() -> Path:
    """获取当前用户的 Startup 文件夹路径"""
    if platform.system() == "Windows":
        try:
            import winreg

            key_path = (
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            )
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_QUERY_VALUE
            ) as key:
                val, _ = winreg.QueryValueEx(key, "Startup")
                if val:
                    return Path(val)
        except Exception:
            pass
    base = os.environ.get("APPDATA", "")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def is_auto_start_enabled() -> bool:
    """检查开机自启状态（仅检测注册表 Run 键）"""
    system = platform.system()
    if system == "Windows":
        try:
            import winreg

            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_QUERY_VALUE
            ) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except (FileNotFoundError, OSError):
            pass
        return False
    elif system == "Darwin":
        plist_path = (
            Path.home() / "Library" / "LaunchAgents" / f"com.{APP_NAME.lower()}.plist"
        )
        return plist_path.exists()
    elif system == "Linux":
        desktop_path = (
            Path.home() / ".config" / "autostart" / f"{APP_NAME.lower()}.desktop"
        )
        return desktop_path.exists()
    return False
