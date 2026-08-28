"""Desktop bridge ImportHandler implementation."""


class ImportHandler:
    """Owns the application import boundary for bridge import operations."""

    def __init__(self, library, job_manager, catalog=None, context=None):
        self.library = library
        self.job_manager = job_manager
        self.catalog = catalog
        self.context = context

    def import_paths(self, paths, names=None):
        return self.library.import_paths(paths, names)

    def import_memes(self):
        webview = self.context.webview()

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
        importer = self.library or self.catalog
        imported = importer.import_paths(result)
        if not isinstance(imported, dict):
            imported = {
                "ids": list(imported.imported_ids),
                "rejected": imported.rejected,
            }
        ids = imported.get("ids") or []
        return {
            "ok": True,
            "imported": len(ids),
            "rejected": imported.get("rejected", 0),
        }

    def import_folder(self, catalog, make_collection=True):
        import os

        import webview

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
                for filename in sorted(fnames):
                    if os.path.splitext(filename)[1].lower() not in allowed:
                        continue
                    files.append(os.path.join(root, filename))
                    names.append(os.path.splitext(filename)[0])
            if not files:
                return {"ok": False, "error": "文件夹中没有支持的图片"}
            folder_name = os.path.basename(os.path.normpath(folder))
            imported = catalog.import_folder(files, names, folder_name, make_collection)
            ids = imported.get("ids") or []
            return {
                "ok": True,
                "imported": len(ids),
                "rejected": imported.get("rejected", 0),
                "collection_id": imported.get("collection_id"),
                "collection_name": folder_name if make_collection and ids else None,
            }
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def import_clipboard(self):
        import os
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
                paths = [path for path in clip if os.path.isfile(path)]
                if not paths:
                    return {"ok": False, "error": "剪贴板中没有图片文件"}
                result = self.library.import_clipboard_paths(paths)
                ids = result.get("ids") or []
                return {
                    "ok": True,
                    "id": ids[0] if ids else 0,
                    "name": result.get("name") if ids else "未命名",
                    "rejected": result.get("rejected", 0),
                }
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp_path = tmp.name
            tmp.close()
            try:
                clip.save(tmp_path, "PNG")
                result = self.library.import_clipboard_paths([tmp_path], [""])
                ids = result.get("ids") or []
                return {
                    "ok": True,
                    "id": ids[0] if ids else 0,
                    "name": "未命名",
                    "rejected": result.get("rejected", 0),
                }
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def download_original_image(self, config, url):
        import os
        import shutil
        import tempfile
        from urllib.error import URLError
        from urllib.parse import urlparse
        from urllib.request import urlopen

        source = url.strip()
        local_path = None
        if source.startswith("file://"):
            from urllib.parse import unquote

            local_path = unquote(urlparse(source).path)
            if len(local_path) > 3 and local_path[2] == ":":
                local_path = local_path.lstrip("/")
        elif source.startswith("/") and os.path.isfile(source):
            local_path = source
        elif len(source) > 2 and source[1] == ":" and os.path.isfile(source):
            local_path = source
        if local_path:
            try:
                result = self.library.import_paths([local_path])
            except Exception as error:
                return {"ok": False, "error": str(error)}
            if result.get("ids"):
                return {"ok": True, "id": result["ids"][0]}
            if result.get("rejected"):
                return {
                    "ok": False,
                    "rejected": result["rejected"],
                    "error": "文件超过大小/分辨率限制，已跳过",
                }
            return {"ok": False, "error": "导入失败"}
        clean_url = self.context.strip_url(source)
        if not config.get("try_original_image", False):
            return {"ok": False, "error": "功能未启用"}
        if not self.context.connectivity()["ok"]:
            return {"ok": False, "error": "无网络连接"}
        parsed_path = urlparse(clean_url).path
        ext = os.path.splitext(parsed_path)[1].lower()
        allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
        need_type = not ext or ext not in allowed
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".download")
        tmp_path = tmp.name
        tmp.close()
        try:
            with urlopen(clean_url, timeout=15) as response:
                if need_type:
                    content_type = response.headers.get("Content-Type", "").split(";")[
                        0
                    ]
                    ext = {
                        "image/gif": ".gif",
                        "image/png": ".png",
                        "image/jpeg": ".jpg",
                        "image/webp": ".webp",
                        "image/bmp": ".bmp",
                    }.get(content_type, ".png")
                with open(tmp_path, "wb") as output:
                    shutil.copyfileobj(response, output)
            final_path = tmp_path + ext
            os.rename(tmp_path, final_path)
            result = self.library.import_paths([final_path])
            if result.get("ids"):
                return {"ok": True, "id": result["ids"][0]}
            if result.get("rejected"):
                return {
                    "ok": False,
                    "rejected": result["rejected"],
                    "error": "文件超过大小/分辨率限制，已跳过",
                }
            return {"ok": False, "error": "导入失败"}
        except URLError as error:
            return {"ok": False, "error": f"下载失败: {error.reason}"}
        except Exception as error:
            return {"ok": False, "error": str(error)}
        finally:
            for candidate in (tmp_path, tmp_path + ext):
                try:
                    os.unlink(candidate)
                except OSError:
                    pass
