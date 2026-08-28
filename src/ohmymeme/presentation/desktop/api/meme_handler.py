"""Desktop bridge MemeHandler implementation."""


class MemeHandler:
    """Owns references used by meme and collection bridge operations."""

    def __init__(self, catalog, library, context):
        self.catalog = catalog
        self.library = library
        self.context = context

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
        resize_mode = int(config.get("copy_resize_mode", 1) or 0)
        resize_max = int(config.get("copy_resize_max", 200) or 200)
        match resize_mode:
            case 1:
                path = self.context.copy_mode_1(path, resize_max) or path
            case 2:
                path = self.context.copy_mode_2(path, resize_max) or path
            case 3:
                path = self.context.copy_mode_3(path, resize_max) or path
        if not self.context.copy_image(path):
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
