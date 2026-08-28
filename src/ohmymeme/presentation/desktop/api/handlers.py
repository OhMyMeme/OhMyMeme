"""Desktop bridge domain handlers sharing the Container-owned graph."""

import platform


class MemeHandler:
    """Owns references used by meme and collection bridge operations."""

    def __init__(self, catalog, library):
        self.catalog = catalog
        self.library = library

    def search_memes(
        self, keyword="", tags=None, collection_id=None, offset=0, limit=200
    ):
        return self.catalog.search_memes(keyword, tags, collection_id, offset, limit)

    def count_memes(self, keyword="", tags=None, collection_id=None):
        return self.catalog.count_memes(keyword, tags, collection_id)

    def get_tags(self):
        return self.catalog.get_tags()

    def get_meme_path(self, meme_id):
        return self.catalog.get_meme_path(meme_id)

    def get_meme_paths(self, meme_ids):
        return self.catalog.get_meme_paths(meme_ids)

    def toggle_favorite(self, meme_id):
        return self.library.toggle_favorite(meme_id)

    def is_favorite(self, meme_id):
        return self.library.is_favorite(meme_id)

    def get_meme_tags(self, meme_id):
        return self.catalog.get_meme_tags(meme_id)

    def set_meme_tags(self, meme_id, tags):
        return self.catalog.set_meme_tags(meme_id, tags)

    def get_init_data(self, startup_color):
        return self.catalog.get_init_data(startup_color)

    def start_native_drag(self, webui, meme_id):
        path = self.catalog.get_meme_path(meme_id)
        if not path:
            return False
        try:
            from ohmymeme.integrations.platform.native_drag import start_native_drag

            ok = bool(start_native_drag(path))
            if ok:
                webui.schedule_hide()
            return ok
        except Exception:
            return False

    def copy_meme(self, webui, config, meme_id):
        path = self.catalog.get_meme_path(meme_id)
        if not path:
            return {"ok": False, "status": "copy_failed"}
        from .. import window_manager

        resize_mode = int(config.get("copy_resize_mode", 1) or 0)
        resize_max = int(config.get("copy_resize_max", 200) or 200)
        match resize_mode:
            case 1:
                path = window_manager.convert_image_mode_1(path, resize_max) or path
            case 2:
                path = window_manager.convert_image_mode_2(path, resize_max) or path
            case 3:
                path = window_manager.convert_image_mode_3(path, resize_max) or path
        if not window_manager.copy_image_to_clipboard(path):
            return {"ok": False, "status": "copy_failed"}
        if config.get("record_recent_use", True):
            try:
                self.library.record_use(meme_id)
            except Exception:
                pass
        webui.schedule_hide()
        return {"ok": True, "status": "copied"}

    def rename_meme(self, meme_id, new_name):
        if not new_name:
            return False
        try:
            return self.library.rename_meme(meme_id, new_name)
        except Exception:
            return False

    def delete_meme(self, webui, meme_id):
        result = self.library.delete_meme(meme_id)
        if result and hasattr(webui, "_file_cache"):
            webui._file_cache.clear()
        return result

    def delete_memes(self, meme_ids):
        ids = list(dict.fromkeys(int(x) for x in (meme_ids or [])))
        return self.library.delete_memes(ids)

    def get_collection_ids(self, collection_id):
        return self.catalog._collection_ids(collection_id)

    def collection_tree(self):
        return self.catalog.collection_tree()

    def get_collections(self):
        return self.catalog.get_collections()

    def get_child_collections(self, parent_id):
        return self.catalog.get_child_collections(parent_id)

    def search_collections(self, keyword=""):
        kw = (keyword or "").strip().lower()
        out = []
        for item in self.flatten_collections():
            if not kw or kw in item["name"].lower():
                out.append(item)
        return out[:20]

    def get_collection_members(self, collection_id):
        try:
            return self.catalog.get_collection_members(collection_id)
        except Exception:
            return []

    def flatten_collections(self):
        out = []

        def walk(items, depth):
            for collection in items:
                if collection.get("id", 0) > 0:
                    out.append(
                        {
                            "id": collection["id"],
                            "name": collection["name"],
                            "depth": depth,
                        }
                    )
                for child in collection.get("children", []) or []:
                    walk([child], depth + 1)

        walk(self.collection_tree(), 0)
        return out

    def add_to_collection(self, meme_id, name):
        collection_id = self.library.create_collection(name)
        if collection_id < 0:
            return False
        return self.library.add_to_collection(meme_id, collection_id)

    def add_to_existing_collection(self, meme_id, collection_id):
        try:
            return self.library.add_to_collection(meme_id, collection_id)
        except Exception:
            return False

    def set_collection_members(self, collection_id, meme_ids):
        try:
            return self.library.set_collection_members(collection_id, meme_ids)
        except Exception:
            return False

    def set_collection_members_new(self, name, meme_ids):
        return self.library.create_collection_with_members(name, meme_ids)

    def reorder_memes(self, meme_ids):
        return self.catalog.reorder_memes(meme_ids)

    def reorder_collections(self, collection_ids):
        return self.catalog.reorder_collections(collection_ids)

    def reorder_collection_members(self, collection_id, meme_ids):
        return self.catalog.reorder_collection_members(collection_id, meme_ids)

    def delete_collection(self, collection_id):
        try:
            return self.library.delete_collection(collection_id)
        except Exception:
            return False

    def rename_collection(self, collection_id, new_name):
        if not new_name:
            return False
        try:
            return self.library.rename_collection(collection_id, new_name)
        except Exception:
            return False

    def create_subcollection(self, name, parent_id):
        depth = self.catalog.collection_depth(parent_id)
        if depth >= 1:
            return {"ok": False, "error": "最大支持1层小分组"}
        collection_id = self.library.create_collection(name, parent_id=parent_id)
        if collection_id < 0:
            return {"ok": False}
        return {"ok": True, "id": collection_id}

    def record_meme_use(self, meme_id):
        try:
            self.library.record_use(meme_id)
            return True
        except Exception:
            return False

    def remove_from_recent(self, meme_id):
        try:
            self.library.remove_from_recent(meme_id)
            return True
        except Exception:
            return False

    def clear_recent(self):
        try:
            self.library.clear_recent()
            return True
        except Exception:
            return False

    def remove_from_collection(self, meme_id, collection_id):
        return self.library.remove_from_collection(meme_id, collection_id)

    def rescan_cache(self, cache_dir):
        return self.catalog.rescan_cache(cache_dir)

    def delete_all(self, webui):
        try:
            if not self.library.delete_all():
                return {"ok": False, "error": "删除本地表情失败"}
            try:
                import webview

                if webview.windows:
                    webview.windows[0].evaluate_js(
                        "refreshMemes();refreshTags();refreshCollections();"
                    )
            except Exception:
                pass
            return {"ok": True}
        except Exception as error:
            return {"ok": False, "error": str(error)}


class ImportHandler:
    """Owns the application import boundary for bridge import operations."""

    def __init__(self, library, job_manager, catalog=None):
        self.library = library
        self.job_manager = job_manager
        self.catalog = catalog

    def import_paths(self, paths, names=None):
        return self.library.import_paths(paths, names)

    def import_memes(self):
        from .. import window_manager

        webview = window_manager.webview

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

        from .. import window_manager

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
        clean_url = window_manager._strip_url_modifiers(source)
        if not config.get("try_original_image", False):
            return {"ok": False, "error": "功能未启用"}
        if not window_manager._check_connectivity()["ok"]:
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


class SyncHandler:
    """Owns the Container-created sync service factory and progress seam."""

    def __init__(self, container):
        self.container = container

    def service(self):
        return self.container.create_sync_service()

    def progress(self):
        from ohmymeme.services.sync import service

        return service.get_sync_progress()

    def push(self, delete_remote=None):
        try:
            sync_service = self.service()
        except Exception as error:
            return {"ok": False, "error": str(error), "failed_files": []}
        try:
            result = sync_service.push(delete_remote=delete_remote)
            result["ok"] = True
            return result
        except Exception as error:
            return {
                "ok": False,
                "error": str(error),
                "failed_files": self.progress().get("failed_items", []),
            }

    def pull(self, remove_local=None, refresh=False):
        try:
            sync_service = self.service()
        except Exception as error:
            return {"ok": False, "error": str(error), "failed_files": []}
        try:
            result = sync_service.pull(remove_local=remove_local)
            result["ok"] = True
            if refresh:
                try:
                    import webview

                    if webview.windows:
                        webview.windows[0].evaluate_js(
                            "refreshMemes();refreshTags();refreshCollections();"
                        )
                except Exception:
                    pass
            return result
        except Exception as error:
            return {
                "ok": False,
                "error": str(error),
                "failed_files": self.progress().get("failed_items", []),
            }

    def auto_sync(self):
        try:
            return self.service().auto_sync()
        except Exception as error:
            return {"fetched": False, "synced": False, "error": str(error)}

    def test_connection(self):
        try:
            return self.service().test_connection()
        except Exception as error:
            return str(error)

    def delete_all_remote(self):
        try:
            return self.service().delete_all_remote()
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def cleanup_remote_orphans(self, delete=False):
        try:
            return self.service().cleanup_remote_orphans(delete=delete)
        except Exception as error:
            return {"ok": False, "error": str(error)}

    def status(self):
        try:
            return self.service().get_status()
        except AttributeError:
            return {"ok": False, "error": "同步状态服务不可用"}
        except Exception as error:
            return {"ok": False, "error": str(error)}


class UpdateHandler:
    """Owns update operations while leaving WebUI quit wiring in the facade."""

    def __init__(self, webui):
        self.webui = webui

    def check_update(self, debug=False, force=False):
        from ohmymeme import __version__ as current_version
        from ohmymeme.services import updates

        info = updates.check_latest_cached(force=bool(debug) or bool(force))
        info["current"] = current_version
        if debug or self.webui._update_debug:
            info["has_update"] = True
        return info

    def start_download(self, url):
        from ohmymeme.services import updates

        return updates.start_download(url)

    def download_progress(self):
        from ohmymeme.services import updates

        return updates.get_download_progress()

    def run_downloaded_installer(self):
        from ohmymeme.services import updates

        return updates.run_downloaded_installer()

    def download_update(self, url):
        from ohmymeme.services import updates

        path = updates.download_release(url)
        if not path:
            return {"ok": False, "error": "download failed"}
        ok = updates.run_installer(path)
        return {"ok": ok, "error": "" if ok else "run installer failed"}


class WindowSettingsHandler:
    """Owns shared settings dependencies without constructing a second graph."""

    def __init__(self, webui, settings):
        from .settings_imports import SettingsImportHandler

        self.webui = webui
        self.settings = settings
        self.config = webui._cfg
        self.imports = SettingsImportHandler(webui)

    def get_settings(self):
        return self.settings.get_settings()

    def save_settings(self, settings):
        hotkey = self.settings.save_settings(settings)
        if hotkey:
            self.webui._on_hotkey_change(hotkey)

    def reset_settings(self):
        result = self.settings.reset_settings()
        self.webui._on_hotkey_change(result["hotkey"])
        return result

    def move_window(self, dx, dy):
        window = self.webui._settings_window
        if window:
            try:
                window.move(window.x + dx, window.y + dy)
            except Exception:
                pass

    def move_main_window(self, dx, dy):
        window = self.webui._window
        if window:
            try:
                window.move(window.x + dx, window.y + dy)
            except Exception:
                pass

    def start_window_drag(self, button, root_x, root_y):
        if platform.system() != "Linux":
            return False
        window = self.webui._settings_window
        if not window:
            return False
        try:
            from gi.repository import Gdk, GLib

            native = getattr(window, "native", None)
            if native is None:
                return False
            GLib.idle_add(
                native.begin_move_drag, button, root_x, root_y, Gdk.CURRENT_TIME
            )
            return True
        except Exception:
            return False

    def start_lan(self, port, secret):
        from ohmymeme.services import lan

        current_port = int(port or self.config.get("lan_port", 17852))
        current_secret = (
            secret if secret is not None else self.config.get("lan_secret", "")
        )
        ok = self.webui._container.start_lan(current_port, current_secret)
        return {"ok": ok, "status": lan.get_status()}

    def stop_lan(self):
        from ohmymeme.services import lan

        self.webui._container.stop_lan()
        return {"ok": True, "status": lan.get_status()}

    def lan_status(self):
        from ohmymeme.services import lan

        return lan.get_status()

    def lan_ip(self):
        from ohmymeme.services import lan

        return lan.get_lan_ip()

    def allow_secret_config(self, enabled):
        from ohmymeme.services import lan

        lan.set_allow_secret_config(bool(enabled))
        return {
            "ok": True,
            "allow_secret_config": lan.get_status()["allow_secret_config"],
        }

    def storage_info(self):
        return self.webui._container.library.storage_info()

    def pick_storage_dir(self):
        import webview

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
        import webview

        try:
            result = self.webui._container.library.apply_storage_dir(path, move_files)
        except Exception as error:
            return {"ok": False, "error": str(error)}
        if not result.get("ok"):
            return result
        file_cache = getattr(self.webui, "_file_cache", None)
        if file_cache is not None:
            file_cache.clear()
        try:
            if webview.windows:
                webview.windows[0].evaluate_js("refreshMemes();")
        except Exception:
            pass
        return result

    def open_directory(self, path):
        import os
        import platform
        import subprocess

        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except Exception:
            return False

    def qqnt_check_env(self):
        from ohmymeme.integrations.imports import qqnt

        return qqnt.get_extract_status(
            ini_path=self.config.get("qqnt_ini_path") or qqnt.DEFAULT_INI_PATH,
            userdata_save_path=self.config.get("qqnt_userdata_path") or None,
            fetch_nicknames=True,
        )

    def qqnt_default_dir(self, base, qq_number):
        from ohmymeme.integrations.imports import qqnt

        try:
            directory = qqnt.get_default_output_dir(
                base, qq_number, fetch_nickname=True
            )
        except Exception:
            return {"ok": False}
        return {"ok": True, "dir": directory}

    def start_qq_import(self):
        return self.imports.start_qq_import()

    def get_qq_import_progress(self):
        return self.imports.get_qq_import_progress()

    def save_qq_zip(self):
        return self.imports.save_qq_zip()

    def open_adb_folder(self):
        return self.imports.open_adb_folder()

    def open_adb_help(self):
        return self.imports.open_adb_help()

    def export_logs(self):
        from .logs import export_logs

        return export_logs(self.webui)

    def cancel_qq_import(self):
        return self.imports.cancel_qq_import()

    def pick_tg_tdata(self):
        return self.imports.pick_tg_tdata()

    def start_tg_import(self, tdata_path=None, passcode="", convert_webm=True):
        return self.imports.start_tg_import(tdata_path, passcode, convert_webm)

    def get_tg_import_progress(self):
        return self.imports.get_tg_import_progress()

    def cancel_tg_import(self):
        return self.imports.cancel_tg_import()

    def start_douyin_import(self, cookie):
        return self.imports.start_douyin_import(cookie)

    def get_douyin_import_progress(self):
        return self.imports.get_douyin_import_progress()

    def cancel_douyin_import(self):
        return self.imports.cancel_douyin_import()

    def pick_wechat_root(self):
        return self.imports.pick_wechat_root()

    def inspect_wechat_environment(self, user_root=None):
        return self.imports.inspect_wechat_environment(user_root)

    def list_wechat_stickers(self, user_root, account_path=None):
        return self.imports.list_wechat_stickers(user_root, account_path)

    def start_wechat_import(self, user_root=None, download=True, account_path=None):
        return self.imports.start_wechat_import(user_root, download, account_path)

    def get_wechat_import_progress(self):
        return self.imports.get_wechat_import_progress()

    def cancel_wechat_import(self):
        return self.imports.cancel_wechat_import()

    def qqnt_pick_ini(self):
        return self.imports.qqnt_pick_ini()

    def qqnt_pick_userdata(self):
        return self.imports.qqnt_pick_userdata()

    def qqnt_pick_base(self):
        return self.imports.qqnt_pick_base()

    def qqnt_start(self, qq_number, output_dir, image_only=False, overwrite=False):
        return self.imports.qqnt_start(qq_number, output_dir, image_only, overwrite)

    def qqnt_get_progress(self):
        return self.imports.qqnt_get_progress()

    def qqnt_cancel(self):
        return self.imports.qqnt_cancel()

    def qqnt_open_dir(self, path):
        return self.imports.qqnt_open_dir(path)


def create_handlers(webui, catalog, settings, library):
    """Create the domain handlers for one WebUI Container graph."""
    container = webui._container
    return {
        "meme": MemeHandler(catalog, library),
        "import": ImportHandler(
            library,
            getattr(container, "job_manager", None),
            catalog,
        ),
        "sync": SyncHandler(container),
        "update": UpdateHandler(webui),
        "window_settings": WindowSettingsHandler(webui, settings),
    }
