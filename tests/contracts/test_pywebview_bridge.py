import inspect
import json
import subprocess
from pathlib import Path

import pytest

from ohmymeme.core.schemas.bridge import (
    BRIDGE_CONTRACT,
    MAIN_BRIDGE_CONTRACT,
    BridgeContractError,
)
from ohmymeme.presentation.desktop.window_manager import JsApi, SettingsApi

ROOT = Path(__file__).resolve().parents[2]

MAIN_METHODS = (
    "search_memes",
    "count_memes",
    "get_tags",
    "get_meme_tags",
    "set_meme_tags",
    "get_init_data",
    "get_meme_path",
    "get_meme_paths",
    "start_native_drag",
    "copy_meme",
    "toggle_favorite",
    "is_favorite",
    "rename_meme",
    "delete_meme",
    "delete_memes",
    "get_collections",
    "get_child_collections",
    "search_collections",
    "get_collection_members",
    "add_to_collection",
    "add_to_existing_collection",
    "set_collection_members",
    "set_collection_members_new",
    "reorder_memes",
    "reorder_collections",
    "reorder_collection_members",
    "delete_collection",
    "rename_collection",
    "create_subcollection",
    "record_meme_use",
    "remove_from_recent",
    "clear_recent",
    "remove_from_collection",
    "log",
    "rescan_cache",
    "check_update",
    "start_download",
    "get_download_progress",
    "run_downloaded_installer",
    "download_update",
    "check_connectivity",
    "download_original_image",
    "get_sync_progress",
    "sync_push",
    "sync_pull",
    "run_auto_sync",
    "sync_test",
    "import_memes",
    "import_folder",
    "import_from_clipboard",
    "open_settings",
    "lan_confirm_device",
    "get_settings",
    "save_settings",
    "reset_settings",
    "move_window",
    "start_window_drag",
    "hide_window",
)

SETTINGS_METHODS = (
    "check_connectivity",
    "lan_start",
    "lan_stop",
    "lan_get_status",
    "lan_get_ip",
    "lan_set_allow_secret_config",
    "get_settings",
    "refresh_memes",
    "refresh_tags",
    "refresh_collections",
    "save_settings",
    "reset_settings",
    "move_window",
    "start_window_drag",
    "start_qq_import",
    "get_qq_import_progress",
    "save_qq_zip",
    "open_adb_folder",
    "export_logs",
    "open_adb_help",
    "cancel_qq_import",
    "pick_tg_tdata",
    "start_tg_import",
    "get_tg_import_progress",
    "cancel_tg_import",
    "start_douyin_import",
    "get_douyin_import_progress",
    "cancel_douyin_import",
    "pick_wechat_root",
    "inspect_wechat_environment",
    "list_wechat_stickers",
    "start_wechat_import",
    "get_wechat_import_progress",
    "cancel_wechat_import",
    "qqnt_check_env",
    "qqnt_pick_ini",
    "qqnt_pick_userdata",
    "qqnt_pick_base",
    "get_storage_info",
    "pick_storage_dir",
    "apply_storage_dir",
    "qqnt_default_dir",
    "qqnt_start",
    "qqnt_get_progress",
    "qqnt_cancel",
    "qqnt_open_dir",
    "import_memes",
    "close_settings",
    "get_current_version",
    "check_update",
    "start_download",
    "get_download_progress",
    "run_downloaded_installer",
    "download_update",
    "get_sync_progress",
    "sync_push",
    "sync_pull",
    "sync_test",
    "delete_all_local",
    "delete_all_cloud",
    "get_remote_orphans",
    "check_sync_status",
)


def test_bridge_baseline_freezes_public_method_names_and_defaults():
    assert tuple(name for name in MAIN_METHODS if hasattr(JsApi, name)) == MAIN_METHODS
    assert (
        tuple(name for name in SETTINGS_METHODS if hasattr(SettingsApi, name))
        == SETTINGS_METHODS
    )

    assert inspect.signature(JsApi.search_memes).parameters["keyword"].default == ""
    assert inspect.signature(JsApi.search_memes).parameters["tags"].default is None
    assert (
        inspect.signature(JsApi.search_memes).parameters["collection_id"].default
        is None
    )
    assert inspect.signature(JsApi.search_memes).parameters["offset"].default == 0
    assert inspect.signature(JsApi.search_memes).parameters["limit"].default == 200
    assert (
        inspect.signature(JsApi.import_folder).parameters["make_collection"].default
        is True
    )
    assert inspect.signature(JsApi.check_update).parameters["debug"].default is False
    assert inspect.signature(JsApi.check_update).parameters["force"].default is False
    assert inspect.signature(SettingsApi.lan_start).parameters["port"].default is None
    assert inspect.signature(SettingsApi.lan_start).parameters["secret"].default is None
    assert (
        inspect.signature(SettingsApi.start_tg_import).parameters["tdata_path"].default
        is None
    )
    assert (
        inspect.signature(SettingsApi.start_tg_import).parameters["passcode"].default
        == ""
    )
    assert (
        inspect.signature(SettingsApi.start_tg_import)
        .parameters["convert_webm"]
        .default
        is True
    )
    assert (
        inspect.signature(SettingsApi.qqnt_start).parameters["image_only"].default
        is False
    )
    assert (
        inspect.signature(SettingsApi.qqnt_start).parameters["overwrite"].default
        is False
    )
    assert (
        inspect.signature(SettingsApi.sync_push).parameters["delete_remote"].default
        is None
    )
    assert (
        inspect.signature(SettingsApi.sync_pull).parameters["remove_local"].default
        is None
    )
    assert (
        inspect.signature(SettingsApi.get_remote_orphans).parameters["delete"].default
        is False
    )


def test_bridge_schema_and_generated_files_are_present_and_deterministic():
    # 单源 DTO：只有主窗口 generated/bridge.ts 由生成器产出
    schema_path = ROOT / "schemas" / "bridge" / "bridge.schema.json"
    main_dto = (
        ROOT / "src/ohmymeme/presentation/frontend/main/shared/generated/bridge.ts"
    )
    settings_dto = (
        ROOT / "src/ohmymeme/presentation/frontend/settings/shared/generated/bridge.ts"
    )

    assert schema_path.is_file()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert main_dto.is_file()
    assert not settings_dto.is_file()
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert b"\r\n" not in main_dto.read_bytes()
    assert f"{main_dto.relative_to(ROOT).as_posix()} text eol=lf" in attributes
    assert (
        f"{settings_dto.relative_to(ROOT).as_posix()} text eol=lf" not in attributes
    )
    result = subprocess.run(
        ["mise", "run", "generate-schemas", "--", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_bridge_runtime_rejects_malformed_payload_without_calling_inner_service():
    from ohmymeme.presentation.desktop.api.facades import MainBridgeFacade

    calls = []

    class Inner:
        def __init__(self):
            self.result = ["tag"]

        def get_tags(self):
            calls.append("get_tags")
            return self.result

    inner = Inner()
    facade = MainBridgeFacade.__new__(MainBridgeFacade)
    facade._legacy = inner
    assert facade.get_tags() == ["tag"]
    inner.result = {"unexpected": True}
    assert facade.get_tags() == []
    assert calls == ["get_tags", "get_tags"]

    class TagInner:
        def get_meme_tags(self, _meme_id):
            raise AssertionError("malformed input crossed bridge boundary")

    facade._legacy = TagInner()
    assert facade.get_meme_tags(True) == []


def test_main_import_memes_projects_the_historical_result_object():
    # Given: the main facade and an established successful import payload
    from ohmymeme.presentation.desktop.api.facades import MainBridgeFacade

    class Inner:
        def import_memes(self):
            return {"ok": True, "imported": 1, "rejected": 0}

    facade = MainBridgeFacade.__new__(MainBridgeFacade)
    facade._legacy = Inner()
    facade._contract = MAIN_BRIDGE_CONTRACT

    # When: the main bridge dispatches the import action
    result = facade.import_memes()

    # Then: callers receive the legacy result object rather than a boolean sentinel
    assert result == {"ok": True, "imported": 1, "rejected": 0}


def test_bridge_not_ready_and_missing_method_fail_closed():
    from ohmymeme.presentation.desktop.api.pywebview_adapter import PyWebViewAdapter

    adapter = PyWebViewAdapter(None)
    assert adapter.main_window() is None
    assert adapter.settings_window() is None
    assert adapter.evaluate_main("focusSearch()") is False


def test_bridge_window_adapter_targets_roles_not_global_window_order():
    from ohmymeme.presentation.desktop.api.pywebview_adapter import PyWebViewAdapter

    class DialogWindow:
        def __init__(self, value):
            self.value = value
            self.x = 0
            self.y = 0

        def create_file_dialog(self, *_args, **_kwargs):
            return [self.value]

        def evaluate_js(self, _script):
            return None

        def move(self, x, y):
            self.x = x
            self.y = y

    class Dialogs:
        OPEN = "open"
        SAVE = "save"
        FOLDER = "folder"

    class Runtime:
        FileDialog = Dialogs

        def __init__(self, windows):
            self.windows = windows

    main = DialogWindow("main")
    settings = DialogWindow("settings")
    host = type("Host", (), {"_window": main, "_settings_window": settings})()
    adapter = PyWebViewAdapter(Runtime([settings, main]), host)

    assert adapter.file_dialog("settings", "folder") == ["settings"]
    assert adapter.file_dialog("main", "folder") == ["main"]
    assert adapter.move("settings", 3, 4) is True
    assert (settings.x, settings.y) == (3, 4)


def test_bridge_contract_errors_are_structured_and_fail_closed():
    from ohmymeme.core.schemas.bridge import BRIDGE_CONTRACT, BridgeContractError

    with pytest.raises(BridgeContractError) as error:
        BRIDGE_CONTRACT.validate_input("missing_method", ())
    assert error.value.method == "missing_method"
    assert error.value.phase == "input"


def test_facades_do_not_access_raw_pywebview_runtime():
    facade_root = ROOT / "src/ohmymeme/presentation/desktop/api"
    for path in (facade_root / "main_facade.py", facade_root / "settings_facade.py"):
        assert "webview" not in path.read_text(encoding="utf-8")


def test_save_settings_parses_a_closed_pydantic_patch_before_legacy_projection():
    from ohmymeme.core.schemas.bridge import SettingsPatch

    checked = BRIDGE_CONTRACT.validate_input(
        "save_settings", ({"hotkey": "Ctrl+Shift+X"},)
    )
    assert isinstance(checked[0], SettingsPatch)
    with pytest.raises(BridgeContractError):
        BRIDGE_CONTRACT.validate_input("save_settings", ({"unknown": True},))


def test_method_specific_results_reject_malformed_search_and_init_payloads():
    with pytest.raises(BridgeContractError):
        BRIDGE_CONTRACT.validate_output("search_memes", [{"unexpected": True}])
    with pytest.raises(BridgeContractError):
        BRIDGE_CONTRACT.validate_output("get_init_data", {"memes": []})


def test_method_specific_boolean_and_void_results_preserve_legacy_semantics():
    assert BRIDGE_CONTRACT.validate_output("start_window_drag", True) is True
    assert BRIDGE_CONTRACT.validate_output("refresh_memes", None) is None


def test_facade_maps_expected_runtime_error_to_legacy_sync_envelope():
    from ohmymeme.presentation.desktop.api.main_facade import MainBridgeFacade

    class Inner:
        def sync_push(self):
            raise RuntimeError("transport down")

    facade = MainBridgeFacade.__new__(MainBridgeFacade)
    facade._legacy = Inner()
    assert facade.sync_push() == {
        "ok": False,
        "error": "sync failed",
        "failed_files": [],
    }


def test_facade_projects_typed_settings_patch_and_rejects_unknown_fields():
    from ohmymeme.presentation.desktop.api.settings_facade import SettingsBridgeFacade

    calls = []

    class Inner:
        def save_settings(self, settings):
            calls.append(settings)
            return None

    facade = SettingsBridgeFacade.__new__(SettingsBridgeFacade)
    facade._legacy = Inner()
    assert facade.save_settings({"hotkey": "Ctrl+Shift+X"}) is None
    assert calls == [{"hotkey": "Ctrl+Shift+X"}]
    assert facade.save_settings({"unknown": True}) is None
    assert calls == [{"hotkey": "Ctrl+Shift+X"}]
    assert facade.save_settings(None) is None


def test_settings_decoder_source_is_owned_and_declares_fail_closed_decoder():
    decoder = (
        ROOT / "src/ohmymeme/presentation/frontend/settings-vue/shared/bridge.ts"
    )
    source = decoder.read_text(encoding="utf-8")
    assert "decodeBridgeResult" in source
    assert "BridgeDecodeError" in source
