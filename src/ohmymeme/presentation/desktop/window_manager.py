"""PyWebView 现代化 UI 窗口管理器 + JS API"""

import logging
import os
import platform
import socket
import threading
import time
from pathlib import Path
from wsgiref.simple_server import make_server

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
    from ohmymeme.integrations.platform.system import is_integrated_gpu

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
    import webview

    HAS_WEBVIEW = True
except ImportError:
    HAS_WEBVIEW = False

try:
    import bottle

    HAS_BOTTLE = True
except ImportError:
    HAS_BOTTLE = False

from ohmymeme.core.imports import ImportBytes
from ohmymeme.integrations.imports import adb_qq, qqnt, telegram
from ohmymeme.integrations.platform.clipboard import (
    convert_image_mode_1,
    convert_image_mode_2,
    convert_image_mode_3,
    copy_image_to_clipboard,
)
from ohmymeme.services import updates as updater
from ohmymeme.services.sync import service as sync_module

from .bottle_app import install_security_hooks
from .import_workers import import_paths
from .media import thumbnail_path
from .routes.media import original_mime_type
from .routes.pages import STATIC_MIME_TYPES, static_mime_type
from .routes.upload import UPLOAD_BODY_LIMIT, read_upload_body
from .security import host_allowed, safe_serve_filename, storage_dir_validation

logger = logging.getLogger(__name__)

# 内存日志缓冲：固定收集 DEBUG 级日志，供设置页"导出日志"
_LOG_BUFFER = []
_LOG_LOCK = threading.Lock()
_LOG_MAX = 5000

# 分页：主窗口单页展示的表情包数量（与前端 index.js MEME_PAGE 保持一致）
MEME_PAGE = 200
_UPLOAD_BODY_LIMIT = UPLOAD_BODY_LIMIT


def _read_upload_body(stream):
    return read_upload_body(stream)


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

HTML_DIR = Path(__file__).resolve().parents[3] / "webui"
RESOURCES_DIR = Path(__file__).resolve().parents[3] / "resources"

# 启动动画视频边缘主色（OhMyMeme.mp4 边框纯黑，写死避免运行时 ffmpeg 抽帧采样）
_STARTUP_BG_COLOR = "#000000"


# 静态资源扩展名 → 强制 Content-Type：本机 mimetypes/注册表 .js 映射可能为
# text/plain，叠加 nosniff 会被 Chromium 拒执行脚本
_STATIC_MIME_TYPES = STATIC_MIME_TYPES

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
    return safe_serve_filename(name)


def _host_allowed(host: str, port: int) -> bool:
    """仅接受本地回环 Host，阻断 DNS rebinding / 跨站直连"""
    return host_allowed(host, port)


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


def _import_result_payload(result):
    """将应用导入结果适配为既有桥接字典。"""
    if isinstance(result, dict):
        return result
    return {
        "ids": list(result.imported_ids),
        "rejected": result.rejected,
    }


def _storage_dir_validation(new_dir, old_dir, protected=()):
    # 校验自定义存储目录，返回 (ok, error)
    return storage_dir_validation(new_dir, old_dir, protected)


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


class JsApi:
    """暴露给前端的 JS API"""

    def __init__(self, webui, catalog, settings, library=None):
        self._webui = webui
        self._cfg = webui._cfg
        self._db = webui._db
        self._catalog = catalog
        self._settings = settings
        self._library = library

    def search_memes(
        self, keyword="", tags=None, collection_id=None, offset=0, limit=200
    ):
        """搜索表情，支持 offset/limit 分页"""
        return self._catalog.search_memes(keyword, tags, collection_id, offset, limit)

    def count_memes(self, keyword="", tags=None, collection_id=None) -> int:
        """统计符合搜索条件（关键字/标签/分组/收藏/最近使用）的表情总数，供分页"""
        return self._catalog.count_memes(keyword, tags, collection_id)

    def get_tags(self) -> list:
        return self._catalog.get_tags()

    def get_meme_tags(self, meme_id):
        """返回某表情的标签列表"""
        return self._catalog.get_meme_tags(meme_id)

    def set_meme_tags(self, meme_id, tags):
        """覆盖式设置某表情的标签"""
        return self._catalog.set_meme_tags(meme_id, tags)

    def get_init_data(self) -> dict:
        """批返回初始化所需数据，减少 JS bridge 往返"""
        return self._catalog.get_init_data(_STARTUP_BG_COLOR)

    def get_meme_path(self, meme_id: int) -> str:
        """返回表情本地文件路径（供拖拽到外部应用），不存在返回空串"""
        return self._catalog.get_meme_path(meme_id)

    def get_meme_paths(self, meme_ids: list) -> dict:
        """批量返回表情本地文件路径 {id: path}，供拖拽到外部应用"""
        return self._catalog.get_meme_paths(meme_ids)

    def start_native_drag(self, meme_id: int) -> bool:
        """用 WinForms DoDragDrop 启动原生文件拖拽（QQ/微信可接收真实文件）"""
        p = self._catalog.get_meme_path(meme_id)
        if not p:
            return False
        try:
            from ohmymeme.integrations.platform.native_drag import (
                start_native_drag as _start,
            )

            ok = bool(_start(p))
            if ok:
                self._webui.schedule_hide()
            return ok
        except Exception:
            return False

    def copy_meme(self, meme_id):
        # 复制表情到剪贴板；copy_resize_mode: 0不处理 1webp缩放 2转gif 3转gif隐写原图
        path = self._catalog.get_meme_path(meme_id)
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
            try:
                self._library.record_use(meme_id)
            except Exception:
                pass
        self._webui.schedule_hide()
        return {"ok": True, "status": "copied"}

    def toggle_favorite(self, meme_id: int) -> bool:
        return self._library.toggle_favorite(meme_id)

    def is_favorite(self, meme_id: int) -> bool:
        return self._library.is_favorite(meme_id)

    def rename_meme(self, meme_id: int, new_name: str) -> bool:
        if not new_name:
            return False
        try:
            return self._library.rename_meme(meme_id, new_name)
        except Exception as e:
            logging.getLogger(__name__).error(f"rename error: {e}")
            return False

    def delete_meme(self, meme_id: int) -> bool:
        result = self._library.delete_meme(meme_id)
        if result and hasattr(self._webui, "_file_cache"):
            self._webui._file_cache.clear()
        return result

    def delete_memes(self, meme_ids: list) -> dict:
        """批量删除，返回 {ok, deleted}"""
        ids = list(dict.fromkeys(int(x) for x in (meme_ids or [])))
        return self._library.delete_memes(ids)

    # 递归获取分组及其所有子分组的 ID 列表
    def _get_collection_ids_recursive(self, collection_id):
        return self._catalog._collection_ids(collection_id)

    # 构建嵌套分组树并统计各分组成员数
    def _build_collection_tree(self, parent_id=None):
        return self._catalog.collection_tree()

    def get_collections(self) -> list:
        return self._catalog.get_collections()

    def get_child_collections(self, parent_id: int) -> list:
        return self._catalog.get_child_collections(parent_id)

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
            return self._catalog.get_collection_members(collection_id)
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
        cid = self._library.create_collection(name)
        if cid < 0:
            return False
        return self._library.add_to_collection(meme_id, cid)

    def add_to_existing_collection(self, meme_id: int, collection_id: int) -> bool:
        try:
            return self._library.add_to_collection(meme_id, collection_id)
        except Exception:
            return False

    def set_collection_members(self, collection_id: int, meme_ids: list) -> bool:
        """批量设置分组内成员（先清空再写入），供添加分组弹窗确定时保存右侧列表"""
        try:
            return self._library.set_collection_members(collection_id, meme_ids)
        except Exception:
            return False

    def set_collection_members_new(self, name: str, meme_ids: list) -> dict:
        """创建新分组并批量设置成员，返回 {ok, id}"""
        return self._library.create_collection_with_members(name, meme_ids)

    def reorder_memes(self, meme_ids: list) -> bool:
        return self._catalog.reorder_memes(meme_ids)

    def reorder_collections(self, collection_ids: list) -> bool:
        return self._catalog.reorder_collections(collection_ids)

    def reorder_collection_members(self, collection_id: int, meme_ids: list) -> bool:
        return self._catalog.reorder_collection_members(collection_id, meme_ids)

    def delete_collection(self, collection_id: int) -> bool:
        try:
            return self._library.delete_collection(collection_id)
        except Exception:
            return False

    def rename_collection(self, collection_id: int, new_name: str) -> bool:
        if not new_name:
            return False
        try:
            return self._library.rename_collection(collection_id, new_name)
        except Exception:
            return False

    def create_subcollection(self, name: str, parent_id: int) -> dict:
        depth = self._catalog.collection_depth(parent_id)
        if depth >= 1:
            return {"ok": False, "error": "最大支持1层小分组"}
        cid = self._library.create_collection(name, parent_id=parent_id)
        if cid < 0:
            return {"ok": False}
        return {"ok": True, "id": cid}

    def record_meme_use(self, meme_id: int) -> bool:
        try:
            self._library.record_use(meme_id)
            return True
        except Exception:
            return False

    def remove_from_recent(self, meme_id: int) -> bool:
        try:
            self._library.remove_from_recent(meme_id)
            return True
        except Exception:
            return False

    def clear_recent(self) -> bool:
        try:
            self._library.clear_recent()
            return True
        except Exception:
            return False

    def remove_from_collection(self, meme_id: int, collection_id: int) -> bool:
        return self._library.remove_from_collection(meme_id, collection_id)

    def log(self, msg, level="info"):
        """供前端输出调试日志到终端"""
        getattr(logger, level, logger.info)(msg)

    def rescan_cache(self) -> bool:
        return self._catalog.rescan_cache(self._cfg.cache_dir)

    # 非阻塞检查更新：新鲜缓存即返，首次/过期/force 触发后台检查返回 pending
    def check_update(self, debug=False, force=False) -> dict:
        from ohmymeme import __version__ as cur_ver

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
            try:
                r = _import_result_payload(self._library.import_paths([local_path]))
            except Exception as e:
                return {"ok": False, "error": str(e)}
            ids = r.get("ids") or []
            if ids:
                return {"ok": True, "id": ids[0]}
            if r.get("rejected"):
                return {
                    "ok": False,
                    "rejected": r["rejected"],
                    "error": "文件超过大小/分辨率限制，已跳过",
                }
            return {"ok": False, "error": "导入失败"}

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
            r = _import_result_payload(self._library.import_paths([final_path]))
            ids = r.get("ids") or []
            if ids:
                return {"ok": True, "id": ids[0]}
            if r.get("rejected"):
                return {
                    "ok": False,
                    "rejected": r["rejected"],
                    "error": "文件超过大小/分辨率限制，已跳过",
                }
            return {"ok": False, "error": "导入失败"}
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

    def get_sync_progress(self) -> dict:
        return sync_module.get_sync_progress()

    def sync_push(self) -> dict:
        try:
            r = self._webui._container.create_sync_service().push()
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
            r = self._webui._container.create_sync_service().pull()
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
        try:
            return self._webui._container.create_sync_service().auto_sync()
        except Exception as e:
            return {"fetched": False, "synced": False, "error": str(e)}

    def sync_test(self) -> str:
        try:
            return self._webui._container.create_sync_service().test_connection()
        except Exception as e:
            return str(e)

    def import_memes(self) -> bool:
        # 通过系统文件对话框选择导入
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
        r = self._catalog.import_paths(result)
        return {
            "ok": True,
            "imported": len(r.get("ids") or []),
            "rejected": r.get("rejected", 0),
        }

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
            allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
            files = []
            names = []
            for root, _, fnames in os.walk(folder):
                for fn in sorted(fnames):
                    ext = os.path.splitext(fn)[1].lower()
                    if ext not in allowed:
                        continue
                    files.append(os.path.join(root, fn))
                    names.append(os.path.splitext(fn)[0])
            if not files:
                return {"ok": False, "error": "文件夹中没有支持的图片"}
            r = self._catalog.import_folder(
                files,
                names,
                os.path.basename(os.path.normpath(folder)),
                make_collection,
            )
            ids = r.get("ids") or []
            rejected = r.get("rejected", 0)
            collection_id = r.get("collection_id")
            folder_name = os.path.basename(os.path.normpath(folder))
            return {
                "ok": True,
                "imported": len(ids),
                "rejected": rejected,
                "collection_id": collection_id,
                "collection_name": folder_name if make_collection and ids else None,
            }
        except Exception as e:
            logger.error(f"import_folder failed: {e}")
            return {"ok": False, "error": str(e)}

    def import_from_clipboard(self) -> dict:
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
                try:
                    r = self._library.import_clipboard_paths(paths)
                except Exception as e:
                    return {"ok": False, "error": str(e)}
                ids = r.get("ids") or []
                rejected = r.get("rejected", 0)
                if ids:
                    return {
                        "ok": True,
                        "id": ids[0],
                        "name": r.get("name") or "未命名",
                        "rejected": rejected,
                    }
                return {"ok": True, "id": 0, "name": "未命名", "rejected": rejected}
            img = clip
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp_path = tmp.name
            tmp.close()
            try:
                img.save(tmp_path, "PNG")
                try:
                    r = self._library.import_clipboard_paths([tmp_path], [""])
                except Exception as e:
                    return {"ok": False, "error": str(e)}
                ids = r.get("ids") or []
                rejected = r.get("rejected", 0)
                if ids:
                    return {
                        "ok": True,
                        "id": ids[0],
                        "name": "未命名",
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

    def lan_confirm_device(self, approved: bool, confirm_id: str = "") -> dict:
        from ohmymeme.services import lan

        lan.confirm_device(bool(approved), confirm_id)
        return {"ok": True}

    def get_settings(self) -> dict:
        return self._settings.get_settings()

    def save_settings(self, settings: dict):
        hotkey = self._settings.save_settings(settings)
        if hotkey:
            self._webui._on_hotkey_change(hotkey)

    def reset_settings(self) -> dict:
        result = self._settings.reset_settings()
        self._webui._on_hotkey_change(result["hotkey"])
        return result

    def move_window(self, dx: int, dy: int):
        w = self._webui._window
        if w:
            try:
                w.move(w.x + dx, w.y + dy)
            except Exception:
                pass

    def start_window_drag(self, button: int, root_x: int, root_y: int) -> bool:
        """Linux 用 GTK begin_move_drag 合成器拖动；其他平台走增量回退"""
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
_QQNT_JOB_MANAGER = None
_QQNT_JOB_ID = None
_QQNT_JOB_SNAPSHOT = None


def _set_qqnt(**kw):
    global _QQNT_JOB_SNAPSHOT
    with _QQNT_LOCK:
        _QQNT_STATE.update(**kw)
        snapshot = _QQNT_JOB_SNAPSHOT
        state = dict(_QQNT_STATE)
    if snapshot is not None:
        snapshot(
            phase=state["status"],
            progress=state["progress"] / 100,
            message=state["message"],
            error_code="error" if state["status"] == "error" else "",
            error=state["error"],
        )


def _append_qqnt_log(msg):
    with _QQNT_LOCK:
        _QQNT_STATE["log"] = (_QQNT_STATE["log"] + [msg])[-100:]


def get_qqnt_progress() -> dict:
    with _QQNT_LOCK:
        return dict(_QQNT_STATE)


def cancel_qqnt_extract():
    global _QQNT_CANCEL
    _QQNT_CANCEL = True
    if _QQNT_JOB_MANAGER is not None and _QQNT_JOB_ID is not None:
        _QQNT_JOB_MANAGER.cancel(_QQNT_JOB_ID)


def start_qqnt_extract(
    qq_number: str,
    output_dir: str,
    image_only: bool = False,
    overwrite: bool = False,
    ini_path: str = None,
    userdata_save_path: str = None,
    job_manager=None,
) -> bool:
    global _QQNT_CANCEL, _QQNT_JOB_MANAGER, _QQNT_JOB_ID
    if job_manager is not None and job_manager.active("import.qqnt") is not None:
        return False
    with _QQNT_LOCK:
        if job_manager is None and _QQNT_STATE["status"] == "running":
            return False
        _QQNT_CANCEL = False
        _QQNT_STATE.update(
            status="running",
            progress=0,
            message="准备中",
            error="",
            log=[],
            result=None,
        )
    args = (
        qq_number,
        output_dir,
        image_only,
        overwrite,
        ini_path,
        userdata_save_path,
    )
    if job_manager is None:
        threading.Thread(target=_qqnt_worker, args=args, daemon=True).start()
    else:

        def target(context):
            global _QQNT_JOB_MANAGER, _QQNT_JOB_ID, _QQNT_JOB_SNAPSHOT
            _QQNT_JOB_MANAGER = job_manager
            _QQNT_JOB_ID = context.job_id
            _QQNT_JOB_SNAPSHOT = context.snapshot
            try:
                _qqnt_worker(*args, cancellation_event=context.cancellation_event)
                if _QQNT_STATE["status"] == "error":
                    raise RuntimeError(_QQNT_STATE["error"])
            finally:
                _QQNT_JOB_MANAGER = None
                _QQNT_JOB_ID = None
                _QQNT_JOB_SNAPSHOT = None

        record, created = job_manager.try_start(
            "import.qqnt", target, resources=("qqnt",)
        )
        if not created:
            return False
        with _QQNT_LOCK:
            if job_manager.active("import.qqnt") is not None:
                _QQNT_JOB_ID = record.id
    return True


def _qqnt_worker(
    qq_number,
    output_dir,
    image_only,
    overwrite,
    ini_path,
    userdata_save_path,
    cancellation_event=None,
):
    """后台执行 QQNT 表情提取并转发进度/错误到 _QQNT_STATE"""

    def on_progress(done, total, src, dst):
        pct = int(done * 100 / total) if total else 0
        _set_qqnt(progress=pct, message="复制中 %d/%d" % (done, total))

    def on_error(src, msg):
        _append_qqnt_log("失败: %s (%s)" % (src, msg))

    def on_log(msg):
        _append_qqnt_log(msg)

    try:
        result = qqnt.extract_qq_emojis(
            qq_number,
            output_dir,
            userdata_save_path=userdata_save_path,
            ini_path=ini_path or qqnt.DEFAULT_INI_PATH,
            image_only=image_only,
            overwrite=overwrite,
            should_stop=lambda: _QQNT_CANCEL
            or (cancellation_event is not None and cancellation_event.is_set()),
            on_progress=on_progress,
            on_error=on_error,
            on_log=on_log,
        )
        if _QQNT_CANCEL or (
            cancellation_event is not None and cancellation_event.is_set()
        ):
            _set_qqnt(status="cancelled", message="已取消", result=result)
        else:
            _set_qqnt(status="done", progress=100, message="提取完成", result=result)
    except Exception as e:
        logger.error("qqnt extract error: %s", e)
        _set_qqnt(status="error", message="提取失败", error=str(e))


class SettingsApi:
    """暴露给设置窗口的 JS API（仅设置相关方法）"""

    def __init__(self, webui, settings):
        self._webui = webui
        self._cfg = webui._cfg
        self._settings = settings
        self._library = webui._container.library

    def check_connectivity(self) -> dict:
        return _check_connectivity()

    def lan_start(self, port: int = None, secret: str = None) -> dict:
        p = int(port or self._cfg.get("lan_port", 17852))
        s = secret if secret is not None else self._cfg.get("lan_secret", "")
        from ohmymeme.services import lan

        ok = self._webui._container.start_lan(p, s)
        return {"ok": ok, "status": lan.get_status()}

    def lan_stop(self) -> dict:
        from ohmymeme.services import lan

        self._webui._container.stop_lan()
        return {"ok": True, "status": lan.get_status()}

    def lan_get_status(self) -> dict:
        from ohmymeme.services import lan

        return lan.get_status()

    def lan_get_ip(self) -> str:
        from ohmymeme.services import lan

        return lan.get_lan_ip()

    def lan_set_allow_secret_config(self, enabled: bool) -> dict:
        from ohmymeme.services import lan

        lan.set_allow_secret_config(bool(enabled))
        return {
            "ok": True,
            "allow_secret_config": lan.get_status()["allow_secret_config"],
        }

    def get_settings(self) -> dict:
        return self._settings.get_settings()

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
        hotkey = self._settings.save_settings(settings)
        if hotkey:
            self._webui._on_hotkey_change(hotkey)

    def reset_settings(self) -> dict:
        result = self._settings.reset_settings()
        self._webui._on_hotkey_change(result["hotkey"])
        return result

    def move_window(self, dx: int, dy: int):
        w = self._webui._settings_window
        if w:
            try:
                w.move(w.x + dx, w.y + dy)
            except Exception:
                pass

    def start_window_drag(self, button: int, root_x: int, root_y: int) -> bool:
        """Linux 用 GTK begin_move_drag 合成器拖动；其他平台走增量回退"""
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
        started = adb_qq.start_qq_import(self._webui._container.job_manager)
        return {"ok": started, **({} if started else {"error": "已有导入任务正在进行"})}

    def get_qq_import_progress(self) -> dict:
        return adb_qq.get_qq_progress()

    def save_qq_zip(self) -> dict:
        """把生成的 QQ ZIP 通过另存为对话框保存到用户选择的位置"""
        st = adb_qq.get_qq_progress()
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
        adb_qq.reset_qq_import()
        return {"ok": True, "path": dst}

    def open_adb_folder(self) -> bool:
        try:
            adb_qq.open_adb_folder()
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
            adb_qq.open_adb_help()
            return True
        except Exception:
            return False

    def cancel_qq_import(self):
        adb_qq.cancel_qq_import()

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
        if not telegram.is_valid_tdata(path):
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
        started = telegram.start_tg_import(
            self._webui._container.library.import_paths,
            tdata_path,
            passcode,
            convert_webm,
            self._webui._container.job_manager,
        )
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_tg_import_progress(self) -> dict:
        return telegram.get_tg_progress()

    def cancel_tg_import(self):
        telegram.cancel_tg_import()

    def start_douyin_import(self, cookie: str) -> dict:
        """启动抖音表情包下载导入（全部下载）"""
        try:
            from ohmymeme.integrations.imports import douyin
        except ImportError as e:
            return {"ok": False, "error": f"缺少依赖: {e}"}

        started = douyin.start_douyin_import(
            self._webui._container.library.import_paths,
            cookie,
            self._webui._container.job_manager,
        )
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_douyin_import_progress(self) -> dict:
        from ohmymeme.integrations.imports import douyin

        return douyin.get_douyin_progress()

    def cancel_douyin_import(self):
        from ohmymeme.integrations.imports import douyin

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
        from ohmymeme.integrations.imports import wechat

        return wechat.inspect_wechat_environment(user_root)

    def list_wechat_stickers(self, user_root, account_path=None):
        """列出可导入的微信表情"""
        from ohmymeme.integrations.imports import wechat

        return wechat.list_wechat_stickers(user_root, account_path)

    def start_wechat_import(self, user_root=None, download=True, account_path=None):
        """启动微信表情包导入，已有任务时返回 {"ok": False}"""
        from ohmymeme.integrations.imports import wechat

        started = wechat.start_wechat_import(
            self._webui._container.library.import_paths,
            user_root,
            download,
            account_path,
            self._webui._container.job_manager,
        )
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_wechat_import_progress(self):
        """获取微信导入进度"""
        from ohmymeme.integrations.imports import wechat

        return wechat.get_wechat_progress()

    def cancel_wechat_import(self):
        """取消微信导入"""
        from ohmymeme.integrations.imports import wechat

        wechat.cancel_wechat_import()

    def qqnt_check_env(self) -> dict:
        """检查 QQNT 提取环境，返回 get_extract_status 结果"""
        return qqnt.get_extract_status(
            ini_path=self._cfg.get("qqnt_ini_path") or qqnt.DEFAULT_INI_PATH,
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
        return self._library.storage_info()

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
        """应用新的表情包存储目录；move_files=True 时把现有文件迁移过去"""
        try:
            result = self._library.apply_storage_dir(path, move_files)
        except Exception as error:
            return {"ok": False, "error": str(error)}
        if not result.get("ok"):
            return result
        fc = getattr(self._webui, "_file_cache", None)
        if fc is not None:
            fc.clear()
        try:
            if len(webview.windows) > 0:
                webview.windows[0].evaluate_js("refreshMemes();")
        except Exception:
            pass
        return result

    def qqnt_default_dir(self, base: str, qq_number: str) -> dict:
        """按账号生成默认输出目录（昵称+QQ号）"""
        try:
            d = qqnt.get_default_output_dir(base, qq_number, fetch_nickname=True)
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
            job_manager=self._webui._container.job_manager,
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
        try:
            r = _import_result_payload(self._library.import_paths(result))
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "imported": len(r.get("ids") or []),
            "rejected": r.get("rejected", 0),
        }

    def close_settings(self):
        self._webui.close_settings()

    def get_current_version(self) -> str:
        from ohmymeme import __version__

        return __version__

    # 非阻塞检查更新：新鲜缓存即返，首次/过期/force 触发后台检查返回 pending
    def check_update(self, debug=False, force=False) -> dict:
        from ohmymeme import __version__ as cur_ver

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
            r = self._webui._container.create_sync_service().push(
                delete_remote=delete_remote
            )
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
            r = self._webui._container.create_sync_service().pull(
                remove_local=remove_local
            )
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
            return self._webui._container.create_sync_service().test_connection()
        except Exception as e:
            return str(e)

    def delete_all_local(self) -> dict:
        """删除本地所有表情包"""
        try:
            if not self._library.delete_all():
                return {"ok": False, "error": "删除本地表情失败"}
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
            return self._webui._container.create_sync_service().delete_all_remote()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_remote_orphans(self, delete: bool = False) -> dict:
        """扫描云端孤儿文件；delete=True 时物理删除"""
        try:
            return self._webui._container.create_sync_service().cleanup_remote_orphans(
                delete=delete
            )
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def check_sync_status(self) -> dict:
        """比较本地与云端同步状态"""
        try:
            manifest = self._webui._container.create_sync_service().get_status()
            return manifest
        except AttributeError:
            return {"ok": False, "error": "同步状态服务不可用"}
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


def _detect_image_ext(path):
    """读取文件头魔数识别真实扩展名（QQ 保存常为 .jpg，实为 png/webp 等），未知返回空串"""  # noqa: E501
    try:
        with open(path, "rb") as f:
            return adb_qq._detect_ext(f.read(16))
    except OSError:
        return ""


def _try_decode_stego(gif_path):
    """实验性：检测 GIF 隐写并解码还原原图到临时文件；非隐写/失败返回 None"""
    try:
        with open(gif_path, "rb") as f:
            if b"STG3" not in f.read():
                return None
        from ohmymeme.core.gif_stego import decode as stego_decode
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

    def __init__(
        self, container, update_debug: bool = False, silent_start: bool = False
    ):
        self._container = container
        self._cfg = container.config
        self._db = container.db
        locator = container.resource_locator
        self._html_dir = locator.webui_dir
        self._resources_dir = locator.resources_dir
        self._window = None
        self._settings_window = None
        self._port = self._find_free_port()
        self._bottle_thread = None
        self._bottle_server = None
        self._bottle_lock = threading.Lock()
        self._bottle_stopping = False
        self._api = JsApi(
            self, container.catalog, container.settings, container.library
        )
        self._settings_api = SettingsApi(self, container.settings)
        self._visible = False
        self._started = False
        self._pending_hide = False
        self._hotkey_session = False
        self._on_hotkey_change_cb = None
        self._update_debug = update_debug
        self._silent_start = silent_start
        self._decode_stego = _try_decode_stego
        container.library.configure_stego_decoder(self._decode_stego)

    def _init_lan(self):
        from ohmymeme.services import lan

        lan.set_confirm_callback(self._lan_confirm_cb)

    def set_on_hotkey_change(self, cb):
        self._on_hotkey_change_cb = cb

    def _lan_confirm_cb(self, device: dict):
        """LAN 设备连接确认：显示主窗口并弹窗展示设备信息，等待 JS 回传结果"""
        import json

        from ohmymeme.services import lan

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
        return thumbnail_path(self, meme_id, filename, size)

    def _do_import(self, file_paths, names=None):
        return import_paths(self, file_paths, names)

    def _on_hotkey_change(self, new_hotkey: str):
        if self._on_hotkey_change_cb:
            self._on_hotkey_change_cb(new_hotkey)

    # --- Bottle 路由 ---

    def _setup_bottle(self):
        app = bottle.Bottle()

        install_security_hooks(app, bottle, self._port)

        @app.route("/")
        def index():
            vue_html = self._html_dir / "vue.html"
            # 仅当 vue.html 与构建产物都存在时才走 Vue 前端，否则回退旧 index.html
            if vue_html.exists() and (self._html_dir / "dist" / "ohmymeme.js").exists():
                return bottle.static_file("vue.html", root=str(self._html_dir))
            html_path = self._html_dir / "index.html"
            if html_path.exists():
                return bottle.static_file("index.html", root=str(self._html_dir))
            return "<h1>OhMyMeme</h1><p>index.html not found</p>"

        @app.route("/settings/")
        def settings_page():
            html_path = self._html_dir / "settings.html"
            if html_path.exists():
                return bottle.static_file("settings.html", root=str(self._html_dir))
            return "<h1>设置</h1><p>settings.html not found</p>"

        @app.route("/api/contributors")
        def serve_contributors():
            # 代理贡献者 SVG：剥离白色背景矩形，适配深色主题
            try:
                from urllib.request import Request, urlopen

                url = "https://contributor.starsfire.top/TNTXZ/OhMyMeme"
                req = Request(url, headers={"User-Agent": "OhMyMeme"})
                with urlopen(req, timeout=10) as resp:
                    svg = resp.read().decode("utf-8", "replace")
                white_rect = '<rect width="100%" height="100%" fill="#ffffff"/>'
                svg = svg.replace(white_rect, "")
                bottle.response.content_type = "image/svg+xml; charset=utf-8"
                return svg
            except Exception:
                bottle.response.status = 502
                return ""

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
            path = self._container.library.find_meme_file(filename)
            if path:
                ext = os.path.splitext(filename)[1].lower()
                ctype = original_mime_type(ext)
                return bottle.static_file(
                    os.path.basename(path), root=os.path.dirname(path), mimetype=ctype
                )
            bottle.response.status = 404
            return ""

        @app.route("/api/upload/", method="POST")
        def upload_memes():
            try:
                import json

                content_length = bottle.request.headers.get("Content-Length", "0")
                if (
                    content_length.isdigit()
                    and int(content_length) > _UPLOAD_BODY_LIMIT
                ):
                    bottle.response.status = 413
                    return {"ok": False, "error": "上传内容超过限制"}
                body = _read_upload_body(bottle.request.body)
                if body is None:
                    bottle.response.status = 413
                    return {"ok": False, "error": "上传内容超过限制"}
                data = json.loads(body)
                files = data.get("files", []) if isinstance(data, dict) else data
                if not isinstance(files, list) or len(files) > 200:
                    bottle.response.status = 413
                    return {"ok": False, "error": "上传项目超过限制"}
                requests = []
                for item in files:
                    oname = item.get("name", "")
                    b64 = item.get("data", "")
                    if not oname or not b64:
                        continue
                    import base64

                    if len(b64) > _UPLOAD_BODY_LIMIT:
                        continue
                    raw = base64.b64decode(b64)
                    requests.append(ImportBytes(raw, oname))
                if requests:
                    self._container.library.import_batch(requests)
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
            return bottle.static_file(name, root=str(self._resources_dir))

        @app.route("/<filepath:path>")
        def static_files(filepath):
            # 按扩展名强制 MIME，规避本机 .js 映射被改写成 text/plain 时
            # 叠加 nosniff 导致 Chromium 拒执行脚本；未知类型走 bottle 自动检测
            ctype = static_mime_type(filepath)
            if ctype:
                return bottle.static_file(
                    filepath, root=str(self._html_dir), mimetype=ctype
                )
            return bottle.static_file(filepath, root=str(self._html_dir))

        server = make_server("127.0.0.1", self._port, app)
        with self._bottle_lock:
            if self._bottle_stopping:
                server.server_close()
                return
            self._bottle_server = server
        try:
            server.serve_forever()
        finally:
            server.server_close()
            with self._bottle_lock:
                if self._bottle_server is server:
                    self._bottle_server = None

    # --- 缓存扫描 ---

    def scan_cache(self):
        self._container.library.rescan_cache(self._cfg.cache_dir)

    # --- 启动 ---

    def start(self) -> bool:
        if not HAS_WEBVIEW:
            logger.error("pywebview not installed")
            return False
        if not HAS_BOTTLE:
            logger.error("bottle not installed")
            return False

        with self._bottle_lock:
            self._bottle_stopping = False
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
            self._webui._container.stop_lan()
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

    def _remember_window_position(self):
        if not self._window:
            return
        self._cfg.set("window_x", self._window.x)
        self._cfg.set("window_y", self._window.y)

    def stop(self):
        self._remember_window_position()
        with self._bottle_lock:
            self._bottle_stopping = True
            server = self._bottle_server
        if server is not None:
            server.shutdown()
        if self._bottle_thread is not None:
            bottle_thread = self._bottle_thread
            bottle_thread.join(1.0)
            if bottle_thread.is_alive():
                bottle_thread.join(1.0)
            self._bottle_thread = None
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
