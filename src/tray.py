"""系统托盘 - 跨平台托盘图标"""

import logging
import threading

try:
    from PIL import Image as PILImage
    from PIL import ImageDraw

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import pystray

    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False

logger = logging.getLogger(__name__)


def _create_default_icon():
    """程序化生成托盘图标，避免嵌入损坏的base64数据"""
    if not HAS_PIL:
        return None
    size = 64
    img = PILImage.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size // 2
    r = size // 2 - 2
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(74, 158, 255, 255))
    draw.ellipse(
        [cx - r // 4, cy - r // 3, cx + r // 4, cy + r // 3], fill=(255, 255, 255, 255)
    )
    draw.ellipse(
        [cx - r // 4 + r // 2, cy - r // 3, cx + r // 4 + r // 2, cy + r // 3],
        fill=(255, 255, 255, 255),
    )
    draw.arc(
        [cx - r // 2, cy + r // 6, cx + r // 2, cy + r // 2],
        0,
        180,
        fill=(255, 255, 255, 255),
        width=3,
    )
    return img


class TrayManager:
    """系统托盘管理器"""

    def __init__(self, on_show=None, on_quit=None):
        self._icon = None
        self._thread = None
        self._on_show = on_show
        self._on_quit = on_quit
        self._running = False

    def start(self):
        """启动托盘"""
        if not HAS_PYSTRAY:
            logger.error("pystray not installed")
            return False

        icon_image = _create_default_icon()
        if icon_image is None:
            logger.error("Cannot create tray icon (PIL missing)")
            return False

        menu = pystray.Menu(
            pystray.MenuItem(
                "显示/隐藏", self._on_show or (lambda: None), default=True
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._on_quit or (lambda: None)),
        )

        self._icon = pystray.Icon("OhMyMeme", icon_image, "OhMyMeme", menu)
        self._running = True
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    def notify(self, title: str, message: str):
        if self._icon and HAS_PYSTRAY:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass
