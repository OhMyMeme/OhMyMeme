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
