"""PyWebView 现代化 UI 窗口管理器 + JS API"""

import io
import logging
import math
import os
import platform
import socket
import tempfile
import threading
import time
from pathlib import Path

# WSL 环境强制软件渲染（必须在导入 webview/GUI 之前设置）
if platform.system() == "Linux":
    try:
        with open("/proc/version", "r", encoding="utf-8") as _f:
            if "microsoft" in _f.read().lower():
                os.environ["MESA_LOADER_DRIVER_OVERRIDE"] = "llvmpipe"
                os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
                os.environ["VK_ICD_FILENAMES"] = ""
    except Exception:
        pass

# 仅核显禁用 WebView2 GPU 合成，独显保持硬件加速避免 CPU 滥用
if platform.system() == "Windows":
    from .platform_util import is_integrated_gpu

    if is_integrated_gpu():
        logging.getLogger(__name__).debug(
            "integrated GPU detected, disable gpu compositing"
        )
        _wv2_args = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
        if "--disable-gpu-compositing" not in _wv2_args:
            os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
                f"{_wv2_args} --disable-gpu-compositing".strip()
            )

try:
    from PIL import Image as PILImage

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import webview

    HAS_WEBVIEW = True
except ImportError:
    HAS_WEBVIEW = False

try:
    import bottle

    HAS_BOTTLE = True
except ImportError:
    HAS_BOTTLE = False

from . import adb_util, qqnt_extract, tg_stickers, updater
from . import sync as sync_module
from .clipboard_util import (
    _is_animated,
    convert_image_mode_1,
    convert_image_mode_2,
    convert_image_mode_3,
    copy_image_to_clipboard,
)
from .config import _IMPORT_MAX_BYTES, _IMPORT_MAX_PX, get_config
from .database import get_db
from .manifest import build as build_manifest

logger = logging.getLogger(__name__)

# 内存日志缓冲：固定收集 DEBUG 级日志，供设置页"导出日志"
_LOG_BUFFER = []
_LOG_LOCK = threading.Lock()
_LOG_MAX = 5000

# 分页：主窗口单页展示的表情包数量（与前端 index.js MEME_PAGE 保持一致）
MEME_PAGE = 200

# 贡献者 SVG 缓存：TTL 1 小时，避免每次打开设置页都请求外网
_CONTRIBUTORS_TTL = 3600
_CONTRIBUTORS_CACHE = {"svg": None, "at": 0.0}


class _LogBufferHandler(logging.Handler):
    """把 DEBUG 级日志缓存在内存中（限量 5000 条）"""

    def emit(self, record):
        try:
            line = self.format(record)
        except Exception:
            line = record.getMessage()
        with _LOG_LOCK:
            _LOG_BUFFER.append(line)
            if len(_LOG_BUFFER) > _LOG_MAX:
                del _LOG_BUFFER[: len(_LOG_BUFFER) - _LOG_MAX]


def install_log_buffer():
    """挂载内存日志缓冲，根 logger 固定 DEBUG（控制台级别由 main 控制）"""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    handler = _LogBufferHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(handler)
    return handler


install_log_buffer()

HTML_DIR = Path(__file__).resolve().parent / "webui"
RESOURCES_DIR = Path(__file__).resolve().parent / "resources"

# 启动动画视频边缘主色（OhMyMeme.mp4 边框纯黑，写死避免运行时 ffmpeg 抽帧采样）
_STARTUP_BG_COLOR = "#000000"


# 静态资源扩展名 → 强制 Content-Type：本机 mimetypes/注册表 .js 映射可能为
# text/plain，叠加 nosniff 会被 Chromium 拒执行脚本
_STATIC_MIME_TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

# ─── 工具函数  ───


def _strip_url_modifiers(url: str) -> str:
    """去掉图片 URL 中的 @ 修饰参数，返回原图 URL"""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    if "@" in parsed.path:
        clean_path = parsed.path[: parsed.path.index("@")]
    else:
        clean_path = parsed.path
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            clean_path,
            parsed.params,
            parsed.query,
            parsed.fragment,
        )
    )


def _safe_serve_filename(name: str) -> bool:
    """校验用于文件服务/DB 查询的文件名，拒绝路径穿越与绝对路径"""
    return (
        bool(name)
        and name not in (".", "..")
        and not name.startswith((".", "/", "\\", "~", ".."))
        and "/" not in name
        and "\\" not in name
    )


def _host_allowed(host: str, port: int) -> bool:
    """仅接受本地回环 Host，阻断 DNS rebinding / 跨站直连"""
    host = (host or "").strip()
    if not host:
        return False
    base = host.split(":")[0] if ":" in host else host
    if base not in ("127.0.0.1", "localhost"):
        return False
    if ":" in host and host.rsplit(":", 1)[-1] != str(port):
        return False
    return True


def _check_connectivity() -> dict:
    """检查互联网连接，返回 {ok, latency}"""
    import socket as _socket

    hosts = [("baidu.com", 80), ("www.baidu.com", 443)]
    for host, port in hosts:
        try:
            t0 = time.time()
            s = _socket.create_connection((host, port), timeout=3)
            s.close()
            latency = int((time.time() - t0) * 1000)
            return {"ok": True, "latency": f"{latency}ms"}
        except Exception:
            continue
    return {"ok": False, "latency": ""}


def _storage_dir_validation(new_dir, old_dir, protected=()):
    # 校验自定义存储目录，返回 (ok, error)
    if not new_dir or not isinstance(new_dir, str):
        return False, "目录不能为空"
    if not os.path.isabs(new_dir):
        return False, "请选择绝对路径"
    try:
        new = Path(new_dir).resolve()
        old = Path(old_dir).resolve()
    except OSError:
        return False, "路径无效"
    if new == old:
        return False, "与当前目录相同"
    if old in new.parents:
        return False, "不能选择当前目录的子目录"
    if new in old.parents:
        return False, "不能选择当前目录的上级目录"
    for p in protected:
        try:
            p = Path(p).resolve()
        except OSError:
            continue
        if new == p or new in p.parents or p in new.parents:
            return False, "不能选择应用数据/缩略图目录或其上下级目录"
    return True, ""


def _find_hotkey_window_position(cursor, work_area, width, height):
    """按固定候选顺序选择完整落入工作区的窗口位置"""
    cursor_x, cursor_y = cursor
    left, top, right, bottom = work_area
    candidates = (
        (cursor_x, cursor_y),
        (right - width, cursor_y),
        (cursor_x, bottom - height),
        (right - width, bottom - height),
    )
    for x, y in candidates:
        if left <= x and top <= y and x + width <= right and y + height <= bottom:
            return x, y
    return None


def _window_drag_update(win_x, win_y, origin, last_move, dx, dy):
    # 窗口拖动一步计算：返回 (origin, last_move, target)。
    # origin 为空时记录拖动起点并返回（本次不动）；8ms 节流期内丢弃；
    # 否则按起点+总偏移移动到绝对目标（自愈，无累积滞后）。
    now = time.monotonic()
    if origin is None:
        return (win_x - dx, win_y - dy), now, None
    if now - last_move < 0.008:
        return origin, last_move, None
    return origin, now, (origin[0] + dx, origin[1] + dy)


class JsApi:
    """暴露给前端的 JS API"""

    def __init__(self, webui):
        self._webui = webui
        self._cfg = get_config()
        self._db = get_db()
        self._drag_origin = None
        self._drag_last_move = 0.0

    def search_memes(
        self, keyword="", tags=None, collection_id=None, offset=0, limit=200
    ):
        """搜索表情，支持 offset/limit 分页"""
        if tags is not None and len(tags) == 0:
            tags = None
        fav_only = collection_id == -2
        recent_only = collection_id == -3
        uncategorized = collection_id == -4
        cid = None if (fav_only or recent_only or uncategorized) else collection_id
        if recent_only:
            rows = self._db.get_recent(limit, offset)
        else:
            if cid is not None and cid > 0:
                cid = self._get_collection_ids_recursive(cid)
            rows = self._db.search(
                keyword=keyword,
                tags=tags,
                collection_id=cid,
                favorite_only=fav_only,
                uncategorized_only=uncategorized,
                offset=offset,
                limit=limit,
            )
        favorited_ids = set()
        try:
            conn = self._db._get_conn()
            fav_rows = conn.execute("SELECT meme_id FROM favorites").fetchall()
            favorited_ids = {r[0] for r in fav_rows}
        except Exception:
            pass
        auto_gif = self._cfg.get("auto_play_gif", True)
        hover_play = self._cfg.get("hover_to_play", False)
        result = []
        for r in rows:
            fname = r["filename"].lower()
            is_gif = r.get("mime_type", "").endswith("gif") or fname.endswith(".gif")
            # 动画检测：GIF 或 WebP 动图
            if is_gif:
                is_animated = True
            elif fname.endswith(".webp"):
                path = self._find_meme_file(r["filename"])
                is_animated = _is_animated(path) if path else False
            else:
                is_animated = False
            oname = r.get("original_name", "")
            if not oname:
                oname = os.path.splitext(r["filename"])[0]
            result.append(
                {
                    "id": r["id"],
                    "filename": r["filename"],
                    "name": oname,
                    "file_hash": r.get("file_hash", ""),
                    "from_stego": r.get("from_stego", 0),
                    "width": r.get("width", 0),
                    "height": r.get("height", 0),
                    "mime_type": r.get("mime_type", ""),
                    "is_gif": is_gif,
                    "is_animated": is_animated,
                    "favorited": r["id"] in favorited_ids,
                    "auto_play_gif": auto_gif,
                    "hover_to_play": hover_play,
                }
            )
        return result

    def count_memes(self, keyword="", tags=None, collection_id=None) -> int:
        """统计符合搜索条件（关键字/标签/分组/收藏/最近使用）的表情总数，供分页"""
        if tags is not None and len(tags) == 0:
            tags = None
        fav_only = collection_id == -2
        recent_only = collection_id == -3
        uncategorized = collection_id == -4
        if recent_only:
            return self._db.count_recent()
        cid = None if (fav_only or recent_only or uncategorized) else collection_id
        if cid is not None and cid > 0:
            cid = self._get_collection_ids_recursive(cid)
        return self._db.count(
            keyword=keyword,
            tags=tags,
            collection_id=cid,
            favorite_only=fav_only,
            uncategorized_only=uncategorized,
        )

    def get_tags(self) -> list:
        return self._db.get_all_tags()

    def get_meme_tags(self, meme_id):
        """返回某表情的标签列表"""
        try:
            return self._db.get_meme_tags(meme_id) or []
        except Exception as e:
            logger.error(f"get_meme_tags error: {e}")
            return []

    def set_meme_tags(self, meme_id, tags):
        """覆盖式设置某表情的标签"""
        try:
            self._db.set_meme_tags(meme_id, tags or [])
            return True
        except Exception as e:
            logger.error(f"set_meme_tags error: {e}")
            return False

    def get_init_data(self) -> dict:
        """批返回初始化所需数据，减少 JS bridge 往返"""
        q = ""
        tags = None
        collection_id = None
        fav_only = False
        rows = self._db.search(
            keyword=q,
            tags=tags,
            collection_id=collection_id,
            favorite_only=fav_only,
            limit=MEME_PAGE,
        )
        favorited_ids = set()
        try:
            conn = self._db._get_conn()
            fav_rows = conn.execute("SELECT meme_id FROM favorites").fetchall()
            favorited_ids = {r[0] for r in fav_rows}
        except Exception:
            pass
        auto_gif = self._cfg.get("auto_play_gif", True)
        hover_play = self._cfg.get("hover_to_play", False)
        memes = []
        for r in rows:
            fname = r["filename"].lower()
            is_gif = r.get("mime_type", "").endswith("gif") or fname.endswith(".gif")
            if is_gif:
                is_animated = True
            elif fname.endswith(".webp"):
                path = self._find_meme_file(r["filename"])
                is_animated = _is_animated(path) if path else False
            else:
                is_animated = False
            oname = r.get("original_name", "")
            if not oname:
                oname = os.path.splitext(r["filename"])[0]
            memes.append(
                {
                    "id": r["id"],
                    "filename": r["filename"],
                    "name": oname,
                    "file_hash": r.get("file_hash", ""),
                    "from_stego": r.get("from_stego", 0),
                    "width": r.get("width", 0),
                    "height": r.get("height", 0),
                    "mime_type": r.get("mime_type", ""),
                    "is_gif": is_gif,
                    "is_animated": is_animated,
                    "favorited": r["id"] in favorited_ids,
                    "auto_play_gif": auto_gif,
                    "hover_to_play": hover_play,
                }
            )
        sys_cols = [
            {"id": -2, "name": "收藏夹", "count": self._db.count(favorite_only=True)},
            {"id": -3, "name": "最近使用", "count": len(self._db.get_recent(9999))},
        ]
        if self._cfg.get("show_uncategorized", True):
            sys_cols.append(
                {
                    "id": -4,
                    "name": "未分类",
                    "count": self._db.count(uncategorized_only=True),
                }
            )
        collections = sys_cols + self._build_collection_tree()
        return {
            "memes": memes,
            "tags": self._db.get_all_tags(),
            "collections": collections,
            "show_startup_animation": self._cfg.get("show_startup_animation", True),
            "startup_bg_color": _STARTUP_BG_COLOR,
        }

    def get_meme_path(self, meme_id: int) -> str:
        """返回表情本地文件路径（供拖拽到外部应用），不存在返回空串"""
        row = self._db.get_by_id(meme_id)
        if not row:
            return ""
        return self._find_meme_file(row["filename"])

    def get_meme_paths(self, meme_ids: list) -> dict:
        """批量返回表情本地文件路径 {id: path}，供拖拽到外部应用"""
        out = {}
        for mid in meme_ids:
            try:
                row = self._db.get_by_id(int(mid))
                if row:
                    p = self._find_meme_file(row["filename"])
                    if p:
                        out[int(mid)] = p
            except Exception:
                continue
        return out

    def start_native_drag(self, meme_id: int) -> bool:
        """用 WinForms DoDragDrop 启动原生文件拖拽（QQ/微信可接收真实文件）"""
        row = self._db.get_by_id(meme_id)
        if not row:
            return False
        p = self._find_meme_file(row["filename"])
        if not p:
            return False
        try:
            from .native_drag import start_native_drag as _start

            ok = bool(_start(p))
            if ok:
                self._webui.schedule_hide()
            return ok
        except Exception:
            return False

    def copy_meme(self, meme_id):
        # 复制表情到剪贴板；copy_resize_mode: 0不处理 1webp缩放 2转gif 3转gif隐写原图
        row = self._db.get_by_id(meme_id)
        if not row:
            return {"ok": False, "status": "copy_failed"}
        path = self._find_meme_file(row["filename"])
        if not path:
            return {"ok": False, "status": "copy_failed"}
        resize_mode = int(self._cfg.get("copy_resize_mode", 1) or 0)
        resize_max = int(self._cfg.get("copy_resize_max", 200) or 200)
        match resize_mode:
            case 1:
                path = convert_image_mode_1(path, resize_max) or path
            case 2:
                path = convert_image_mode_2(path, resize_max) or path
            case 3:
                path = convert_image_mode_3(path, resize_max) or path
        ok = copy_image_to_clipboard(path)
        if not ok:
            return {"ok": False, "status": "copy_failed"}
        if self._cfg.get("record_recent_use", True):
            self._db.record_use(meme_id)
        self._webui.schedule_hide()
        return {"ok": True, "status": "copied"}

    def toggle_favorite(self, meme_id: int) -> bool:
        return self._db.toggle_favorite(meme_id)

    def is_favorite(self, meme_id: int) -> bool:
        return self._db.is_favorite(meme_id)

    def rename_meme(self, meme_id: int, new_name: str) -> bool:
        if not new_name:
            return False
        try:
            self._db.update_meme(meme_id, original_name=new_name)
            build_manifest()
            return True
        except Exception as e:
            logging.getLogger(__name__).error(f"rename error: {e}")
            return False

    def _delete_meme_files(self, meme_id) -> bool:
        """删除磁盘原图+缩略图+file_cache 条目；id 不存在返回 False"""
        import os

        row = self._db.get_by_id(meme_id)
        if not row:
            return False
        file_path = self._find_meme_file(row["filename"])
        if file_path:
            try:
                os.remove(file_path)
            except Exception:
                pass
        thumb_dir = self._cfg.thumbnail_dir
        for f in thumb_dir.glob(f"{meme_id}_*.png"):
            try:
                f.unlink()
            except Exception:
                pass
        if hasattr(self._webui, "_file_cache"):
            self._webui._file_cache.pop(row["filename"], None)
        return True

    def delete_meme(self, meme_id: int) -> bool:
        if not self._delete_meme_files(meme_id):
            return False
        self._db.delete_meme(meme_id)
        build_manifest()
        return True

    def delete_memes(self, meme_ids: list) -> dict:
        """批量删除，返回 {ok, deleted}"""
        ids = list(dict.fromkeys(int(x) for x in (meme_ids or [])))
        deleted = 0
        for mid in ids:
            if self._delete_meme_files(mid):
                deleted += 1
        if deleted:
            self._db.delete_memes(ids)
            build_manifest()  # 只重建一次 manifest
        return {"ok": True, "deleted": deleted}

    # 递归获取分组及其所有子分组的 ID 列表
    def _get_collection_ids_recursive(self, collection_id):
        ids = [collection_id]
        children = self._db.get_child_collections(collection_id)
        for child in children:
            ids.extend(self._get_collection_ids_recursive(child["id"]))
        return ids

    # 构建嵌套分组树并统计各分组成员数
    def _build_collection_tree(self, parent_id=None):
        raw = self._db.get_collections()
        result = []
        for cid, name, pid, _ in raw:
            if pid != parent_id:
                continue
            children = self._build_collection_tree(parent_id=cid)
            all_ids = self._get_collection_ids_recursive(cid)
            cnt = self._db.count(collection_id=all_ids)
            item = {"id": cid, "name": name, "count": cnt}
            if children:
                item["children"] = children
            result.append(item)
        return result

    def get_collections(self) -> list:
        top = self._build_collection_tree()
        recent = self._db.get_recent(9999)
        sys_cols = [
            {"id": -2, "name": "收藏夹", "count": self._db.count(favorite_only=True)},
            {"id": -3, "name": "最近使用", "count": len(recent)},
        ]
        if self._cfg.get("show_uncategorized", True):
            sys_cols.append(
                {
                    "id": -4,
                    "name": "未分类",
                    "count": self._db.count(uncategorized_only=True),
                }
            )
        return sys_cols + top

    def get_child_collections(self, parent_id: int) -> list:
        return self._db.get_child_collections(parent_id)

    def search_collections(self, keyword: str = "") -> list:
        """按名称搜索已有分组（顶层 + 子分组），供添加分组弹窗下拉框"""
        kw = (keyword or "").strip().lower()
        out = []
        for item in self._flatten_collections():
            if not kw or kw in item["name"].lower():
                out.append(
                    {"id": item["id"], "name": item["name"], "depth": item["depth"]}
                )
        return out[:20]

    def get_collection_members(self, collection_id: int) -> list:
        """返回分组内表情成员，供添加分组弹窗右侧栏展示"""
        try:
            return self._db.search(collection_id=collection_id, limit=5000) or []
        except Exception:
            return []

    def _flatten_collections(self) -> list:
        """展平分组树（含子分组），带 depth"""
        out = []

        def walk(items, depth):
            for c in items:
                if c.get("id", 0) > 0:
                    out.append({"id": c["id"], "name": c["name"], "depth": depth})
                for ch in c.get("children", []) or []:
                    walk([ch], depth + 1)

        walk(self._build_collection_tree(), 0)
        return out

    def add_to_collection(self, meme_id: int, name: str) -> bool:
        cid = self._db.create_collection(name)
        if cid < 0:
            return False
        self._db.add_to_collection(meme_id, cid)
        return True

    def add_to_existing_collection(self, meme_id: int, collection_id: int) -> bool:
        try:
            self._db.add_to_collection(meme_id, collection_id)
            return True
        except Exception:
            return False

    def set_collection_members(self, collection_id: int, meme_ids: list) -> bool:
        """批量设置分组内成员（先清空再写入），供添加分组弹窗确定时保存右侧列表"""
        try:
            self._db.set_collection_members(collection_id, meme_ids)
            build_manifest()
            return True
        except Exception:
            return False

    def set_collection_members_new(self, name: str, meme_ids: list) -> dict:
        """创建新分组并批量设置成员，返回 {ok, id}"""
        try:
            if self._db.collection_exists(name):
                return {"ok": False, "error": "同名分组已存在，请从下拉框选择已有分组"}
            cid = self._db.create_collection(name)
            if cid < 0:
                return {"ok": False}
            self._db.set_collection_members(cid, meme_ids)
            build_manifest()
            return {"ok": True, "id": cid}
        except Exception:
            return {"ok": False}

    def reorder_memes(self, meme_ids: list) -> bool:
        try:
            self._db.reorder_memes(meme_ids)
            build_manifest()
            return True
        except Exception:
            return False

    def reorder_collections(self, collection_ids: list) -> bool:
        try:
            self._db.reorder_collections(collection_ids)
            build_manifest()
            return True
        except Exception:
            return False

    def reorder_collection_members(self, collection_id: int, meme_ids: list) -> bool:
        try:
            self._db.reorder_collection_members(collection_id, meme_ids)
            build_manifest()
            return True
        except Exception:
            return False

    def delete_collection(self, collection_id: int) -> bool:
        try:
            self._db.delete_collection(collection_id)
            return True
        except Exception:
            return False

    def rename_collection(self, collection_id: int, new_name: str) -> bool:
        if not new_name:
            return False
        try:
            self._db.rename_collection(collection_id, new_name)
            build_manifest()
            return True
        except Exception:
            return False

    def create_subcollection(self, name: str, parent_id: int) -> dict:
        depth = self._db.get_collection_depth(parent_id)
        if depth >= 1:
            return {"ok": False, "error": "最大支持1层小分组"}
        cid = self._db.create_collection(name, parent_id=parent_id)
        if cid < 0:
            return {"ok": False}
        return {"ok": True, "id": cid}

    def record_meme_use(self, meme_id: int) -> bool:
        try:
            self._db.record_use(meme_id)
            return True
        except Exception:
            return False

    def remove_from_recent(self, meme_id: int) -> bool:
        try:
            self._db.remove_from_recent(meme_id)
            return True
        except Exception:
            return False

    def clear_recent(self) -> bool:
        try:
            self._db.clear_recent()
            return True
        except Exception:
            return False

    def remove_from_collection(self, meme_id: int, collection_id: int) -> bool:
        self._db.remove_from_collection(meme_id, collection_id)
        return True

    def log(self, msg, level="info"):
        """供前端输出调试日志到终端"""
        getattr(logger, level, logger.info)(msg)

    def rescan_cache(self) -> bool:
        self._webui.scan_cache()
        return True

    # 非阻塞检查更新：新鲜缓存即返，首次/过期/force 触发后台检查返回 pending
    def check_update(self, debug=False, force=False) -> dict:
        from . import __version__ as cur_ver

        info = updater.check_latest_cached(force=bool(debug) or bool(force))
        info["current"] = cur_ver
        if debug or self._webui._update_debug:
            info["has_update"] = True
        return info

    def start_download(self, url: str) -> bool:
        return updater.start_download(url)

    def get_download_progress(self) -> dict:
        return updater.get_download_progress()

    def run_downloaded_installer(self) -> bool:
        ok = updater.run_downloaded_installer()
        if ok:
            self._webui._schedule_quit()
        return ok

    def download_update(self, url: str) -> dict:
        """同步下载（旧版，保留兼容）"""
        path = updater.download_release(url)
        if not path:
            return {"ok": False, "error": "download failed"}
        ok = updater.run_installer(path)
        return {"ok": ok, "error": "" if ok else "run installer failed"}

    def check_connectivity(self) -> dict:
        return _check_connectivity()

    def download_original_image(self, url: str) -> dict:
        """下载浏览器来源的原始图片，或导入本地文件"""
        s = url.strip()
        # 本地文件：file:// URI 或裸绝对路径
        local_path = None
        if s.startswith("file://"):
            from urllib.parse import unquote, urlparse

            local_path = unquote(urlparse(s).path)
            # Windows: file:///C:/path → /C:/path → 去掉前导 /
            if len(local_path) > 3 and local_path[2] == ":":
                local_path = local_path.lstrip("/")
        elif s.startswith("/") and os.path.isfile(s):
            local_path = s
        elif len(s) > 2 and s[1] == ":" and os.path.isfile(s):
            # Windows 裸路径: C:\Users\...
            local_path = s
        if local_path:
            return self._import_with_similar_decision(
                local_path, os.path.basename(local_path)
            )

        clean_url = _strip_url_modifiers(s)

        # 网络图片原图下载
        if not self._cfg.get("try_original_image", False):
            return {"ok": False, "error": "功能未启用"}
        conn = _check_connectivity()
        if not conn["ok"]:
            return {"ok": False, "error": "无网络连接"}
        import shutil
        import tempfile
        from urllib.error import URLError
        from urllib.parse import urlparse
        from urllib.request import urlopen

        # 从 URL 路径推断扩展名
        parsed_path = urlparse(clean_url).path
        _, ext = os.path.splitext(parsed_path)
        ext = ext.lower() if ext else ""
        allowed_img_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

        # URL 路径无扩展名时，从响应 Content-Type 推断
        need_type = not ext or ext not in allowed_img_ext

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".download")
        tmp_path = tmp.name
        tmp.close()
        try:
            with urlopen(clean_url, timeout=15) as resp:
                if need_type:
                    ct = resp.headers.get("Content-Type", "")
                    content_type = ct.split(";")[0].strip()
                    type_map = {
                        "image/gif": ".gif",
                        "image/png": ".png",
                        "image/jpeg": ".jpg",
                        "image/webp": ".webp",
                        "image/bmp": ".bmp",
                    }
                    ext = type_map.get(content_type, ".png")
                with open(tmp_path, "wb") as f:
                    shutil.copyfileobj(resp, f)
            # 重命名为正确扩展名
            final_path = tmp_path + ext
            os.rename(tmp_path, final_path)
            r = self._import_with_similar_decision(
                final_path, os.path.splitext(os.path.basename(clean_url))[0] or None
            )
            return r
        except URLError as e:
            return {"ok": False, "error": f"下载失败: {e.reason}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            try:
                os.unlink(tmp_path + ext)
            except Exception:
                pass

    def _import_with_similar_decision(self, path, oname=""):
        """单图导入决策：哈希命中提示已存在；内容近似转相似（委托 WebUI 统一逻辑）"""
        return self._webui._import_with_similar_decision(path, oname)

    def resolve_similar_import(self, token: str, action: str) -> dict:
        """响应用户对相似图的导入决策（action: discard/keep_old/keep_new/keep_both）"""
        item = _pop_pending_similar(token)
        if not item:
            return {"ok": False, "error": "决策已过期，请重新导入"}
        path = item["path"]
        action = action or "keep_new"
        if action in ("discard", "keep_old"):
            # 丢弃/仅保留旧图：删掉待决策临时文件，不导入
            try:
                os.unlink(path)
            except OSError:
                pass
            return {"ok": True, "action": action, "imported": False}
        # 取最相似候选（distance 最小）作为"旧图"，用于 keep_new 替换
        cands = item.get("candidates") or []
        best_id = (
            min(cands, key=lambda c: c.get("distance", 99))["id"] if cands else None
        )
        try:
            r = self._webui._do_import(
                [path], [item.get("oname")] if item.get("oname") else None
            )
        except Exception as e:
            logger.error("resolve similar import error: %s", e)
            return {"ok": False, "error": "导入失败"}
        finally:
            try:
                os.unlink(path)  # 清理待决策临时文件
            except OSError:
                pass
        ids = r.get("ids") or []
        if ids:
            replaced = False
            if action == "keep_new" and best_id:
                # keep_new：导入新图并替换旧图——完整删除链（文件+缩略图+缓存+DB）
                try:
                    replaced = self.delete_meme(best_id)
                except Exception as e:
                    logger.error("keep_new 替换旧图失败: %s", e)
            return {
                "ok": True,
                "id": ids[0],
                "imported": True,
                "replaced": replaced,
            }
        if r.get("rejected"):
            return {"ok": False, "error": "文件超过大小/分辨率限制，已跳过"}
        return {"ok": False, "error": "导入失败"}

    def get_sync_progress(self) -> dict:
        return sync_module.get_sync_progress()

    def sync_push(self) -> dict:
        try:
            r = sync_module.push()
            r["ok"] = True
            return r
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "failed_files": sync_module.get_sync_progress().get("failed_items", []),
            }

    def sync_pull(self) -> dict:
        try:
            r = sync_module.pull()
            r["ok"] = True
            return r
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "failed_files": sync_module.get_sync_progress().get("failed_items", []),
            }

    def run_auto_sync(self) -> dict:
        """启动时自动同步：根据配置拉取远端索引和/或全量同步"""
        result = {"fetched": False, "synced": False, "error": ""}
        sync_type = self._cfg.get("sync_type", "")
        if not sync_type:
            return result
        try:
            if self._cfg.get("sync_auto_fetch_index", False):
                from .sync import download_index

                data = download_index()
                result["fetched"] = data is not None
            if self._cfg.get("sync_auto_sync", False):
                from .sync import pull

                r = pull()
                result["synced"] = r.get("downloaded", 0) > 0
        except Exception as e:
            result["error"] = str(e)
        return result

    def sync_test(self) -> str:
        try:
            from .sync import sync_test as _test

            return _test()
        except Exception as e:
            return str(e)

    def import_memes(self) -> bool:
        # 通过系统文件对话框选择导入（后台执行，避免大数量导入阻塞界面）
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=("图片文件 (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)",),
            )
        except Exception:
            return {"ok": False}
        if not result:
            return {"ok": False, "cancelled": True}
        paths = list(result)
        if not start_import_job(self._webui, paths, None, False, ""):
            return {"ok": False, "error": "已有导入在进行中"}
        return {"ok": True, "async": True}

    def import_folder(self, make_collection=True) -> dict:
        """选择文件夹并导入其中全部图片；make_collection 时以文件夹名创建分组"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER, allow_multiple=False
            )
        except Exception:
            return {"ok": False, "error": "无法打开目录选择对话框"}
        if not result:
            return {"ok": False, "cancelled": True}
        folder = result[0] if isinstance(result, (tuple, list)) else result
        try:
            files = []
            names = []
            for root, _, fnames in os.walk(folder):
                for fn in sorted(fnames):
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in _ALLOWED_IMPORT_EXT:
                        continue
                    files.append(os.path.join(root, fn))
                    names.append(os.path.splitext(fn)[0])
            if not files:
                return {"ok": False, "error": "文件夹中没有支持的图片"}
            folder_name = os.path.basename(os.path.normpath(folder))
            if not start_import_job(
                self._webui, files, names, make_collection, folder_name
            ):
                return {"ok": False, "error": "已有导入在进行中"}
            return {"ok": True, "async": True, "total": len(files)}
        except Exception as e:
            logger.error(f"import_folder failed: {e}")
            return {"ok": False, "error": str(e)}

    def get_import_progress(self):
        # 后台导入进度快照（前端轮询用）
        return get_import_progress()

    def cancel_import_job(self):
        # 请求取消当前后台导入
        return cancel_import_job()

    def import_from_clipboard(self) -> dict:
        import hashlib
        import tempfile

        from PIL import ImageGrab

        try:
            clip = ImageGrab.grabclipboard()
        except Exception:
            return {"ok": False, "error": "读取剪贴板失败"}
        if clip is None:
            return {"ok": False, "error": "剪贴板中没有图片"}
        try:
            if isinstance(clip, list):
                paths = [p for p in clip if os.path.isfile(p)]
                if not paths:
                    return {"ok": False, "error": "剪贴板中没有图片文件"}
                r = self._webui._do_import(paths)
                ids = r.get("ids") or []
                rejected = r.get("rejected", 0)
                if ids:
                    row = self._db.get_by_id(ids[0])
                    orig = row["original_name"] if row else ""
                    return {
                        "ok": True,
                        "id": ids[0],
                        "name": orig or "未命名",
                        "rejected": rejected,
                    }
                return {"ok": True, "id": 0, "name": "未命名", "rejected": rejected}
            img = clip
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp_path = tmp.name
            tmp.close()
            try:
                img.save(tmp_path, "PNG")
                sha256 = hashlib.sha256()
                with open(tmp_path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha256.update(chunk)
                if self._db.get_by_hash(sha256.hexdigest()):
                    return {"ok": False, "error": "该图片已存在"}
                r = self._webui._do_import([tmp_path], [""])
                ids = r.get("ids") or []
                rejected = r.get("rejected", 0)
                if ids:
                    row = self._db.get_by_id(ids[0])
                    orig = row["original_name"] if row else ""
                    return {
                        "ok": True,
                        "id": ids[0],
                        "name": orig or "未命名",
                        "rejected": rejected,
                    }
                return {"ok": True, "id": 0, "name": "未命名", "rejected": rejected}
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_settings(self):
        return self._webui.open_settings()

    def lan_confirm_device(self, approved: bool) -> dict:
        from . import lan

        lan.confirm_device(bool(approved))
        return {"ok": True}

    def get_settings(self) -> dict:
        d = self._cfg.to_dict()
        from .platform_util import is_auto_start_enabled

        return {
            "hotkey": d.get("hotkey", "Ctrl+Alt+N"),
            "hotkey_show_at_mouse": d.get("hotkey_show_at_mouse", False),
            "auto_play_gif": d.get("auto_play_gif", True),
            "try_original_image": d.get("try_original_image", False),
            "auto_start": is_auto_start_enabled(),
            "silent_start": d.get("silent_start", False),
            "sync_auto_fetch_index": d.get("sync_auto_fetch_index", False),
            "sync_auto_sync": d.get("sync_auto_sync", False),
            "sync_type": d.get("sync_type", ""),
            "sync_delete_remote": d.get("sync_delete_remote", False),
            "sync_remove_local": d.get("sync_remove_local", False),
            "sync_hide_upload_warning": d.get("sync_hide_upload_warning", False),
            "ftp_host": d.get("ftp_host", ""),
            "ftp_port": d.get("ftp_port", 21),
            "ftp_user": d.get("ftp_user", ""),
            "ftp_password": d.get("ftp_password", ""),
            "ftp_path": d.get("ftp_path", "/"),
            "s3_endpoint": d.get("s3_endpoint", ""),
            "s3_region": d.get("s3_region", ""),
            "s3_bucket": d.get("s3_bucket", ""),
            "s3_access_key": d.get("s3_access_key", ""),
            "s3_secret_key": d.get("s3_secret_key", ""),
            "s3_path": d.get("s3_path", ""),
            "r2_account_id": d.get("r2_account_id", ""),
            "r2_access_key_id": d.get("r2_access_key_id", ""),
            "r2_secret_access_key": d.get("r2_secret_access_key", ""),
            "r2_bucket": d.get("r2_bucket", ""),
            "r2_path": d.get("r2_path", ""),
            "webdav_url": d.get("webdav_url", ""),
            "webdav_user": d.get("webdav_user", ""),
            "webdav_password": d.get("webdav_password", ""),
            "webdav_path": d.get("webdav_path", ""),
            "show_upload_progress": d.get("show_upload_progress", True),
            "show_upload_done": d.get("show_upload_done", True),
            "show_download_progress": d.get("show_download_progress", True),
            "show_download_done": d.get("show_download_done", True),
            "show_uncategorized": d.get("show_uncategorized", True),
            "record_recent_use": d.get("record_recent_use", True),
            "show_startup_animation": d.get("show_startup_animation", True),
        }

    def save_settings(self, settings: dict):
        if isinstance(settings, dict):
            if "auto_start" in settings:
                from .platform_util import set_auto_start

                set_auto_start(settings["auto_start"])
            self._cfg.update_from_dict(settings)
            self._cfg.save()
            if "hotkey" in settings:
                self._webui._on_hotkey_change(settings["hotkey"])

    def reset_settings(self) -> dict:
        prev_cache_dir = self._cfg.get("cache_dir", "")
        self._cfg.reset()
        if prev_cache_dir:
            self._cfg.set("cache_dir", prev_cache_dir)
        self._cfg.save()
        hotkey = self._cfg.get("hotkey", "Ctrl+Alt+N")
        self._webui._on_hotkey_change(hotkey)
        from .platform_util import set_auto_start

        set_auto_start(False)
        return {
            "hotkey": hotkey,
            "hotkey_show_at_mouse": self._cfg.get("hotkey_show_at_mouse", False),
            "auto_play_gif": self._cfg.get("auto_play_gif", True),
            "copy_resize_mode": self._cfg.get("copy_resize_mode", 1),
            "auto_start": False,
            "silent_start": False,
            "sync_auto_fetch_index": False,
            "sync_auto_sync": False,
            "sync_type": "",
            "sync_delete_remote": False,
            "sync_remove_local": False,
            "sync_hide_upload_warning": False,
            "ftp_host": "",
            "ftp_port": 21,
            "ftp_user": "",
            "ftp_password": "",
            "ftp_path": "/",
            "s3_endpoint": "",
            "s3_region": "",
            "s3_bucket": "",
            "s3_access_key": "",
            "s3_secret_key": "",
            "s3_path": "",
            "r2_account_id": "",
            "r2_access_key_id": "",
            "r2_secret_access_key": "",
            "r2_bucket": "",
            "r2_path": "",
            "webdav_url": "",
            "webdav_user": "",
            "webdav_password": "",
            "webdav_path": "",
            "show_upload_progress": True,
            "show_upload_done": True,
            "show_download_progress": True,
            "show_download_done": True,
            "show_startup_animation": True,
        }

    def move_window(self, dx: int, dy: int):
        w = self._webui._window
        if not w:
            return
        try:
            origin, last, target = _window_drag_update(
                w.x, w.y, self._drag_origin, self._drag_last_move, dx, dy
            )
            self._drag_origin, self._drag_last_move = origin, last
            if target:
                w.move(*target)
        except Exception:
            pass

    def stop_window_drag(self):
        self._drag_origin = None

    def start_window_drag(self, button: int, root_x: int, root_y: int) -> bool:
        """Linux 用 GTK begin_move_drag 合成器拖动；其他平台走增量回退"""
        self._drag_origin = None
        if platform.system() != "Linux":
            return False
        w = self._webui._window
        if not w:
            return False
        try:
            from gi.repository import Gdk, GLib

            native = getattr(w, "native", None)
            if native is None:
                return False
            # Gdk.CURRENT_TIME(0)：GDK 文档明确允许未知时间时用它，X11 下回填最近
            # 一次真实输入事件时间，Wayland 下该参数不参与合成器拖动
            GLib.idle_add(
                native.begin_move_drag, button, root_x, root_y, Gdk.CURRENT_TIME
            )
            return True
        except Exception:
            return False

    def hide_window(self):
        self._webui.hide()

    def _find_meme_file(self, filename: str) -> str:
        cache_dir = self._cfg.cache_dir
        for root, _, files in os.walk(cache_dir):
            if filename in files:
                return os.path.join(root, filename)
        return ""


# ─── QQNT 提取驱动（后台线程 + 状态，供设置页向导轮询） ───

_QQNT_STATE = {
    "status": "idle",  # idle|running|done|cancelled|error
    "progress": 0,
    "message": "",
    "error": "",
    "log": [],
    "result": None,
}
_QQNT_LOCK = threading.Lock()
_QQNT_CANCEL = False


def _set_qqnt(**kw):
    with _QQNT_LOCK:
        _QQNT_STATE.update(**kw)


def _append_qqnt_log(msg):
    with _QQNT_LOCK:
        _QQNT_STATE["log"] = (_QQNT_STATE["log"] + [msg])[-100:]


def get_qqnt_progress() -> dict:
    with _QQNT_LOCK:
        return dict(_QQNT_STATE)


def cancel_qqnt_extract():
    global _QQNT_CANCEL
    _QQNT_CANCEL = True


def start_qqnt_extract(
    qq_number: str,
    output_dir: str,
    image_only: bool = False,
    overwrite: bool = False,
    ini_path: str = None,
    userdata_save_path: str = None,
) -> bool:
    global _QQNT_CANCEL
    _QQNT_CANCEL = False
    _set_qqnt(
        status="running", progress=0, message="准备中", error="", log=[], result=None
    )
    threading.Thread(
        target=_qqnt_worker,
        args=(
            qq_number,
            output_dir,
            image_only,
            overwrite,
            ini_path,
            userdata_save_path,
        ),
        daemon=True,
    ).start()
    return True


def _qqnt_worker(
    qq_number, output_dir, image_only, overwrite, ini_path, userdata_save_path
):
    """后台执行 QQNT 表情提取：调用 qqnt_extract 并转发进度/错误到 _QQNT_STATE"""

    def on_progress(done, total, src, dst):
        pct = int(done * 100 / total) if total else 0
        _set_qqnt(progress=pct, message="复制中 %d/%d" % (done, total))

    def on_error(src, msg):
        _append_qqnt_log("失败: %s (%s)" % (src, msg))

    def on_log(msg):
        _append_qqnt_log(msg)

    try:
        result = qqnt_extract.extract_qq_emojis(
            qq_number,
            output_dir,
            userdata_save_path=userdata_save_path,
            ini_path=ini_path or qqnt_extract.DEFAULT_INI_PATH,
            image_only=image_only,
            overwrite=overwrite,
            should_stop=lambda: _QQNT_CANCEL,
            on_progress=on_progress,
            on_error=on_error,
            on_log=on_log,
        )
        if _QQNT_CANCEL:
            _set_qqnt(status="cancelled", message="已取消", result=result)
        else:
            _set_qqnt(status="done", progress=100, message="提取完成", result=result)
    except Exception as e:
        logger.error("qqnt extract error: %s", e)
        _set_qqnt(status="error", message="提取失败", error=str(e))


# ─── 存储位置迁移进度（后台线程 + 轮询） ───
_STORAGE_MIGRATE_STATE = {
    "status": "idle",  # idle|running|done|error|cancelled
    "progress": 0,
    "message": "",
    "current": "",
    "moved": 0,
    "total": 0,
    "failed": [],
    "error": "",
    "cancel_requested": False,
}
_STORAGE_MIGRATE_LOCK = threading.Lock()
_STORAGE_MIGRATE_THREAD = None


def _set_storage_migrate(**kw):
    with _STORAGE_MIGRATE_LOCK:
        _STORAGE_MIGRATE_STATE.update(**kw)


def get_storage_migration_progress() -> dict:
    import copy

    with _STORAGE_MIGRATE_LOCK:
        return copy.deepcopy(_STORAGE_MIGRATE_STATE)


def cancel_storage_migration():
    with _STORAGE_MIGRATE_LOCK:
        if _STORAGE_MIGRATE_STATE["status"] == "running":
            _STORAGE_MIGRATE_STATE["cancel_requested"] = True
    return {"ok": True}


def start_storage_migration_thread(new_dir: Path):
    """后台迁移 cache_dir 文件到 new_dir，避免阻塞桥接与 UI"""
    global _STORAGE_MIGRATE_THREAD
    old = get_config().cache_dir
    with _STORAGE_MIGRATE_LOCK:
        if _STORAGE_MIGRATE_STATE["status"] == "running":
            return False
        _STORAGE_MIGRATE_STATE.update(
            status="running",
            progress=0,
            message="准备迁移",
            current="",
            moved=0,
            total=0,
            failed=[],
            error="",
            cancel_requested=False,
        )
    _STORAGE_MIGRATE_THREAD = threading.Thread(
        target=_storage_migrate_worker,
        args=(old, new_dir),
        daemon=True,
    )
    _STORAGE_MIGRATE_THREAD.start()
    return True


def _storage_migrate_worker(old: Path, new: Path):
    """两阶段迁移：预检冲突 → 逐文件移动（含取消支持）"""
    import shutil

    moved_pairs = []
    try:
        # 阶段一：扫描 + 预检冲突
        plan = []
        for root, dirs, files in os.walk(str(old)):
            rel = os.path.relpath(root, str(old))
            for d in list(dirs):
                if d == "thumbnails":
                    dirs.remove(d)
            for name in files:
                src = os.path.join(root, name)
                dst = (new if rel == "." else new / rel) / name
                plan.append((src, dst))
        total = len(plan)
        _set_storage_migrate(total=total, message="预检目标目录...")
        if plan:
            collisions = [
                {
                    "name": os.path.basename(src),
                    "path": os.path.relpath(src, str(old)),
                }
                for src, dst in plan
                if dst.exists()
            ]
            if collisions:
                _set_storage_migrate(
                    status="error",
                    message="目标目录已存在同名文件，未迁移",
                    error="目标目录已存在 %d 个同名文件" % len(collisions),
                    failed=[],
                )
                return
        moved = 0
        for src, dst in plan:
            with _STORAGE_MIGRATE_LOCK:
                cancel_requested = _STORAGE_MIGRATE_STATE["cancel_requested"]
            if cancel_requested:
                for s, d in reversed(moved_pairs):
                    try:
                        shutil.move(str(d), s)
                    except OSError:
                        pass
                _set_storage_migrate(
                    status="cancelled", message="已取消，已回滚已移动文件"
                )
                return
            dst.parent.mkdir(parents=True, exist_ok=True)
            # 排他创建目标（O_EXCL：目标已存在则抛 FileExistsError，
            # 防 precheck→write 期间并发覆盖既有文件），O_WRONLY 确保 fd 可写
            try:
                fd = os.open(str(dst), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o644)
            except FileExistsError:
                # 迁移期间目标被其他进程新建：并发冲突，整批回滚并报清晰错误
                for s, d in reversed(moved_pairs):
                    try:
                        shutil.move(str(d), s)
                    except OSError:
                        pass
                _set_storage_migrate(
                    status="error",
                    message="迁移失败：目标目录出现同名文件（与进程冲突），已回滚",
                    error=f"目标已存在: {dst}",
                )
                return
            try:
                with os.fdopen(fd, "wb") as out_f, open(src, "rb") as in_f:
                    shutil.copyfileobj(in_f, out_f)
            except Exception:
                try:
                    os.unlink(str(dst))  # 清理复制中途失败留下的半写孤儿目标
                except OSError:
                    pass
                raise
            try:
                os.unlink(src)
            except OSError:
                pass  # 源删除失败不阻断（目标已排他写入成功）
            moved_pairs.append((src, dst))
            moved += 1
            _set_storage_migrate(
                progress=int(moved * 100 / total) if total else 100,
                moved=moved,
                current=os.path.basename(src),
            )
        # 迁移成功后写入新配置（回滚场景不写入，保持旧目录）
        get_config().set("cache_dir", str(new))
        get_config().save()
        _set_storage_migrate(
            status="done", progress=100, message="迁移完成", current=""
        )
        try:
            if len(webview.windows) > 0:
                webview.windows[0].evaluate_js("refreshMemes();")
        except Exception:
            pass
    except Exception as e:
        logger.error("storage migrate error: %s", e)
        # 回滚已移动文件，保持旧目录完整
        for s, d in reversed(moved_pairs):
            try:
                shutil.move(str(d), s)
            except OSError:
                pass
        _set_storage_migrate(status="error", message="迁移失败", error=str(e))


class SettingsApi:
    """暴露给设置窗口的 JS API（仅设置相关方法）"""

    def __init__(self, webui):
        self._webui = webui
        self._cfg = get_config()
        self._drag_origin = None
        self._drag_last_move = 0.0

    def check_connectivity(self) -> dict:
        return _check_connectivity()

    def lan_start(self, port: int = None, secret: str = None) -> dict:
        from . import lan

        p = int(port or self._cfg.get("lan_port", 17852))
        s = secret if secret is not None else self._cfg.get("lan_secret", "")
        ok = lan.start(p, s)
        return {"ok": ok, "status": lan.get_status()}

    def lan_stop(self) -> dict:
        from . import lan

        lan.stop()
        return {"ok": True, "status": lan.get_status()}

    def lan_get_status(self) -> dict:
        from . import lan

        return lan.get_status()

    def lan_get_ip(self) -> str:
        from . import lan

        return lan.get_lan_ip()

    def lan_set_allow_secret_config(self, enabled: bool) -> dict:
        from . import lan

        lan.set_allow_secret_config(bool(enabled))
        return {
            "ok": True,
            "allow_secret_config": lan.get_status()["allow_secret_config"],
        }

    def get_settings(self) -> dict:
        d = self._cfg.to_dict()
        from .platform_util import is_auto_start_enabled

        return {
            "hotkey": d.get("hotkey", "Ctrl+Alt+N"),
            "hotkey_show_at_mouse": d.get("hotkey_show_at_mouse", False),
            "auto_play_gif": d.get("auto_play_gif", True),
            "try_original_image": d.get("try_original_image", False),
            "copy_resize_mode": int(d.get("copy_resize_mode", 1) or 0),
            "cache_dir": str(self._cfg.cache_dir),
            "lan_port": d.get("lan_port", 17852),
            "lan_secret": d.get("lan_secret", ""),
            "auto_start": is_auto_start_enabled(),
            "silent_start": d.get("silent_start", False),
            "sync_auto_fetch_index": d.get("sync_auto_fetch_index", False),
            "sync_auto_sync": d.get("sync_auto_sync", False),
            "sync_type": d.get("sync_type", ""),
            "sync_delete_remote": d.get("sync_delete_remote", False),
            "sync_remove_local": d.get("sync_remove_local", False),
            "sync_hide_upload_warning": d.get("sync_hide_upload_warning", False),
            "ftp_host": d.get("ftp_host", ""),
            "ftp_port": d.get("ftp_port", 21),
            "ftp_user": d.get("ftp_user", ""),
            "ftp_password": d.get("ftp_password", ""),
            "ftp_path": d.get("ftp_path", "/"),
            "s3_endpoint": d.get("s3_endpoint", ""),
            "s3_region": d.get("s3_region", ""),
            "s3_bucket": d.get("s3_bucket", ""),
            "s3_access_key": d.get("s3_access_key", ""),
            "s3_secret_key": d.get("s3_secret_key", ""),
            "s3_path": d.get("s3_path", ""),
            "r2_account_id": d.get("r2_account_id", ""),
            "r2_access_key_id": d.get("r2_access_key_id", ""),
            "r2_secret_access_key": d.get("r2_secret_access_key", ""),
            "r2_bucket": d.get("r2_bucket", ""),
            "r2_path": d.get("r2_path", ""),
            "webdav_url": d.get("webdav_url", ""),
            "webdav_user": d.get("webdav_user", ""),
            "webdav_password": d.get("webdav_password", ""),
            "webdav_path": d.get("webdav_path", ""),
            "show_upload_progress": d.get("show_upload_progress", True),
            "show_upload_done": d.get("show_upload_done", True),
            "show_download_progress": d.get("show_download_progress", True),
            "show_download_done": d.get("show_download_done", True),
            "show_uncategorized": d.get("show_uncategorized", True),
            "record_recent_use": d.get("record_recent_use", True),
            "show_startup_animation": d.get("show_startup_animation", True),
            "tg_tdata_path": d.get("tg_tdata_path", ""),
            "hover_to_play": d.get("hover_to_play", False),
        }

    def _safe_refresh(self, js_function: str) -> dict:
        """执行前端刷新函数，并在异常时记录日志"""
        try:
            if len(webview.windows) > 0:
                webview.windows[0].evaluate_js(f"{js_function}();")
        except Exception:
            logger.exception("前端刷新函数 %s 执行失败", js_function)
        return {"ok": True}

    def refresh_memes(self):
        """设置窗口同步完成后刷新主窗口表情列表"""
        return self._safe_refresh("refreshMemes")

    def refresh_tags(self):
        """设置窗口同步完成后刷新主窗口标签栏"""
        return self._safe_refresh("refreshTags")

    def refresh_collections(self):
        """设置窗口同步完成后刷新主窗口分组树"""
        return self._safe_refresh("refreshCollections")

    def save_settings(self, settings: dict):
        if isinstance(settings, dict):
            if "auto_start" in settings:
                from .platform_util import set_auto_start

                set_auto_start(settings["auto_start"])
            self._cfg.update_from_dict(settings)
            self._cfg.save()
            if "hotkey" in settings:
                self._webui._on_hotkey_change(settings["hotkey"])
            try:
                if len(webview.windows) > 0:
                    webview.windows[0].evaluate_js("refreshMemes();")
            except Exception:
                pass

    def reset_settings(self) -> dict:
        prev_cache_dir = self._cfg.get("cache_dir", "")
        self._cfg.reset()
        if prev_cache_dir:
            self._cfg.set("cache_dir", prev_cache_dir)
        self._cfg.save()
        hotkey = self._cfg.get("hotkey", "Ctrl+Alt+N")
        self._webui._on_hotkey_change(hotkey)
        from .platform_util import set_auto_start

        set_auto_start(False)
        try:
            if len(webview.windows) > 0:
                webview.windows[0].evaluate_js("refreshMemes();")
        except Exception:
            pass
        return {
            "hotkey": hotkey,
            "hotkey_show_at_mouse": self._cfg.get("hotkey_show_at_mouse", False),
            "auto_play_gif": self._cfg.get("auto_play_gif", True),
            "copy_resize_mode": self._cfg.get("copy_resize_mode", 1),
            "auto_start": False,
            "silent_start": False,
            "sync_auto_fetch_index": False,
            "sync_auto_sync": False,
            "sync_type": "",
            "sync_delete_remote": False,
            "sync_remove_local": False,
            "sync_hide_upload_warning": False,
            "ftp_host": "",
            "ftp_port": 21,
            "ftp_user": "",
            "ftp_password": "",
            "ftp_path": "/",
            "s3_endpoint": "",
            "s3_region": "",
            "s3_bucket": "",
            "s3_access_key": "",
            "s3_secret_key": "",
            "s3_path": "",
            "r2_account_id": "",
            "r2_access_key_id": "",
            "r2_secret_access_key": "",
            "r2_bucket": "",
            "r2_path": "",
            "webdav_url": "",
            "webdav_user": "",
            "webdav_password": "",
            "webdav_path": "",
            "show_upload_progress": True,
            "show_upload_done": True,
            "show_download_progress": True,
            "show_download_done": True,
            "record_recent_use": True,
            "show_startup_animation": True,
            "tg_tdata_path": self._cfg.get("tg_tdata_path", ""),
            "hover_to_play": self._cfg.get("hover_to_play", False),
        }

    def move_window(self, dx: int, dy: int):
        w = self._webui._settings_window
        if not w:
            return
        try:
            origin, last, target = _window_drag_update(
                w.x, w.y, self._drag_origin, self._drag_last_move, dx, dy
            )
            self._drag_origin, self._drag_last_move = origin, last
            if target:
                w.move(*target)
        except Exception:
            pass

    def stop_window_drag(self):
        self._drag_origin = None

    def start_window_drag(self, button: int, root_x: int, root_y: int) -> bool:
        """Linux 用 GTK begin_move_drag 合成器拖动；其他平台走增量回退"""
        self._drag_origin = None
        if platform.system() != "Linux":
            return False
        w = self._webui._settings_window
        if not w:
            return False
        try:
            from gi.repository import Gdk, GLib

            native = getattr(w, "native", None)
            if native is None:
                return False
            # Gdk.CURRENT_TIME(0)：GDK 文档明确允许未知时间时用它，X11 下回填最近
            # 一次真实输入事件时间，Wayland 下该参数不参与合成器拖动
            GLib.idle_add(
                native.begin_move_drag, button, root_x, root_y, Gdk.CURRENT_TIME
            )
            return True
        except Exception:
            return False

    def start_qq_import(self) -> dict:
        adb_util.start_qq_import()
        return {"ok": True}

    def get_qq_import_progress(self) -> dict:
        return adb_util.get_qq_progress()

    def save_qq_zip(self) -> dict:
        """把生成的 QQ ZIP 通过另存为对话框保存到用户选择的位置"""
        st = adb_util.get_qq_progress()
        if st["status"] != "done" or not st["zip_path"]:
            return {"ok": False, "error": "no zip ready"}
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.SAVE,
                allow_multiple=False,
                file_types=("ZIP 文件 (*.zip)",),
            )
        except Exception:
            return {"ok": False, "error": "dialog failed"}
        if not result:
            return {"ok": False, "error": "cancelled"}
        import shutil

        dst = result[0] if isinstance(result, (tuple, list)) else result
        if not dst.lower().endswith(".zip"):
            dst += ".zip"
        src = st["zip_path"]
        shutil.copy2(src, dst)
        try:
            os.unlink(src)
        except OSError:
            pass
        adb_util.reset_qq_import()
        return {"ok": True, "path": dst}

    def open_adb_folder(self) -> bool:
        try:
            adb_util.open_adb_folder()
            return True
        except Exception:
            return False

    def export_logs(self) -> dict:
        """导出本次运行收集的日志（DEBUG 级）到用户选择的位置"""
        win = self._webui._settings_window or (
            webview.windows[0] if webview.windows else None
        )
        if not win:
            return {"ok": False, "error": "no window"}
        try:
            result = win.create_file_dialog(
                webview.FileDialog.SAVE,
                allow_multiple=False,
                save_filename="OhMyMeme-logs.txt",
                file_types=("文本文件 (*.txt)",),
            )
        except Exception as e:
            logger.warning(f"export_logs dialog error: {e!r}")
            return {"ok": False, "error": "dialog failed"}
        if not result:
            return {"ok": False, "error": "cancelled"}
        dst = result[0] if isinstance(result, (tuple, list)) else result
        if not dst.lower().endswith(".txt"):
            dst += ".txt"
        with _LOG_LOCK:
            lines = list(_LOG_BUFFER)
        if not lines:
            return {"ok": False, "error": "no logs"}
        try:
            with open(dst, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except OSError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "path": dst, "count": len(lines)}

    def open_adb_help(self) -> bool:
        try:
            adb_util.open_adb_help()
            return True
        except Exception:
            return False

    def cancel_qq_import(self):
        adb_util.cancel_qq_import()

    def pick_tg_tdata(self) -> dict:
        """手动选择 Telegram Desktop tdata 目录（校验并持久化）"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER, allow_multiple=False
            )
        except Exception:
            return {"ok": False, "error": "无法打开目录选择对话框"}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        if not tg_stickers.is_valid_tdata(path):
            return {
                "ok": False,
                "error": "所选目录不是有效的 tdata 目录（未找到 key_datas）",
            }
        self._cfg.set("tg_tdata_path", path)
        self._cfg.save()
        return {"ok": True, "path": path}

    def start_tg_import(self, tdata_path=None, passcode="", convert_webm=True) -> dict:
        """启动 Telegram 缓存导入，已有任务时返回 {"ok": False, "error"}"""
        if not tdata_path:
            tdata_path = self._cfg.get("tg_tdata_path", "") or None
        started = tg_stickers.start_tg_import(
            self._webui, tdata_path, passcode, convert_webm
        )
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_tg_import_progress(self) -> dict:
        return tg_stickers.get_tg_progress()

    def cancel_tg_import(self):
        tg_stickers.cancel_tg_import()

    def start_douyin_import(self, cookie: str) -> dict:
        """启动抖音表情包下载导入（全部下载）"""
        try:
            from . import douyin
        except ImportError as e:
            return {"ok": False, "error": f"缺少依赖: {e}"}

        started = douyin.start_douyin_import(self._webui, cookie)
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_douyin_import_progress(self) -> dict:
        from . import douyin

        return douyin.get_douyin_progress()

    def cancel_douyin_import(self):
        from . import douyin

        douyin.cancel_douyin_import()

    def pick_wechat_root(self):
        """手动选择微信文件根目录"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER, allow_multiple=False
            )
        except Exception:
            return {"ok": False, "error": "无法打开目录选择对话框"}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        if not os.path.isdir(path):
            return {"ok": False, "error": "所选目录不存在"}
        return {"ok": True, "path": path}

    def inspect_wechat_environment(self, user_root=None):
        """检测微信环境"""
        from . import wechat_probe

        return wechat_probe.inspect_wechat_environment(user_root)

    def list_wechat_stickers(self, user_root, account_path=None):
        """列出可导入的微信表情"""
        from . import wechat_probe

        return wechat_probe.list_wechat_stickers(user_root, account_path)

    def start_wechat_import(self, user_root=None, download=True, account_path=None):
        """启动微信表情包导入，已有任务时返回 {"ok": False}"""
        from . import wechat_probe

        started = wechat_probe.start_wechat_import(
            self._webui, user_root, download, account_path
        )
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_wechat_import_progress(self):
        """获取微信导入进度"""
        from . import wechat_probe

        return wechat_probe.get_wechat_progress()

    def cancel_wechat_import(self):
        """取消微信导入"""
        from . import wechat_probe

        wechat_probe.cancel_wechat_import()

    def qqnt_check_env(self) -> dict:
        """检查 QQNT 提取环境，返回 get_extract_status 结果"""
        return qqnt_extract.get_extract_status(
            ini_path=self._cfg.get("qqnt_ini_path") or qqnt_extract.DEFAULT_INI_PATH,
            userdata_save_path=self._cfg.get("qqnt_userdata_path") or None,
            fetch_nicknames=True,
        )

    def qqnt_pick_ini(self) -> dict:
        """选择 UserDataInfo.ini，保存到配置并返回环境状态"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=False,
                file_types=("INI Files (*.ini);;All Files (*)",),
            )
        except Exception:
            return {"ok": False}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        self._cfg.set("qqnt_ini_path", path)
        self._cfg.set("qqnt_userdata_path", "")
        self._cfg.save()
        return self.qqnt_check_env()

    def qqnt_pick_userdata(self) -> dict:
        """选择用户数据目录，保存到配置并返回环境状态"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER, allow_multiple=False
            )
        except Exception:
            return {"ok": False}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        self._cfg.set("qqnt_userdata_path", path)
        self._cfg.save()
        return self.qqnt_check_env()

    def qqnt_pick_base(self) -> dict:
        """选择保存基础目录"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER, allow_multiple=False
            )
        except Exception:
            return {"ok": False}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        return {"ok": True, "base": path}

    def get_storage_info(self):
        """返回存储目录信息（供设置页展示）"""
        cfg = self._cfg
        cache = cfg.cache_dir
        count = 0
        total = 0
        try:
            if cache.exists():
                for root, dirs, files in os.walk(str(cache)):
                    for d in list(dirs):
                        if d == "thumbnails":
                            dirs.remove(d)
                    for name in files:
                        count += 1
                        try:
                            total += (Path(root) / name).stat().st_size
                        except OSError:
                            pass
        except OSError:
            pass
        return {
            "cache_dir": str(cache),
            "data_dir": str(cfg.data_dir),
            "custom": bool(cfg.get("cache_dir", "")),
            "file_count": count,
            "total_size": total,
        }

    def pick_storage_dir(self):
        """选择新的表情包存储目录（只返回路径，不立即生效）"""
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.FOLDER, allow_multiple=False
            )
        except Exception:
            return {"ok": False, "error": "dialog failed"}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        return {"ok": True, "path": path}

    def apply_storage_dir(self, path, move_files=False):
        """应用新的表情包存储目录；move_files=True 时后台迁移现有文件"""
        old = self._cfg.cache_dir
        protected = (self._cfg.data_dir, self._cfg.thumbnail_dir)
        ok, err = _storage_dir_validation(path, str(old), protected)
        if not ok:
            return {"ok": False, "error": err}
        new = Path(path).resolve()
        try:
            new.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "error": f"创建目录失败: {e}"}
        if not os.access(new, os.W_OK):
            return {"ok": False, "error": "目标目录不可写"}
        if not move_files:
            self._cfg.set("cache_dir", str(new))
            self._cfg.save()
            self._invalidate_cache_refresh()
            return {"ok": True, "cache_dir": str(new), "moved": 0, "failed": []}
        started = start_storage_migration_thread(new)
        if not started:
            return {"ok": False, "error": "有迁移任务正在运行"}
        # 后台迁移进行中，前端轮询 get_storage_migration_progress()
        return {"ok": True, "async": True, "cache_dir": str(new)}

    def _invalidate_cache_refresh(self):
        fc = getattr(self._webui, "_file_cache", None)
        if fc is not None:
            fc.clear()
        try:
            if len(webview.windows) > 0:
                webview.windows[0].evaluate_js("refreshMemes();")
        except Exception:
            pass

    def get_storage_migration_progress(self) -> dict:
        return get_storage_migration_progress()

    def cancel_storage_migration(self) -> dict:
        return cancel_storage_migration()

    def qqnt_default_dir(self, base: str, qq_number: str) -> dict:
        """按账号生成默认输出目录（昵称+QQ号）"""
        try:
            d = qqnt_extract.get_default_output_dir(
                base, qq_number, fetch_nickname=True
            )
        except Exception:
            return {"ok": False}
        return {"ok": True, "dir": d}

    def qqnt_start(
        self,
        qq_number: str,
        output_dir: str,
        image_only: bool = False,
        overwrite: bool = False,
    ) -> dict:
        ok = start_qqnt_extract(
            qq_number,
            output_dir,
            image_only=image_only,
            overwrite=overwrite,
            ini_path=self._cfg.get("qqnt_ini_path") or None,
            userdata_save_path=self._cfg.get("qqnt_userdata_path") or None,
        )
        return {"ok": ok}

    def qqnt_get_progress(self) -> dict:
        return get_qqnt_progress()

    def qqnt_cancel(self):
        cancel_qqnt_extract()

    def qqnt_open_dir(self, path: str) -> bool:
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                import subprocess

                subprocess.Popen(["open", path])
            else:
                import subprocess

                subprocess.Popen(["xdg-open", path])
            return True
        except Exception:
            return False

    def import_memes(self) -> dict:
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=("图片文件 (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)",),
            )
        except Exception:
            return {"ok": False}
        if not result:
            return {"ok": False, "cancelled": True}
        r = self._webui._do_import(result)
        return {
            "ok": True,
            "imported": len(r.get("ids") or []),
            "rejected": r.get("rejected", 0),
        }

    def close_settings(self):
        self._webui.close_settings()

    def get_current_version(self) -> str:
        from . import __version__

        return __version__

    # 非阻塞检查更新：新鲜缓存即返，首次/过期/force 触发后台检查返回 pending
    def check_update(self, debug=False, force=False) -> dict:
        from . import __version__ as cur_ver

        info = updater.check_latest_cached(force=bool(debug) or bool(force))
        info["current"] = cur_ver
        if debug or self._webui._update_debug:
            info["has_update"] = True
        return info

    def start_download(self, url: str) -> bool:
        return updater.start_download(url)

    def get_download_progress(self) -> dict:
        return updater.get_download_progress()

    def run_downloaded_installer(self) -> bool:
        ok = updater.run_downloaded_installer()
        if ok:
            self._webui._schedule_quit()
        return ok

    def download_update(self, url: str) -> dict:
        path = updater.download_release(url)
        if not path:
            return {"ok": False, "error": "download failed"}
        ok = updater.run_installer(path)
        return {"ok": ok, "error": "" if ok else "run installer failed"}

    def get_sync_progress(self) -> dict:
        return sync_module.get_sync_progress()

    def sync_push(self, delete_remote: bool = None) -> dict:
        try:
            r = sync_module.push(delete_remote=delete_remote)
            r["ok"] = True
            return r
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "failed_files": sync_module.get_sync_progress().get("failed_items", []),
            }

    def sync_pull(self, remove_local: bool = None) -> dict:
        try:
            r = sync_module.pull(remove_local=remove_local)
            r["ok"] = True
            # 刷新主窗口数据
            try:
                if len(webview.windows) > 0:
                    webview.windows[0].evaluate_js(
                        "refreshMemes();refreshTags();refreshCollections();"
                    )
            except Exception:
                pass
            return r
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "failed_files": sync_module.get_sync_progress().get("failed_items", []),
            }

    def sync_test(self) -> str:
        try:
            from .sync import sync_test as _test

            return _test()
        except Exception as e:
            return str(e)

    def delete_all_local(self) -> dict:
        """删除本地所有表情包"""
        try:
            db = get_db()
            db.delete_all()
            cache = self._cfg.cache_dir
            if cache.exists():
                for f in cache.iterdir():
                    if f.is_file():
                        f.unlink()
            thumbs = self._cfg.thumbnail_dir
            if thumbs.exists():
                for f in thumbs.iterdir():
                    if f.is_file():
                        f.unlink()
            from .manifest import build as build_manifest

            build_manifest()
            try:
                if len(webview.windows) > 0:
                    webview.windows[0].evaluate_js(
                        "refreshMemes();refreshTags();refreshCollections();"
                    )
            except Exception:
                pass
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def delete_all_cloud(self) -> dict:
        """删除云端所有表情包"""
        try:
            return sync_module.delete_all_remote()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_remote_orphans(self, delete: bool = False) -> dict:
        """扫描云端孤儿文件；delete=True 时物理删除"""
        try:
            return sync_module.cleanup_remote_orphans(delete=delete)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def check_sync_status(self) -> dict:
        """比较本地与云端同步状态"""
        try:
            from .sync import download_index

            manifest = download_index()
            if not manifest:
                return {"ok": False, "error": "无法获取远端索引"}
            db = get_db()
            local_rows = db.search(keyword="", tags=None, limit=999999)
            local_count = len(local_rows)
            local_filenames = {r["filename"] for r in local_rows}
            remote_memes = manifest.get("memes", [])
            remote_count = len(remote_memes)
            remote_filenames = {m["filename"] for m in remote_memes}
            local_extra = local_filenames - remote_filenames
            local_missing = remote_filenames - local_filenames
            if not local_extra and not local_missing:
                return {
                    "ok": True,
                    "synced": True,
                    "local_count": local_count,
                    "remote_count": remote_count,
                }
            return {
                "ok": True,
                "synced": False,
                "local_count": local_count,
                "remote_count": remote_count,
                "local_extra": len(local_extra),
                "local_missing": len(local_missing),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}


def _file_sha256(path):
    """计算文件 SHA-256"""
    import hashlib

    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


# 感知哈希去重（pHash）：内容近似但 SHA-256 不同时，判定汉明距离阈值
_PHASH_SIMILAR_DIST = 12  # 64 位感知哈希的汉明距离阈值，≤此值视为近似
_PHASH_SYNC_BACKFILL_MAX = 5  # 缺失 phash 行数超过此值则后台异步回填，避免阻塞导入
_PHASH_CACHE = {}  # 文件路径 → (mtime, size, hash)：避免对大库重复全解码
_PHASH_CACHE_LOCK = threading.Lock()
_PHASH_BACKFILL_LOCK = threading.Lock()
_PHASH_BACKFILLING = False  # 当前是否有后台回填线程在跑（防重入）
_IMPORT_LOCK = threading.Lock()  # 串行化 _do_import 关键区，防并发导入同图重复

# 后台导入进度（文件夹/文件对话框/剪贴板等交互式多文件导入）
_IMPORT_JOB_STATE = {
    "status": "idle",  # idle|running|done|error|cancelled
    "progress": 0,
    "message": "",
    "current": "",
    "done": 0,
    "total": 0,
    "imported": 0,
    "rejected": 0,
    "skipped_dup": 0,
    "error": "",
    "token": None,  # 任务代次：旧 worker 令牌不匹配时不覆盖新任务状态
}
_IMPORT_JOB_LOCK = threading.Lock()
_IMPORT_JOB_CANCEL = False
_ALLOWED_IMPORT_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _set_import_job(**kw):
    with _IMPORT_JOB_LOCK:
        _IMPORT_JOB_STATE.update(**kw)


def _set_import_job_current(my_token, **kw):
    """仅当 my_token 仍是当前任务令牌时更新状态（旧 worker 在开新任务后不再覆盖）"""
    with _IMPORT_JOB_LOCK:
        if _IMPORT_JOB_STATE.get("token") != my_token:
            return False
        _IMPORT_JOB_STATE.update(**kw)
        return True


def get_import_progress() -> dict:
    with _IMPORT_JOB_LOCK:
        return dict(_IMPORT_JOB_STATE)


def cancel_import_job():
    global _IMPORT_JOB_CANCEL
    with _IMPORT_JOB_LOCK:
        if _IMPORT_JOB_STATE["status"] == "running":
            _IMPORT_JOB_CANCEL = True
    return {"ok": True}


def _import_job_progress_cb(my_token, done, total, current):
    """_do_import 逐文件回调：更新进度（仅限当前任务令牌）；取消时返回 False 中断"""
    cancel = False
    with _IMPORT_JOB_LOCK:
        cancel = _IMPORT_JOB_CANCEL
    pct = int(done * 100 / total) if total else 100
    _set_import_job_current(
        my_token,
        progress=pct,
        done=done,
        total=total,
        current=current,
        message=f"导入中 {done}/{total}",
        status="cancelled" if cancel else "running",
    )
    return False if cancel else None


def _import_job_worker(webui, files, names, make_collection, folder_name, my_token):
    """后台执行交互式导入（folder/文件对话框/剪贴板），逐文件报进度"""
    global _IMPORT_JOB_CANCEL
    db = get_db()

    def cb(done, total, current):
        return _import_job_progress_cb(my_token, done, total, current)

    try:
        if _IMPORT_JOB_CANCEL:
            _set_import_job_current(my_token, status="cancelled")
            return
        r = webui._do_import(files, names, cb)
        ids = r.get("ids") or []
        imported = len(ids)
        rejected = r.get("rejected", 0)
        skipped_dup = r.get("skipped_dup", 0)
        with _IMPORT_JOB_LOCK:
            was_cancel = _IMPORT_JOB_CANCEL
            is_current = _IMPORT_JOB_STATE.get("token") == my_token
        if not is_current:
            # 本任务已不是当前令牌（被新任务取代），立刻返回，
            # 避免旧 worker 执行 create_collection/add_to_collection 等副作用污染新任务
            return
        if not was_cancel:
            # 正常完成：进度满格、done 为全部
            _set_import_job_current(
                my_token,
                imported=imported,
                rejected=rejected,
                skipped_dup=skipped_dup,
                progress=100,
                done=len(files),
                total=len(files),
            )
        else:
            # 取消：保留 progress_cb 已更新的实际 done/total，不强制 100%
            _set_import_job_current(
                my_token, imported=imported, rejected=rejected, skipped_dup=skipped_dup
            )
            _set_import_job_current(my_token, status="cancelled", message="导入已取消")
            return
        collection_id = None
        if make_collection and ids and folder_name:
            collection_id = db.create_collection(folder_name)
            if collection_id > 0:
                for mid in ids:
                    db.add_to_collection(mid, collection_id)
                from .manifest import build as build_manifest

                build_manifest()
        _set_import_job_current(
            my_token,
            status="done",
            progress=100,
            message="导入完成",
            collection_id=collection_id,
        )
    except Exception as e:
        logger.error("import job error: %s", e)
        _set_import_job_current(
            my_token, status="error", error=str(e), message="导入失败"
        )
    finally:
        # 仅当仍是当前任务（token 匹配）时才重置取消标志；
        # 旧 worker 收尾不清新任务的取消标志，保证 token 代次隔离
        with _IMPORT_JOB_LOCK:
            if _IMPORT_JOB_STATE.get("token") == my_token:
                _IMPORT_JOB_CANCEL = False


def start_import_job(webui, files, names, make_collection=False, folder_name=""):
    """启动后台导入，立即返回；前端轮询 get_import_progress()"""
    import secrets

    global _IMPORT_JOB_CANCEL
    with _IMPORT_JOB_LOCK:
        if _IMPORT_JOB_STATE["status"] == "running":
            return False
        token = secrets.token_hex(6)
        _IMPORT_JOB_CANCEL = False
        _IMPORT_JOB_STATE.update(
            token=token,
            status="running",
            progress=0,
            message="开始导入",
            current="",
            done=0,
            total=len(files),
            imported=0,
            rejected=0,
            skipped_dup=0,
            error="",
        )
    threading.Thread(
        target=_import_job_worker,
        args=(webui, files, names, make_collection, folder_name, token),
        daemon=True,
    ).start()
    return True


# pHash 的一次性 DCT 基（模块加载时预计算，跨图复用）：_PHASH_DCT_COS[k][x]、
# _PHASH_DCT_NORM[k]（k=0 用 1.0，否则 sqrt(0.5)）
_PHASH_DCT_COS = [
    [math.cos((2 * x + 1) * k * math.pi / (2 * 32)) for x in range(32)]
    for k in range(8)
]
_PHASH_DCT_NORM = [1.0 if k == 0 else math.sqrt(0.5) for k in range(8)]


def _phash_path_cached(fpath):
    """带 (mtime, size) 校验的 phash 缓存，文件未变时避免重复解码"""
    try:
        st = os.stat(fpath)
        key = (st.st_mtime, st.st_size)
    except OSError:
        return 0
    with _PHASH_CACHE_LOCK:
        cached = _PHASH_CACHE.get(fpath)
        if cached and cached[0] == key:
            return cached[1]
    h = _perceptual_hash_path(fpath)
    if h:
        with _PHASH_CACHE_LOCK:
            if len(_PHASH_CACHE) >= 4096:
                _PHASH_CACHE.clear()  # 简单防膨胀：超过容量整体清空重建
            _PHASH_CACHE[fpath] = (key, h)
    return h


def _gray_pixels(img):
    """取 32x32 灰度像素列表（兼容新旧 Pillow：get_flattened_data/getdata）"""
    from PIL import Image

    small = img.convert("L").resize((32, 32), Image.LANCZOS)
    getter = getattr(small, "get_flattened_data", None)
    if getter is not None:
        return list(getter())
    return list(small.getdata())


def _perceptual_hash(img) -> int:
    """计算 PIL 图像的 64 位感知哈希（pHash，8x8 可分离 DCT）；比均值哈希判别力更强"""
    try:
        px = _gray_pixels(img)
        rows = [[0.0] * 32 for _ in range(8)]
        for k in range(8):
            ck = _PHASH_DCT_COS[k]
            for x in range(32):
                ckx = ck[x]
                row = rows[k]
                base = x * 32
                for y in range(32):
                    row[y] += px[base + y] * ckx
        dct = [[0.0] * 8 for _ in range(8)]
        for k in range(8):
            ck = _PHASH_DCT_NORM[k]
            for j in range(8):
                s = 0.0
                cl = _PHASH_DCT_COS[j]
                for y in range(32):
                    s += rows[k][y] * cl[y]
                dct[k][j] = ck * _PHASH_DCT_NORM[j] * s / 4.0
        coeffs = [dct[k][j] for k in range(8) for j in range(8)]
        median = sorted(coeffs)[len(coeffs) // 2]
        h = 0
        for i, c in enumerate(coeffs):
            if c > median:
                h |= 1 << i
        return h
    except Exception:
        return 0


def _perceptual_hash_path(path) -> int:
    """对图片文件计算感知哈希，失败返回 0（表示不可用）"""
    if not HAS_PIL:
        return 0
    try:
        with PILImage.open(path) as img:
            # 动画取首帧
            if getattr(img, "n_frames", 1) > 1:
                img.seek(0)
            return _perceptual_hash(img)
    except Exception:
        return 0


def _phash_hamming(a: int, b: int) -> int:
    """两个 64 位哈希的汉明距离"""
    return bin(a ^ b).count("1")


# 等待用户决策的相似图导入项（token → 待导入信息），避免 tmp 被清理
_PENDING_SIMILAR = {}
_PENDING_SIMILAR_LOCK = threading.Lock()
_PENDING_SIMILAR_TTL = 300  # 秒，超时自动丢弃


def _register_pending_similar(path: str, oname: str, candidates: list) -> str:
    import secrets

    token = secrets.token_hex(16)
    with _PENDING_SIMILAR_LOCK:
        _PENDING_SIMILAR[token] = {
            "path": path,
            "oname": oname,
            "candidates": candidates,
            "ts": time.time(),
        }
        # 清理过期项
        now = time.time()
        for k, v in list(_PENDING_SIMILAR.items()):
            if now - v["ts"] > _PENDING_SIMILAR_TTL:
                try:
                    os.unlink(v["path"])
                except OSError:
                    pass
                del _PENDING_SIMILAR[k]
    return token


def _pop_pending_similar(token: str) -> dict:
    with _PENDING_SIMILAR_LOCK:
        item = _PENDING_SIMILAR.pop(token, None)
        if item and time.time() - item.get("ts", 0) > _PENDING_SIMILAR_TTL:
            # 已过期：删除临时文件并视为不存在
            try:
                os.unlink(item["path"])
            except OSError:
                pass
            item = None
    return item


def _iter_cache_images(cache_dir):
    """遍历缓存目录下所有在库图片的 (filename, fullpath)，跳过 thumbnails 与子目录"""
    try:
        for root, dirs, files in os.walk(str(cache_dir)):
            for d in list(dirs):
                if d == "thumbnails":
                    dirs.remove(d)
            for name in files:
                if _detect_image_ext(os.path.join(root, name)):
                    yield name, os.path.join(root, name)
    except OSError:
        return


def _build_cache_index():
    """一次性构建 库中 filename → 绝对路径 映射（供批量回填，避免逐行 walk）"""
    idx = {}
    cfg = get_config()
    for fname, fpath in _iter_cache_images(Path(str(cfg.cache_dir))):
        idx[fname] = fpath
    return idx


def _resolve_cache_file(filename, index=None):
    """根据 DB 中的 filename 定位缓存文件绝对路径（一级优先，退化用 index/遍历）"""
    if index is not None:
        return index.get(filename) or ""
    cfg = get_config()
    cache_dir = cfg.cache_dir
    direct = cache_dir / filename
    if direct.is_file():
        return str(direct)
    for _fname, fpath in _iter_cache_images(Path(str(cache_dir))):
        if _fname == filename:
            return fpath
    return ""


def _backfill_phash_background(rows, index):
    """后台线程：为 phash 为空的旧库行补算并写回 DB（不阻塞导入）"""
    global _PHASH_BACKFILLING
    db = get_db()
    try:
        for row in rows:
            fname = row.get("filename")
            fpath = index.get(fname) if index else _resolve_cache_file(fname)
            if not fpath:
                continue
            try:
                phash = _phash_path_cached(fpath)
            except Exception:
                continue
            # 无条件写入（set_perceptual_hash 内部处理 0→"0" 占位）
            db.set_perceptual_hash(row["id"], phash)
    finally:
        with _PHASH_BACKFILL_LOCK:
            _PHASH_BACKFILLING = False


def _ensure_backfill_daemon(rows, index):
    """若当前无后台回填在跑，启动一个（防重入）；已跑则跳过"""
    global _PHASH_BACKFILLING
    if not rows:
        return
    with _PHASH_BACKFILL_LOCK:
        if _PHASH_BACKFILLING:
            return
        _PHASH_BACKFILLING = True
    try:
        threading.Thread(
            target=_backfill_phash_background,
            args=(rows, index),
            daemon=True,
        ).start()
    except Exception:
        with _PHASH_BACKFILL_LOCK:
            _PHASH_BACKFILLING = False


def _find_similar_candidates(img_path):
    """基于 DB 感知哈希的全库比对：只解码新图，存量直接读 DB（微秒级）

    返回候选列表（全库比对，无截断）。phash 为空的旧库行惰性回填（算一次写回 DB）。
    """
    cfg = get_config()
    db = get_db()
    if not cfg.cache_dir or not HAS_PIL:
        return []
    target_hash = _phash_path_cached(img_path)
    if target_hash == 0:
        return []
    rows = db.get_all_phash()
    matches = []
    missing = [r for r in rows if not r.get("perceptual_hash")]
    # 缺失行少：同步回填；缺失多：后台回填，本次只比对已填的（无缺失则不遍历目录）
    if missing:
        try:
            idx = _build_cache_index()
        except Exception:
            idx = {}
        if len(missing) <= _PHASH_SYNC_BACKFILL_MAX:
            for row in missing:
                fpath = idx.get(row.get("filename")) or ""
                if fpath:
                    try:
                        ph = _phash_path_cached(fpath)
                    except Exception:
                        ph = 0
                    # 无条件写入（set_perceptual_hash 内部处理 0→"0" 占位）
                    db.set_perceptual_hash(row["id"], ph)
                    row["perceptual_hash"] = "0" if ph == 0 else hex(ph)
        else:
            _ensure_backfill_daemon(missing, idx)
    for row in rows:
        fname = row.get("filename")
        phash = row.get("perceptual_hash")
        if not phash:
            continue  # 未回填（已交给后台），本次跳过
        try:
            phash = int(phash, 16)
        except (TypeError, ValueError):
            continue
        if not phash:
            continue  # 占位 "0"（无感知内容）跳过比较
        dist = _phash_hamming(target_hash, phash)
        if dist <= _PHASH_SIMILAR_DIST:
            matches.append(
                {
                    "id": row["id"],
                    "filename": fname,
                    "name": row.get("original_name") or fname,
                    "distance": dist,
                }
            )
    matches.sort(key=lambda x: x["distance"])
    # DB 比对为微秒级整数运算，全库比对无截断漏检
    return matches[:5]


def _prepare_image_import(path) -> dict:
    """单图导入前的去重决策：返回 hash_dup / similar / ok / rejected"""
    db = get_db()
    w = h = 0
    try:
        fsize = os.path.getsize(path)
    except OSError:
        fsize = 0
    if HAS_PIL:
        try:
            with PILImage.open(path) as img:
                w, h = img.size
        except Exception:
            pass
    if fsize > _IMPORT_MAX_BYTES or max(w, h) > _IMPORT_MAX_PX:
        return {"status": "rejected", "error": "文件超过大小/分辨率限制，已跳过"}
    fhash = _file_sha256(path)
    row = db.get_by_hash(fhash)
    if row:
        return {
            "status": "hash_dup",
            "hash": fhash,
            "existing_id": row["id"],
        }
    candidates = _find_similar_candidates(path)
    if candidates:
        return {"status": "similar", "candidates": candidates}
    return {"status": "ok", "hash": fhash}


def _detect_image_ext(path):
    """读取文件头魔数识别真实扩展名（QQ 保存常为 .jpg，实为 png/webp 等），未知返回空串"""  # noqa: E501
    try:
        with open(path, "rb") as f:
            return adb_util._detect_ext(f.read(16))
    except OSError:
        return ""


def _try_decode_stego(gif_path):
    """实验性：检测 GIF 隐写并解码还原原图到临时文件；非隐写/失败返回 None"""
    try:
        with open(gif_path, "rb") as f:
            if b"STG3" not in f.read():
                return None
        from .gif_stego import decode as stego_decode
    except Exception as e:
        logger.warning(f"_try_decode_stego detect: {e}")
        return None
    try:
        import glob
        import tempfile
        import uuid

        base = os.path.join(tempfile.gettempdir(), f"ohmm_dec_{uuid.uuid4().hex}")
        stego_decode(gif_path, base, quiet=True)
        cands = [
            c
            for c in glob.glob(base + "*")
            if os.path.isfile(c) and os.path.getsize(c) > 0
        ]
        return cands[0] if cands else None
    except Exception as e:
        logger.warning(f"_try_decode_stego decode: {e}")
        return None


class WebUI:
    """PyWebView UI 管理器"""

    def __init__(self, update_debug: bool = False, silent_start: bool = False):
        self._cfg = get_config()
        self._window = None
        self._settings_window = None
        self._port = self._find_free_port()
        self._bottle_thread = None
        self._api = JsApi(self)
        self._settings_api = SettingsApi(self)
        self._visible = False
        self._started = False
        self._pending_hide = False
        self._hotkey_session = False
        self._on_hotkey_change_cb = None
        self._update_debug = update_debug
        self._silent_start = silent_start

    def _init_lan(self):
        from . import lan

        lan.set_confirm_callback(self._lan_confirm_cb)

    def set_on_hotkey_change(self, cb):
        self._on_hotkey_change_cb = cb

    def _lan_confirm_cb(self, device: dict):
        """LAN 设备连接确认：显示主窗口并弹窗展示设备信息，等待 JS 回传结果"""
        import json

        from . import lan

        if not self._window:
            lan.confirm_device(False)
            return
        try:
            self.show()
            js = "window.showLanDeviceConfirm(%s)" % json.dumps(
                device, ensure_ascii=False
            )
            self._window.evaluate_js(js)
        except Exception as e:
            logger.warning(f"lan confirm dialog error: {e}")
            lan.confirm_device(False)

    # --- 窗口控制（从任何线程调用安全）---

    def _get_hotkey_window_position(self):
        """获取 Windows 光标所在显示器工作区内的热键窗口位置"""
        if platform.system() != "Windows":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = (("x", wintypes.LONG), ("y", wintypes.LONG))

            class RECT(ctypes.Structure):
                _fields_ = (
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                )

            class MONITORINFO(ctypes.Structure):
                _fields_ = (
                    ("cbSize", wintypes.DWORD),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD),
                )

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.GetCursorPos.argtypes = (ctypes.POINTER(POINT),)
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.MonitorFromPoint.argtypes = (POINT, wintypes.DWORD)
            user32.MonitorFromPoint.restype = wintypes.HMONITOR
            user32.GetMonitorInfoW.argtypes = (
                wintypes.HMONITOR,
                ctypes.POINTER(MONITORINFO),
            )
            user32.GetMonitorInfoW.restype = wintypes.BOOL

            cursor = POINT()
            if not user32.GetCursorPos(ctypes.byref(cursor)):
                raise ctypes.WinError(ctypes.get_last_error())
            monitor = user32.MonitorFromPoint(cursor, 2)
            if not monitor:
                raise ctypes.WinError(ctypes.get_last_error())
            monitor_info = MONITORINFO()
            monitor_info.cbSize = ctypes.sizeof(MONITORINFO)
            if not user32.GetMonitorInfoW(monitor, ctypes.byref(monitor_info)):
                raise ctypes.WinError(ctypes.get_last_error())

            work = monitor_info.rcWork
            return _find_hotkey_window_position(
                (cursor.x, cursor.y),
                (work.left, work.top, work.right, work.bottom),
                self._window.width,
                self._window.height,
            )
        except Exception as e:
            logger.warning("hotkey window position error: %s", e)
            return None

    # 显示主窗口并清理非热键会话状态
    def show(self):
        self._visible = True
        self._hotkey_session = False
        if self._window:
            try:
                self._window.on_top = True  # 置顶一下提升 z-order，随即复位不长期置顶
                self._window.on_top = False
                if callable(self._window.show):
                    self._window.show()
                if callable(self._window.focus):
                    self._window.focus()
                self._window.evaluate_js("focusSearch()")
            except Exception as e:
                logger.warning(f"show window error: {e}")

    def hide(self):
        self._visible = False
        self._hotkey_session = False
        if self._window:
            try:
                self._save_window_position()
                if callable(self._window.hide):
                    self._window.hide()
            except Exception as e:
                logger.warning(f"hide window error: {e}")

    def toggle(self):
        if self._visible:
            self.hide()
        else:
            self.show()

    def toggle_safe(self):
        # show/hide 底层为 Invoke 调度，任意线程调用均安全
        if self._window:
            self.toggle()

    def toggle_hotkey_safe(self):
        """按热键专用定位规则安全切换窗口"""
        if not self._window:
            return
        if self._visible:
            self.hide()
            return
        if self._cfg.get("hotkey_show_at_mouse", False):
            try:
                position = self._get_hotkey_window_position()
                if position is not None:
                    self._window.move(*position)
            except Exception as e:
                logger.warning("hotkey window move error: %s", e)
        self.show()
        self._hotkey_session = True

    def schedule_hide(self):
        if not self._hotkey_session:
            return False
        self._pending_hide = True
        if self._window:
            self._run_on_gui(0.1, self._process_pending_hide)
        return True

    def _process_pending_hide(self):
        if self._pending_hide:
            self._pending_hide = False
            self.hide()

    def _run_on_gui(self, delay: float, func):
        """延时在 GUI 线程执行（pywebview Window 无 after 方法）"""
        if threading.current_thread() is threading.main_thread() and delay <= 0:
            func()
            return
        t = threading.Timer(delay, func)
        t.daemon = True
        t.start()

    def _schedule_quit(self):
        """更新安装程序启动后，短暂等待并强制结束当前进程（确保 exe 不被占用）"""

        def _force_kill():
            time.sleep(1.5)
            if os.name == "nt":
                try:
                    import ctypes

                    ctypes.windll.kernel32.TerminateProcess(
                        ctypes.windll.kernel32.GetCurrentProcess(), 0
                    )
                except Exception:
                    pass
            os._exit(0)

        threading.Thread(target=_force_kill, daemon=True).start()

    @property
    def is_visible(self) -> bool:
        return self._visible

    # --- 缩略图 ---

    def _get_thumbnail_path(self, meme_id: int, filename: str, size: int = 150) -> str:
        cache_dir = self._cfg.thumbnail_dir
        thumb_path = cache_dir / f"{meme_id}_{size}.png"
        if thumb_path.exists():
            return str(thumb_path)
        meme_path = self._find_meme_file(filename)
        if not meme_path or not HAS_PIL:
            return ""
        try:
            img = PILImage.open(meme_path)
            img.thumbnail((size, size), PILImage.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            cache_dir.mkdir(parents=True, exist_ok=True)
            # 并发请求同一缩略图时避免交错写同一文件：先写临时文件再原子替换
            fd, tmp_path = tempfile.mkstemp(dir=str(cache_dir), suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(buf.getvalue())
                os.replace(tmp_path, thumb_path)
            except Exception:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                raise
            return str(thumb_path)
        except Exception as e:
            logger.warning(f"thumb error {filename}: {e}")
            return ""

    def _find_meme_file(self, filename: str) -> str:
        if not _safe_serve_filename(filename):
            return ""
        cache_dir = self._cfg.cache_dir
        direct = cache_dir / filename
        if direct.exists():
            return str(direct)
        if not hasattr(self, "_file_cache"):
            self._file_cache = {}
        if filename in self._file_cache:
            cached = self._file_cache[filename]
            if os.path.exists(cached):
                return cached
        for root, _, files in os.walk(cache_dir):
            if filename in files:
                full = os.path.join(root, filename)
                self._file_cache[filename] = full
                return full
        return ""

    def _do_import(self, file_paths, names=None, progress_cb=None):
        import shutil

        cfg = get_config()
        db = get_db()
        cache_dir = cfg.cache_dir
        imported = 0
        rejected = 0
        skipped_dup = 0
        imported_ids = []
        total = len(file_paths)
        done = 0
        stop_import = False
        for i, src in enumerate(file_paths):
            try:
                base_name = (
                    names[i]
                    if names and i < len(names)
                    else os.path.splitext(os.path.basename(src))[0]
                )
                # 隐写 GIF 无论开关与否都只入库解码还原的原图（开关仅控制复制输出）
                restored = None
                if _detect_image_ext(src) == ".gif":
                    restored = _try_decode_stego(src)
                if restored:
                    items = [(restored, base_name, None, 1)]
                else:
                    items = [(src, base_name, None, 0)]
                for path, oname, stego_of_hash, from_stego in items:
                    w = h = 0
                    try:
                        fsize = os.path.getsize(path)
                    except OSError:
                        fsize = 0
                    if HAS_PIL:
                        try:
                            with PILImage.open(path) as img:
                                w, h = img.size
                        except Exception:
                            pass
                    if fsize > _IMPORT_MAX_BYTES or max(w, h) > _IMPORT_MAX_PX:
                        rejected += 1
                        logger.info(
                            "import rejected (over limit): %s", os.path.basename(path)
                        )
                        continue
                    fhash = _file_sha256(path)
                    ext = _detect_image_ext(path) or os.path.splitext(path)[1] or ".png"
                    # 感知哈希计算较重（解码+DCT），放锁外避免持锁阻塞其他导入
                    src_phash = _perceptual_hash_path(path)
                    # 去重检查 + 落盘 + 入库 在同一临界区：并发导入同图时不产生重复记录
                    with _IMPORT_LOCK:
                        if db.get_by_hash(fhash):
                            skipped_dup += 1
                            continue
                        dst = cache_dir / f"{fhash[:16]}{ext}"
                        shutil.copy2(path, dst)
                        db.add_meme(
                            filename=dst.name,
                            file_hash=fhash,
                            width=w,
                            height=h,
                            file_size=fsize,
                            mime_type=f"image/{ext[1:]}" if ext else "image/png",
                            original_name=oname,
                            stego_of_hash=stego_of_hash,
                            from_stego=from_stego,
                            perceptual_hash=src_phash,
                        )
                        row = db.get_by_hash(fhash)
                        if row:
                            imported_ids.append(row["id"])
                        imported += 1
                if restored:
                    try:
                        os.unlink(restored)
                    except OSError:
                        pass
            except Exception as e:
                logger.error(f"import {src}: {e}")
            finally:
                # 每个源文件无论 导入/去重跳过/拒绝/异常 都推进进度并检查取消
                done += 1
                if progress_cb:
                    try:
                        if progress_cb(done, total, os.path.basename(src)) is False:
                            stop_import = True
                    except Exception:
                        pass
            if stop_import:
                break  # 取消：progress_cb 返回 False 时中断导入
        if imported:
            build_manifest()
        logger.info(f"导入完成: {imported} 个")
        return {"ids": imported_ids, "rejected": rejected, "skipped_dup": skipped_dup}

    def _import_with_similar_decision(self, path, oname=""):
        """单图导入决策：哈希命中提示已存在；内容近似转相似（URL 拖放与文件上传复用）"""
        try:
            prep = _prepare_image_import(path)
        except Exception as e:
            logger.error("import decision error: %s", e)
            return {"ok": False, "error": "导入失败"}
        if prep.get("status") == "ok":
            r = self._do_import([path], [oname] if oname else None)
            ids = r.get("ids") or []
            if ids:
                return {"ok": True, "id": ids[0]}
            if r.get("skipped_dup"):
                return {
                    "ok": False,
                    "duplicate": True,
                    "error": "该图片已存在，无需重复导入",
                }
            if r.get("rejected"):
                return {
                    "ok": False,
                    "rejected": r["rejected"],
                    "error": "文件超过大小/分辨率限制，已跳过",
                }
            return {"ok": False, "error": "导入失败"}
        if prep.get("status") == "rejected":
            return {
                "ok": False,
                "rejected": 1,
                "error": prep.get("error") or "导入失败",
            }
        if prep.get("status") == "hash_dup":
            return {
                "ok": False,
                "duplicate": True,
                "existing_id": prep.get("existing_id", 0),
                "error": "该图片已存在，无需重复导入",
            }
        # similar：先把文件复制到独立临时目录，避免调用方 finally 清理源文件
        import tempfile

        cands = prep.get("candidates") or []
        hold = None
        try:
            ext = os.path.splitext(path)[1] or ".png"
            fd, hold = tempfile.mkstemp(prefix="ohmm_simil_", suffix=ext)
            os.close(fd)
            import shutil

            shutil.copy2(path, hold)
        except OSError:
            if hold:
                try:
                    os.unlink(hold)
                except OSError:
                    pass
            return {"ok": False, "error": "导入失败"}
        token = _register_pending_similar(hold, oname, cands)
        return {
            "ok": False,
            "similar_pending": True,
            "token": token,
            "candidates": cands,
        }

    def ensure_import_collection(self, ids, group_name, parent_id=None):
        """把导入 ids 加入固定名分组（同名复用，不存在则建）；返回 collection_id"""
        if not ids or not group_name:
            return -1
        db = get_db()
        cid = db.create_collection(group_name, parent_id=parent_id)
        if cid > 0:
            for mid in ids:
                db.add_to_collection(mid, cid)
            from .manifest import build as build_manifest

            build_manifest()
        return cid

    def _on_hotkey_change(self, new_hotkey: str):
        if self._on_hotkey_change_cb:
            self._on_hotkey_change_cb(new_hotkey)

    # --- Bottle 路由 ---

    def _setup_bottle(self):
        app = bottle.Bottle()

        @app.hook("before_request")
        def _guard_cross_origin():
            # 仅接受本地回环 Host，阻断 DNS rebinding 与外部直连
            if not _host_allowed(bottle.request.headers.get("Host", ""), self._port):
                bottle.abort(403, "Forbidden")
            if bottle.request.method == "POST":
                origin = bottle.request.headers.get("Origin", "")
                if origin:
                    allowed = (
                        f"http://127.0.0.1:{self._port}",
                        f"http://localhost:{self._port}",
                    )
                    if origin not in allowed:
                        bottle.abort(403, "Forbidden")
                if bottle.request.headers.get("Sec-Fetch-Site", "") == "cross-site":
                    bottle.abort(403, "Forbidden")

        @app.hook("after_request")
        def _set_security_headers():
            bottle.response.headers["X-Content-Type-Options"] = "nosniff"
            bottle.response.headers["Referrer-Policy"] = "no-referrer"
            bottle.response.headers["X-Frame-Options"] = "DENY"
            if bottle.request.path.startswith("/api/"):
                bottle.response.headers["Cache-Control"] = "no-store"

        @app.route("/")
        def index():
            vue_html = HTML_DIR / "vue.html"
            # 仅当 vue.html 与构建产物都存在时才走 Vue 前端，否则回退旧 index.html
            if vue_html.exists() and (HTML_DIR / "dist" / "ohmymeme.js").exists():
                return bottle.static_file("vue.html", root=str(HTML_DIR))
            html_path = HTML_DIR / "index.html"
            if html_path.exists():
                return bottle.static_file("index.html", root=str(HTML_DIR))
            return "<h1>OhMyMeme</h1><p>index.html not found</p>"

        @app.route("/settings/")
        def settings_page():
            html_path = HTML_DIR / "settings.html"
            if html_path.exists():
                return bottle.static_file("settings.html", root=str(HTML_DIR))
            return "<h1>设置</h1><p>settings.html not found</p>"

        @app.route("/api/contributors")
        def serve_contributors():
            # 代理贡献者 SVG：剥离白色背景矩形，适配深色主题；TTL 缓存，失败回退旧缓存
            now = time.time()
            if _CONTRIBUTORS_CACHE["svg"] is None or now >= (
                _CONTRIBUTORS_CACHE["at"] + _CONTRIBUTORS_TTL
            ):
                try:
                    from urllib.request import Request, urlopen

                    url = "https://contributor.starsfire.top/TNTXZ/OhMyMeme"
                    req = Request(url, headers={"User-Agent": "OhMyMeme"})
                    with urlopen(req, timeout=10) as resp:
                        svg = resp.read().decode("utf-8", "replace")
                    _CONTRIBUTORS_CACHE["svg"] = svg
                    _CONTRIBUTORS_CACHE["at"] = now
                except Exception:
                    if _CONTRIBUTORS_CACHE["svg"] is None:
                        bottle.response.status = 502
                        return ""
            white_rect = '<rect width="100%" height="100%" fill="#ffffff"/>'
            svg = _CONTRIBUTORS_CACHE["svg"].replace(white_rect, "")
            bottle.response.content_type = "image/svg+xml; charset=utf-8"
            return svg

        @app.route("/api/thumb/<meme_id>/<filename>")
        def serve_thumb(meme_id, filename):
            path = self._get_thumbnail_path(int(meme_id), filename)
            if path:
                return bottle.static_file(
                    os.path.basename(path),
                    root=os.path.dirname(path),
                    mimetype="image/png",
                )
            bottle.response.status = 404
            return ""

        @app.route("/api/original/<meme_id>/<filename>")
        def serve_original(meme_id, filename):
            path = self._find_meme_file(filename)
            if path:
                ext = os.path.splitext(filename)[1].lower()
                ctype = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".gif": "image/gif",
                    ".webp": "image/webp",
                }.get(ext, "application/octet-stream")
                return bottle.static_file(
                    os.path.basename(path), root=os.path.dirname(path), mimetype=ctype
                )
            bottle.response.status = 404
            return ""

        @app.route("/api/upload/", method="POST")
        def upload_memes():
            try:
                import json

                data = json.loads(bottle.request.body.read())
                files = data.get("files", []) if isinstance(data, dict) else data
                allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
                paths, names = [], []
                for item in files:
                    oname = item.get("name", "")
                    b64 = item.get("data", "")
                    ext = os.path.splitext(oname)[1].lower()
                    if ext not in allowed or not b64:
                        continue
                    import base64
                    import uuid

                    raw = base64.b64decode(b64)
                    tmp = str(self._cfg.cache_dir / f"_upload_{uuid.uuid4().hex}{ext}")
                    with open(tmp, "wb") as f:
                        f.write(raw)
                    paths.append(tmp)
                    base = os.path.splitext(oname)[0]
                    names.append(base)
                if paths:
                    if len(paths) == 1:
                        # 单张上传走相似/哈希决策，能触发重复与近似检测
                        r = self._import_with_similar_decision(
                            paths[0], names[0] if names else ""
                        )
                        for p in paths:
                            try:
                                os.unlink(p)
                            except Exception:
                                pass
                        return r
                    self._do_import(paths, names)
                    for p in paths:
                        try:
                            os.unlink(p)
                        except Exception:
                            pass
                return {"ok": True}
            except Exception as e:
                logger.error(f"upload error: {e}")
                bottle.response.status = 500
                return {"ok": False, "error": str(e)}

        @app.route("/resources/<filepath:path>")
        def serve_resources(filepath):
            # 启动动画等内置资源（src/resources），防止路径穿越
            name = os.path.basename(filepath)
            if not name or name != filepath.replace("\\", "/").split("/")[-1]:
                bottle.abort(404, "Not Found")
            return bottle.static_file(name, root=str(RESOURCES_DIR))

        @app.route("/<filepath:path>")
        def static_files(filepath):
            # 按扩展名强制 MIME，规避本机 .js 映射被改写成 text/plain 时
            # 叠加 nosniff 导致 Chromium 拒执行脚本；未知类型走 bottle 自动检测
            ctype = _STATIC_MIME_TYPES.get(os.path.splitext(filepath)[1].lower())
            if ctype:
                return bottle.static_file(filepath, root=str(HTML_DIR), mimetype=ctype)
            return bottle.static_file(filepath, root=str(HTML_DIR))

        # 多线程 wsgiref：默认单线程下慢请求（外网抓取/缩略图生成）会阻塞
        # 其他路由，导致设置页资源排队、JS 监听未注册期间窗口无法交互
        from socketserver import ThreadingMixIn
        from wsgiref.simple_server import WSGIServer

        class _ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
            daemon_threads = True

        bottle.run(
            app,
            host="127.0.0.1",
            port=self._port,
            quiet=True,
            server_class=_ThreadedWSGIServer,
        )

    # --- 缓存扫描 ---

    def scan_cache(self):
        """扫描本地缓存目录，将已有文件自动注册到数据库"""
        import hashlib

        cache_dir = self._cfg.cache_dir
        db = get_db()
        allowed_ext = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
        added = 0
        if not cache_dir.exists():
            logger.debug(f"scan_cache: cache dir not found {cache_dir}")
            return
        for root, _, files in os.walk(cache_dir):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in allowed_ext:
                    continue
                fpath = os.path.join(root, fname)
                if "thumbnails" in fpath:
                    continue
                # 跳过由 WebP 动图自动生成的 GIF（同名 .webp 存在即为生成物）
                stem = os.path.splitext(fname)[0]
                if ext == ".gif" and os.path.isfile(os.path.join(root, stem + ".webp")):
                    continue
                if db.get_by_filename(fname):
                    continue
                try:
                    fsize = os.path.getsize(fpath)
                    w = h = 0
                    if HAS_PIL:
                        try:
                            with PILImage.open(fpath) as img:
                                w, h = img.size
                        except Exception:
                            pass
                    if fsize > _IMPORT_MAX_BYTES or max(w, h) > _IMPORT_MAX_PX:
                        logger.info("scan_cache skip (over limit): %s", fname)
                        continue
                    sha256 = hashlib.sha256()
                    with open(fpath, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            sha256.update(chunk)
                    fhash = sha256.hexdigest()
                    if db.get_by_hash(fhash):
                        continue
                    mime = f"image/{ext[1:]}" if ext else "image/png"
                    oname = os.path.splitext(fname)[0]
                    db.add_meme(
                        filename=fname,
                        file_hash=fhash,
                        width=w,
                        height=h,
                        file_size=fsize,
                        mime_type=mime,
                        original_name=oname,
                        perceptual_hash=_perceptual_hash_path(fpath),
                    )
                    added += 1
                except Exception as e:
                    logger.warning(f"scan_cache skip {fname}: {e}")
        if added:
            logger.info(f"缓存扫描完成: 新增 {added} 个文件")
        build_manifest()

    # --- 启动 ---

    def start(self) -> bool:
        if not HAS_WEBVIEW:
            logger.error("pywebview not installed")
            return False
        if not HAS_BOTTLE:
            logger.error("bottle not installed")
            return False

        # 启动 Bottle 服务器
        self._bottle_thread = threading.Thread(target=self._setup_bottle, daemon=True)
        self._bottle_thread.start()
        time.sleep(0.3)

        url = f"http://127.0.0.1:{self._port}/"
        wx = self._cfg.get("window_x", -1)
        wy = self._cfg.get("window_y", -1)
        self._window = webview.create_window(
            "OhMyMeme",
            url,
            js_api=self._api,
            width=960,
            height=640,
            x=wx if (wx is not None and wx >= 0) else None,
            y=wy if (wy is not None and wy >= 0) else None,
            resizable=True,
            frameless=True,
            easy_drag=False,
            hidden=self._silent_start,
        )
        self._visible = not self._silent_start

        self._started = True
        # 注册 LAN 设备确认回调（窗口创建完成后）
        self._init_lan()
        # start() blocks - 在调用线程运行 GUI 循环
        gui = "gtk" if platform.system() == "Linux" else None
        webview.start(debug=False, http_server=False, gui=gui)
        return True

    def open_settings(self):
        return self._create_settings_window()

    def _create_settings_window(self):
        try:
            if self._settings_window is not None:
                try:
                    self._settings_window.destroy()
                except Exception:
                    pass
                self._settings_window = None

            settings_url = f"http://127.0.0.1:{self._port}/settings/"
            self._settings_window = webview.create_window(
                "设置 - OhMyMeme",
                settings_url,
                js_api=self._settings_api,
                width=720,
                height=560,
                resizable=False,
                frameless=True,
                easy_drag=False,
            )
            return True
        except Exception as e:
            logger.warning(f"create settings window error: {e}")
            return False

    def close_settings(self):
        if self._settings_window:
            try:
                self._settings_window.destroy()
            except Exception as e:
                logger.warning(f"destroy settings error: {e}")
            self._settings_window = None
        # 关闭设置页时自动停止局域网服务
        try:
            from . import lan

            lan.stop()
        except Exception:
            pass

    def _save_window_position(self):
        if not self._window:
            return
        try:
            self._cfg.set("window_x", self._window.x)
            self._cfg.set("window_y", self._window.y)
            self._cfg.save()
        except Exception:
            pass

    def stop(self):
        self._save_window_position()
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None
        if self._settings_window:
            try:
                self._settings_window.destroy()
            except Exception:
                pass
            self._settings_window = None

    @staticmethod
    def _find_free_port() -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port
