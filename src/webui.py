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

from . import adb_util, updater
from . import sync as sync_module
from .clipboard_util import copy_image_to_clipboard
from .config import get_config
from .database import get_db
from .manifest import build as build_manifest

logger = logging.getLogger(__name__)

HTML_DIR = Path(__file__).resolve().parent / "webui"

# ─── 工具函数 (DeepSeek V4 Flash) ───


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


def _check_connectivity() -> dict:  # DeepSeek V4 Flash
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
            is_gif = r.get("mime_type", "").endswith("gif") or r[
                "filename"
            ].lower().endswith(".gif")
            oname = r.get("original_name", "")
            if not oname:
                oname = os.path.splitext(r["filename"])[0]
            result.append(
                {
                    "id": r["id"],
                    "filename": r["filename"],
                    "name": oname,
                    "file_hash": r.get("file_hash", ""),
                    "width": r.get("width", 0),
                    "height": r.get("height", 0),
                    "mime_type": r.get("mime_type", ""),
                    "is_gif": is_gif,
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
            is_gif = r.get("mime_type", "").endswith("gif") or r[
                "filename"
            ].lower().endswith(".gif")
            oname = r.get("original_name", "")
            if not oname:
                oname = os.path.splitext(r["filename"])[0]
            memes.append(
                {
                    "id": r["id"],
                    "filename": r["filename"],
                    "name": oname,
                    "file_hash": r.get("file_hash", ""),
                    "width": r.get("width", 0),
                    "height": r.get("height", 0),
                    "mime_type": r.get("mime_type", ""),
                    "is_gif": is_gif,
                    "favorited": r["id"] in favorited_ids,
                    "auto_play_gif": auto_gif,
                }
            )
        collections = self._build_collection_tree()
        return {
            "memes": memes,
            "tags": self._db.get_all_tags(),
            "collections": collections,
        }

    def copy_meme(self, meme_id: int) -> bool:
        row = self._db.get_by_id(meme_id)
        if not row:
            return False
        path = self._find_meme_file(row["filename"])
        if not path:
            return False
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

    def reorder_memes(self, meme_ids: list) -> bool:
        try:
            self._db.reorder_memes(meme_ids)
            return True
        except Exception:
            return False

    def reorder_collections(self, collection_ids: list) -> bool:
        try:
            self._db.reorder_collections(collection_ids)
            return True
        except Exception:
            return False

    def delete_collection(self, collection_id: int) -> bool:
        try:
            self._db.delete_collection(collection_id)
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

    def remove_from_collection(self, meme_id: int, collection_id: int) -> bool:
        self._db.remove_from_collection(meme_id, collection_id)
        return True

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

    def check_connectivity(self) -> dict:  # DeepSeek V4 Flash
        return _check_connectivity()

    def download_original_image(self, url: str) -> dict:  # DeepSeek V4 Flash
        """下载浏览器来源的原始图片（去掉 @ 修饰），导入到缓存"""
        if not self._cfg.get("try_original_image", False):
            return {"ok": False, "error": "功能未启用"}
        conn = _check_connectivity()
        if not conn["ok"]:
            return {"ok": False, "error": "无网络连接"}
        clean_url = _strip_url_modifiers(url)
        import shutil
        import tempfile
        from urllib.error import URLError
        from urllib.request import urlopen

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tmp")
        tmp_path = tmp.name
        tmp.close()
        try:
            with urlopen(clean_url, timeout=15) as resp:
                with open(tmp_path, "wb") as f:
                    shutil.copyfileobj(resp, f)
            ids = self._webui._do_import([tmp_path])
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

    def get_sync_progress(self) -> dict:
        return sync_module.get_sync_progress()

    def sync_push(self) -> dict:
        try:
            r = sync_module.push()
            r["ok"] = True
            return r
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync_pull(self) -> dict:
        try:
            r = sync_module.pull()
            r["ok"] = True
            return r
        except Exception as e:
            return {"ok": False, "error": str(e)}

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

    def get_settings(self) -> dict:
        d = self._cfg.to_dict()
        from .platform_util import is_auto_start_enabled

        return {
            "hotkey": d.get("hotkey", "Ctrl+Alt+N"),
            "auto_play_gif": d.get("auto_play_gif", True),
            # DeepSeek V4 Flash
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
        self._cfg.reset()
        self._cfg.save()
        hotkey = self._cfg.get("hotkey", "Ctrl+Alt+N")
        self._webui._on_hotkey_change(hotkey)
        from .platform_util import set_auto_start

        set_auto_start(False)
        return {
            "hotkey": hotkey,
            "auto_play_gif": self._cfg.get("auto_play_gif", True),
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

    def hide_window(self):
        self._webui.hide()

    def _find_meme_file(self, filename: str) -> str:
        cache_dir = self._cfg.cache_dir
        for root, _, files in os.walk(cache_dir):
            if filename in files:
                return os.path.join(root, filename)
        return ""


class SettingsApi:
    """暴露给设置窗口的 JS API（仅设置相关方法）"""

    def __init__(self, webui):
        self._webui = webui
        self._cfg = get_config()

    def check_connectivity(self) -> dict:  # DeepSeek V4 Flash
        return _check_connectivity()

    def get_settings(self) -> dict:
        d = self._cfg.to_dict()
        from .platform_util import is_auto_start_enabled

        return {
            "hotkey": d.get("hotkey", "Ctrl+Alt+N"),
            "auto_play_gif": d.get("auto_play_gif", True),
            # DeepSeek V4 Flash
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
        self._cfg.reset()
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

    def open_adb_help(self) -> bool:
        try:
            adb_util.open_adb_help()
            return True
        except Exception:
            return False

    def cancel_qq_import(self):
        adb_util.cancel_qq_import()

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
            return {"ok": False, "error": str(e)}

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
            return {"ok": False, "error": str(e)}

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

    def set_on_hotkey_change(self, cb):
        self._on_hotkey_change_cb = cb

    # --- 窗口控制（从任何线程调用安全）---

    def show(self):
        self._visible = True
        if self._window:
            try:
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
        if self._window:
            if threading.current_thread() is threading.main_thread():
                self.toggle()
            else:
                try:
                    self._window.after(0, self.toggle)
                except Exception:
                    self.toggle()

    def schedule_hide(self):
        self._pending_hide = True
        if self._window:
            try:
                self._window.after(100, self._process_pending_hide)
            except Exception:
                pass

    def _process_pending_hide(self):
        if self._pending_hide:
            self._pending_hide = False
            self.hide()

    def _schedule_quit(self):
        """在当前循环结束后关闭窗口并退出进程"""
        if self._window:
            try:
                self._window.after(0, self.stop)
            except Exception:
                pass

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
        import hashlib
        import shutil

        cfg = get_config()
        db = get_db()
        cache_dir = cfg.cache_dir
        imported = 0
        imported_ids = []
        for i, src in enumerate(file_paths):
            try:
                sha256 = hashlib.sha256()
                with open(src, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha256.update(chunk)
                fhash = sha256.hexdigest()
                if db.get_by_hash(fhash):
                    continue
                ext = os.path.splitext(src)[1] or ".png"
                dst = cache_dir / f"{fhash[:16]}{ext}"
                shutil.copy2(src, dst)
                w = h = 0
                if HAS_PIL:
                    try:
                        img = PILImage.open(src)
                        w, h = img.size
                    except Exception:
                        pass
                oname = (
                    names[i]
                    if names and i < len(names)
                    else os.path.splitext(os.path.basename(src))[0]
                )
                db.add_meme(
                    filename=dst.name,
                    file_hash=fhash,
                    width=w,
                    height=h,
                    file_size=os.path.getsize(src),
                    mime_type=f"image/{ext[1:]}" if ext else "image/png",
                    original_name=oname,
                )
                row = db.get_by_hash(fhash)
                if row:
                    imported_ids.append(row["id"])
                imported += 1
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
            x=wx if wx >= 0 else None,
            y=wy if wy >= 0 else None,
            resizable=True,
            frameless=True,
            easy_drag=False,
            hidden=self._silent_start,
        )

        self._started = True
        # start() blocks - 在调用线程运行 GUI 循环
        # DeepSeek V4 Flash: Linux 强制 GTK 后端（Qt WebEngine Wayland 下崩溃）
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
