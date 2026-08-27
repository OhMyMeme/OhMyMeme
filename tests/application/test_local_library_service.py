import pytest

from ohmymeme.app.local_library import LocalLibraryService
from ohmymeme.core.assets import AssetPaths
from ohmymeme.core.database import MemeDB
from ohmymeme.core.imports import ImportBytes, ImportResult


class FakeDb:
    def __init__(self, fail_operation=None):
        self.calls = []
        self.fail_operation = fail_operation

    def _record(self, call):
        if call[0] == self.fail_operation:
            raise OSError("database write failed")
        self.calls.append(call)

    def get_by_id(self, meme_id):
        return {"id": meme_id, "filename": "example.png"}

    def delete_meme(self, meme_id):
        self._record(("delete_meme", meme_id))

    def update_meme(self, meme_id, **values):
        self._record(("update_meme", meme_id, values))

    def reorder_memes(self, meme_ids):
        self._record(("reorder_memes", tuple(meme_ids)))

    def reorder_collections(self, collection_ids):
        self._record(("reorder_collections", tuple(collection_ids)))

    def reorder_collection_members(self, collection_id, meme_ids):
        self._record(("reorder_collection_members", collection_id, tuple(meme_ids)))

    def apply_remote_metadata(self, remote_data):
        self._record(("apply_remote_metadata", remote_data))

    def set_meme_tags(self, meme_id, tags):
        self._record(("set_meme_tags", meme_id, tuple(tags)))

    def set_collection_members(self, collection_id, meme_ids):
        self._record(("set_collection_members", collection_id, tuple(meme_ids)))

    def add_to_collection(self, meme_id, collection_id):
        self._record(("add_to_collection", meme_id, collection_id))

    def remove_from_collection(self, meme_id, collection_id):
        self._record(("remove_from_collection", meme_id, collection_id))

    def create_collection(self, name, parent_id=None):
        self._record(("create_collection", name, parent_id))
        return 4

    def rename_collection(self, collection_id, name):
        self._record(("rename_collection", collection_id, name))

    def delete_collection(self, collection_id):
        self._record(("delete_collection", collection_id))


class FakeImporter:
    def __init__(self):
        self.calls = []

    def import_bytes(self, request):
        self.calls.append(("import_bytes", request))
        return {"imported_ids": (7,)}


def _service(tmp_path, project=None):
    assets = AssetPaths(tmp_path, tmp_path / "cache")
    assets.cache_dir.mkdir()
    db = FakeDb()
    importer = FakeImporter()
    service = LocalLibraryService(
        db,
        assets,
        importer,
        project or (lambda: None),
    )
    return service, db, importer, assets


def test_mutation_projects_only_after_database_commit(tmp_path):
    events = []

    def project():
        events.append("project")

    service, db, _, _ = _service(tmp_path, project)

    assert service.rename_meme(3, "renamed") is True

    assert db.calls == [("update_meme", 3, {"original_name": "renamed"})]
    assert events == ["project"]


def test_projection_failure_restores_previous_manifest_snapshot(tmp_path):
    service, db, _, assets = _service(tmp_path)
    manifest = assets.manifest_path
    manifest.write_bytes(b'{"version":3,"memes":[{"filename":"old.png"}]}')

    def fail_after_writing_new_projection():
        manifest.write_text("new", encoding="utf-8")
        raise OSError("projection failed")

    service._project_manifest = fail_after_writing_new_projection

    assert service.rename_meme(3, "renamed") is False

    assert manifest.read_bytes() == b'{"version":3,"memes":[{"filename":"old.png"}]}'
    assert db.calls == [("update_meme", 3, {"original_name": "renamed"})]


def test_runtime_projection_failure_restores_previous_manifest_snapshot(tmp_path):
    service, db, _, assets = _service(tmp_path)
    manifest = assets.manifest_path
    manifest.write_bytes(b"old")

    def fail_after_writing_new_projection():
        manifest.write_bytes(b"new")
        raise RuntimeError("projection failed")

    service._project_manifest = fail_after_writing_new_projection

    assert service.rename_meme(3, "renamed") is False

    assert manifest.read_bytes() == b"old"
    assert db.calls == [("update_meme", 3, {"original_name": "renamed"})]


def test_import_delegates_validation_and_deduplication_to_import_service(tmp_path):
    service, db, importer, assets = _service(tmp_path)

    result = service.import_bytes(ImportBytes(b"payload", "example.png"))

    assert result == {"imported_ids": (7,)}
    assert importer.calls == [("import_bytes", ImportBytes(b"payload", "example.png"))]
    assert db.calls == []
    assert not assets.manifest_path.exists()


def test_import_paths_delegates_downloaded_files_to_import_service(tmp_path):
    service, _, importer, _ = _service(tmp_path)
    importer.import_batch = lambda requests: ImportResult((8,), 0)

    result = service.import_paths((tmp_path / "telegram.webp",))

    assert result == ImportResult((8,), 0)


@pytest.mark.parametrize(
    ("method", "args", "expected"),
    (
        ("delete_meme", (3,), True),
        ("reorder_memes", ([3, 2],), True),
        ("reorder_collections", ([4, 5],), True),
        ("reorder_collection_members", (4, [3, 2]), True),
        ("set_meme_tags", (3, ["funny"]), True),
        ("set_collection_members", (4, [3]), True),
        ("add_to_collection", (3, 4), True),
        ("remove_from_collection", (3, 4), True),
        ("rename_collection", (4, "renamed"), True),
        ("delete_collection", (4,), True),
        ("create_collection", ("new",), 4),
        ("apply_remote_metadata", ({"memes": []},), True),
    ),
)
def test_mutation_operations_project_after_success(tmp_path, method, args, expected):
    service, db, _, _ = _service(tmp_path)

    assert getattr(service, method)(*args) == expected

    assert db.calls


def test_database_failure_does_not_project_or_change_manifest(tmp_path):
    events = []
    service, db, _, assets = _service(
        tmp_path,
        lambda: events.append("project"),
    )
    db.fail_operation = "reorder_memes"
    assets.manifest_path.write_bytes(b"old")

    assert service.reorder_memes([3]) is False

    assert events == []
    assert assets.manifest_path.read_bytes() == b"old"


def test_cache_failure_does_not_project_or_change_manifest(tmp_path, monkeypatch):
    events = []
    service, db, _, assets = _service(
        tmp_path,
        lambda: events.append("project"),
    )
    assets.manifest_path.write_bytes(b"old")
    cache_path = assets.cache_dir / "example.png"
    cache_path.write_bytes(b"image")
    original_unlink = cache_path.unlink

    def fail_cache_unlink(*args, **kwargs):
        if cache_path == assets.cache_dir / "example.png":
            raise OSError("cache write failed")
        return original_unlink(*args, **kwargs)

    monkeypatch.setattr(type(cache_path), "unlink", fail_cache_unlink)

    assert service.delete_meme(3) is False

    assert db.calls == []
    assert events == []
    assert assets.manifest_path.read_bytes() == b"old"


def _real_service(tmp_path, projector):
    assets = AssetPaths(tmp_path, tmp_path / "cache")
    assets.cache_dir.mkdir()
    db = MemeDB(tmp_path / "memes.db")
    service = LocalLibraryService(db, assets, FakeImporter(), projector)
    return service, db, assets


def test_real_database_commit_and_manifest_projection_are_both_observable(tmp_path):
    # Given: a real SQLite database and a projector writing a versioned manifest
    manifest_path = tmp_path / "meme-index.json"

    def project():
        manifest_path.write_text(
            '{"version": 3, "memes": [{"filename": "example.png"}]}',
            encoding="utf-8",
        )

    service, db, assets = _real_service(tmp_path, project)
    meme_id = db.add_meme("example.png", original_name="old")

    # When: a committed database mutation is projected
    result = service.rename_meme(meme_id, "renamed")

    # Then: the result, database row, and manifest state identify a success
    assert result is True
    assert db.get_by_id(meme_id)["original_name"] == "renamed"
    assert assets.manifest_path.read_text(encoding="utf-8") == (
        '{"version": 3, "memes": [{"filename": "example.png"}]}'
    )
    db.close()


def test_real_database_mutation_kept_when_projection_restores_old_manifest(
    tmp_path,
):
    # Given: a real row, an old manifest, and a projector that fails after writing
    manifest_path = tmp_path / "meme-index.json"

    def project():
        manifest_path.write_text("new", encoding="utf-8")
        raise OSError("projection failed")

    service, db, assets = _real_service(tmp_path, project)
    meme_id = db.add_meme("example.png", original_name="old")
    assets.manifest_path.write_bytes(b"old")

    # When: the database commit succeeds but projection fails
    result = service.rename_meme(meme_id, "renamed")

    # Then: failure is returned, DB mutation remains, and old manifest is restored
    assert result is False
    assert db.get_by_id(meme_id)["original_name"] == "renamed"
    assert assets.manifest_path.read_bytes() == b"old"
    db.close()


def test_public_project_manifest_restores_old_manifest_after_projection_failure(
    tmp_path,
):
    # Given: a real SQLite database, an old manifest, and a projector that fails
    # after writing
    manifest_path = tmp_path / "meme-index.json"

    def project():
        manifest_path.write_text("new", encoding="utf-8")
        raise OSError("projection failed")

    service, db, assets = _real_service(tmp_path, project)
    assets.manifest_path.write_bytes(b"old")

    # When: the public projection operation is called
    result = service.project_manifest()

    # Then: the operation reports failure and restores the exact old bytes
    assert result is False
    assert assets.manifest_path.read_bytes() == b"old"
    db.close()


def test_projection_failure_without_manifest_removes_partial_manifest(
    tmp_path,
):
    # Given: a real row and no prior manifest
    manifest_path = tmp_path / "meme-index.json"

    def project():
        manifest_path.write_text("partial", encoding="utf-8")
        raise OSError("projection failed")

    service, db, assets = _real_service(tmp_path, project)
    meme_id = db.add_meme("example.png", original_name="old")

    # When: projection fails without an old snapshot
    result = service.rename_meme(meme_id, "renamed")

    # Then: failure is returned, DB mutation remains, and no manifest is exposed
    assert result is False
    assert db.get_by_id(meme_id)["original_name"] == "renamed"
    assert not assets.manifest_path.exists()
    db.close()


def test_projection_restore_failure_is_raised_and_not_reported_as_success(
    tmp_path,
    monkeypatch,
):
    # Given: a real row, an old manifest, and a projector that fails after writing
    manifest_path = tmp_path / "meme-index.json"

    def project():
        manifest_path.write_text("new", encoding="utf-8")
        raise ValueError("projection failed")

    service, db, assets = _real_service(tmp_path, project)
    meme_id = db.add_meme("example.png", original_name="old")
    assets.manifest_path.write_bytes(b"old")

    def fail_restore(path, snapshot):
        raise OSError("restore failed")

    monkeypatch.setattr(service, "_restore_manifest", fail_restore)

    # When: a public mutation commits before projection and recovery both fail
    with pytest.raises(ValueError, match="projection failed") as error:
        service.rename_meme(meme_id, "renamed")

    # Then: the error exposes recovery failure as its cause, never a success value
    assert isinstance(error.value, ValueError)
    assert isinstance(error.value.__cause__, OSError)
    assert str(error.value.__cause__) == "restore failed"
    assert db.get_by_id(meme_id)["original_name"] == "renamed"
    assert assets.manifest_path.read_bytes() == b"new"
    db.close()
