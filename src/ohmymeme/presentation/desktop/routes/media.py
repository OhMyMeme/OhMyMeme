"""媒体路由 MIME 映射。"""

ORIGINAL_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def original_mime_type(extension: str) -> str:
    """返回原图响应 MIME 类型。"""
    return ORIGINAL_MIME_TYPES.get(extension.lower(), "application/octet-stream")
