"""PyWebView 现代化 UI 窗口管理器 + JS API"""

import io
import logging
import os
import platform
import socket
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

from . import adb_util, qqnt_extract, updater
from . import sync as sync_module
from .clipboard_util import (
    _is_animated,
    convert_image_mode_1,
    convert_image_mode_2,
    convert_image_mode_3,
    copy_image_to_clipboard,
)
from .config import get_config
from .database import get_db
from .manifest import build as build_manifest

logger = logging.getLogger(__name__)

# 内存日志缓冲：固定收集 DEBUG 级日志，供设置页"导出日志"
_LOG_BUFFER = []
_LOG_LOCK = threading.Lock()
_LOG_MAX = 5000


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


class JsApi:
    """暴露给前端的 JS API"""

    def __init__(self, webui):
        self._webui = webui
        self._cfg = get_config()
        self._db = get_db()

    def search_memes(
        self, keyword: str = "", tags: list = None, collection_id: int = None
    ) -> list:
        if tags is not None and len(tags) == 0:
            tags = None
        fav_only = collection_id == -2
        recent_only = collection_id == -3
        cid = None if fav_only or recent_only else collection_id
        if recent_only:
            rows = self._db.get_recent(200)
        else:
            rows = self._db.search(
                keyword=keyword,
                tags=tags,
                collection_id=cid,
                favorite_only=fav_only,
                limit=200,
            )
        favorited_ids = set()
        try:
            conn = self._db._get_conn()
            fav_rows = conn.execute("SELECT meme_id FROM favorites").fetchall()
            favorited_ids = {r[0] for r in fav_rows}
        except Exception:
            pass
        auto_gif = self._cfg.get("auto_play_gif", True)
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
                }
            )
        return result

    def get_tags(self) -> list:
        return self._db.get_all_tags()

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
            limit=200,
        )
        favorited_ids = set()
        try:
            conn = self._db._get_conn()
            fav_rows = conn.execute("SELECT meme_id FROM favorites").fetchall()
            favorited_ids = {r[0] for r in fav_rows}
        except Exception:
            pass
        auto_gif = self._cfg.get("auto_play_gif", True)
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
                }
            )
        sys_cols = [
            {"id": -2, "name": "收藏夹", "count": self._db.count(favorite_only=True)},
            {"id": -3, "name": "最近使用", "count": len(self._db.get_recent(9999))},
        ]
        collections = sys_cols + self._build_collection_tree()
        return {
            "memes": memes,
            "tags": self._db.get_all_tags(),
            "collections": collections,
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

            return bool(_start(p))
        except Exception:
            return False

    def copy_meme(self, meme_id: int) -> bool:
        # 复制表情到剪贴板；copy_resize_mode: 0不处理 1webp缩放 2转gif 3转gif隐写原图
        row = self._db.get_by_id(meme_id)
        if not row:
            return False
        path = self._find_meme_file(row["filename"])
        if not path:
            return False
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
        if ok:
            self._db.record_use(meme_id)
            self._webui.schedule_hide()
        return ok

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

    def delete_meme(self, meme_id: int) -> bool:
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
        self._db.delete_meme(meme_id)
        build_manifest()
        return True

    def _build_collection_tree(self, parent_id=None) -> list:
        raw = self._db.get_collections()
        result = []
        for cid, name, pid, _ in raw:
            if pid != parent_id:
                continue
            cnt = self._db.count(collection_id=cid)
            children = self._build_collection_tree(parent_id=cid)
            item = {"id": cid, "name": name, "count": cnt}
            if children:
                item["children"] = children
            result.append(item)
        return result

    def get_collections(self) -> list:
        top = self._build_collection_tree()
        recent = self._db.get_recent(9999)
        return [
            {"id": -2, "name": "收藏夹", "count": self._db.count(favorite_only=True)},
            {"id": -3, "name": "最近使用", "count": len(recent)},
        ] + top

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
            return self._db.search(collection_id=collection_id, limit=200) or []
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

    def check_update(self, debug: bool = False) -> dict:
        """检查更新，返回版本信息 + 是否建议更新"""
        from . import __version__ as cur_ver

        info = updater.check_latest()
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
            ids = self._webui._do_import([local_path])
            if ids:
                return {"ok": True, "id": ids[0]}
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
            ids = self._webui._do_import([final_path])
            if ids:
                return {"ok": True, "id": ids[0]}
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
        # 通过系统文件对话框选择导入
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=("图片文件 (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)",),
            )
        except Exception:
            return False
        if not result:
            return False
        self._webui._do_import(result)
        return True

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
            ids = self._webui._do_import(files, names)
            collection_id = None
            folder_name = os.path.basename(os.path.normpath(folder))
            if make_collection and ids:
                collection_id = self._db.create_collection(folder_name)
                if collection_id > 0:
                    for mid in ids:
                        self._db.add_to_collection(mid, collection_id)
                    from .manifest import build as build_manifest

                    build_manifest()
            return {
                "ok": True,
                "imported": len(ids),
                "collection_id": collection_id,
                "collection_name": folder_name if make_collection and ids else None,
            }
        except Exception as e:
            logger.error(f"import_folder failed: {e}")
            return {"ok": False, "error": str(e)}

    def import_from_clipboard(self) -> dict:
        import hashlib
        import shutil
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
                ids = self._webui._do_import(paths)
                if ids:
                    row = self._db.get_by_id(ids[0])
                    orig = row["original_name"] if row else ""
                    return {"ok": True, "id": ids[0], "name": orig or "未命名"}
                return {"ok": True, "id": 0, "name": "未命名"}
            img = clip
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp_path = tmp.name
            tmp.close()
            img.save(tmp_path, "PNG")
            sha256 = hashlib.sha256()
            with open(tmp_path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    sha256.update(chunk)
            fhash = sha256.hexdigest()
            db = self._db
            if db.get_by_hash(fhash):
                os.unlink(tmp_path)
                return {"ok": False, "error": "该图片已存在"}
            cache_dir = self._cfg.cache_dir
            dst = cache_dir / f"{fhash[:16]}.png"
            shutil.move(tmp_path, dst)
            w, h = img.size
            db.add_meme(
                filename=dst.name,
                file_hash=fhash,
                width=w,
                height=h,
                file_size=os.path.getsize(dst),
                mime_type="image/png",
                original_name="",
            )
            build_manifest()
            row = db.get_by_hash(fhash)
            mid = row["id"] if row else 0
            return {"ok": True, "id": mid, "name": "未命名"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def open_settings(self):
        self._webui.open_settings()

    def lan_confirm_device(self, approved: bool) -> dict:
        from . import lan

        lan.confirm_device(bool(approved))
        return {"ok": True}

    def get_settings(self) -> dict:
        d = self._cfg.to_dict()
        from .platform_util import is_auto_start_enabled

        return {
            "hotkey": d.get("hotkey", "Ctrl+Alt+N"),
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
        }

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
        _set_qqnt(status="error", message="提取失败", error=str(e))


class SettingsApi:
    """暴露给设置窗口的 JS API（仅设置相关方法）"""

    def __init__(self, webui):
        self._webui = webui
        self._cfg = get_config()

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
        }

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
        """应用新的表情包存储目录；move_files=True 时把现有文件迁移过去"""
        import shutil

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
        moved, failed = 0, []
        if move_files:
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
                    return {
                        "ok": False,
                        "error": f"目标目录已存在 {len(collisions)} 个同名文件，未迁移",
                        "failed": [
                            {
                                "name": c["name"],
                                "path": c["path"],
                                "error": "目标目录已存在同名文件",
                            }
                            for c in collisions
                        ],
                    }
                moved_pairs = []
                for src, dst in plan:
                    try:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(src, str(dst))
                        moved_pairs.append((src, dst))
                        moved += 1
                    except OSError as e:
                        for s, d in reversed(moved_pairs):
                            try:
                                shutil.move(str(d), s)
                            except OSError:
                                pass
                        return {
                            "ok": False,
                            "error": f"迁移失败（{e}），已回滚已移动文件",
                            "failed": [
                                {
                                    "name": os.path.basename(s),
                                    "path": os.path.relpath(s, str(old)),
                                    "error": str(e),
                                }
                                for s, _d in moved_pairs
                            ],
                        }
        self._cfg.set("cache_dir", str(new))
        self._cfg.save()
        fc = getattr(self._webui, "_file_cache", None)
        if fc is not None:
            fc.clear()
        try:
            if len(webview.windows) > 0:
                webview.windows[0].evaluate_js("refreshMemes();")
        except Exception:
            pass
        return {"ok": True, "cache_dir": str(new), "moved": moved, "failed": failed}

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

    def import_memes(self) -> bool:
        try:
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=True,
                file_types=("图片文件 (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp)",),
            )
        except Exception:
            return False
        if not result:
            return False
        self._webui._do_import(result)
        return True

    def close_settings(self):
        self._webui.close_settings()

    def get_current_version(self) -> str:
        from . import __version__

        return __version__

    def check_update(self, debug: bool = False) -> dict:
        from . import __version__ as cur_ver

        info = updater.check_latest()
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

    def show(self):
        self._visible = True
        if self._window:
            try:
                self._window.on_top = True  # 置顶一下提升 z-order，随即复位不长期置顶
                self._window.on_top = False
                if callable(self._window.show):
                    self._window.show()
                if callable(self._window.focus):
                    self._window.focus()
            except Exception as e:
                logger.warning(f"show window error: {e}")

    def hide(self):
        self._visible = False
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

    def schedule_hide(self):
        self._pending_hide = True
        if self._window:
            self._run_on_gui(0.1, self._process_pending_hide)

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
            thumb_path.write_bytes(buf.getvalue())
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

    def _do_import(self, file_paths, names=None):
        import shutil

        cfg = get_config()
        db = get_db()
        cache_dir = cfg.cache_dir
        imported = 0
        imported_ids = []
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
                    fhash = _file_sha256(path)
                    if db.get_by_hash(fhash):
                        continue
                    ext = _detect_image_ext(path) or os.path.splitext(path)[1] or ".png"
                    dst = cache_dir / f"{fhash[:16]}{ext}"
                    shutil.copy2(path, dst)
                    w = h = 0
                    if HAS_PIL:
                        try:
                            img = PILImage.open(path)
                            w, h = img.size
                        except Exception:
                            pass
                    db.add_meme(
                        filename=dst.name,
                        file_hash=fhash,
                        width=w,
                        height=h,
                        file_size=os.path.getsize(path),
                        mime_type=f"image/{ext[1:]}" if ext else "image/png",
                        original_name=oname,
                        stego_of_hash=stego_of_hash,
                        from_stego=from_stego,
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
        if imported:
            build_manifest()
        logger.info(f"导入完成: {imported} 个")
        return imported_ids

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

        @app.route("/<filepath:path>")
        def static_files(filepath):
            return bottle.static_file(filepath, root=str(HTML_DIR))

        bottle.run(app, host="127.0.0.1", port=self._port, quiet=True)

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
                    sha256 = hashlib.sha256()
                    with open(fpath, "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            sha256.update(chunk)
                    fhash = sha256.hexdigest()
                    if db.get_by_hash(fhash):
                        continue
                    w = h = 0
                    if HAS_PIL:
                        try:
                            img = PILImage.open(fpath)
                            w, h = img.size
                        except Exception:
                            pass
                    mime = f"image/{ext[1:]}" if ext else "image/png"
                    oname = os.path.splitext(fname)[0]
                    db.add_meme(
                        filename=fname,
                        file_hash=fhash,
                        width=w,
                        height=h,
                        file_size=os.path.getsize(fpath),
                        mime_type=mime,
                        original_name=oname,
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
            width=700,
            height=500,
            x=wx if (wx is not None and wx >= 0) else None,
            y=wy if (wy is not None and wy >= 0) else None,
            resizable=True,
            frameless=True,
            easy_drag=False,
            hidden=self._silent_start,
        )

        self._started = True
        # 注册 LAN 设备确认回调（窗口创建完成后）
        self._init_lan()
        # start() blocks - 在调用线程运行 GUI 循环
        gui = "gtk" if platform.system() == "Linux" else None
        webview.start(debug=False, http_server=False, gui=gui)
        return True

    def open_settings(self):
        self._create_settings_window()

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
                width=460,
                height=560,
                resizable=False,
                frameless=True,
                easy_drag=False,
            )
        except Exception as e:
            logger.warning(f"create settings window error: {e}")

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
