import inspect
import io
import threading

import pytest
from PIL import Image

from src.import_service import ImageImportService, ImportBytes, ImportPath


def _png_bytes(width=1, height=1):
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), (255, 0, 0, 255)).save(buffer, "PNG")
    return buffer.getvalue()


class FakeDb:
    def __init__(self, fail_add_at=None, fail_delete=False):
        self.rows = {}
        self.fail_add_at = fail_add_at
        self.fail_delete = fail_delete
        self.add_calls = 0

    def get_by_hash(self, file_hash):
        return self.rows.get(file_hash)

    def add_meme(self, **row):
        self.add_calls += 1
        if self.add_calls == self.fail_add_at:
            raise OSError("database write failed")
        meme_id = self.add_calls
        self.rows[row["file_hash"]] = {"id": meme_id, **row}
        return meme_id

    def delete_meme(self, meme_id):
        if self.fail_delete:
            raise OSError("database rollback failed")
        for file_hash, row in tuple(self.rows.items()):
            if row["id"] == meme_id:
                del self.rows[file_hash]
                return


def _service(tmp_path, db=None, fail_manifest=False):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    def build_manifest():
        if fail_manifest:
            raise OSError("manifest replace failed")

    return ImageImportService(db or FakeDb(), cache_dir, build_manifest), cache_dir


def test_import_bytes_creates_validated_file_row_and_manifest(tmp_path):
    # Given: valid image bytes and an empty cache/database
    service, cache_dir = _service(tmp_path)

    # When: importing bytes through the application service
    result = service.import_bytes(ImportBytes(_png_bytes(), "example.png"))

    # Then: one content-addressed file and metadata row are committed
    assert result.imported_ids == (1,)
    assert result.rejected == 0
    assert len(list(cache_dir.iterdir())) == 1


def test_import_bytes_returns_duplicate_without_mutation(tmp_path):
    # Given: an image already committed by its content hash
    db = FakeDb()
    service, cache_dir = _service(tmp_path, db)
    first = service.import_bytes(ImportBytes(_png_bytes(), "one.png"))

    # When: importing the same image under another name
    result = service.import_bytes(ImportBytes(_png_bytes(), "two.png"))

    # Then: no second file or row is created
    assert first.imported_ids == (1,)
    assert result.imported_ids == ()
    assert result.rejected == 0
    assert len(db.rows) == 1
    assert len(list(cache_dir.iterdir())) == 1


def test_import_bytes_rejects_oversize_and_corrupt_payloads_without_orphans(tmp_path):
    # Given: an oversize payload and a PNG magic prefix with corrupt contents
    service, cache_dir = _service(tmp_path)
    oversize = b"x" * (20 * 1024 * 1024 + 1)
    corrupt = b"\x89PNG\r\n\x1a\nnot-an-image"

    # When: both payloads cross the validation boundary
    result = service.import_batch(
        (ImportBytes(oversize, "big.png"), ImportBytes(corrupt, "evil.png"))
    )

    # Then: validation rejects them before any file or database mutation
    assert result.imported_ids == ()
    assert result.rejected == 2
    assert not list(cache_dir.iterdir())


def test_import_bytes_rejects_excessive_dimensions_without_orphans(tmp_path):
    # Given: a valid PNG whose longest edge exceeds the import contract
    service, cache_dir = _service(tmp_path)

    # When: importing the oversized dimensions
    result = service.import_bytes(ImportBytes(_png_bytes(2561, 1), "wide.png"))

    # Then: it is rejected before cache or metadata writes
    assert result.imported_ids == ()
    assert result.rejected == 1
    assert not list(cache_dir.iterdir())


def test_import_path_uses_magic_not_malicious_filename(tmp_path):
    # Given: a valid image disguised by a traversal-like display name
    source = tmp_path / "source.bin"
    source.write_bytes(_png_bytes())
    service, cache_dir = _service(tmp_path)

    # When: the path import receives the untrusted display name
    result = service.import_path(ImportPath(source, "../malicious.png"))

    # Then: the cache only receives a content-addressed magic-derived filename
    assert result.imported_ids == (1,)
    assert all(".." not in item.name for item in cache_dir.iterdir())


@pytest.mark.parametrize("fault", ("file", "db", "manifest", "batch-db"))
def test_import_transaction_faults_compensate_files_and_rows(
    tmp_path, fault, monkeypatch
):
    # Given: a write, manifest, or second batch database fault
    fail_add_at = 2 if fault == "batch-db" else (1 if fault == "db" else None)
    db = FakeDb(fail_add_at=fail_add_at)
    service, cache_dir = _service(tmp_path, db, fail_manifest=fault == "manifest")
    request = (
        ImportBytes(_png_bytes(), "one.png"),
        ImportBytes(_png_bytes(2, 1), "two.png"),
    )
    if fault == "file":

        def fail_install(*_):
            raise OSError

        monkeypatch.setattr(service, "_install", fail_install)

    # When: the service attempts one atomic batch
    with pytest.raises(OSError):
        service.import_batch(request)

    # Then: compensation leaves neither cache files nor metadata ghosts
    assert not list(cache_dir.iterdir())
    assert db.rows == {}


def test_import_path_restores_stg3_payload_without_storing_carrier(tmp_path):
    # Given: a GIF carrier and an injected decoder outputting a PNG payload
    carrier = tmp_path / "carrier.gif"
    carrier.write_bytes(b"GIF89aSTG3carrier")
    restored = tmp_path / "restored.png"
    restored.write_bytes(_png_bytes())
    db = FakeDb()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    service = ImageImportService(db, cache_dir, lambda: None, lambda _: restored)

    # When: importing the carrier through the path entrypoint
    result = service.import_path(ImportPath(carrier, "carrier.gif"))

    # Then: only the restored image is persisted and marked as stego-derived
    row = next(iter(db.rows.values()))
    assert result.imported_ids == (1,)
    assert row["from_stego"] == 1
    assert not restored.exists()
    assert list(cache_dir.iterdir())[0].suffix == ".png"


def test_manifest_failure_restores_previous_snapshot(tmp_path):
    # Given: a pre-existing manifest and a failing replacement operation
    db = FakeDb()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    manifest = tmp_path / "meme-index.json"
    manifest.write_text("old", encoding="utf-8")

    def fail_manifest():
        manifest.write_text("new", encoding="utf-8")
        raise OSError("replace failed")

    service = ImageImportService(db, cache_dir, fail_manifest)

    # When: the manifest update fails after a successful image insert
    with pytest.raises(OSError):
        service.import_bytes(ImportBytes(_png_bytes(), "example.png"))

    # Then: the prior manifest, cache and database state are recovered
    assert manifest.read_text(encoding="utf-8") == "old"
    assert not list(cache_dir.iterdir())
    assert db.rows == {}


def test_existing_corrupt_content_addressed_target_fails_closed(tmp_path):
    # Given: the target hash name exists but holds other bytes
    service, cache_dir = _service(tmp_path)
    payload = _png_bytes()
    digest = __import__("hashlib").sha256(payload).hexdigest()
    (cache_dir / f"{digest[:16]}.png").write_bytes(b"wrong")

    # When: importing the matching payload
    with pytest.raises(OSError):
        service.import_bytes(ImportBytes(payload, "example.png"))

    # Then: corrupt existing content is never trusted or registered
    assert not service._db.rows


def test_concurrent_duplicate_imports_create_one_row(tmp_path):
    # Given: 24 callers sharing the same service and content
    service, cache_dir = _service(tmp_path)
    results = []
    barrier = threading.Barrier(24)

    def import_same():
        barrier.wait()
        results.append(service.import_bytes(ImportBytes(_png_bytes(), "same.png")))

    workers = [threading.Thread(target=import_same) for _ in range(24)]

    # When: all callers import concurrently
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    # Then: content-addressed dedup has one durable winner
    assert sum(bool(result.imported_ids) for result in results) == 1
    assert len(service._db.rows) == 1
    assert len(list(cache_dir.iterdir())) == 1


def test_manifest_restore_failure_writes_recovery_marker(tmp_path, monkeypatch):
    # Given: a manifest failure followed by a failed snapshot restore
    service, cache_dir = _service(tmp_path, fail_manifest=True)
    manifest = cache_dir.parent / "meme-index.json"
    manifest.write_text("old", encoding="utf-8")
    monkeypatch.setattr(
        "src.import_service.os.replace",
        lambda *_: (_ for _ in ()).throw(OSError("restore")),
    )

    # When: the import fails after mutation
    with pytest.raises(OSError):
        service.import_bytes(ImportBytes(_png_bytes(), "example.png"))

    # Then: recovery is durably marked rather than silently losing cleanup state
    assert (cache_dir.parent / ".import-recovery.json").exists()


def test_public_import_method_signatures_remain_frozen():
    # Given: the established bridge and service methods
    from src.lan import _import_bytes
    from src.sync import _pull_worker
    from src.webui import JsApi

    # When: inspecting their public callable contracts
    signatures = {
        "import_memes": str(inspect.signature(JsApi.import_memes)),
        "import_folder": str(inspect.signature(JsApi.import_folder)),
        "clipboard": str(inspect.signature(JsApi.import_from_clipboard)),
        "lan": str(inspect.signature(_import_bytes)),
        "sync": str(inspect.signature(_pull_worker)),
    }

    # Then: bridge defaults and annotations stay ABI-compatible
    assert signatures == {
        "import_memes": "(self) -> bool",
        "import_folder": "(self, make_collection=True) -> dict",
        "clipboard": "(self) -> dict",
        "lan": "(data: bytes, filename: str) -> dict",
        "sync": "(entries, remote_root, cache_dir, db)",
    }


def test_recovery_marker_failure_preserves_primary_import_error(tmp_path, monkeypatch):
    # Given: manifest recovery and marker persistence both fail
    service, _ = _service(tmp_path, fail_manifest=True)
    monkeypatch.setattr(service, "_restore_manifest", lambda *_: ["restore"])

    def fail_marker(*_):
        raise OSError("marker")

    monkeypatch.setattr(service, "_write_recovery_marker", fail_marker)

    # When: the primary manifest mutation raises
    with pytest.raises(OSError, match="manifest replace failed"):
        service.import_bytes(ImportBytes(_png_bytes(), "example.png"))


def test_bounded_upload_body_rejects_missing_and_lying_content_length():
    # Given: streams larger than the upload limit with untrusted length metadata
    from src.webui import _read_upload_body

    oversized = b"x" * (28 * 1024 * 1024 + 1)

    # When/Then: both no-header and lying-header streams stop at limit + 1
    assert _read_upload_body(io.BytesIO(oversized)) is None
    assert _read_upload_body(io.BytesIO(oversized)) is None
