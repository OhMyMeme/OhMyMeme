import ast
from pathlib import Path
from types import SimpleNamespace

from ohmymeme.presentation.desktop.api.handlers import create_handlers
from ohmymeme.presentation.desktop.window_manager import JsApi, SettingsApi


class FakeConfig:
    cache_dir = Path("cache")

    def get(self, key, default=None):
        return default


class FakeWebUI:
    _cfg = FakeConfig()
    _db = None
    _update_debug = False

    def __init__(self):
        self.refreshes = []
        self.hotkeys = []
        self._container = SimpleNamespace(library=None)

    def _on_hotkey_change(self, hotkey):
        self.hotkeys.append(hotkey)


class FakeCatalog:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def import_paths(self, paths, names=None):
        self.calls.append((paths, names))
        return self.result

    def get_meme_path(self, meme_id, *_args):
        self.calls.append(("meme_path", meme_id))
        return (
            self.result.get("path", "")
            if isinstance(self.result, dict)
            else self.result
        )

    def import_clipboard_paths(self, paths, names=None):
        self.calls.append(("clipboard", paths, names))
        if self.error:
            raise self.error
        return {
            "ids": list(self.result.imported_ids),
            "rejected": self.result.rejected,
            "name": "命名图片",
        }

    def import_folder(self, paths, names, collection_name, make_collection=True):
        self.calls.append((paths, names, collection_name, make_collection))
        return self.result

    def meme_path(self, meme_id):
        self.calls.append(("meme_path", meme_id))
        return self.result

    def meme_paths(self, meme_ids):
        self.calls.append(("meme_paths", meme_ids))
        return self.result

    def copy_source(self, meme_id):
        self.calls.append(("copy_source", meme_id))
        return self.result

    def get_collection_members(self, collection_id):
        self.calls.append(("get_collection_members", collection_id))
        return self.result

    def get_child_collections(self, parent_id):
        self.calls.append(("get_child_collections", parent_id))
        return self.result

    def collection_depth(self, parent_id):
        self.calls.append(("collection_depth", parent_id))
        return self.result


class FakeSettings:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def save_settings(self, settings):
        self.calls.append(settings)
        return self.result

    def get_settings(self):
        self.calls.append(("get_settings",))
        return {"hotkey": "Ctrl+Alt+N"}

    def reset_settings(self):
        self.calls.append(("reset_settings",))
        return {"hotkey": "Ctrl+Alt+N"}


class FakeLibrary:
    def __init__(self, result=None, error=None):
        self.result = result or SimpleNamespace(imported_ids=(11,), rejected=0)
        self.error = error
        self.calls = []

    def import_paths(self, paths, names=None):
        self.calls.append((paths, names))
        if self.error:
            raise self.error
        return self.result

    def import_clipboard_paths(self, paths, names=None):
        self.calls.append(("clipboard", paths, names))
        if self.error:
            raise self.error
        return {
            "ids": list(self.result.imported_ids),
            "rejected": self.result.rejected,
            "name": "命名图片",
        }

    def storage_info(self):
        self.calls.append(("storage_info",))
        if self.error:
            raise self.error
        return {
            "cache_dir": "cache",
            "data_dir": "data",
            "custom": False,
            "file_count": 2,
            "total_size": 12,
        }

    def rescan_cache(self, cache_dir):
        self.calls.append(("rescan_cache", cache_dir))
        if self.error:
            raise self.error
        return True

    def apply_storage_dir(self, path, move_files=False):
        self.calls.append(("apply_storage_dir", path, move_files))
        if self.error:
            raise self.error
        return self.result

    def toggle_favorite(self, meme_id):
        self.calls.append(("toggle_favorite", meme_id))
        return self.result

    def is_favorite(self, meme_id):
        self.calls.append(("is_favorite", meme_id))
        return self.result

    def record_use(self, meme_id):
        self.calls.append(("record_use", meme_id))
        return self.result

    def remove_from_recent(self, meme_id):
        self.calls.append(("remove_from_recent", meme_id))
        return self.result

    def clear_recent(self):
        self.calls.append(("clear_recent",))
        return self.result

    def find_meme_file(self, filename):
        self.calls.append(("find_meme_file", filename))
        return self.result


def test_js_business_paths_delegate_without_db_access():
    # Given: application services and a DB that the bridge must not touch.
    webui = FakeWebUI()
    webui._window = None
    webui._db = SimpleNamespace(
        get_by_id=lambda *_: (_ for _ in ()).throw(AssertionError("DB bypass")),
        is_favorite=lambda *_: (_ for _ in ()).throw(AssertionError("DB bypass")),
        record_use=lambda *_: (_ for _ in ()).throw(AssertionError("DB bypass")),
    )
    catalog = FakeCatalog({"path": "meme.png", "filename": "meme.png"})
    library = FakeLibrary(True)
    api = JsApi(webui, catalog, FakeSettings(None), library)

    # When: bridge business entry points are used.
    assert api.get_meme_path(1) == "meme.png"
    assert api.toggle_favorite(1) is True
    assert api.is_favorite(1) is True
    assert api.record_meme_use(1) is True
    assert api.remove_from_recent(1) is True
    assert api.clear_recent() is True

    # Then: all decisions were delegated to application services.
    assert ("meme_path", 1) in catalog.calls
    assert ("toggle_favorite", 1) in library.calls


def test_bridge_handlers_share_container_owned_dependencies():
    # Given: one Container-owned dependency graph exposed through both facades.
    webui = FakeWebUI()
    library = FakeLibrary(True)
    catalog = FakeCatalog({})
    webui._container.catalog = catalog
    webui._container.settings = object()
    webui._container.job_manager = object()

    # When: domain handlers are created for the desktop bridge.
    handlers = create_handlers(webui, catalog, webui._container.settings, library)

    # Then: every handler retains the same application-owned resources.
    assert handlers["meme"].catalog is catalog
    assert handlers["meme"].library is library
    assert handlers["import"].library is library
    assert handlers["import"].job_manager is webui._container.job_manager
    assert handlers["sync"].container is webui._container
    assert handlers["window_settings"].webui is webui


def test_qqnt_output_is_user_owned_and_projected_through_library(monkeypatch, tmp_path):
    # Given: QQNT writes a valid image into the user-selected output directory.
    import threading

    from ohmymeme.presentation.desktop import window_manager

    output_dir = tmp_path / "qqnt-output"
    output_dir.mkdir()
    image_path = output_dir / "sticker.png"
    image_path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0dIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff"
        b"\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    library = FakeLibrary(SimpleNamespace(imported_ids=(11,), rejected=0))
    imported = threading.Event()
    original_import_paths = library.import_paths
    webui = FakeWebUI()
    webui._container.library = library
    webui._container.job_manager = None
    settings = SettingsApi(webui, FakeSettings(None))

    def extract(_qq_number, destination, **_kwargs):
        Path(destination).mkdir(parents=True, exist_ok=True)
        image_path.touch()
        return {"output_dir": destination, "copied": 1}

    def import_paths(paths, names=None):
        result = original_import_paths(paths, names)
        imported.set()
        return result

    monkeypatch.setattr(window_manager.qqnt, "extract_qq_emojis", extract)
    webui._container.library.import_paths = import_paths

    # When: the bridge starts QQNT extraction and the worker completes.
    assert settings.qqnt_start("123", str(output_dir))["ok"] is True
    assert imported.wait(1)
    window_manager._QQNT_JOB_MANAGER = None
    window_manager._QQNT_JOB_ID = None
    window_manager._QQNT_JOB_SNAPSHOT = None

    # Then: the user output remains, while the application library owns projection.
    assert image_path.exists()
    assert library.calls == [([str(image_path)], None)]


def test_qqnt_cancel_during_projection_rolls_back_library_import(monkeypatch, tmp_path):
    # Given: projection requests cancellation after the application import commits.
    from ohmymeme.presentation.desktop import window_manager

    output_dir = tmp_path / "qqnt-output"
    output_dir.mkdir()
    image_path = output_dir / "sticker.png"
    image_path.write_bytes(b"image")
    app_state = {"db": 0, "cache": False, "manifest": False}
    finished = __import__("threading").Event()
    webui = FakeWebUI()
    webui._container.job_manager = None

    class Library:
        def import_paths(self, _paths, _cancellation_event=None):
            app_state.update(db=1, cache=True, manifest=True)
            window_manager.cancel_qqnt_extract()
            finished.set()
            return {"ids": [42], "rejected": 0}

        def delete_memes(self, ids):
            assert ids == [42]
            app_state.update(db=0, cache=False, manifest=False)

    webui._container.library = Library()
    settings = SettingsApi(webui, FakeSettings(None))

    def extract(_qq_number, destination, **_kwargs):
        Path(destination).mkdir(parents=True, exist_ok=True)
        image_path.touch()
        return {"output_dir": destination, "copied": 1}

    monkeypatch.setattr(window_manager.qqnt, "extract_qq_emojis", extract)

    # When: extraction projects and cancellation is raised during that handoff.
    assert settings.qqnt_start("123", str(output_dir))["ok"] is True
    assert finished.wait(1)

    # Then: the committed projection is compensated while user output remains.
    assert app_state == {"db": 0, "cache": False, "manifest": False}
    assert image_path.exists()


def test_js_import_memes_delegates_import_and_preserves_failure_shape(monkeypatch):
    # Given: the dialog returns files and the application import fails.
    webui = FakeWebUI()
    catalog = FakeCatalog({"imported_ids": (), "rejected": 1})
    api = JsApi(webui, catalog, FakeSettings(None))
    monkeypatch.setattr(
        "ohmymeme.presentation.desktop.window_manager.webview",
        type(
            "WebView",
            (),
            {
                "windows": [
                    type(
                        "Window",
                        (),
                        {"create_file_dialog": lambda *_args, **_kwargs: ["a.png"]},
                    )()
                ],
                "FileDialog": type("FileDialog", (), {"OPEN": "open"}),
            },
        ),
    )

    # When: the bridge handles the import dialog.
    result = api.import_memes()

    # Then: the adapter returns the historical success envelope without refreshing.
    assert result == {"ok": True, "imported": 0, "rejected": 1}
    assert catalog.calls == [(["a.png"], None)]
    assert webui.refreshes == []


def test_settings_save_does_not_refresh_after_application_failure():
    # Given: the settings use case rejects the write.
    webui = FakeWebUI()
    settings = FakeSettings(None)
    api = SettingsApi(webui, settings)

    # When: the bridge forwards the settings payload.
    result = api.save_settings({"hotkey": "Ctrl+Alt+X"})

    # Then: the historical void return and UI side effect contract remain intact.
    assert result is None
    assert settings.calls == [{"hotkey": "Ctrl+Alt+X"}]
    assert webui.hotkeys == []


def test_settings_import_memes_uses_library_and_preserves_empty_failure(monkeypatch):
    # Given: a selected file and a library that rejects it.
    webui = FakeWebUI()
    library = FakeLibrary(SimpleNamespace(imported_ids=(), rejected=1))
    webui._container.library = library
    api = SettingsApi(webui, FakeSettings(None))
    monkeypatch.setattr(
        "ohmymeme.presentation.desktop.window_manager.webview",
        SimpleNamespace(
            windows=[
                SimpleNamespace(
                    create_file_dialog=lambda *_args, **_kwargs: ["bad.png"]
                )
            ],
            FileDialog=SimpleNamespace(OPEN="open"),
        ),
    )
    webui._do_import = lambda *_args: (_ for _ in ()).throw(
        AssertionError("legacy import bypass")
    )

    # When: the settings import bridge handles the dialog.
    result = api.import_memes()

    # Then: the canonical library owns the operation and the envelope remains.
    assert result == {"ok": True, "imported": 0, "rejected": 1}
    assert library.calls == [(["bad.png"], None)]


def test_download_original_local_path_uses_library_and_preserves_failure(tmp_path):
    # Given: a local image path and an application failure.
    path = tmp_path / "image.png"
    path.write_bytes(b"not decoded here")
    webui = FakeWebUI()
    library = FakeLibrary(error=RuntimeError("import failed"))
    webui._container.library = library
    api = JsApi(webui, FakeCatalog(None), FakeSettings(None), library)
    webui._do_import = lambda *_args: (_ for _ in ()).throw(
        AssertionError("legacy import bypass")
    )

    # When: the original-image bridge receives a local path.
    result = api.download_original_image(str(path))

    # Then: the historical generic failure envelope is returned and no refresh occurs.
    assert result == {"ok": False, "error": "import failed"}
    assert library.calls == [([str(path)], None)]
    assert webui.refreshes == []


def test_clipboard_import_uses_library_and_preserves_empty_failure(
    monkeypatch, tmp_path
):
    # Given: clipboard contains a file path and the canonical library rejects it.
    webui = FakeWebUI()
    library = FakeLibrary(SimpleNamespace(imported_ids=(), rejected=1))
    webui._container.library = library
    api = JsApi(webui, FakeCatalog(None), FakeSettings(None), library)
    clip_path = tmp_path / "clip.png"
    clip_path.write_bytes(b"invalid")
    monkeypatch.setattr("PIL.ImageGrab.grabclipboard", lambda: [str(clip_path)])
    webui._do_import = lambda *_args: (_ for _ in ()).throw(
        AssertionError("legacy import bypass")
    )

    # When: the clipboard bridge handles the path list.
    result = api.import_from_clipboard()

    # Then: the canonical library receives the paths and no stale refresh occurs.
    assert result == {"ok": True, "id": 0, "name": "未命名", "rejected": 1}
    assert library.calls == [("clipboard", [str(clip_path)], None)]
    assert webui.refreshes == []


def test_webui_scan_cache_delegates_to_library_service(monkeypatch):
    # Given: a WebUI with a canonical library service and no legacy scan allowed.
    from ohmymeme.presentation.desktop.window_manager import WebUI

    ui = object.__new__(WebUI)
    ui._cfg = FakeConfig()
    ui._container = SimpleNamespace(library=FakeLibrary())
    ui._db = SimpleNamespace(
        get_by_filename=lambda _name: (_ for _ in ()).throw(
            AssertionError("scan must not query DB in presentation")
        )
    )

    # When: the compatibility scan entry point runs.
    result = ui.scan_cache()

    # Then: the application boundary owns scanning and the void result remains.
    assert result is None
    assert ui._container.library.calls[0][0] == "rescan_cache"


def test_storage_application_delegation_preserves_failure_without_refresh():
    # Given: storage application fails before any UI refresh.
    webui = FakeWebUI()
    library = FakeLibrary(error=RuntimeError("storage failed"))
    webui._container.library = library
    api = SettingsApi(webui, FakeSettings(None))
    api._storage = library

    # When: the settings bridge applies a new storage directory.
    result = api.apply_storage_dir("C:/new-cache", move_files=True)

    # Then: the failure envelope is preserved and no refresh occurs.
    assert result == {"ok": False, "error": "storage failed"}
    assert webui.refreshes == []


def test_storage_info_delegates_cache_statistics_without_traversal():
    # Given: a service with stats and a cache path the bridge must not traverse.
    webui = FakeWebUI()
    library = FakeLibrary()
    webui._container.library = library
    api = SettingsApi(webui, FakeSettings(None))
    api._cfg.cache_dir = Path("missing-cache")

    # When: the settings bridge requests storage information.
    result = api.get_storage_info()

    # Then: the service response is preserved and the bridge only delegates.
    assert result["file_count"] == 2
    assert result["total_size"] == 12
    assert library.calls == [("storage_info",)]


class _RecordingHandler:
    def __init__(self, values=None):
        self.calls = []
        self.values = values or {}

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self.values.get(name, {"ok": True})

        return call


def test_js_facade_routes_named_sync_import_update_and_window_abi():
    # Given: handlers return typed representative bridge values and record arguments.
    webui = FakeWebUI()
    webui.open_settings = lambda: True
    webui.hide = lambda: None
    webui._schedule_quit = lambda: None
    api = JsApi(webui, FakeCatalog({}), FakeSettings(None))
    handlers = {
        name: _RecordingHandler()
        for name in ("meme", "import", "sync", "update", "window_settings")
    }
    handlers["meme"].values.update({"get_init_data": {"startup_bg_color": "#000000"}})
    handlers["import"].values.update({"import_memes": True})
    handlers["update"].values.update({"download_progress": {"status": "idle"}})
    handlers["update"].values.update({"start_download": True})
    handlers["sync"].values.update({"progress": {"progress": 0}})
    handlers["sync"].values.update({"test_connection": "连接成功"})
    api._handlers = handlers

    # When: every dynamic caller-facing operation is invoked through the façade.
    handlers["meme"].values["search_memes"] = []
    assert isinstance(api.search_memes("q", ["tag"], 7, 2, 3), list)
    assert isinstance(api.check_update(False, True), dict)
    assert api.start_download("https://example.test/a") is True
    assert isinstance(api.get_download_progress(), dict)
    assert isinstance(api.get_sync_progress(), dict)
    assert isinstance(api.sync_push(), dict)
    assert isinstance(api.sync_pull(), dict)
    assert isinstance(api.run_auto_sync(), dict)
    assert api.sync_test() == "连接成功"
    assert api.import_memes() is True
    assert isinstance(api.import_folder(False), dict)
    assert isinstance(api.import_from_clipboard(), dict)
    assert isinstance(api.get_settings(), dict)
    assert api.save_settings({"hotkey": "Ctrl+Alt+X"}) == {"ok": True}
    assert isinstance(api.reset_settings(), dict)
    assert api.move_window(4, -3) == {"ok": True}
    assert api.start_window_drag(1, 20, 30) is False
    assert api.hide_window() is None

    # Then: names and exact positional/default ABI remain stable at each domain seam.
    assert handlers["meme"].calls[0] == ("search_memes", ("q", ["tag"], 7, 2, 3), {})
    assert ("check_update", (False, True), {}) in handlers["update"].calls
    assert ("start_download", ("https://example.test/a",), {}) in handlers[
        "update"
    ].calls
    assert ("sync_push", (), {}) not in handlers["sync"].calls
    assert ("push", (), {}) in handlers["sync"].calls
    assert ("pull", (), {}) in handlers["sync"].calls
    assert ("auto_sync", (), {}) in handlers["sync"].calls
    assert ("test_connection", (), {}) in handlers["sync"].calls
    assert ("import_folder", (api._catalog, False), {}) in handlers["import"].calls
    assert ("save_settings", ({"hotkey": "Ctrl+Alt+X"},), {}) in handlers[
        "window_settings"
    ].calls
    assert ("move_main_window", (4, -3), {}) in handlers["window_settings"].calls


def test_main_facade_preserves_sync_import_update_and_window_failure_envelopes(
    monkeypatch,
):
    # Given: production handlers are wired to deterministic failing boundaries.
    webui = FakeWebUI()
    webui._window = None
    webui._schedule_quit = lambda: None
    api = JsApi(webui, FakeCatalog({}), FakeSettings(None), FakeLibrary())
    api._handlers["sync"].service = lambda: (_ for _ in ()).throw(
        RuntimeError("sync failed")
    )
    monkeypatch.setattr(
        "ohmymeme.presentation.desktop.window_manager.webview",
        SimpleNamespace(
            windows=[
                SimpleNamespace(
                    create_file_dialog=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                        RuntimeError("dialog failed")
                    )
                )
            ],
            FileDialog=SimpleNamespace(OPEN="open"),
        ),
    )
    from ohmymeme.services import updates

    monkeypatch.setattr(updates, "download_release", lambda _url: None)

    # When: representative main-window operations cross their production handlers.
    sync_result = api.sync_push()
    import_result = api.import_memes()
    update_result = api.download_update("https://example.test/a")
    move_result = api.move_window(1, 2)

    # Then: each failure/void shape remains the public ABI.
    assert sync_result == {"ok": False, "error": "sync failed", "failed_files": []}
    assert import_result == {"ok": False}
    assert update_result == {"ok": False, "error": "download failed"}
    assert move_result is None


def test_settings_facade_preserves_failure_envelopes_and_primitive_types():
    # Given: production settings handlers return their documented failure shapes.
    webui = FakeWebUI()
    webui._container.library = FakeLibrary()
    api = SettingsApi(webui, FakeSettings(None))
    api._handlers["window_settings"].apply_storage_dir = lambda *_args: {
        "ok": False,
        "error": "storage failed",
    }
    api._handlers["window_settings"].start_lan = lambda *_args: {
        "ok": False,
        "status": {"running": False},
    }
    api._handlers["update"].start_download = lambda _url: False

    # When: settings-window failure and update operations are invoked.
    storage_result = api.apply_storage_dir("C:/cache", False)
    lan_result = api.lan_start(17852, "secret")
    download_result = api.start_download("https://example.test/a")

    # Then: error fields and primitive return types remain exact.
    assert storage_result == {"ok": False, "error": "storage failed"}
    assert lan_result == {"ok": False, "status": {"running": False}}
    assert download_result is False


def test_settings_facade_routes_import_sync_update_and_refresh_abi(monkeypatch):
    # Given: a settings façade with deterministic handlers and a JS refresh target.
    webui = FakeWebUI()
    webui._container.library = FakeLibrary()
    webui._container.job_manager = None
    api = SettingsApi(webui, FakeSettings(None))
    handlers = {
        name: _RecordingHandler()
        for name in ("import", "sync", "update", "window_settings")
    }
    api._handlers = handlers
    evaluated = []
    monkeypatch.setattr(
        "ohmymeme.presentation.desktop.window_manager.webview",
        SimpleNamespace(windows=[SimpleNamespace(evaluate_js=evaluated.append)]),
    )

    # When: settings-window dynamic methods and refresh callbacks are used.
    assert isinstance(api.get_settings(), dict)
    assert api.save_settings({"sync_auto_sync": True}) is None
    assert isinstance(api.reset_settings(), dict)
    assert isinstance(api.lan_start(), dict)
    assert isinstance(api.lan_stop(), dict)
    assert isinstance(api.lan_get_status(), dict)
    assert isinstance(api.lan_get_ip(), dict)
    assert isinstance(api.lan_set_allow_secret_config(True), dict)
    assert isinstance(api.get_storage_info(), dict)
    assert isinstance(api.pick_storage_dir(), dict)
    assert isinstance(api.apply_storage_dir("C:/cache", True), dict)
    assert api.start_tg_import() == {"ok": True}
    assert isinstance(api.get_tg_import_progress(), dict)
    assert api.start_douyin_import("cookie") == {"ok": True}
    assert isinstance(api.get_douyin_import_progress(), dict)
    assert api.start_wechat_import("C:/wechat", False, "acct") == {"ok": True}
    assert isinstance(api.get_wechat_import_progress(), dict)
    assert api.qqnt_start("123", "C:/out", True, True) == {"ok": True}
    assert isinstance(api.qqnt_get_progress(), dict)
    assert isinstance(api.start_download("https://example.test/a"), dict)
    assert isinstance(api.get_download_progress(), dict)
    assert isinstance(api.check_update(False, True), dict)
    assert api.refresh_memes() == {"ok": True}
    assert api.refresh_tags() == {"ok": True}
    assert api.refresh_collections() == {"ok": True}

    # Then: argument order/defaults and refresh expressions are observable contracts.
    assert ("start_lan", (None, None), {}) in handlers["window_settings"].calls
    assert ("apply_storage_dir", ("C:/cache", True), {}) in handlers[
        "window_settings"
    ].calls
    assert ("start_tg_import", (None, "", True), {}) in handlers[
        "window_settings"
    ].calls
    assert ("start_douyin_import", ("cookie",), {}) in handlers["window_settings"].calls
    assert ("start_wechat_import", ("C:/wechat", False, "acct"), {}) in handlers[
        "window_settings"
    ].calls
    assert ("qqnt_start", ("123", "C:/out", True, True), {}) in handlers[
        "window_settings"
    ].calls
    assert evaluated == ["refreshMemes();", "refreshTags();", "refreshCollections();"]


def test_desktop_facades_leave_domain_bodies_in_named_handlers():
    # Given: the production desktop bridge source and its named handler module.
    root = Path(__file__).parents[2]
    facade_tree = ast.parse(
        (root / "src/ohmymeme/presentation/desktop/window_manager.py").read_text(
            encoding="utf-8"
        )
    )
    handler_tree = ast.parse(
        (root / "src/ohmymeme/presentation/desktop/api/handlers.py").read_text(
            encoding="utf-8"
        )
    )

    # When: the façade classes and handler declarations are inspected structurally.
    facade_classes = {
        node.name: node
        for node in facade_tree.body
        if isinstance(node, ast.ClassDef) and node.name in {"JsApi", "SettingsApi"}
    }
    handler_classes = {
        node.name: node
        for node in handler_tree.body
        if isinstance(node, ast.ClassDef)
        and node.name
        in {
            "MemeHandler",
            "ImportHandler",
            "SyncHandler",
            "UpdateHandler",
            "WindowSettingsHandler",
        }
    }
    facade_code = ast.unparse(
        ast.Module(body=list(facade_classes.values()), type_ignores=[])
    )

    # Then: façades contain routing/wiring only, while named handlers contain bodies.
    assert "create_file_dialog" not in facade_code
    assert "extract_qq_emojis" not in facade_code
    assert "qqnt_handler._STATE" in ast.unparse(facade_tree)
    assert set(handler_classes) == {
        "MemeHandler",
        "ImportHandler",
        "SyncHandler",
        "UpdateHandler",
        "WindowSettingsHandler",
    }
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "start_tg_import"
        for node in ast.walk(handler_tree)
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_file_dialog"
        for node in ast.walk(
            ast.Module(body=list(handler_classes.values()), type_ignores=[])
        )
    )
