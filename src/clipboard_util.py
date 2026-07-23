"""剪贴板操作 - 复制图片到系统剪贴板"""

import io
import logging
import os
import struct

logger = logging.getLogger(__name__)

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pyperclip
    HAS_PYPERCLIP = True
except ImportError:
    HAS_PYPERCLIP = False


def copy_image_to_clipboard(image_path: str) -> bool:
    """将图片文件复制到系统剪贴板，支持跨平台"""
    if not os.path.isfile(image_path):
        logger.warning(f"copy_image_to_clipboard: file not found {image_path}")
        return False

    ext = os.path.splitext(image_path)[1].lower()

    if os.name == "nt":
        return _copy_image_windows(image_path, ext)
    elif os.name == "posix":
        import platform
        if platform.system() == "Darwin":
            return _copy_image_macos(image_path, ext)
        else:
            return _copy_image_linux(image_path, ext)
    return False


def _copy_image_windows(image_path: str, ext: str) -> bool:
    """Windows: 使用 ctypes 调用原生 Win32 API（零外部依赖）"""
    # GIF：优先尝试保留动画的专用路径
    if ext == ".gif":
        if _copy_gif_windows(image_path):
            return True

    if HAS_PIL:
        try:
            img = PILImage.open(image_path)
            output = io.BytesIO()
            img.convert("RGB").save(output, format="BMP")
            dib_data = output.getvalue()[14:]
            output.close()
            if _set_clipboard_dib(dib_data):
                return True
        except Exception as e:
            logger.warning(f"_copy_image_windows PIL: {e}")

    # PowerShell 回退
    try:
        import subprocess
        abs_path = os.path.abspath(image_path)
        ps_cmd = (
            f'Add-Type -AssemblyName System.Windows.Forms; '
            f'$img = [System.Drawing.Image]::FromFile("{abs_path}"); '
            f'[System.Windows.Forms.Clipboard]::SetImage($img); '
            f'$img.Dispose()'
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, timeout=10, check=True
        )
        return True
    except Exception:
        pass

    return False


def _set_clipboard_dib(dib_data: bytes) -> bool:
    """使用 ctypes 将 DIB 数据设置到剪贴板（CF_DIB）"""
    try:
        import ctypes
        from ctypes import wintypes

        GMEM_MOVEABLE = 0x0002
        CF_DIB = 8

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # 设置参数/返回类型（64位兼容）
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

        size = len(dib_data)
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h_mem:
            return False

        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            kernel32.GlobalFree(h_mem)
            return False

        ctypes.memmove(p_mem, dib_data, size)
        kernel32.GlobalUnlock(h_mem)

        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(h_mem)
            return False

        user32.EmptyClipboard()
        result = user32.SetClipboardData(CF_DIB, h_mem)
        user32.CloseClipboard()

        if not result:
            kernel32.GlobalFree(h_mem)
            return False
        return True
    except Exception as e:
        logger.warning(f"_set_clipboard_dib: {e}")
        return False


def _copy_gif_windows(gif_path: str) -> bool:
    """复制 GIF 到剪贴板（保留动画）"""
    # 方案1: 使用 ctypes 注册 GIF 格式写入原始字节
    try:
        import ctypes
        from ctypes import wintypes

        GMEM_MOVEABLE = 0x0002
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.RegisterClipboardFormatW.restype = wintypes.UINT
        user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
        user32.SetClipboardData.restype = wintypes.HANDLE
        user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

        with open(gif_path, "rb") as f:
            raw = f.read()

        gif_fmt = user32.RegisterClipboardFormatW("GIF")
        if not gif_fmt:
            raise OSError("RegisterClipboardFormatW failed")

        size = len(raw)
        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h_mem:
            raise OSError("GlobalAlloc failed")

        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            kernel32.GlobalFree(h_mem)
            raise OSError("GlobalLock failed")

        ctypes.memmove(p_mem, raw, size)
        kernel32.GlobalUnlock(h_mem)

        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(h_mem)
            raise OSError("OpenClipboard failed")

        user32.EmptyClipboard()
        result = user32.SetClipboardData(gif_fmt, h_mem)
        user32.CloseClipboard()

        if not result:
            kernel32.GlobalFree(h_mem)
            raise OSError("SetClipboardData failed")
        return True
    except Exception as e:
        logger.warning(f"_copy_gif_windows ctypes: {e}")

    # 方案2: PowerShell 回退
    try:
        import subprocess
        abspath = os.path.abspath(gif_path)
        ps = (
            f'Add-Type -AssemblyName System.Windows.Forms; '
            f'$data = [System.IO.File]::ReadAllBytes("{abspath}"); '
            f'[System.Windows.Forms.Clipboard]::SetData("GIF", $data);'
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=10, check=True
        )
        return True
    except Exception:
        pass

    return False


def _copy_image_macos(image_path: str, ext: str) -> bool:
    """macOS: 使用 osascript"""
    try:
        import subprocess
        abs_path = os.path.abspath(image_path)
        script = (
            f'set theFile to (POSIX file "{abs_path}") as alias\n'
            f'set theClipboard to current date\n'
            f'set theImage to (load image theFile)\n'
            f'set thePasteboard to current date\n'
        )
        subprocess.run(
            ["osascript", "-e", f'set theImage to (load image POSIX file "{abs_path}")',
             "-e", "set the clipboard to theImage"],
            capture_output=True, timeout=10
        )
        return True
    except Exception:
        if HAS_PYPERCLIP:
            try:
                pyperclip.copy(str(image_path))
                return True
            except Exception:
                pass
        return False


def _copy_image_linux(image_path: str, ext: str) -> bool:
    """Linux: 使用 xclip 或 wl-copy"""
    try:
        import subprocess
        abs_path = os.path.abspath(image_path)
        # 尝试 xclip
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", "image/png", "-i", abs_path],
                capture_output=True, timeout=5, check=True
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        # 尝试 wl-copy (Wayland)
        try:
            subprocess.run(
                ["wl-copy", "--type", "image/png", "-i", abs_path],
                capture_output=True, timeout=5, check=True
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
    except Exception:
        pass

    if HAS_PYPERCLIP:
        try:
            pyperclip.copy(str(image_path))
            return True
        except Exception:
            pass
    return False


def copy_text(text: str) -> bool:
    """复制文本到剪贴板"""
    if HAS_PYPERCLIP:
        try:
            pyperclip.copy(text)
            return True
        except Exception:
            pass
    # 回退：使用系统命令
    try:
        import subprocess
        if os.name == "nt":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", f'Set-Clipboard -Value "{text}"'],
                capture_output=True, timeout=5, check=True
            )
            return True
        elif os.name == "posix":
            import platform
            if platform.system() == "Darwin":
                subprocess.run(
                    ["osascript", "-e", f'set the clipboard to "{text}"'],
                    capture_output=True, timeout=5
                )
            else:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"],
                    input=text.encode(), timeout=5
                )
            return True
    except Exception:
        pass
    return False
