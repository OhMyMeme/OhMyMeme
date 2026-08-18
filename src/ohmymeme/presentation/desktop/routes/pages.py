"""固定运行时页面和静态资源路由约定。"""

STATIC_MIME_TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}


def static_mime_type(filepath: str):
    """返回本地静态资源的强制 MIME 类型。"""
    from os.path import splitext

    return STATIC_MIME_TYPES.get(splitext(filepath)[1].lower())
