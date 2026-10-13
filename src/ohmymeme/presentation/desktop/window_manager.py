"""PyWebView 现代化 UI 窗口管理器 + JS API"""

import binascii
import logging
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

from ohmymeme.app.remote_mutation_coordinator import (
    RemoteMutationBusyError,
    RemoteMutationConflictError,
)
from ohmymeme.core.adapters.fetch_policy import (
    FetchError,
    FetchPolicy,
    validate_image_bytes,
)
from ohmymeme.core.imports import ImportBytes, ImportPath
from ohmymeme.integrations.imports import adb_qq, qqnt, telegram
from ohmymeme.integrations.platform.clipboard import (
    convert_image_mode_1,
    convert_image_mode_2,
    convert_image_mode_3,
    copy_image_to_clipboard,
)
from ohmymeme.services import updates as updater
from ohmymeme.services.sync import service as sync_module

from .api.facades import JsApi, SettingsApi
from .api.plugin_dispatch import compatibility_registry
from .api.pywebview_adapter import PyWebViewAdapter
from .bottle_app import create_bottle_app, install_security_hooks
from .import_workers import import_paths
from .media import find_meme_file, thumbnail_path
from .routes.media import original_mime_type
from .routes.pages import STATIC_MIME_TYPES, static_mime_type
from .routes.upload import UPLOAD_BODY_LIMIT, read_upload_body
from .security import host_allowed, safe_serve_filename, storage_dir_validation

logger = logging.getLogger(__name__)
_FETCH_POLICY = FetchPolicy()

# 内存日志缓冲：固定收集 DEBUG 级日志，供设置页"导出日志"
_LOG_BUFFER = []
_LOG_LOCK = threading.Lock()
_LOG_MAX = 5000

# 分页：主窗口单页展示的表情包数量（与前端 useMemes.ts MEME_PAGE 保持一致）
MEME_PAGE = 200
_UPLOAD_BODY_LIMIT = UPLOAD_BODY_LIMIT


def _read_upload_body(stream):
    return read_upload_body(stream)


def _webview_adapter(webui):
    """Return the host-owned pywebview boundary adapter."""
    adapter = getattr(webui, "_pywebview", None)
    if adapter is not None:
        return adapter
    return PyWebViewAdapter(webview if HAS_WEBVIEW else None, webui)


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
    hosts = ("https://baidu.com/", "https://www.baidu.com/")
    for url in hosts:
        try:
            t0 = time.time()
            _FETCH_POLICY.probe(url)
            latency = int((time.time() - t0) * 1000)
            return {"ok": True, "latency": f"{latency}ms"}
        except (FetchError, OSError):
            continue
    return {"ok": False, "latency": ""}


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


class _LegacyJsApi:
    """暴露给前端的 JS API"""

    def __init__(self, webui, catalog, settings):
        self._webui = webui
        self._cfg = webui._cfg
        self._catalog = catalog
        self._settings = settings
        self._sync = getattr(getattr(webui, "_container", None), "sync", sync_module)

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
        filename = self._catalog.get_meme_filename(meme_id)
        if not filename:
            return ""
        return self._find_meme_file(filename)

    def get_meme_paths(self, meme_ids: list) -> dict:
        """批量返回表情本地文件路径 {id: path}，供拖拽到外部应用"""
        out = {}
        for mid in meme_ids:
            try:
                meme_id = int(mid)
                filename = self._catalog.get_meme_filename(meme_id)
                if filename:
                    p = self._find_meme_file(filename)
                    if p:
                        out[meme_id] = p
            except Exception:
                continue
        return out

    def start_native_drag(self, meme_id: int) -> bool:
        """用 WinForms DoDragDrop 启动原生文件拖拽（QQ/微信可接收真实文件）"""
        filename = self._catalog.get_meme_filename(meme_id)
        if not filename:
            return False
        p = self._find_meme_file(filename)
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
        filename = self._catalog.get_meme_filename(meme_id)
        if not filename:
            return {"ok": False, "status": "copy_failed"}
        path = self._find_meme_file(filename)
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
            self._catalog.record_meme_use(meme_id)
        self._webui.schedule_hide()
        return {"ok": True, "status": "copied"}

    def toggle_favorite(self, meme_id: int) -> bool:
        return self._catalog.toggle_favorite(meme_id)

    def is_favorite(self, meme_id: int) -> bool:
        return self._catalog.is_favorite(meme_id)

    def rename_meme(self, meme_id: int, new_name: str) -> bool:
        return self._catalog.rename_meme(meme_id, new_name)

    def _delete_meme_files(self, meme_id, filename) -> bool:
        """删除磁盘原图+缩略图+file_cache 条目；id 不存在返回 False"""
        import os

        if not filename:
            return False
        file_path = self._find_meme_file(filename)
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
            self._webui._file_cache.pop(filename, None)
        return True

    def delete_meme(self, meme_id: int) -> bool:
        filename = self._catalog.get_meme_filename(meme_id)
        if not self._delete_meme_files(meme_id, filename):
            return False
        return self._catalog.delete_meme(meme_id)

    def delete_memes(self, meme_ids: list) -> dict:
        """批量删除，返回 {ok, deleted}"""
        ids = list(dict.fromkeys(int(x) for x in (meme_ids or [])))
        deleted = 0
        persisted = []
        for mid in ids:
            filename = self._catalog.get_meme_filename(mid)
            if self._delete_meme_files(mid, filename):
                deleted += 1
                persisted.append(mid)
        if deleted:
            self._catalog.delete_memes(persisted)
        return {"ok": True, "deleted": deleted}

    def get_collections(self) -> list:
        return self._catalog.get_collections()

    def get_child_collections(self, parent_id: int) -> list:
        return self._catalog.get_child_collections(parent_id)

    def search_collections(self, keyword: str = "") -> list:
        """按名称搜索已有分组（顶层 + 子分组），供添加分组弹窗下拉框"""
        return self._catalog.search_collections(keyword)

    def get_collection_members(self, collection_id: int) -> list:
        """返回分组内表情成员，供添加分组弹窗右侧栏展示"""
        return self._catalog.get_collection_members(collection_id)

    def add_to_collection(self, meme_id: int, name: str) -> bool:
        return self._catalog.add_to_collection(meme_id, name)

    def add_to_existing_collection(self, meme_id: int, collection_id: int) -> bool:
        return self._catalog.add_to_existing_collection(meme_id, collection_id)

    def set_collection_members(self, collection_id: int, meme_ids: list) -> bool:
        """批量设置分组内成员（先清空再写入），供添加分组弹窗确定时保存右侧列表"""
        return self._catalog.set_collection_members(collection_id, meme_ids)

    def set_collection_members_new(self, name: str, meme_ids: list) -> dict:
        """创建新分组并批量设置成员，返回 {ok, id}"""
        return self._catalog.create_collection_members(name, meme_ids)

    def reorder_memes(self, meme_ids: list) -> bool:
        return self._catalog.reorder_memes(meme_ids)

    def reorder_collections(self, collection_ids: list) -> bool:
        return self._catalog.reorder_collections(collection_ids)

    def reorder_collection_members(self, collection_id: int, meme_ids: list) -> bool:
        return self._catalog.reorder_collection_members(collection_id, meme_ids)

    def delete_collection(self, collection_id: int) -> bool:
        return self._catalog.delete_collection(collection_id)

    def rename_collection(self, collection_id: int, new_name: str) -> bool:
        return self._catalog.rename_collection(collection_id, new_name)

    def create_subcollection(self, name: str, parent_id: int) -> dict:
        return self._catalog.create_subcollection(name, parent_id)

    def record_meme_use(self, meme_id: int) -> bool:
        return self._catalog.record_meme_use(meme_id)

    def remove_from_recent(self, meme_id: int) -> bool:
        return self._catalog.remove_from_recent(meme_id)

    def clear_recent(self) -> bool:
        return self._catalog.clear_recent()

    def remove_from_collection(self, meme_id: int, collection_id: int) -> bool:
        return self._catalog.remove_from_collection(meme_id, collection_id)

    def log(self, msg, level="info"):
        """供前端输出调试日志到终端"""
        getattr(logger, level, logger.info)(msg)

    def rescan_cache(self) -> bool:
        self._webui.scan_cache()
        return True

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
        ok = updater.run_installer(path, updater._ASSET_HASHES.get(path))
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
            r = self._webui._do_import([local_path])
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
        from urllib.parse import urlparse

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
            data = _FETCH_POLICY.fetch_bytes(clean_url, image=True)
            if need_type:
                ext = validate_image_bytes(data)
            with open(tmp_path, "wb") as f:
                f.write(data)
            # 重命名为正确扩展名
            final_path = tmp_path + ext
            os.rename(tmp_path, final_path)
            r = self._webui._do_import([final_path])
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
        except FetchError as e:
            return {"ok": False, "error": f"下载失败: {e}"}
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
        return self._sync.get_sync_progress()

    def sync_push(self) -> dict:
        try:
            r = self._sync.push()
            r["ok"] = True
            return r
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "failed_files": (
                    self._sync.get_sync_progress().get("failed_items", [])
                    if hasattr(self._sync, "get_sync_progress")
                    else sync_module.get_sync_progress().get("failed_items", [])
                ),
            }

    def sync_pull(self) -> dict:
        try:
            r = self._sync.pull()
            r["ok"] = True
            return r
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "failed_files": (
                    self._sync.get_sync_progress().get("failed_items", [])
                    if hasattr(self._sync, "get_sync_progress")
                    else sync_module.get_sync_progress().get("failed_items", [])
                ),
            }

    def run_auto_sync(self) -> dict:
        """启动时自动同步：根据配置拉取远端索引和/或全量同步"""
        result = {"fetched": False, "synced": False, "error": ""}
        sync_type = self._cfg.get("sync_type", "")
        if not sync_type:
            return result
        try:
            if self._cfg.get("sync_auto_fetch_index", False):
                data = self._sync.download_index()
                result["fetched"] = data is not None
            if self._cfg.get("sync_auto_sync", False):
                r = self._sync.pull()
                result["synced"] = r.get("downloaded", 0) > 0
        except Exception as e:
            result["error"] = str(e)
        return result

    def sync_test(self) -> str:
        try:
            return self._sync.sync_test()
        except Exception as e:
            return str(e)

    def import_memes(self) -> bool:
        # 通过系统文件对话框选择导入
        result = _webview_adapter(self._webui).file_dialog(
            "main",
            "open",
            allow_multiple=True,
            file_types=("图片文件 (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)",),
        )
        if result is None:
            return {"ok": False}
        if not result:
            return {"ok": False, "cancelled": True}
        r = self._webui._do_import(result)
        return {
            "ok": True,
            "imported": len(r.get("ids") or []),
            "rejected": r.get("rejected", 0),
        }

    def import_folder(self, make_collection=True) -> dict:
        """选择文件夹并导入其中全部图片；make_collection 时以文件夹名创建分组"""
        result = _webview_adapter(self._webui).file_dialog("main", "folder")
        if result is None:
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
            r = self._webui._do_import(files, names)
            ids = r.get("ids") or []
            rejected = r.get("rejected", 0)
            collection_id = None
            folder_name = os.path.basename(os.path.normpath(folder))
            if make_collection and ids:
                collection_id = self._catalog.add_imported_to_collection(
                    folder_name, ids
                )
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
        import hashlib

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
                    orig = self._catalog.get_meme_display_name(ids[0])
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
                if self._catalog.has_meme_hash(sha256.hexdigest()):
                    return {"ok": False, "error": "该图片已存在"}
                r = self._webui._do_import([tmp_path], [""])
                ids = r.get("ids") or []
                rejected = r.get("rejected", 0)
                if ids:
                    orig = self._catalog.get_meme_display_name(ids[0])
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
        _webview_adapter(self._webui).move("main", dx, dy)

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

    def _find_meme_file(self, filename: str) -> str:
        cache_dir = self._cfg.cache_dir
        for root, _, files in os.walk(cache_dir):
            if filename in files:
                return os.path.join(root, filename)
        return ""


class _LegacySettingsApi:
    """暴露给设置窗口的 JS API（仅设置相关方法）"""

    def __init__(self, webui, settings):
        self._webui = webui
        self._cfg = webui._cfg
        self._library = webui._library
        self._settings = settings
        self._sync = getattr(getattr(webui, "_container", None), "sync", sync_module)

    def _lan_service(self):
        from ohmymeme.services import lan

        return getattr(getattr(self._webui, "_container", None), "lan", lan)

    def check_connectivity(self) -> dict:
        return _check_connectivity()

    def lan_start(self, port: int = None, secret: str = None) -> dict:
        getter = getattr(self._cfg, "get_plugin_value", None)
        p, s = port, secret
        if p is None:
            p = (
                getter("transport.lan", "port", "lan_port", default=17852)
                if callable(getter)
                else self._cfg.get("lan_port", 17852)
            )
        if s is None:
            s = (
                getter("transport.lan", "secret", "lan_secret", default="", secret=True)
                if callable(getter)
                else self._cfg.get("lan_secret", "")
            )
        service = self._lan_service()
        ok = service.start(p, s)
        return {"ok": ok, "status": service.get_status()}

    def lan_stop(self) -> dict:
        service = self._lan_service()
        service.stop()
        return {"ok": True, "status": service.get_status()}

    def lan_get_status(self) -> dict:
        return self._lan_service().get_status()

    def lan_get_ip(self) -> str:
        return self._lan_service().get_lan_ip()

    def lan_set_allow_secret_config(self, enabled: bool) -> dict:
        service = self._lan_service()
        service.set_allow_secret_config(bool(enabled))
        return {
            "ok": True,
            "allow_secret_config": service.get_status()["allow_secret_config"],
        }

    def get_settings(self) -> dict:
        return self._settings.get_settings()
        d = self._cfg.to_dict()
        from ohmymeme.integrations.platform.system import is_auto_start_enabled

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
        _webview_adapter(self._webui).evaluate_main(f"{js_function}();")
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
        return

    def reset_settings(self) -> dict:
        result = self._settings.reset_settings()
        self._webui._on_hotkey_change(result["hotkey"])
        return result

    def move_window(self, dx: int, dy: int):
        _webview_adapter(self._webui).move("settings", dx, dy)

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
        adb_qq.start_qq_import()
        return {"ok": True}

    def get_qq_import_progress(self) -> dict:
        return adb_qq.get_qq_progress()

    def save_qq_zip(self) -> dict:
        """把生成的 QQ ZIP 通过另存为对话框保存到用户选择的位置"""
        st = adb_qq.get_qq_progress()
        if st["status"] != "done" or not st["zip_path"]:
            return {"ok": False, "error": "no zip ready"}
        result = _webview_adapter(self._webui).file_dialog(
            "settings", "save", file_types=("ZIP 文件 (*.zip)",)
        )
        if result is None:
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
        result = _webview_adapter(self._webui).file_dialog(
            "settings",
            "save",
            file_types=("文本文件 (*.txt)",),
            save_filename="OhMyMeme-logs.txt",
        )
        if result is None:
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
        result = _webview_adapter(self._webui).file_dialog("settings", "folder")
        if result is None:
            return {"ok": False, "error": "无法打开目录选择对话框"}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        from .import_workers import get_import_worker

        get_import_worker(self, "source.telegram")
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
        from .import_workers import get_import_worker

        started = get_import_worker(self, "source.telegram").start(
            {"tdata_path": tdata_path, "convert_webm": convert_webm},
            {"passcode": passcode},
        )
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_tg_import_progress(self) -> dict:
        from .import_workers import get_import_worker

        return get_import_worker(self, "source.telegram").get_progress()

    def cancel_tg_import(self):
        from .import_workers import get_import_worker

        get_import_worker(self, "source.telegram").cancel()

    def start_douyin_import(self, cookie: str) -> dict:
        """启动抖音表情包下载导入（全部下载）"""
        try:
            from .import_workers import get_import_worker

            worker = get_import_worker(self, "source.douyin")
        except ImportError as e:
            return {"ok": False, "error": f"缺少依赖: {e}"}

        started = worker.start({}, {"cookie": cookie})
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_douyin_import_progress(self) -> dict:
        from .import_workers import get_import_worker

        return get_import_worker(self, "source.douyin").get_progress()

    def cancel_douyin_import(self):
        from .import_workers import get_import_worker

        get_import_worker(self, "source.douyin").cancel()

    def pick_wechat_root(self):
        """手动选择微信文件根目录"""
        result = _webview_adapter(self._webui).file_dialog("settings", "folder")
        if result is None:
            return {"ok": False, "error": "无法打开目录选择对话框"}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        if not os.path.isdir(path):
            return {"ok": False, "error": "所选目录不存在"}
        return {"ok": True, "path": path}

    def inspect_wechat_environment(self, user_root=None):
        """检测微信环境"""
        from .import_workers import get_import_worker

        return get_import_worker(self, "source.wechat").query(
            "inspect", {"user_root": user_root}
        )

    def list_wechat_stickers(self, user_root, account_path=None):
        """列出可导入的微信表情"""
        from .import_workers import get_import_worker

        return get_import_worker(self, "source.wechat").list_wechat(
            user_root, account_path
        )

    def start_wechat_import(self, user_root=None, download=True, account_path=None):
        """启动微信表情包导入，已有任务时返回 {"ok": False}"""
        from .import_workers import get_import_worker

        started = get_import_worker(self, "source.wechat").start(
            {"user_root": user_root, "download": download, "account_path": account_path}
        )
        if not started:
            return {"ok": False, "error": "已有导入任务正在进行"}
        return {"ok": True}

    def get_wechat_import_progress(self):
        """获取微信导入进度"""
        from .import_workers import get_import_worker

        return get_import_worker(self, "source.wechat").get_progress()

    def cancel_wechat_import(self):
        """取消微信导入"""
        from .import_workers import get_import_worker

        get_import_worker(self, "source.wechat").cancel()

    def qqnt_check_env(self) -> dict:
        """检查 QQNT 提取环境，返回 get_extract_status 结果"""
        from .import_workers import get_import_worker

        worker = get_import_worker(self, "source.qqnt")
        return worker.query(
            "inspect",
            {
                "ini_path": self._cfg.get("qqnt_ini_path") or qqnt.DEFAULT_INI_PATH,
                "userdata_save_path": self._cfg.get("qqnt_userdata_path") or None,
            },
            nickname_lookup=qqnt.get_user_nickname,
        )

    def qqnt_pick_ini(self) -> dict:
        """选择 UserDataInfo.ini，保存到配置并返回环境状态"""
        result = _webview_adapter(self._webui).file_dialog(
            "settings", "open", file_types=("INI Files (*.ini);;All Files (*)",)
        )
        if result is None:
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
        result = _webview_adapter(self._webui).file_dialog("settings", "folder")
        if result is None:
            return {"ok": False}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        self._cfg.set("qqnt_userdata_path", path)
        self._cfg.save()
        return self.qqnt_check_env()

    def qqnt_pick_base(self) -> dict:
        """选择保存基础目录"""
        result = _webview_adapter(self._webui).file_dialog("settings", "folder")
        if result is None:
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
        result = _webview_adapter(self._webui).file_dialog("settings", "folder")
        if result is None:
            return {"ok": False, "error": "dialog failed"}
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (tuple, list)) else result
        return {"ok": True, "path": path}

    def apply_storage_dir(self, path, move_files=False):
        """应用新的表情包存储目录；move_files=True 时把现有文件迁移过去"""
        coordinator = getattr(
            getattr(self._webui, "_container", None), "remote_mutations", None
        )
        if coordinator is None:
            return self._apply_storage_dir(path, move_files)
        try:
            with coordinator.mutation("storage.apply") as lease:
                result = self._apply_storage_dir(path, move_files)
                if result.get("ok"):
                    lease.commit()
                return result
        except (RemoteMutationBusyError, RemoteMutationConflictError) as error:
            return {"ok": False, "error": str(error)}

    def _apply_storage_dir(self, path, move_files=False):
        """执行不含协调器 admission 的存储目录迁移。"""
        from ohmymeme.core.recovery import StorageRecovery

        old = self._cfg.cache_dir
        protected = (self._cfg.data_dir, self._cfg.thumbnail_dir)
        ok, err = _storage_dir_validation(path, str(old), protected)
        if not ok:
            return {"ok": False, "error": err}
        new = Path(path).resolve()
        previous_cache_dir = self._cfg.get("cache_dir", "")
        previous_dirty = self._cfg._dirty

        def commit_database():
            self._cfg.set("cache_dir", str(new))
            try:
                self._cfg.save()
            except OSError:
                self._cfg._data["cache_dir"] = previous_cache_dir
                self._cfg._dirty = previous_dirty
                raise

        try:
            container = self._webui._container
            moved = StorageRecovery(self._cfg.data_dir, old).migrate(
                new,
                move_files,
                commit_database,
                container.build_manifest,
            )
        except OSError as error:
            return {"ok": False, "error": f"迁移失败: {error}", "failed": []}
        fc = getattr(self._webui, "_file_cache", None)
        if fc is not None:
            fc.clear()
        _webview_adapter(self._webui).evaluate_main("refreshMemes();")
        return {"ok": True, "cache_dir": str(new), "moved": moved, "failed": []}

    def qqnt_default_dir(self, base: str, qq_number: str) -> dict:
        """按账号生成默认输出目录（昵称+QQ号）"""
        try:
            from .import_workers import get_import_worker

            get_import_worker(self, "source.qqnt")
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
        from .import_workers import get_import_worker

        try:
            worker = get_import_worker(self, "source.qqnt")
            ok = worker.start_qqnt(
                qq_number, output_dir, image_only, overwrite, self._cfg
            )
            return {"ok": ok}
        except Exception:
            return {"ok": False}

    def qqnt_get_progress(self) -> dict:
        from .import_workers import get_import_worker

        return get_import_worker(self, "source.qqnt").get_progress()

    def qqnt_cancel(self):
        from .import_workers import get_import_worker

        get_import_worker(self, "source.qqnt").cancel()

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
        result = _webview_adapter(self._webui).file_dialog(
            "settings",
            "open",
            allow_multiple=True,
            file_types=("图片文件 (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)",),
        )
        if result is None:
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
        return self._sync.get_sync_progress()

    def sync_push(self, delete_remote: bool = None) -> dict:
        try:
            r = self._sync.push(delete_remote=delete_remote)
            r["ok"] = True
            return r
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "failed_files": self._sync.get_sync_progress().get("failed_items", []),
            }

    def sync_pull(self, remove_local: bool = None) -> dict:
        try:
            r = self._sync.pull(remove_local=remove_local)
            r["ok"] = True
            _webview_adapter(self._webui).evaluate_main(
                "refreshMemes();refreshTags();refreshCollections();"
            )
            return r
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "failed_files": self._sync.get_sync_progress().get("failed_items", []),
            }

    def sync_test(self) -> str:
        try:
            return self._sync.sync_test()
        except Exception as e:
            return str(e)

    def delete_all_local(self) -> dict:
        """删除本地所有表情包"""
        coordinator = getattr(
            getattr(self._webui, "_container", None), "remote_mutations", None
        )
        if coordinator is None:
            return self._delete_all_local()
        try:
            with coordinator.mutation("library.delete_all_local") as lease:
                result = self._delete_all_local(lease)
                if result.get("ok"):
                    lease.commit()
                return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _delete_all_local(self, lease=None) -> dict:
        """执行不含协调器 admission 的本地清空。"""
        try:
            if lease is None:
                self._library.delete_all_metadata()
            else:
                self._library.delete_all_metadata(lease)
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
            if lease is None:
                self._library.rebuild_manifest()
            else:
                container = self._webui._container
                container.build_manifest()
            _webview_adapter(self._webui).evaluate_main(
                "refreshMemes();refreshTags();refreshCollections();"
            )
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def delete_all_cloud(self) -> dict:
        """删除云端所有表情包"""
        try:
            return self._sync.delete_all_remote()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def get_remote_orphans(self, delete: bool = False) -> dict:
        """扫描云端孤儿文件；delete=True 时物理删除"""
        try:
            return self._sync.cleanup_remote_orphans(delete=delete)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def check_sync_status(self) -> dict:
        """比较本地与云端同步状态"""
        try:
            manifest = self._sync.download_index()
            if not manifest:
                return {"ok": False, "error": "无法获取远端索引"}
            local_filenames = set(self._library.get_all_meme_filenames())
            local_count = len(local_filenames)
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


def _detect_image_ext(path):
    """读取文件头魔数识别真实扩展名（QQ 保存常为 .jpg，实为 png/webp 等），未知返回空串"""  # noqa: E501
    try:
        with open(path, "rb") as f:
            return adb_qq._detect_ext(f.read(16))
    except OSError:
        return ""


def _try_decode_stego(data):
    """实验性：在内存中解码 GIF 隐写；非隐写或失败返回 None。"""
    try:
        if b"STG3" not in data:
            return None
        from ohmymeme.core.gif_stego import decode_bytes
    except Exception as e:
        logger.warning(f"_try_decode_stego detect: {e}")
        return None
    try:
        decoded, _extension = decode_bytes(data)
        return decoded
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
        self._library = container.catalog
        locator = container.resource_locator
        self._html_dir = locator.webui_dir
        self._resources_dir = locator.resources_dir
        self._window = None
        self._settings_window = None
        self._pywebview = PyWebViewAdapter(webview if HAS_WEBVIEW else None, self)
        self._port = self._find_free_port()
        self._bottle_thread = None
        self._api = JsApi(self, self._library, container.settings)
        self._settings_api = SettingsApi(self, container.settings)
        self._plugin_action_registry = compatibility_registry(
            self._settings_api._legacy
        )
        self._enabled_import_plugins = None
        self._visible = False
        self._started = False
        self._pending_hide = False
        self._hotkey_session = False
        self._on_hotkey_change_cb = None
        self._update_debug = update_debug
        self._silent_start = silent_start
        self._decode_stego = _try_decode_stego

    def _init_lan(self):
        from ohmymeme.services import lan

        service = getattr(self._container, "lan", lan)
        service.set_confirm_callback(self._lan_confirm_cb)

    def set_on_hotkey_change(self, cb):
        self._on_hotkey_change_cb = cb

    def _lan_confirm_cb(self, device: dict):
        """LAN 设备连接确认：显示主窗口并弹窗展示设备信息，等待 JS 回传结果"""
        import json

        service = getattr(self._container, "lan", None)
        if service is None:
            from ohmymeme.services import lan

            service = lan
        if not self._window:
            service.confirm_device(False)
            return
        try:
            self.show()
            js = "window.showLanDeviceConfirm(%s)" % json.dumps(
                device, ensure_ascii=False
            )
            self._window.evaluate_js(js)
        except Exception as e:
            logger.warning(f"lan confirm dialog error: {e}")
            service.confirm_device(False)

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

    def _find_meme_file(self, filename: str) -> str:
        return find_meme_file(self, filename)

    def _do_import(self, file_paths, names=None):
        return import_paths(self, file_paths, names)

    def _on_hotkey_change(self, new_hotkey: str):
        if self._on_hotkey_change_cb:
            self._on_hotkey_change_cb(new_hotkey)

    # --- Bottle 路由 ---

    def build_bottle_app(self):
        """构建完整 WSGI 应用（注册路由与安全钩子，不启动服务器）"""
        app = bottle.Bottle()

        install_security_hooks(app, bottle, self._port)

        @app.route("/")
        def index():
            vue_html = self._html_dir / "vue.html"
            # 主窗口唯一入口为 Vue；构建产物缺失时返回可读 503 说明而非回退旧页面
            if vue_html.exists() and (self._html_dir / "dist" / "ohmymeme.js").exists():
                return bottle.static_file("vue.html", root=str(self._html_dir))
            bottle.response.status = 503
            return (
                "主窗口前端产物缺失：请先构建两个窗口"
                "（vite build 与 vite build --config vite.settings.config.ts）"
            )

        @app.route("/settings/")
        def settings_page():
            vue_settings = self._html_dir / "vue-settings.html"
            # 设置窗口唯一入口为 Vue；构建产物缺失时返回可读 503 说明而非回退旧页面
            if (
                vue_settings.exists()
                and (self._html_dir / "dist" / "settings-vue.js").exists()
            ):
                return bottle.static_file("vue-settings.html", root=str(self._html_dir))
            bottle.response.status = 503
            return (
                "设置窗口前端产物缺失：请先构建两个窗口"
                "（vite build 与 vite build --config vite.settings.config.ts）"
            )

        @app.route("/api/plugin-ui")
        def plugin_ui():
            # 固定宿主数据，不加载 provider，不扩展 Bridge 或设置返回对象。
            from .api.ui_contributions import load_ui_projection

            try:
                return load_ui_projection(self._html_dir / "plugin-ui.json")
            except (OSError, ValueError):
                bottle.response.status = 503
                return {"error": "ui: host contribution data rejected"}

        @app.route("/api/plugins")
        def plugin_catalog():
            # 只读插件目录：宿主渲染，不接受插件注入
            from ohmymeme.core.plugins.manifest import CANONICAL_PROVIDERS
            from ohmymeme.core.plugins.runtime import seeding
            from ohmymeme.presentation.desktop.api.ui_contributions import SCREENS

            labels = {provider: label for provider, label, *_ in SCREENS}
            disabled = self._cfg.get("disabled_plugins", None)
            disabled = set(disabled) if isinstance(disabled, (list, tuple)) else set()
            state = seeding.read_state(self._cfg.data_dir)
            entries = state.get("plugins") or {}
            rows = []
            for provider_id, _package_root, _capabilities in CANONICAL_PROVIDERS:
                record = entries.get(provider_id) or {}
                active = record.get("active")
                versions = dict(record.get("versions") or {})
                available = (
                    bool(active)
                    and (
                        seeding.plugins_dir(self._cfg.data_dir)
                        / provider_id
                        / str(active)
                    ).is_dir()
                )
                rows.append(
                    {
                        "id": provider_id,
                        "label": labels.get(provider_id, provider_id),
                        "kind": provider_id.split(".", 1)[0],
                        "origin": record.get("origin", ""),
                        "official": True,
                        "version": (
                            (versions.get(active) or {}).get("version", "")
                            if available
                            else ""
                        ),
                        "enabled": provider_id not in disabled,
                        "available": available,
                        "versions": sorted(versions.keys()) if available else [],
                    }
                )
            for row in seeding.installed_plugins(self._cfg.data_dir):
                rows.append(
                    {
                        "id": row["id"],
                        "label": row["name"],
                        "kind": row["kind"],
                        "origin": "installed",
                        "official": False,
                        "version": row["version"],
                        "enabled": row["id"] not in disabled,
                        "available": True,
                        "versions": row["versions"],
                    }
                )
            return {"plugins": rows}

        @app.route("/api/plugins/install", method="POST")
        def plugin_install():
            # 第三方 ZIP 安装：宿主校验并原子落盘，UI 负责确认
            from ohmymeme.core.plugins.runtime import seeding

            try:
                length = int(bottle.request.content_length or 0)
            except (TypeError, ValueError):
                length = 0
            if length <= 0 or length > 256 * 1024 * 1024:
                bottle.response.status = 413
                return {"ok": False, "error": "package size"}
            temp = None
            try:
                with tempfile.NamedTemporaryFile(
                    "wb", suffix=".zip", delete=False, dir=str(self._cfg.data_dir)
                ) as handle:
                    temp = handle.name
                    body = bottle.request.body
                    while True:
                        chunk = body.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                entry = seeding.install_plugin(self._cfg.data_dir, temp)
                self._container.plugin_runtime.stop_plugin(entry["id"], "install")
                self._drop_worker_cache(entry["id"])
                return {
                    "ok": True,
                    "plugin": entry["id"],
                    "version": entry["version"],
                }
            except seeding.PluginSeedError as error:
                bottle.response.status = 400
                return {"ok": False, "error": str(error)}
            finally:
                if temp:
                    try:
                        os.unlink(temp)
                    except OSError:
                        pass

        @app.route("/api/plugins/uninstall", method="POST")
        def plugin_uninstall():
            # 官方与第三方均可卸载
            from ohmymeme.core.plugins.runtime import seeding

            payload = bottle.request.json or {}
            plugin_id = payload.get("id")
            try:
                seeding.uninstall_plugin(self._cfg.data_dir, plugin_id)
            except seeding.PluginSeedError as error:
                bottle.response.status = 400
                return {"ok": False, "error": str(error)}
            self._container.plugin_runtime.stop_plugin(plugin_id, "uninstall")
            self._drop_worker_cache(plugin_id)
            return {"ok": True}

        @app.route("/api/plugins/reload", method="POST")
        def plugin_reload():
            # 重载 = 停止 worker，下次动作按磁盘版本重新加载
            payload = bottle.request.json or {}
            plugin_id = payload.get("id")
            self._container.plugin_runtime.stop_plugin(plugin_id, "reload")
            return {"ok": True}

        @app.route("/api/plugins/rollback", method="POST")
        def plugin_rollback():
            # 回滚/前进到已安装版本，并停止 worker 以便重新加载
            from ohmymeme.core.plugins.runtime import seeding

            payload = bottle.request.json or {}
            try:
                entry = seeding.activate_version(
                    self._cfg.data_dir, payload.get("id"), payload.get("version")
                )
            except seeding.PluginSeedError as error:
                bottle.response.status = 400
                return {"ok": False, "error": str(error)}
            self._container.plugin_runtime.stop_plugin(entry["id"], "rollback")
            self._drop_worker_cache(entry["id"])
            return {"ok": True, "version": entry["version"]}

        def _drop_worker_cache(plugin_id):
            for name in ("_runtime_import_workers", "_import_workers"):
                cache = getattr(self, name, None)
                if isinstance(cache, dict):
                    cache.pop(plugin_id, None)

        @app.route("/api/plugins/ui")
        def plugin_ui_contributions():
            # 聚合已装插件的声明式贡献；无效 ui.json 只隔离该插件
            from ohmymeme.core.plugins.runtime import seeding, ui_injection

            disabled = self._cfg.get("disabled_plugins", None)
            disabled = set(disabled) if isinstance(disabled, (list, tuple)) else set()
            contributions = []
            for row in seeding.installed_plugins(self._cfg.data_dir):
                try:
                    injections = ui_injection.read_contributions(
                        self._cfg.data_dir, row["id"]
                    )
                except Exception as error:
                    logger.warning("plugin ui rejected: %s (%s)", row["id"], error)
                    continue
                for injection in injections:
                    contributions.append(
                        {
                            "provider": row["id"],
                            "available": True,
                            "enabled": row["id"] not in disabled,
                            "injection": injection,
                        }
                    )
            return {"contributions": contributions}

        @app.route("/api/plugins/ui/action", method="POST")
        def plugin_ui_action():
            # 动作必须已在 ui.json 声明；执行仍走 worker allowlist
            from ohmymeme.core.plugins.runtime import ui_injection

            payload = bottle.request.json or {}
            provider = payload.get("provider")
            name = payload.get("name")
            arguments = payload.get("payload") or {}
            disabled = self._cfg.get("disabled_plugins", None)
            disabled = set(disabled) if isinstance(disabled, (list, tuple)) else set()
            if provider in disabled:
                bottle.response.status = 403
                return {"ok": False, "error": "provider_disabled"}
            try:
                injections = ui_injection.read_contributions(
                    self._cfg.data_dir, provider
                )
            except Exception as error:
                bottle.response.status = 400
                return {"ok": False, "error": str(error)}
            allowed = {
                action["name"]
                for item in injections
                for action in item.get("actions", ())
            }
            if name not in allowed:
                bottle.response.status = 400
                return {"ok": False, "error": "action not declared"}
            try:
                result = self._container.plugin_runtime.call_ui_action(
                    provider, name, arguments
                )
            except Exception as error:
                bottle.response.status = 502
                return {"ok": False, "error": str(error)}
            return {"ok": True, "result": result}

        @app.route("/api/plugins/ui/config")
        def plugin_ui_config_read():
            # 读取声明过的面板字段；secret 只回是否已配置
            from ohmymeme.core.plugins.runtime import ui_config, ui_injection

            provider = bottle.request.query.get("provider") or ""
            disabled = self._cfg.get("disabled_plugins", None)
            disabled = set(disabled) if isinstance(disabled, (list, tuple)) else set()
            if provider in disabled:
                bottle.response.status = 403
                return {"ok": False, "error": "provider_disabled"}
            try:
                injections = ui_injection.read_contributions(
                    self._cfg.data_dir, provider
                )
                values = ui_config.read_values(self._cfg, provider, injections)
            except Exception as error:
                bottle.response.status = 400
                return {"ok": False, "error": str(error)}
            return {"ok": True, "values": values}

        @app.route("/api/plugins/ui/config", method="POST")
        def plugin_ui_config_write():
            # 仅写入声明过的字段，类型按声明严格转换
            from ohmymeme.core.plugins.runtime import ui_config, ui_injection

            payload = bottle.request.json or {}
            provider = payload.get("provider")
            values = payload.get("values") or {}
            disabled = self._cfg.get("disabled_plugins", None)
            disabled = set(disabled) if isinstance(disabled, (list, tuple)) else set()
            if provider in disabled:
                bottle.response.status = 403
                return {"ok": False, "error": "provider_disabled"}
            try:
                injections = ui_injection.read_contributions(
                    self._cfg.data_dir, provider
                )
                applied = ui_config.apply_values(
                    self._cfg, provider, injections, values
                )
                self._cfg.save()
            except Exception as error:
                bottle.response.status = 400
                return {"ok": False, "error": str(error)}
            return {"ok": True, "values": applied}

        @app.route("/api/plugins/<plugin_id>/ui/<asset:path>")
        def plugin_ui_asset(plugin_id, asset):
            # iframe 静态资源：只放行声明过的入口，CSP 禁止外部资源
            from ohmymeme.core.plugins.runtime import seeding, ui_injection

            try:
                entry = seeding.resolve_plugin(self._cfg.data_dir, plugin_id)
                injections = ui_injection.load_contributions(entry["package_dir"])
            except Exception:
                bottle.response.status = 404
                return "not found"
            allowed = {
                item["entry"]
                for item in injections
                if item.get("point") == "plugin_detail.iframe"
            }
            if asset not in allowed:
                bottle.response.status = 404
                return "not found"
            target = ui_injection.resolve_asset(entry["package_dir"], asset)
            if target is None:
                bottle.response.status = 404
                return "not found"
            response = bottle.static_file(str(target), root=str(entry["package_dir"]))
            csp = (
                "default-src 'none'; script-src 'unsafe-inline'; "
                "style-src 'unsafe-inline'; img-src data:"
            )
            response.set_header("Content-Security-Policy", csp)
            response.set_header("Cache-Control", "no-store")
            bottle.response.set_header("Content-Security-Policy", csp)
            return response

        @app.route("/api/contributors")
        def serve_contributors():
            # 代理贡献者 SVG：剥离白色背景矩形，适配深色主题
            try:
                url = "https://contributor.starsfire.top/TNTXZ/OhMyMeme"
                svg = _FETCH_POLICY.fetch_bytes(
                    url,
                    headers={"User-Agent": "OhMyMeme"},
                    max_bytes=1024 * 1024,
                ).decode("utf-8", "replace")
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
            path = self._find_meme_file(filename)
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
                    try:
                        raw = base64.b64decode(b64, validate=True)
                    except (ValueError, binascii.Error):
                        bottle.response.status = 400
                        return {"ok": False, "error": "文件数据解码失败"}
                    requests.append(ImportBytes(raw, oname))
                if requests:
                    result = self._container.create_import_service(
                        _try_decode_stego
                    ).import_batch(requests)
                    if result.rejected:
                        bottle.response.status = 400
                        return {"ok": False, "error": "图片解析失败或超过导入限制"}
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

        return app

    def _setup_bottle(self):
        """启动本地 Bottle 服务器"""
        bottle.run(
            create_bottle_app(self, bottle),
            host="127.0.0.1",
            port=self._port,
            quiet=True,
        )

    # --- 缓存扫描 ---

    def scan_cache(self):
        """扫描本地缓存目录，将已有文件自动注册到数据库"""
        cache_dir = self._cfg.cache_dir
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
                if self._library.has_meme_filename(fname):
                    continue
                try:
                    result = self._container.create_import_service(
                        self._decode_stego
                    ).register_existing_path(ImportPath(Path(fpath), fname))
                    added += len(result.imported_ids)
                except Exception as e:
                    logger.warning(f"scan_cache skip {fname}: {e}")
        if added:
            logger.info(f"缓存扫描完成: 新增 {added} 个文件")
        self._library.rebuild_manifest()

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
            sx = None
            sy = None
            try:
                if self._window is not None:
                    wx = self._window.x
                    wy = self._window.y
                    if wx is not None and wx >= 0:
                        sx = wx + (960 - 720) // 2
                    if wy is not None and wy >= 0:
                        sy = wy + (640 - 560) // 2
            except Exception:
                sx = None
                sy = None
            self._settings_window = webview.create_window(
                "设置 - OhMyMeme",
                settings_url,
                js_api=self._settings_api,
                width=720,
                height=560,
                x=sx,
                y=sy,
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
            service = getattr(self._container, "lan", None)
            if service is not None:
                service.stop()
            else:
                from ohmymeme.services import lan

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
