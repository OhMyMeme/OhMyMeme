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


def _is_animated(path: str) -> bool:
    """检测文件是否为动图（GIF / WebP）"""
    try:
        with open(path, "rb") as f:
            header = f.read(50)
        # GIF89a 一般为动图
        if header[:6] == b"GIF89a":
            return True
        # WebP: ANIM chunk 在 VP8X 之后（约偏移 30+），扫描整个头
        if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
            return b"ANIM" in header
        return False
    except Exception:
        return False


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

    # WebP：直接传送原文件（QQ/微信原生支持 WebP，无需转 GIF）
    if ext == ".webp":
        if _copy_webp_windows(image_path):
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
            f"Add-Type -AssemblyName System.Windows.Forms; "
            f'$img = [System.Drawing.Image]::FromFile("{abs_path}"); '
            f"[System.Windows.Forms.Clipboard]::SetImage($img); "
            f"$img.Dispose()"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True,
            timeout=10,
            check=True,
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
    """复制 GIF 到剪贴板，供 QQ/微信等应用粘贴动图"""
    try:
        import ctypes
        from ctypes import wintypes

        GMEM_MOVEABLE = 0x0002
        CF_DIB = 8
        CF_HDROP = 15
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
            raw_gif = f.read()

        abspath = os.path.abspath(gif_path)

        # ── 1) CF_DIB: 第一帧转 BMP（静态回退） ──
        dib_data = None
        if HAS_PIL:
            try:
                img = PILImage.open(gif_path)
                output = io.BytesIO()
                img.convert("RGB").save(output, format="BMP")
                dib_data = output.getvalue()[14:]
                output.close()
            except Exception as e:
                logger.warning(f"_copy_gif_windows PIL->DIB: {e}")

        # ── 2) 构建 CF_HDROP 数据（文件拖放，QQ/微信用这个） ──
        path_utf16 = (abspath + "\0").encode("utf-16-le")
        dropfile_size = 20  # sizeof(DROPFILES) = 5 * 4
        hdrop_data = (
            struct.pack(
                "<IiiII", dropfile_size, 0, 0, 0, 1
            )  # pFiles, pt.x/y, fNC=0, fWide=1
            + path_utf16
            + b"\0\0"  # double null terminator
        )

        # ── 3) 注册自定义 GIF 格式 ──
        gif_fmt = user32.RegisterClipboardFormatW("GIF")
        if not gif_fmt:
            raise OSError("RegisterClipboardFormatW failed")

        # ── 分配全局内存：GIF 字节 ──
        h_gif = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw_gif))
        if not h_gif:
            raise OSError("GlobalAlloc failed for GIF")
        p_gif = kernel32.GlobalLock(h_gif)
        if not p_gif:
            kernel32.GlobalFree(h_gif)
            raise OSError("GlobalLock failed for GIF")
        ctypes.memmove(p_gif, raw_gif, len(raw_gif))
        kernel32.GlobalUnlock(h_gif)

        # ── 分配全局内存：CF_DIB ──
        h_dib = None
        if dib_data:
            h_dib = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib_data))
            if h_dib:
                p_dib = kernel32.GlobalLock(h_dib)
                if p_dib:
                    ctypes.memmove(p_dib, dib_data, len(dib_data))
                    kernel32.GlobalUnlock(h_dib)
                else:
                    kernel32.GlobalFree(h_dib)
                    h_dib = None

        # ── 分配全局内存：CF_HDROP ──
        h_hdrop = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(hdrop_data))
        if not h_hdrop:
            kernel32.GlobalFree(h_gif)
            if h_dib:
                kernel32.GlobalFree(h_dib)
            raise OSError("GlobalAlloc failed for HDROP")
        p_hdrop = kernel32.GlobalLock(h_hdrop)
        if not p_hdrop:
            kernel32.GlobalFree(h_gif)
            kernel32.GlobalFree(h_hdrop)
            if h_dib:
                kernel32.GlobalFree(h_dib)
            raise OSError("GlobalLock failed for HDROP")
        ctypes.memmove(p_hdrop, hdrop_data, len(hdrop_data))
        kernel32.GlobalUnlock(h_hdrop)

        # ── 打开剪贴板，设置所有格式 ──
        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(h_gif)
            kernel32.GlobalFree(h_hdrop)
            if h_dib:
                kernel32.GlobalFree(h_dib)
            raise OSError("OpenClipboard failed")

        user32.EmptyClipboard()
        ok = False

        # 自定义 GIF 格式
        if user32.SetClipboardData(gif_fmt, h_gif):
            ok = True
        else:
            kernel32.GlobalFree(h_gif)

        # CF_HDROP — QQ/微信通过此格式读取文件路径
        if user32.SetClipboardData(CF_HDROP, h_hdrop):
            ok = True
        else:
            kernel32.GlobalFree(h_hdrop)

        # CF_DIB — 静态回退
        if h_dib:
            if user32.SetClipboardData(CF_DIB, h_dib):
                ok = True
            else:
                kernel32.GlobalFree(h_dib)

        user32.CloseClipboard()

        if not ok:
            raise OSError("SetClipboardData failed for all formats")
        return True
    except Exception as e:
        logger.warning(f"_copy_gif_windows ctypes: {e}")

    # 方案2: PowerShell 回退
    try:
        import subprocess

        abspath = os.path.abspath(gif_path)
        ps = (
            f"Add-Type -AssemblyName System.Windows.Forms; "
            f'$data = [System.IO.File]::ReadAllBytes("{abspath}"); '
            f'[System.Windows.Forms.Clipboard]::SetData("GIF", $data);'
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=10,
            check=True,
        )
        return True
    except Exception:
        pass

    return False


def _copy_webp_windows(webp_path: str) -> bool:
    """复制 WebP 到剪贴板，直接传送原文件（QQ/微信原生支持 WebP）"""
    try:
        import ctypes
        from ctypes import wintypes

        GMEM_MOVEABLE = 0x0002
        CF_DIB = 8
        CF_HDROP = 15
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

        with open(webp_path, "rb") as f:
            raw_webp = f.read()

        abspath = os.path.abspath(webp_path)

        # CF_DIB: 首帧转 BMP（静态回退）
        dib_data = None
        if HAS_PIL:
            try:
                img = PILImage.open(webp_path)
                output = io.BytesIO()
                img.convert("RGB").save(output, format="BMP")
                dib_data = output.getvalue()[14:]
                output.close()
            except Exception as e:
                logger.warning(f"_copy_webp_windows PIL->DIB: {e}")

        # CF_HDROP 数据（文件拖放，QQ/微信用这个）
        path_utf16 = (abspath + "\0").encode("utf-16-le")
        dropfile_size = 20
        hdrop_data = (
            struct.pack("<IiiII", dropfile_size, 0, 0, 0, 1) + path_utf16 + b"\0\0"
        )

        # 注册自定义 WebP 格式
        webp_fmt = user32.RegisterClipboardFormatW("WebP")
        if not webp_fmt:
            raise OSError("RegisterClipboardFormatW failed")

        # 分配全局内存：WebP 字节
        h_webp = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw_webp))
        if not h_webp:
            raise OSError("GlobalAlloc failed for WebP")
        p_webp = kernel32.GlobalLock(h_webp)
        if not p_webp:
            kernel32.GlobalFree(h_webp)
            raise OSError("GlobalLock failed for WebP")
        ctypes.memmove(p_webp, raw_webp, len(raw_webp))
        kernel32.GlobalUnlock(h_webp)

        # 分配全局内存：CF_DIB
        h_dib = None
        if dib_data:
            h_dib = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib_data))
            if h_dib:
                p_dib = kernel32.GlobalLock(h_dib)
                if p_dib:
                    ctypes.memmove(p_dib, dib_data, len(dib_data))
                    kernel32.GlobalUnlock(h_dib)
                else:
                    kernel32.GlobalFree(h_dib)
                    h_dib = None

        # 分配全局内存：CF_HDROP
        h_hdrop = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(hdrop_data))
        if not h_hdrop:
            kernel32.GlobalFree(h_webp)
            if h_dib:
                kernel32.GlobalFree(h_dib)
            raise OSError("GlobalAlloc failed for HDROP")
        p_hdrop = kernel32.GlobalLock(h_hdrop)
        if not p_hdrop:
            kernel32.GlobalFree(h_webp)
            kernel32.GlobalFree(h_hdrop)
            if h_dib:
                kernel32.GlobalFree(h_dib)
            raise OSError("GlobalLock failed for HDROP")
        ctypes.memmove(p_hdrop, hdrop_data, len(hdrop_data))
        kernel32.GlobalUnlock(h_hdrop)

        # 打开剪贴板，设置所有格式
        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(h_webp)
            kernel32.GlobalFree(h_hdrop)
            if h_dib:
                kernel32.GlobalFree(h_dib)
            raise OSError("OpenClipboard failed")

        user32.EmptyClipboard()
        ok = False

        if user32.SetClipboardData(webp_fmt, h_webp):
            ok = True
        else:
            kernel32.GlobalFree(h_webp)

        if user32.SetClipboardData(CF_HDROP, h_hdrop):
            ok = True
        else:
            kernel32.GlobalFree(h_hdrop)

        if h_dib:
            if user32.SetClipboardData(CF_DIB, h_dib):
                ok = True
            else:
                kernel32.GlobalFree(h_dib)

        user32.CloseClipboard()

        if not ok:
            raise OSError("SetClipboardData failed for all formats")
        return True
    except Exception as e:
        logger.warning(f"_copy_webp_windows ctypes: {e}")

    # 方案2: PowerShell 回退
    try:
        import subprocess

        abspath = os.path.abspath(webp_path)
        ps = (
            f"Add-Type -AssemblyName System.Windows.Forms; "
            f'$data = [System.IO.File]::ReadAllBytes("{abspath}"); '
            f'[System.Windows.Forms.Clipboard]::SetData("WebP", $data);'
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            timeout=10,
            check=True,
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
        subprocess.run(
            [
                "osascript",
                "-e",
                f'set theImage to (load image POSIX file "{abs_path}")',
                "-e",
                "set the clipboard to theImage",
            ],
            capture_output=True,
            timeout=10,
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
        # WebP 直接传原文件，动图（GIF）用 image/gif MIME
        ext = os.path.splitext(image_path)[1].lower()
        if ext == ".webp":
            mime = "image/webp"
        elif _is_animated(image_path):
            mime = "image/gif"
        else:
            mime = "image/png"
        # 尝试 xclip
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard", "-t", mime, "-i", abs_path],
                capture_output=True,
                timeout=5,
                check=True,
            )
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            pass
        # 尝试 wl-copy (Wayland)
        try:
            subprocess.run(
                ["wl-copy", "--type", mime, "-i", abs_path],
                capture_output=True,
                timeout=5,
                check=True,
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
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f'Set-Clipboard -Value "{text}"',
                ],
                capture_output=True,
                timeout=5,
                check=True,
            )
            return True
        elif os.name == "posix":
            import platform

            if platform.system() == "Darwin":
                subprocess.run(
                    ["osascript", "-e", f'set the clipboard to "{text}"'],
                    capture_output=True,
                    timeout=5,
                )
            else:
                subprocess.run(
                    ["xclip", "-selection", "clipboard"], input=text.encode(), timeout=5
                )
            return True
    except Exception:
        pass
    return False
