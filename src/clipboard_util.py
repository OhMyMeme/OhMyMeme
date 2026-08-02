"""剪贴板操作 - 复制图片到系统剪贴板"""

import hashlib
import io
import logging
import os
import struct
import tempfile

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


# 重采样 WebP 编码参数（参与缓存键：改这里旧缓存自动失效）
_RESIZE_WEBP_QUALITY = 90
_RESIZE_CACHE_VERSION = 1


def _is_valid_webp(path: str) -> bool:
    """校验 WebP 文件是否完整有效"""
    try:
        with PILImage.open(path) as im:
            if im.format != "WEBP":
                return False
            im.verify()
        return True
    except Exception:
        return False


def _resize_static_to_webp(image_path: str, max_side: int):
    """超限的静态图重采样为 WebP 临时文件；不适用或失败返回 None"""
    if not HAS_PIL:
        return None
    try:
        img = PILImage.open(image_path)
        if getattr(img, "is_animated", False):
            return None
        w, h = img.size
        if max(w, h) <= max_side:
            return None
        md5 = hashlib.md5()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                md5.update(chunk)
        # 故意不删除：CF_HDROP 指向该路径，QQ 粘贴时才读文件；
        # 缓存键含编码参数与版本号（改编码逻辑自动失效），命中时校验完整性
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"ohmm_resize_{md5.hexdigest()}_{max_side}"
            f"_q{_RESIZE_WEBP_QUALITY}_v{_RESIZE_CACHE_VERSION}.webp",
        )
        if os.path.isfile(tmp_path) and _is_valid_webp(tmp_path):
            return tmp_path
        ratio = max_side / float(max(w, h))
        img = img.resize(
            (max(1, int(w * ratio)), max(1, int(h * ratio))), PILImage.LANCZOS
        )
        img.convert("RGBA").save(tmp_path, format="WEBP", quality=_RESIZE_WEBP_QUALITY)
        return tmp_path
    except Exception as e:
        logger.warning(f"_resize_static_to_webp: {e}")
        return None


def _is_valid_gif(path: str) -> bool:
    """校验 GIF 文件是否完整有效"""
    try:
        with PILImage.open(path) as im:
            if im.format != "GIF":
                return False
            im.verify()
        return True
    except Exception:
        return False


def _make_stego_gif(image_path: str, max_side: int):
    """实验性：把超限静态图转为携带无损原图的隐写 GIF；不适用/失败返回 None"""
    if not HAS_PIL:
        return None
    try:
        from .gif_stego import make_stego_gif as _stego
    except Exception:
        try:
            from gif_stego import make_stego_gif as _stego
        except Exception as e:
            logger.warning(f"_make_stego_gif import: {e}")
            return None
    try:
        img = PILImage.open(image_path)
        if getattr(img, "is_animated", False):
            return None
        w, h = img.size
        if max(w, h) <= max_side:
            return None
        md5 = hashlib.md5()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                md5.update(chunk)
        # 故意不删除：CF_HDROP 需在粘贴时仍存在；缓存键含版本号，命中时校验完整性
        tmp_path = os.path.join(
            tempfile.gettempdir(), f"ohmm_stego_{md5.hexdigest()}_v1.gif"
        )
        if os.path.isfile(tmp_path) and _is_valid_gif(tmp_path):
            return tmp_path
        _stego(image_path, tmp_path, quiet=True)
        if os.path.isfile(tmp_path) and _is_valid_gif(tmp_path):
            return tmp_path
        return None
    except Exception as e:
        logger.warning(f"_make_stego_gif: {e}")
        return None


# GIF 转换编码参数（参与缓存键：改这里旧缓存自动失效）
_GIF_CACHE_VERSION = 1


def _static_to_gif(image_path: str, max_side: int):
    """超限的静态图按原分辨率转为普通 GIF（无隐写、不缩放）；不适用或失败返回 None"""
    if not HAS_PIL:
        return None
    try:
        img = PILImage.open(image_path)
        if getattr(img, "is_animated", False):
            return None
        w, h = img.size
        if max(w, h) <= max_side:
            return None
        md5 = hashlib.md5()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                md5.update(chunk)
        # 故意不删除：CF_HDROP 指向该路径，QQ 粘贴时才读文件；
        # 缓存键含版本号（改编码逻辑自动失效），命中时校验完整性
        tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"ohmm_gif_{md5.hexdigest()}_v{_GIF_CACHE_VERSION}.gif",
        )
        if os.path.isfile(tmp_path) and _is_valid_gif(tmp_path):
            return tmp_path
        img.convert("P", palette=PILImage.ADAPTIVE, colors=256).save(
            tmp_path, format="GIF", optimize=True
        )
        if os.path.isfile(tmp_path) and _is_valid_gif(tmp_path):
            return tmp_path
        return None
    except Exception as e:
        logger.warning(f"_static_to_gif: {e}")
        return None


# convert_image_mode_x：返回处理完图片在 cache 中的路径


def convert_image_mode_1(image_path: str, resize_max: int) -> str:
    if not os.path.isfile(image_path):
        logger.warning(f"convert_image_mode_1: file not found {image_path}")
        return ""

    resized = _resize_static_to_webp(image_path, resize_max)
    if resized:
        image_path = resized

    return image_path


def convert_image_mode_2(image_path: str, resize_max: int) -> str:
    if not os.path.isfile(image_path):
        logger.warning(f"convert_image_mode_2: file not found {image_path}")
        return ""

    gif_path = _static_to_gif(image_path, resize_max)
    if gif_path:
        image_path = gif_path

    return image_path


def convert_image_mode_3(image_path: str, resize_max: int) -> str:
    if not os.path.isfile(image_path):
        logger.warning(f"convert_image_mode_3: file not found {image_path}")
        return ""

    # 隐写 GIF 与原图同分辨率（不缩放）；失败时原样复制原图
    steg_path = _make_stego_gif(image_path, resize_max)
    if steg_path:
        return steg_path

    return image_path


def copy_image_to_clipboard(image_path: str) -> bool:
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

    # PNG 带透明：走专用路径保留 alpha（QQ/微信经 CF_HDROP 读 PNG 原文件）
    if ext == ".png" and HAS_PIL:
        try:
            img = PILImage.open(image_path)
            if img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            ):
                if _copy_png_windows(image_path):
                    return True
        except Exception:
            pass

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


def _copy_png_windows(png_path: str) -> bool:
    """复制 PNG 到剪贴板，保留透明（CF_HDROP + 自定义 PNG 格式 + CF_DIB 回退）"""
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

        with open(png_path, "rb") as f:
            raw_png = f.read()

        abspath = os.path.abspath(png_path)

        # CF_DIB: 首帧转 BMP（静态回退）
        dib_data = None
        if HAS_PIL:
            try:
                img = PILImage.open(png_path)
                output = io.BytesIO()
                img.convert("RGB").save(output, format="BMP")
                dib_data = output.getvalue()[14:]
                output.close()
            except Exception as e:
                logger.warning(f"_copy_png_windows PIL->DIB: {e}")

        # CF_HDROP 数据（文件拖放，QQ/微信用这个）
        path_utf16 = (abspath + "\0").encode("utf-16-le")
        dropfile_size = 20
        hdrop_data = (
            struct.pack("<IiiII", dropfile_size, 0, 0, 0, 1) + path_utf16 + b"\0\0"
        )

        # 注册自定义 PNG 格式
        png_fmt = user32.RegisterClipboardFormatW("PNG")
        if not png_fmt:
            raise OSError("RegisterClipboardFormatW failed")

        # 分配全局内存：PNG 字节
        h_png = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw_png))
        if not h_png:
            raise OSError("GlobalAlloc failed for PNG")
        p_png = kernel32.GlobalLock(h_png)
        if not p_png:
            kernel32.GlobalFree(h_png)
            raise OSError("GlobalLock failed for PNG")
        ctypes.memmove(p_png, raw_png, len(raw_png))
        kernel32.GlobalUnlock(h_png)

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
            kernel32.GlobalFree(h_png)
            if h_dib:
                kernel32.GlobalFree(h_dib)
            raise OSError("GlobalAlloc failed for HDROP")
        p_hdrop = kernel32.GlobalLock(h_hdrop)
        if not p_hdrop:
            kernel32.GlobalFree(h_png)
            kernel32.GlobalFree(h_hdrop)
            if h_dib:
                kernel32.GlobalFree(h_dib)
            raise OSError("GlobalLock failed for HDROP")
        ctypes.memmove(p_hdrop, hdrop_data, len(hdrop_data))
        kernel32.GlobalUnlock(h_hdrop)

        # 打开剪贴板，设置所有格式
        if not user32.OpenClipboard(None):
            kernel32.GlobalFree(h_png)
            kernel32.GlobalFree(h_hdrop)
            if h_dib:
                kernel32.GlobalFree(h_dib)
            raise OSError("OpenClipboard failed")

        user32.EmptyClipboard()
        ok = False

        # 自定义 PNG 格式
        if user32.SetClipboardData(png_fmt, h_png):
            ok = True
        else:
            kernel32.GlobalFree(h_png)

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
        logger.warning(f"_copy_png_windows ctypes: {e}")

    # 方案2: PowerShell 回退
    try:
        import subprocess

        abspath = os.path.abspath(png_path)
        ps = (
            f"Add-Type -AssemblyName System.Windows.Forms; "
            f'$data = [System.IO.File]::ReadAllBytes("{abspath}"); '
            f'[System.Windows.Forms.Clipboard]::SetData("PNG", $data);'
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
