"""桌面媒体文件解析与缩略图生成。"""

import io
import os

try:
    from PIL import Image as PILImage

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from .security import safe_serve_filename


def find_meme_file(webui, filename: str) -> str:
    """在当前 Container 配置的缓存目录中定位媒体。"""
    if not safe_serve_filename(filename):
        return ""
    cache_dir = webui._cfg.cache_dir
    direct = cache_dir / filename
    if direct.exists():
        return str(direct)
    if not hasattr(webui, "_file_cache"):
        webui._file_cache = {}
    cached = webui._file_cache.get(filename)
    if cached and os.path.exists(cached):
        return cached
    for root, _, files in os.walk(cache_dir):
        if filename in files:
            path = os.path.join(root, filename)
            webui._file_cache[filename] = path
            return path
    return ""


def thumbnail_path(webui, meme_id: int, filename: str, size: int = 150) -> str:
    """返回或生成 PNG 缩略图。"""
    path = webui._cfg.thumbnail_dir / f"{meme_id}_{size}.png"
    if path.exists():
        return str(path)
    original = find_meme_file(webui, filename)
    if not original or not HAS_PIL:
        return ""
    try:
        image = PILImage.open(original)
        image.thumbnail((size, size), PILImage.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buffer.getvalue())
        return str(path)
    except OSError:
        return ""
