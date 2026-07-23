"""PyWebView 现代化 UI 窗口管理器 + JS API"""

import base64
import io
import logging
import os
import socket
import threading
import time
from pathlib import Path

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

from .config import get_config
from .database import get_db
from .clipboard_util import copy_image_to_clipboard

logger = logging.getLogger(__name__)

HTML_DIR = Path(__file__).resolve().parent / "webui"


class JsApi:
    """暴露给前端的 JS API"""

    def __init__(self, webui):
        self._webui = webui
        self._cfg = get_config()
        self._db = get_db()

    def search_memes(self, keyword: str = "", tags: list = None,
                     collection_id: int = None) -> list:
        if tags is not None and len(tags) == 0:
            tags = None
        fav_only = collection_id == -1
        cid = None if fav_only else collection_id
        rows = self._db.search(keyword=keyword, tags=tags,
                               collection_id=cid, favorite_only=fav_only, limit=200)
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
            thumb_b64 = self._webui.get_thumbnail_base64(r["id"], r["filename"])
            is_gif = r.get("mime_type", "").endswith("gif") or r["filename"].lower().endswith(".gif")
            result.append({
                "id": r["id"],
                "filename": r["filename"],
                "file_hash": r.get("file_hash", ""),
                "width": r.get("width", 0),
                "height": r.get("height", 0),
                "mime_type": r.get("mime_type", ""),
                "is_gif": is_gif,
                "favorited": r["id"] in favorited_ids,
                "auto_play_gif": auto_gif,
                "thumb_b64": thumb_b64 or "",
            })
        return result

    def get_tags(self) -> list:
        return self._db.get_all_tags()

    def copy_meme(self, meme_id: int) -> bool:
        row = self._db.get_by_id(meme_id)
        if not row:
            return False
        path = self._find_meme_file(row["filename"])
        if not path:
            return False
        ok = copy_image_to_clipboard(path)
        if ok:
            self._webui.schedule_hide()
        return ok

    def toggle_favorite(self, meme_id: int) -> bool:
        return self._db.toggle_favorite(meme_id)

    def is_favorite(self, meme_id: int) -> bool:
        return self._db.is_favorite(meme_id)

    def rename_meme(self, meme_id: int, new_name: str) -> bool:
        import os
        row = self._db.get_by_id(meme_id)
        if not row or not new_name:
            return False
        old_path = self._find_meme_file(row["filename"])
        if not old_path:
            return False
        ext = os.path.splitext(row["filename"])[1]
        new_filename = new_name if new_name.endswith(ext) else new_name + ext
        new_path = os.path.join(os.path.dirname(old_path), new_filename)
        try:
            os.rename(old_path, new_path)
            self._db.update_meme(meme_id, filename=new_filename)
            # 缩略图重命名
            cache_dir = self._cfg.cache_dir
            for f in cache_dir.parent.rglob(f"*{row['filename']}"):
                pass
            return True
        except Exception as e:
            logging.getLogger(__name__).error(f"rename error: {e}")
            return False

    def delete_meme(self, meme_id: int) -> bool:
        import os, glob as gglob
        row = self._db.get_by_id(meme_id)
        if not row:
            return False
        # 删除缓存文件
        file_path = self._find_meme_file(row["filename"])
        if file_path:
            try:
                os.remove(file_path)
            except Exception:
                pass
        # 删除缩略图
        thumb_dir = self._cfg.thumbnail_dir
        for f in thumb_dir.glob(f"{meme_id}_*.png"):
            try:
                f.unlink()
            except Exception:
                pass
        self._db.delete_meme(meme_id)
        return True

    def get_collections(self) -> list:
        raw = self._db.get_collections()
        result = [{"id": -1, "name": "收藏夹", "count": self._db.count(favorite_only=True)}]
        for cid, name in raw:
            cnt = self._db.count(collection_id=cid)
            result.append({"id": cid, "name": name, "count": cnt})
        return result

    def add_to_collection(self, meme_id: int, name: str) -> bool:
        cid = self._db.create_collection(name)
        if cid < 0:
            return False
        self._db.add_to_collection(meme_id, cid)
        return True

    def remove_from_collection(self, meme_id: int, collection_id: int) -> bool:
        self._db.remove_from_collection(meme_id, collection_id)
        return True

    def rescan_cache(self) -> bool:
        self._webui.scan_cache()
        return True

    def import_memes(self) -> bool:
        # 通过系统文件对话框选择导入
        try:
            file_types = ("图片文件 (*.png;*.jpg;*.jpeg;*.gif;*.webp)",)
            result = webview.windows[0].create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=True, file_types=file_types
            )
        except Exception:
            return False
        if not result:
            return False
        self._webui._do_import(result)
        return True

    def get_settings(self) -> dict:
        d = self._cfg.to_dict()
        return {
            "hotkey": d.get("hotkey", "Ctrl+Alt+M"),
            "sync_mode": d.get("sync_mode", "manual"),
            "auto_play_gif": d.get("auto_play_gif", True),
        }

    def save_settings(self, settings: dict):
        if isinstance(settings, dict):
            self._cfg.update_from_dict(settings)
            self._cfg.save()
            if "hotkey" in settings:
                self._webui._on_hotkey_change(settings["hotkey"])

    def reset_settings(self) -> dict:
        self._cfg.reset()
        self._cfg.save()
        hotkey = self._cfg.get("hotkey", "Ctrl+Alt+M")
        self._webui._on_hotkey_change(hotkey)
        return {"hotkey": hotkey, "sync_mode": self._cfg.get("sync_mode", "manual"),
                "auto_play_gif": self._cfg.get("auto_play_gif", True)}

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


class WebUI:
    """PyWebView UI 管理器"""

    def __init__(self):
        self._cfg = get_config()
        self._window = None
        self._port = self._find_free_port()
        self._bottle_thread = None
        self._api = JsApi(self)
        self._visible = False
        self._started = False
        self._pending_hide = False
        self._on_hotkey_change_cb = None

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

    @property
    def is_visible(self) -> bool:
        return self._visible

    # --- 缩略图 ---

    def get_thumbnail_base64(self, meme_id: int, filename: str,
                             size: int = 150) -> str:
        cache_dir = self._cfg.thumbnail_dir
        thumb_path = cache_dir / f"{meme_id}_{size}.png"
        if thumb_path.exists():
            try:
                data = thumb_path.read_bytes()
                return base64.b64encode(data).decode()
            except Exception:
                pass
        # 生成缩略图
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
            return base64.b64encode(buf.getvalue()).decode()
        except Exception as e:
            logger.warning(f"thumb error {filename}: {e}")
            return ""

    def _find_meme_file(self, filename: str) -> str:
        cache_dir = self._cfg.cache_dir
        for root, _, files in os.walk(cache_dir):
            if filename in files:
                return os.path.join(root, filename)
        return ""

    def _do_import(self, file_paths):
        import hashlib
        import shutil
        cfg = get_config()
        db = get_db()
        cache_dir = cfg.cache_dir
        imported = 0
        for src in file_paths:
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
                db.add_meme(
                    filename=dst.name, file_hash=fhash,
                    width=w, height=h, file_size=os.path.getsize(src),
                    mime_type=f"image/{ext[1:]}" if ext else "image/png",
                )
                imported += 1
            except Exception as e:
                logger.error(f"import {src}: {e}")
        logger.info(f"导入完成: {imported} 个")

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

        @app.route("/api/thumb/<meme_id>/<filename>")
        def serve_thumb(meme_id, filename):
            b64 = self.get_thumbnail_base64(int(meme_id), filename)
            if b64:
                data = base64.b64decode(b64)
                bottle.response.content_type = "image/png"
                return data
            bottle.response.status = 404
            return ""

        @app.route("/api/original/<meme_id>/<filename>")
        def serve_original(meme_id, filename):
            path = self._find_meme_file(filename)
            if path:
                ext = os.path.splitext(filename)[1].lower()
                ctype = {
                    ".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".gif": "image/gif",
                    ".webp": "image/webp",
                }.get(ext, "application/octet-stream")
                return bottle.static_file(os.path.basename(path),
                                          root=os.path.dirname(path),
                                          mimetype=ctype)
            bottle.response.status = 404
            return ""

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
                    db.add_meme(
                        filename=fname, file_hash=fhash,
                        width=w, height=h,
                        file_size=os.path.getsize(fpath),
                        mime_type=mime,
                    )
                    added += 1
                except Exception as e:
                    logger.warning(f"scan_cache skip {fname}: {e}")
        if added:
            logger.info(f"缓存扫描完成: 新增 {added} 个文件")

    # --- 启动 ---

    def start(self) -> bool:
        if not HAS_WEBVIEW:
            logger.error("pywebview not installed")
            return False
        if not HAS_BOTTLE:
            logger.error("bottle not installed")
            return False

        # 启动 Bottle 服务器
        self._bottle_thread = threading.Thread(
            target=self._setup_bottle, daemon=True
        )
        self._bottle_thread.start()
        time.sleep(0.3)

        # 创建窗口
        url = f"http://127.0.0.1:{self._port}/"
        self._window = webview.create_window(
            "OhMyMeme",
            url,
            js_api=self._api,
            width=self._cfg.get("window_width", 700),
            height=self._cfg.get("window_height", 500),
            resizable=True,
            frameless=True,
            easy_drag=False,
        )
        self._started = True
        # start() blocks - 在调用线程运行 GUI 循环
        webview.start(debug=False, http_server=False)
        return True

    def stop(self):
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    @staticmethod
    def _find_free_port() -> int:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port
