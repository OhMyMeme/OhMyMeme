"""本地表情库写入边界。"""

import os
import shutil
import sqlite3
from pathlib import Path

from ohmymeme.core.imports import ImportPath


class LocalLibraryService:
    """Serialize local-library writes and project committed state to a manifest."""

    def __init__(self, db, assets, importer, build_manifest, config=None):
        self._db = db
        self._assets = assets
        self._importer = importer
        self._project_manifest = build_manifest
        self._config = config

    def configure_stego_decoder(self, decoder):
        """Configure the optional decoder on the Container-owned importer."""
        self._importer._stego_decoder = decoder

    def rescan_cache(self, cache_dir=None):
        """Register supported cache files and project once after the scan."""
        cache_dir = cache_dir or self._assets.cache_dir
        if not cache_dir.exists():
            return
        allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
        for root, dirs, files in os.walk(cache_dir):
            dirs[:] = [name for name in dirs if name != "thumbnails"]
            for filename in files:
                path = Path(root) / filename
                if path.suffix.lower() not in allowed:
                    continue
                if (
                    path.suffix.lower() == ".gif"
                    and path.with_suffix(".webp").is_file()
                ):
                    continue
                if self._db.get_by_filename(filename):
                    continue
                self.register_existing_path(ImportPath(path, filename), project=False)
        self._project_after_mutation()

    def apply_storage_dir(self, path, move_files=False):
        """Apply and persist the cache directory, including atomic file migration."""
        if self._config is None:
            return {"ok": False, "error": "存储服务不可用"}
        old = self._config.cache_dir
        new = Path(path).resolve()
        protected = (self._config.data_dir, self._config.thumbnail_dir)
        old_resolved = old.resolve()
        if (
            new == old_resolved
            or new in protected
            or any(parent in protected for parent in new.parents)
        ):
            return {"ok": False, "error": "目标目录不能是当前目录或受保护目录"}
        try:
            new.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return {"ok": False, "error": f"创建目录失败: {error}"}
        plan = []
        if move_files:
            for root, dirs, files in os.walk(old):
                dirs[:] = [name for name in dirs if name != "thumbnails"]
                for filename in files:
                    source = Path(root) / filename
                    destination = new / source.relative_to(old)
                    plan.append((source, destination))
            collisions = [
                destination for _, destination in plan if destination.exists()
            ]
            if collisions:
                return {
                    "ok": False,
                    "error": f"目标目录已存在 {len(collisions)} 个同名文件，未迁移",
                    "failed": [
                        {
                            "name": path.name,
                            "path": str(path),
                            "error": "目标目录已存在同名文件",
                        }
                        for path in collisions
                    ],
                }
        moved = []
        try:
            for source, destination in plan:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
                moved.append((source, destination))
            previous = self._config.get("cache_dir", "")
            self._config.set("cache_dir", str(new))
            self._config.save()
        except OSError as error:
            for source, destination in reversed(moved):
                if destination.exists():
                    shutil.move(str(destination), str(source))
            self._config.set("cache_dir", previous)
            return {"ok": False, "error": f"迁移失败（{error}），已回滚已移动文件"}
        return {"ok": True, "cache_dir": str(new), "moved": len(moved), "failed": []}

    def import_bytes(self, request):
        """Delegate image validation, deduplication, compensation, and projection."""
        return self._importer.import_bytes(request)

    def import_path(self, request):
        """Delegate image validation, deduplication, compensation, and projection."""
        return self._importer.import_path(request)

    def import_batch(self, requests):
        """Delegate batch import through the local-library boundary."""
        return self._importer.import_batch(requests)

    def import_paths(self, paths):
        """Import downloaded paths through the local-library boundary."""
        from ohmymeme.core.imports import ImportPath

        requests = tuple(ImportPath(Path(path), Path(path).stem) for path in paths)
        return self.import_batch(requests)

    def import_clipboard_paths(self, paths, names=None):
        """Import clipboard paths and resolve the display name at the app boundary."""
        names = names or [Path(path).stem for path in paths]
        result = self.import_batch(
            tuple(ImportPath(Path(path), name) for path, name in zip(paths, names))
        )
        imported_ids = list(result.imported_ids)
        name = "未命名"
        if imported_ids:
            row = self._db.get_by_id(imported_ids[0])
            name = (row or {}).get("original_name") or name
        return {"ids": imported_ids, "rejected": result.rejected, "name": name}

    def storage_info(self):
        """Return storage metadata and cache statistics for the UI."""
        cache = self._config.cache_dir
        count = 0
        total = 0
        if cache.exists():
            for root, dirs, files in os.walk(cache):
                dirs[:] = [name for name in dirs if name != "thumbnails"]
                for filename in files:
                    count += 1
                    try:
                        total += (Path(root) / filename).stat().st_size
                    except OSError:
                        pass
        return {
            "cache_dir": str(cache),
            "data_dir": str(self._config.data_dir),
            "custom": bool(self._config.get("cache_dir", "")),
            "file_count": count,
            "total_size": total,
        }

    def toggle_favorite(self, meme_id):
        return self._db.toggle_favorite(meme_id)

    def is_favorite(self, meme_id):
        return self._db.is_favorite(meme_id)

    def record_use(self, meme_id):
        return self._db.record_use(meme_id)

    def remove_from_recent(self, meme_id):
        return self._db.remove_from_recent(meme_id)

    def clear_recent(self):
        return self._db.clear_recent()

    def find_meme_file(self, filename):
        cache_dir = self._assets.cache_dir
        direct = cache_dir / filename
        if direct.is_file():
            return str(direct)
        for root, _, files in os.walk(cache_dir):
            if filename in files:
                return str(Path(root) / filename)
        return ""

    def get_meme_path(self, meme_id):
        row = self._db.get_by_id(meme_id)
        return self.find_meme_file(row["filename"]) if row else ""

    def get_meme_paths(self, meme_ids):
        result = {}
        for meme_id in meme_ids:
            path = self.get_meme_path(int(meme_id))
            if path:
                result[int(meme_id)] = path
        return result

    def get_meme_tags(self, meme_id):
        return self._db.get_meme_tags(meme_id) or []

    def register_existing_path(self, request, project=True):
        """Register a downloaded path, optionally deferring projection for a batch."""
        result = self._importer.register_existing_path(request)
        if project and result.imported_ids:
            self._project_after_mutation()
        return result

    def delete_meme(self, meme_id):
        """Delete one database row and its cache file, then project the manifest."""
        row = self._db.get_by_id(meme_id) if hasattr(self._db, "get_by_id") else None
        if row is None and hasattr(self._db, "rows"):
            index = int(meme_id) - 1
            row = self._db.rows[index] if 0 <= index < len(self._db.rows) else None
        if not row:
            return False
        try:
            path = self._assets.cache_dir / row["filename"]
            path.unlink(missing_ok=True)
            self._db.delete_meme(meme_id)
            return self._project_after_mutation()
        except (OSError, RuntimeError, sqlite3.Error):
            return False

    def delete_memes(self, meme_ids):
        """Delete a deduplicated set of memes and project once."""
        try:
            ids = list(dict.fromkeys(meme_ids))
            existing = [
                (
                    self._db.get_by_id(meme_id)
                    if hasattr(self._db, "get_by_id")
                    else self._db.rows[int(meme_id) - 1]
                )
                for meme_id in ids
            ]
            rows = [row for row in existing if row]
            for row in rows:
                (self._assets.cache_dir / row["filename"]).unlink(missing_ok=True)
                for thumbnail in self._assets.thumbnail_dir.glob(f'{row["id"]}_*.png'):
                    thumbnail.unlink(missing_ok=True)
            if rows:
                self._db.delete_memes(ids)
                if not self._project_after_mutation():
                    return {"ok": False, "deleted": 0}
            return {"ok": True, "deleted": len(rows)}
        except (OSError, RuntimeError, sqlite3.Error):
            return {"ok": False, "deleted": 0}

    def rename_meme(self, meme_id, new_name):
        """Update a meme display name and project the manifest."""
        if not new_name:
            return False
        try:
            self._db.update_meme(meme_id, original_name=new_name)
            return self._project_after_mutation()
        except (OSError, RuntimeError, sqlite3.Error):
            return False

    def reorder_memes(self, meme_ids):
        """Persist global meme ordering and project the manifest."""
        return self._mutate(self._db.reorder_memes, meme_ids)

    def reorder_collections(self, collection_ids):
        """Persist collection ordering and project the manifest."""
        return self._mutate(self._db.reorder_collections, collection_ids)

    def reorder_collection_members(self, collection_id, meme_ids):
        """Persist ordering within one collection and project the manifest."""
        return self._mutate(
            self._db.reorder_collection_members, collection_id, meme_ids
        )

    def set_meme_tags(self, meme_id, tags):
        """Replace meme tags and project the manifest."""
        return self._mutate(self._db.set_meme_tags, meme_id, tags or [])

    def set_collection_members(self, collection_id, meme_ids):
        """Replace collection members and project the manifest."""
        return self._mutate(self._db.set_collection_members, collection_id, meme_ids)

    def add_to_collection(self, meme_id, collection_id):
        """Add one meme to a collection and project the manifest."""
        return self._mutate(self._db.add_to_collection, meme_id, collection_id)

    def remove_from_collection(self, meme_id, collection_id):
        """Remove one meme from a collection and project the manifest."""
        return self._mutate(self._db.remove_from_collection, meme_id, collection_id)

    def create_collection(self, name, parent_id=None):
        """Create or reuse a collection and project the manifest."""
        try:
            collection_id = self._db.create_collection(name, parent_id=parent_id)
            if collection_id < 0:
                return -1
            if not self._project_after_mutation():
                return -1
            return collection_id
        except (OSError, RuntimeError, sqlite3.Error):
            return -1

    def create_collection_with_members(self, name, meme_ids):
        """Create a collection and assign members through one application boundary."""
        try:
            if self._db.collection_exists(name):
                return {"ok": False, "error": "同名分组已存在，请从下拉框选择已有分组"}
            collection_id = self._db.create_collection(name)
            if collection_id < 0:
                return {"ok": False}
            self._db.set_collection_members(collection_id, meme_ids)
            if not self._project_after_mutation():
                return {"ok": False}
            return {"ok": True, "id": collection_id}
        except (OSError, RuntimeError, sqlite3.Error):
            return {"ok": False}

    def apply_remote_metadata(self, remote_data):
        """Apply remote collection and ordering metadata, then project the manifest."""
        return self._mutate(self._db.apply_remote_metadata, remote_data)

    def apply_remote_operation(self, remote_data, operation):
        """Run a sync planning mutation against this library and project it."""
        return self._mutate(operation, remote_data)

    def rollback_delete(self, meme_id):
        """Remove a rollback-created meme and its cache without a second projection."""
        row = self._db.get_by_id(meme_id) if hasattr(self._db, "get_by_id") else None
        if row is None and hasattr(self._db, "rows"):
            index = int(meme_id) - 1
            row = self._db.rows[index] if 0 <= index < len(self._db.rows) else None
        if not row:
            return False
        try:
            (self._assets.cache_dir / row["filename"]).unlink(missing_ok=True)
            self._db.delete_meme(meme_id)
            return True
        except (OSError, RuntimeError, sqlite3.Error):
            return False

    def apply_remote_metadata_with(self, remote_data, operation):
        """Apply metadata through an injected compatibility repository operation."""
        operation(remote_data)
        return self._project_after_mutation()

    def replace_manifest(self, data):
        """Replace the projected manifest through the application boundary."""
        from ohmymeme.core.manifest import _write

        return self._project_data(_write, data)

    def restore_manifest(self, snapshot):
        """Restore an exact manifest snapshot after a failed compound operation."""
        self._restore_manifest(self._assets.manifest_path, snapshot)

    def rename_collection(self, collection_id, new_name):
        """Rename one collection and project the manifest."""
        if not new_name:
            return False
        return self._mutate(self._db.rename_collection, collection_id, new_name)

    def delete_collection(self, collection_id):
        """Delete one collection and project the manifest."""
        return self._mutate(self._db.delete_collection, collection_id)

    def delete_all(self):
        """Delete all local rows and cache files, then project the manifest."""
        try:
            self._db.delete_all()
            for path in self._assets.cache_dir.iterdir():
                if path.is_file():
                    path.unlink()
            for path in self._assets.thumbnail_dir.iterdir():
                if path.is_file():
                    path.unlink()
            return self._project_after_mutation()
        except (OSError, RuntimeError, sqlite3.Error):
            return False

    def _mutate(self, operation, *values):
        try:
            operation(*values)
            return self._project_after_mutation()
        except (OSError, RuntimeError, sqlite3.Error):
            return False

    def _project_after_mutation(self):
        path = self._assets.manifest_path
        snapshot = path.read_bytes() if path.exists() else None
        try:
            self._project_manifest()
        except Exception as error:  # noqa: BLE001
            try:
                self._restore_manifest(path, snapshot)
            except OSError as restore_error:
                raise error from restore_error
            return False
        return True

    def _project_data(self, projector, data):
        path = self._assets.manifest_path
        snapshot = path.read_bytes() if path.exists() else None
        try:
            projector(data, self._assets)
        except Exception as error:  # noqa: BLE001
            try:
                self._restore_manifest(path, snapshot)
            except OSError as restore_error:
                raise error from restore_error
            return False
        return True

    @staticmethod
    def _restore_manifest(path, snapshot):
        if snapshot is None:
            path.unlink(missing_ok=True)
            return
        temporary = path.with_name(path.name + ".restore.tmp")
        temporary.write_bytes(snapshot)
        os.replace(temporary, path)
