import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from ohmymeme.app.catalog import Catalog
from ohmymeme.app.container import Container
from ohmymeme.core.config import Config
from ohmymeme.core.crypto import encrypt_data
from ohmymeme.core.imports import ImportBytes
from ohmymeme.core.manifest import load
from ohmymeme.presentation.desktop.media import thumbnail_path


class _CloseRecorder:
    def __init__(self, name, events):
        self._name = name
        self._events = events

    def close(self):
        self._events.append(self._name)

    def save(self):
        self._events.append(self._name)

    def stop(self):
        self._events.append(self._name)

    def unregister(self):
        self._events.append(self._name)


class _JobRecorder:
    def __init__(self, events):
        self._events = events

    def shutdown(self, timeout):
        self._events.append(("jobs", timeout))
        return False


class _CatalogQueryDb:
    def __init__(self):
        self.search_calls = []
        self.count_calls = []
        self.recent_calls = []
        self.children = {10: [{"id": 11}], 11: [{"id": 12}], 12: []}
        self.rows = [{"id": 1, "filename": "one.png"}]

    def search(
        self,
        keyword="",
        tags=None,
        collection_id=None,
        favorite_only=False,
        uncategorized_only=False,
        offset=0,
        limit=100,
    ):
        self.search_calls.append(
            (
                keyword,
                tags,
                collection_id,
                favorite_only,
                uncategorized_only,
                offset,
                limit,
            )
        )
        return list(self.rows)

    def count(
        self,
        keyword="",
        tags=None,
        collection_id=None,
        favorite_only=False,
        uncategorized_only=False,
    ):
        self.count_calls.append(
            (
                keyword,
                tags,
                collection_id,
                favorite_only,
                uncategorized_only,
            )
        )
        return len(self.rows)

    def get_recent(self, limit=50, offset=0):
        self.recent_calls.append((limit, offset))
        return list(self.rows)

    def count_recent(self):
        return len(self.rows)

    def get_child_collections(self, parent_id):
        return self.children.get(parent_id, [])


class _CatalogLibrary:
    def is_favorite(self, _meme_id):
        return False


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(buffer, "PNG")
    return buffer.getvalue()


def test_catalog_fake_requires_and_records_explicit_query_contract():
    db = _CatalogQueryDb()
    catalog = Catalog(
        SimpleNamespace(get=lambda _key, default=None: default),
        db,
        lambda: None,
        library=_CatalogLibrary(),
    )

    catalog.search_memes(
        keyword="needle", tags=["a", "b"], collection_id=10, offset=4, limit=2
    )
    catalog.search_memes(collection_id=-2)
    catalog.count_memes(keyword="needle", tags=["a", "b"], collection_id=-2)
    catalog.search_memes(collection_id=-3, offset=7, limit=3)

    assert db.search_calls == [
        ("needle", ["a", "b"], [10, 11, 12], False, False, 4, 2),
        ("", None, None, True, False, 0, 200),
    ]
    assert db.count_calls == [("needle", ["a", "b"], None, True, False)]
    assert db.recent_calls == [(3, 7)]


def test_container_thumbnail_generation_creates_clean_root_directory(tmp_path):
    container = Container(tmp_path / "thumbnail-owner")
    webui = container.create_webui()
    source = tmp_path / "source.png"
    source.write_bytes(_png_bytes())

    result = container.library.import_paths([source])
    row = container.db.get_by_id(result.imported_ids[0])
    thumbnail = thumbnail_path(webui, result.imported_ids[0], row["filename"])

    assert Path(thumbnail).is_file()
    assert Path(thumbnail).parent == container.assets.thumbnail_dir
    container.close()


def test_container_close_orders_owned_resources_and_is_idempotent():
    events = []
    container = Container.__new__(Container)
    container._close_lock = threading.Lock()
    container._close_done = threading.Event()
    container._closed = False
    container.job_manager = _JobRecorder(events)
    container.db = _CloseRecorder("db", events)
    container.config = _CloseRecorder("config", events)

    hotkey = _CloseRecorder("hotkey", events)
    tray = _CloseRecorder("tray", events)
    webui = _CloseRecorder("webui", events)

    def stop_lan():
        events.append("lan")

    container.close(hotkey, tray, stop_lan, webui)
    container.close(hotkey, tray, stop_lan, webui)

    assert events == [
        ("jobs", 2.0),
        "hotkey",
        "tray",
        "webui",
        "lan",
        "db",
        "config",
    ]


def test_container_rejects_new_service_admission_after_close(tmp_path):
    container = Container(tmp_path / "closed-admission")
    container.close()

    with pytest.raises(RuntimeError, match="shut down"):
        container.create_sync_service()


def test_container_rejects_new_hotkey_after_close(tmp_path):
    container = Container(tmp_path / "closed-hotkey")
    container.close()

    with pytest.raises(RuntimeError, match="shut down"):
        container.create_hotkey()


def test_container_rejects_new_tray_after_close(tmp_path):
    container = Container(tmp_path / "closed-tray")
    container.close()

    with pytest.raises(RuntimeError, match="shut down"):
        container.create_tray(lambda: None, lambda: None, "source")


def test_container_factory_admission_is_atomic_with_close(monkeypatch, tmp_path):
    container = Container(tmp_path / "admission-race")
    entered = threading.Event()
    release = threading.Event()
    constructed = threading.Event()

    class Sync:
        def __init__(self, *args):
            entered.set()
            release.wait(1)
            constructed.set()

    monkeypatch.setattr("ohmymeme.app.container.SyncService", Sync)
    container._close_lock.acquire()
    factory_thread = threading.Thread(target=container.create_sync_service)
    factory_thread.start()
    close_thread = threading.Thread(target=container.close)
    close_thread.start()
    assert not entered.wait(0.05)
    container._close_lock.release()
    assert entered.wait(1)
    assert close_thread.is_alive()
    release.set()
    factory_thread.join(1)
    close_thread.join(1)

    assert constructed.is_set()
    assert not factory_thread.is_alive()
    assert not close_thread.is_alive()


def test_container_owns_lan_instance_lifecycle(monkeypatch, tmp_path):
    container = Container(tmp_path / "lan-owner")
    events = []

    class Lan:
        def start(self, port, secret):
            events.append(("start", port, secret))
            return True

        def stop(self):
            events.append("stop")

    monkeypatch.setattr(container, "create_lan_server", lambda: Lan())

    assert container.start_lan(19000, "secret") is True
    container.stop_lan()

    assert events == [("start", 19000, "secret"), "stop"]


def test_container_start_lan_reuses_owned_server(monkeypatch, tmp_path):
    container = Container(tmp_path / "lan-reuse")
    servers = []

    class Lan:
        def start(self, port, secret):
            return (port, secret)

        def stop(self):
            pass

    def create_server():
        server = Lan()
        servers.append(server)
        return server

    monkeypatch.setattr(container, "create_lan_server", create_server)
    try:
        assert container.start_lan(19001, "first") == (19001, "first")
        assert container.start_lan(19002, "second") == (19002, "second")
        assert len(servers) == 1
    finally:
        container.close()


def test_container_stops_directly_created_lan_server(tmp_path):
    container = Container(tmp_path / "direct-lan-owner")
    server = container.create_lan_server()
    stopped = []
    server.stop = lambda: stopped.append(True)

    container.close()

    assert stopped == [True]


def test_concurrent_container_close_waits_for_terminal_cleanup(tmp_path):
    container = Container(tmp_path / "close-race")
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def close_db():
        entered.set()
        release.wait(1)
        finished.set()

    container.db.close = close_db
    first = threading.Thread(target=container.close)
    second = threading.Thread(target=container.close)
    first.start()
    assert entered.wait(1)
    second.start()
    assert second.is_alive()
    release.set()
    first.join(1)
    second.join(1)

    assert finished.is_set()
    assert not first.is_alive()
    assert not second.is_alive()


def test_containers_isolate_config_database_and_manifest(tmp_path):
    first = Container(tmp_path / "first")
    second = Container(tmp_path / "second")
    try:
        assert first.config is not second.config
        assert first.db is not second.db
        assert first.config.config_dir != second.config.config_dir
        assert first.db._db_path != second.db._db_path
        first.config.set("hotkey", "Ctrl+Shift+X")
        first.config.save()
        first.db.add_meme("first.png", file_hash="first")
        first.build_manifest()
        assert first.assets.manifest_path.exists()
        assert not second.assets.manifest_path.exists()
        assert second.config.get("hotkey") == "Ctrl+Alt+N"
        assert second.db.count() == 0
    finally:
        first.close()
        second.close()


def test_container_services_share_explicit_dependency_identity(tmp_path):
    container = Container(tmp_path / "services")
    try:
        sync_service = container.create_sync_service()
        lan_server = container.create_lan_server()

        assert sync_service.config is container.config
        assert sync_service.db is container.db
        assert sync_service.assets is container.assets
        assert sync_service.manifest is container.manifest
        assert sync_service.library is container.library
        assert lan_server._commands.config is container.config
        assert lan_server._commands.db is container.db
        assert lan_server._commands.assets is container.assets
        assert lan_server._commands.manifest is container.manifest
        assert lan_server._commands.library is container.library
        assert lan_server._commands._sync_service.library is container.library
    finally:
        container.close()


def test_container_owns_job_manager_and_closes_it(tmp_path):
    container = Container(tmp_path / "jobs")
    try:
        assert container.job_manager.active("missing") is None
    finally:
        container.close()
    with pytest.raises(RuntimeError, match="shut down"):
        container.job_manager.start("after-close", lambda _context: None)


def test_container_creates_local_library_service_with_owned_dependencies(tmp_path):
    container = Container(tmp_path / "library")
    try:
        service = container.create_local_library_service()

        assert service._db is container.db
        assert service._assets is container.assets
        assert service._project_manifest == container.build_manifest
    finally:
        container.close()


def test_container_manifest_build_does_not_replace_module_functions(tmp_path):
    import ohmymeme.core.manifest as manifest_module

    original_config = manifest_module.get_config
    original_db = manifest_module.get_db
    container = Container(tmp_path / "manifest")
    try:
        container.build_manifest()
        assert manifest_module.get_config is original_config
        assert manifest_module.get_db is original_db
    finally:
        container.close()


def test_explicit_manifest_load_uses_supplied_assets_without_singletons(
    monkeypatch, tmp_path
):
    import ohmymeme.core.manifest as manifest_module

    container = Container(tmp_path / "manifest-load")
    try:
        container.assets.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        container.assets.manifest_path.write_text(
            '{"version": 3, "memes": [], "collections": []}', encoding="utf-8"
        )
        monkeypatch.setattr(
            manifest_module, "get_config", lambda: (_ for _ in ()).throw(AssertionError)
        )

        assert container.manifest.load() == {
            "version": 3,
            "memes": [],
            "collections": [],
        }
    finally:
        container.close()


def test_container_lan_command_uses_owned_library_and_paths(tmp_path):
    container = Container(tmp_path / "lan-command")
    try:
        server = container.create_lan_server()
        response = server._cmd_push_manifest(
            {"version": 3, "memes": [], "collections": []}
        )

        assert response == {"ok": True, "local_count": 0}
        assert container.assets.manifest_path.exists()
        assert container.assets.manifest_path.is_relative_to(tmp_path)
        assert server._commands.library is container.library
    finally:
        container.close()


def test_parallel_container_manifest_builds_keep_rows_in_their_roots(tmp_path):
    import ohmymeme.core.manifest as manifest_module

    original_config = manifest_module.get_config
    original_db = manifest_module.get_db
    first = Container(tmp_path / "parallel-first")
    second = Container(tmp_path / "parallel-second")
    try:
        first.db.add_meme("first.png", file_hash="first")
        second.db.add_meme("second.png", file_hash="second")

        def build(container):
            try:
                container.build_manifest()
                return json.loads(
                    container.assets.manifest_path.read_text(encoding="utf-8")
                )
            finally:
                container.db.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            manifests = list(executor.map(build, (first, second)))

        assert manifests[0]["memes"][0]["filename"] == "first.png"
        assert manifests[1]["memes"][0]["filename"] == "second.png"
        assert first.db.count() == 1
        assert second.db.count() == 1
        assert manifest_module.get_config is original_config
        assert manifest_module.get_db is original_db
    finally:
        first.close()
        second.close()


def test_legacy_config_and_manifest_contracts_remain_compatible(monkeypatch, tmp_path):
    import ohmymeme.core.manifest as manifest_module

    root = tmp_path / "legacy"
    config_path = root / "config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        '{"hotkey":"Ctrl+Shift+L",'
        '"s3_secret_key":"%s",'
        '"copy_resize_enabled":false}' % encrypt_data("legacy-secret"),
        encoding="utf-8",
    )

    config = Config(config_path, root / "data")

    assert config.get("hotkey") == "Ctrl+Shift+L"
    assert config.get("s3_secret_key") == "legacy-secret"
    assert config.get("copy_resize_mode") == 0
    assert config.cache_dir == root / "data" / "cache"
    assert config.thumbnail_dir == root / "data" / "thumbnails"
    assert config.db_path == root / "data" / "memes.db"

    manifest_path = root / "data" / "meme-index.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        '{"version":2,"memes":[],"collections":[]}', encoding="utf-8"
    )

    monkeypatch.setattr(manifest_module, "get_config", lambda: config)
    assert load() == {"version": 3, "memes": [], "collections": []}


def test_non_default_container_never_touches_default_singletons(monkeypatch, tmp_path):
    import ohmymeme.core.config as config_module
    import ohmymeme.core.database as database_module

    def fail_default_singleton():
        raise AssertionError("default singleton accessed")

    monkeypatch.setattr(config_module, "get_config", fail_default_singleton)
    monkeypatch.setattr(database_module, "get_config", fail_default_singleton)

    first = Container(tmp_path / "first")
    second = Container(tmp_path / "second")
    try:
        first_service = first.create_import_service(None)
        second_service = second.create_import_service(None)
        first_service._build_manifest = lambda: None
        second_service._build_manifest = lambda: None

        first_result = first_service.import_bytes(
            ImportBytes(_png_bytes(), "first.png")
        )
        second_result = second_service.import_bytes(
            ImportBytes(_png_bytes(), "second.png")
        )

        for path in (
            first.config.config_dir,
            first.config.data_dir,
            first.config.cache_dir,
            first.config.thumbnail_dir,
            first.config.db_path,
            first.assets.manifest_path,
            second.config.config_dir,
            second.config.data_dir,
            second.config.cache_dir,
            second.config.thumbnail_dir,
            second.config.db_path,
            second.assets.manifest_path,
        ):
            assert tmp_path in path.resolve().parents or path.resolve() == tmp_path
        assert first_result.imported_ids
        assert second_result.imported_ids
        assert first.db.count() == 1
        assert second.db.count() == 1
        assert len(list(first.config.cache_dir.iterdir())) == 1
        assert len(list(second.config.cache_dir.iterdir())) == 1
        assert first.db._db_path != second.db._db_path
    finally:
        first.close()
        second.close()


def test_non_default_import_service_uses_container_cache_and_database(
    monkeypatch, tmp_path
):
    import ohmymeme.core.config as config_module

    monkeypatch.setattr(
        config_module,
        "get_config",
        lambda: (_ for _ in ()).throw(AssertionError("default singleton accessed")),
    )
    container = Container(tmp_path / "isolated")
    try:
        result = container.create_import_service(None).import_bytes(
            ImportBytes(b"not-an-image", "legacy.png")
        )

        assert result.imported_ids == ()
        assert result.rejected == 1
        assert container.db.count() == 0
        assert list(container.config.data_dir.rglob("*"))
    finally:
        container.close()


def test_valid_import_writes_supplied_cache_database_and_manifest(tmp_path):
    first = Container(tmp_path / "first")
    second = Container(tmp_path / "second")
    try:
        first_result = first.create_import_service(None).import_bytes(
            ImportBytes(_png_bytes(), "first.png")
        )
        second_result = second.create_import_service(None).import_bytes(
            ImportBytes(_png_bytes(), "second.png")
        )

        assert first_result.imported_ids and second_result.imported_ids
        assert first.db.count() == 1
        assert second.db.count() == 1
        first_manifest = json.loads(
            first.assets.manifest_path.read_text(encoding="utf-8")
        )
        second_manifest = json.loads(
            second.assets.manifest_path.read_text(encoding="utf-8")
        )
        assert first_manifest["version"] == 3
        assert second_manifest["version"] == 3
        assert first_manifest["memes"][0]["filename"] in {
            path.name for path in first.config.cache_dir.iterdir()
        }
        assert second_manifest["memes"][0]["filename"] in {
            path.name for path in second.config.cache_dir.iterdir()
        }
        assert first.assets.manifest_path != second.assets.manifest_path
    finally:
        first.close()
        second.close()


def test_close_is_idempotent_and_continues_after_component_failure(tmp_path):
    events = []

    class BrokenHotkey:
        def unregister(self):
            events.append("hotkey")
            raise RuntimeError("expected")

    class Tray:
        def stop(self):
            events.append("tray")

    class WebUI:
        def stop(self):
            events.append("webui")

    container = Container(tmp_path / "app")
    original_close = container.db.close
    original_save = container.config.save

    def close_db():
        events.append("db")
        original_close()

    def save_config():
        events.append("config")
        original_save()

    container.db.close = close_db
    object.__setattr__(container.config, "save", save_config)
    container.close(BrokenHotkey(), Tray(), lambda: events.append("lan"), WebUI())
    container.close(BrokenHotkey(), Tray(), lambda: events.append("lan"), WebUI())

    assert events == ["hotkey", "tray", "webui", "lan", "db", "config"]
    assert Path(container.config.config_dir / "config.json").exists()


def test_presentation_uses_the_supplied_container_without_global_factories(
    monkeypatch, tmp_path
):
    import ohmymeme.presentation.desktop.window_manager as webui_module

    first = Container(tmp_path / "first")
    second = Container(tmp_path / "second")
    monkeypatch.setattr(
        webui_module,
        "get_config",
        lambda: (_ for _ in ()).throw(AssertionError("global Config factory called")),
        raising=False,
    )
    monkeypatch.setattr(
        webui_module,
        "get_db",
        lambda: (_ for _ in ()).throw(AssertionError("global DB factory called")),
        raising=False,
    )
    try:
        first_ui = first.create_webui()
        second_ui = second.create_webui()

        assert first_ui._cfg is first.config
        assert first_ui._db is first.db
        assert first_ui._api._catalog is first.catalog
        assert first_ui._settings_api._settings is first.settings
        assert second_ui._cfg is second.config
        assert second_ui._db is second.db
        assert second_ui._api._catalog is second.catalog
        assert second_ui._settings_api._settings is second.settings
    finally:
        first.close()
        second.close()
