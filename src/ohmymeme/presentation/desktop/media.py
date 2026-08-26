"""桌面媒体文件解析与缩略图生成。"""

from .security import safe_serve_filename


def find_meme_file(webui, filename: str) -> str:
    """在当前 Container 配置的缓存目录中定位媒体。"""
    if not safe_serve_filename(filename):
        return ""
    return webui._container.library.find_meme_file(filename)


def thumbnail_path(webui, meme_id: int, filename: str, size: int = 150) -> str:
    """返回或生成 PNG 缩略图。"""
    original = find_meme_file(webui, filename)
    if not original:
        return ""
    return webui._container.assets.thumbnail_path(original, meme_id, size)
