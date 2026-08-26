"""主窗口表情桥接所有权。"""

from ..window_manager import JsApi


def create_meme_api(webui, catalog, settings, library=None):
    """创建主窗口既有 ABI 的桥接对象。"""
    if library is None:
        library = webui._container.library
    return JsApi(webui, catalog, settings, library)
