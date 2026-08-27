"""表情目录应用用例。"""

import os
from pathlib import Path

from ohmymeme.core.imports import ImportPath


class Catalog:
    """协调目录查询和变更，不依赖桌面 UI。"""

    def __init__(
        self, config, db, build_manifest, find_file=None, is_animated=None, library=None
    ):
        self._config = config
        self._db = db
        self._build_manifest = build_manifest
        self._find_file = find_file
        self._is_animated = is_animated
        self._library = library

    def search_memes(
        self, keyword="", tags=None, collection_id=None, offset=0, limit=200
    ):
        tags = tags or None
        target_collection, favorite_only, recent_only, uncategorized_only = (
            self._query_collection(collection_id)
        )
        if recent_only:
            rows = self._db.get_recent(limit, offset)
        else:
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
        target_collection, favorite_only, recent_only, uncategorized_only = (
            self._query_collection(collection_id)
        )
        if recent_only:
            return self._db.count_recent()
        return self._db.count(
            keyword=keyword,
            tags=tags,
            collection_id=target_collection,
            favorite_only=favorite_only,
            uncategorized_only=uncategorized_only,
        )

    def _query_collection(self, collection_id):
        """解析特殊分组并保留普通分组筛选值。"""
        favorite_only = collection_id == -2
        recent_only = collection_id == -3
        uncategorized_only = collection_id == -4
        target_collection = (
            None
            if favorite_only or recent_only or uncategorized_only
            else collection_id
        )
        if isinstance(target_collection, int) and target_collection > 0:
            target_collection = self._collection_ids(target_collection)
        return target_collection, favorite_only, recent_only, uncategorized_only

    def get_tags(self):
        return self._db.get_all_tags()

    def get_meme_tags(self, meme_id):
        try:
            return self._library.get_meme_tags(meme_id)
        except Exception:
            return []

    def set_meme_tags(self, meme_id, tags):
        if self._library is None:
            return False
        return self._library.set_meme_tags(meme_id, tags)

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
        return self._library.toggle_favorite(meme_id)

    def get_meme_path(self, meme_id):
        return self._library.get_meme_path(meme_id)

    def get_meme_paths(self, meme_ids):
        return self._library.get_meme_paths(meme_ids)

    def get_collection_members(self, collection_id):
        return self._db.search(collection_id=collection_id, limit=5000) or []

    def get_child_collections(self, parent_id):
        return self._db.get_child_collections(parent_id)

    def collection_depth(self, parent_id):
        return self._db.get_collection_depth(parent_id)

    def collection_tree(self):
        return self._collection_tree()

    def import_paths(self, paths, names=None):
        """通过本地库边界导入文件，并返回桥接所需的统计。"""
        if self._library is None:
            return {"ids": [], "rejected": 0}
        names = names or [Path(path).stem for path in paths]
        result = self._library.import_batch(
            tuple(ImportPath(Path(path), name) for path, name in zip(paths, names))
        )
        return {"ids": list(result.imported_ids), "rejected": result.rejected}

    def import_folder(self, paths, names, collection_name, make_collection=True):
        """导入文件夹内容并在成功后创建同名分组。"""
        result = self.import_paths(paths, names)
        ids = result["ids"]
        collection_id = None
        if make_collection and ids and self._library is not None:
            collection = self._library.create_collection(collection_name)
            if collection > 0:
                for meme_id in ids:
                    self._library.add_to_collection(meme_id, collection)
                collection_id = collection
        result["collection_id"] = collection_id
        result["collection_name"] = collection_name if collection_id else None
        return result

    def rescan_cache(self, cache_dir):
        """扫描缓存目录并通过本地库边界注册新文件。"""
        return self._library.rescan_cache(cache_dir)

    def reorder_memes(self, meme_ids):
        if self._library is not None:
            return self._library.reorder_memes(meme_ids)
        return False

    def reorder_collections(self, collection_ids):
        if self._library is not None:
            return self._library.reorder_collections(collection_ids)
        return False

    def reorder_collection_members(self, collection_id, meme_ids):
        if self._library is not None:
            return self._library.reorder_collection_members(collection_id, meme_ids)
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
            "favorited": self._library.is_favorite(row["id"]),
            "auto_play_gif": self._config.get("auto_play_gif", True),
            "hover_to_play": self._config.get("hover_to_play", False),
        }
