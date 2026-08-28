"""表情目录应用用例。"""

import os


class Catalog:
    """协调目录查询和变更，不依赖桌面 UI。"""

    def __init__(self, config, db, build_manifest, find_file=None, is_animated=None):
        self._config = config
        self._db = db
        self._build_manifest = build_manifest
        self._find_file = find_file
        self._is_animated = is_animated

    def search_memes(
        self, keyword="", tags=None, collection_id=None, offset=0, limit=200
    ):
        tags = tags or None
        favorite_only = collection_id == -2
        recent_only = collection_id == -3
        uncategorized_only = collection_id == -4
        target_collection = (
            None
            if favorite_only or recent_only or uncategorized_only
            else collection_id
        )
        if recent_only:
            rows = self._db.get_recent(limit, offset)
        else:
            if target_collection is not None and target_collection > 0:
                target_collection = self._collection_ids(target_collection)
            rows = self._db.search(
                keyword=keyword,
                tags=tags,
                collection_id=target_collection,
                favorite_only=favorite_only,
                uncategorized_only=uncategorized_only,
                offset=offset,
                limit=limit,
            )
        return [self._meme_dto(row) for row in rows]

    def count_memes(self, keyword="", tags=None, collection_id=None):
        tags = tags or None
        if collection_id == -3:
            return self._db.count_recent()
        favorite_only = collection_id == -2
        uncategorized_only = collection_id == -4
        target_collection = (
            None if favorite_only or uncategorized_only else collection_id
        )
        if target_collection is not None and target_collection > 0:
            target_collection = self._collection_ids(target_collection)
        return self._db.count(
            keyword=keyword,
            tags=tags,
            collection_id=target_collection,
            favorite_only=favorite_only,
            uncategorized_only=uncategorized_only,
        )

    def get_tags(self):
        return self._db.get_all_tags()

    def get_meme_tags(self, meme_id):
        try:
            return self._db.get_meme_tags(meme_id) or []
        except Exception:
            return []

    def set_meme_tags(self, meme_id, tags):
        try:
            self._db.set_meme_tags(meme_id, tags or [])
            return True
        except Exception:
            return False

    def get_collections(self):
        system = [
            {
                "id": -2,
                "name": "收藏夹",
                "count": self._db.count(favorite_only=True),
            },
            {"id": -3, "name": "最近使用", "count": len(self._db.get_recent(9999))},
        ]
        if self._config.get("show_uncategorized", True):
            system.append(
                {
                    "id": -4,
                    "name": "未分类",
                    "count": self._db.count(uncategorized_only=True),
                }
            )
        return system + self._collection_tree()

    def get_init_data(self, startup_bg_color):
        return {
            "memes": self.search_memes(limit=200),
            "tags": self.get_tags(),
            "collections": self.get_collections(),
            "show_startup_animation": self._config.get("show_startup_animation", True),
            "startup_bg_color": startup_bg_color,
        }

    def toggle_favorite(self, meme_id):
        return self._db.toggle_favorite(meme_id)

    def reorder_memes(self, meme_ids):
        return self._mutate_manifest(self._db.reorder_memes, meme_ids)

    def reorder_collections(self, collection_ids):
        return self._mutate_manifest(self._db.reorder_collections, collection_ids)

    def reorder_collection_members(self, collection_id, meme_ids):
        try:
            self._db.reorder_collection_members(collection_id, meme_ids)
            self._build_manifest()
            return True
        except Exception:
            return False

    def _mutate_manifest(self, operation, values):
        try:
            operation(values)
            self._build_manifest()
            return True
        except Exception:
            return False

    def _collection_ids(self, collection_id):
        ids = [collection_id]
        for child in self._db.get_child_collections(collection_id):
            ids.extend(self._collection_ids(child["id"]))
        return ids

    def _collection_tree(self, parent_id=None):
        result = []
        for collection_id, name, item_parent_id, _ in self._db.get_collections():
            if item_parent_id != parent_id:
                continue
            children = self._collection_tree(collection_id)
            item = {
                "id": collection_id,
                "name": name,
                "count": self._db.count(
                    collection_id=self._collection_ids(collection_id)
                ),
            }
            if children:
                item["children"] = children
            result.append(item)
        return result

    def _meme_dto(self, row):
        filename = row["filename"]
        lowered = filename.lower()
        is_gif = row.get("mime_type", "").endswith("gif") or lowered.endswith(".gif")
        animated = is_gif
        if lowered.endswith(".webp") and self._find_file and self._is_animated:
            path = self._find_file(filename)
            animated = self._is_animated(path) if path else False
        return {
            "id": row["id"],
            "filename": filename,
            "name": row.get("original_name") or os.path.splitext(filename)[0],
            "file_hash": row.get("file_hash", ""),
            "from_stego": row.get("from_stego", 0),
            "width": row.get("width", 0),
            "height": row.get("height", 0),
            "mime_type": row.get("mime_type", ""),
            "is_gif": is_gif,
            "is_animated": animated,
            "favorited": self._db.is_favorite(row["id"]),
            "auto_play_gif": self._config.get("auto_play_gif", True),
            "hover_to_play": self._config.get("hover_to_play", False),
        }
