import importlib
import json
import subprocess
import sys
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from plugin_fixtures import install_official

from ohmymeme.core.plugins.manifest import (
    ENTRY_POINT_GROUP,
    canonical_descriptor,
    validate_manifest,
)
from ohmymeme.core.plugins.registry import PluginRegistry
from ohmymeme.presentation.desktop import import_workers
from ohmymeme.presentation.desktop import window_manager as desktop


@pytest.fixture
def shell(monkeypatch):
    # Keep native dialogs, provider workers and persistence deterministic and offline.
    config = Mock()
    config.get.side_effect = lambda key, default=None: default
    config.cache_dir = "host-cache"
    config.data_dir = Path("test-host-data")
    qqnt = importlib.import_module("ohmymeme_plugin_qqnt")
    telegram = importlib.import_module("ohmymeme_plugin_telegram")
    webui = SimpleNamespace(
        _cfg=config,
        _library=Mock(),
        _container=SimpleNamespace(
            sync=Mock(),
            lan=Mock(),
            create_import_service=Mock(),
            operations=Mock(),
            create_import_sink=Mock(),
            db=SimpleNamespace(close=Mock()),
            plugins=PluginRegistry(
                (
                    canonical_descriptor("source.qqnt"),
                    canonical_descriptor("source.telegram"),
                ),
                {
                    "source.qqnt": qqnt.create_plugin,
                    "source.telegram": telegram.create_plugin,
                },
                (),
            ),
        ),
        _do_import=Mock(),
        _decode_stego=Mock(),
    )
    dialog = Mock()
    monkeypatch.setattr(desktop, "_webview_adapter", lambda _webui: dialog)
    return desktop.SettingsApi(webui, None), webui, dialog


@pytest.mark.parametrize(
    "provider,method,args,parameters,secrets",
    [
        (
            "source.telegram",
            "start_tg_import",
            (None, "", True),
            {"tdata_path": None, "convert_webm": True},
            {"passcode": ""},
        ),
        (
            "source.douyin",
            "start_douyin_import",
            ("fixture-cookie",),
            {},
            {"cookie": "fixture-cookie"},
        ),
        (
            "source.wechat",
            "start_wechat_import",
            (None, True, None),
            {"user_root": None, "download": True, "account_path": None},
            None,
        ),
    ],
)
def test_characterization_start_success_and_busy(
    shell, monkeypatch, provider, method, args, parameters, secrets
):
    # Preserve envelopes while testing the actual host worker/context seam.
    api, webui, _ = shell
    worker = Mock()
    worker.start.return_value = True
    lookup = Mock(return_value=worker)
    monkeypatch.setattr(import_workers, "get_import_worker", lookup)
    assert getattr(api, method)(*args) == {"ok": True}
    assert lookup.call_args.args[0]._webui is webui
    assert lookup.call_args.args[1] == provider
    worker.start.assert_called_once_with(
        parameters, *(() if secrets is None else (secrets,))
    )
    webui._do_import.assert_not_called()
    worker.start.return_value = False
    assert getattr(api, method)(*args) == {"ok": False, "error": "已有导入任务正在进行"}


def test_characterization_qqnt_start(shell, monkeypatch):
    # QQNT keeps its output choice, defaults and host-owned import callback.
    api, webui, _ = shell
    worker = Mock()
    worker.start_qqnt.return_value = True
    monkeypatch.setattr(import_workers, "get_import_worker", Mock(return_value=worker))
    assert api.qqnt_start("10001", "chosen-output") == {"ok": True}
    worker.start_qqnt.assert_called_once_with(
        "10001", "chosen-output", False, False, webui._cfg
    )
    worker.start_qqnt.return_value = False
    assert api.qqnt_start("10001", "chosen-output") == {"ok": False}


@pytest.mark.parametrize(
    "provider,progress_method,cancel_method",
    [
        (
            "source.qqnt",
            "qqnt_get_progress",
            "qqnt_cancel",
        ),
        (
            "source.telegram",
            "get_tg_import_progress",
            "cancel_tg_import",
        ),
        (
            "source.douyin",
            "get_douyin_import_progress",
            "cancel_douyin_import",
        ),
        (
            "source.wechat",
            "get_wechat_import_progress",
            "cancel_wechat_import",
        ),
    ],
)
def test_characterization_progress_and_cancel(
    shell, monkeypatch, provider, progress_method, cancel_method
):
    # Existing progress dictionaries are not collapsed into a generic result envelope.
    api, _, _ = shell
    state = {
        "status": "done",
        "progress": 100,
        "message": "fixture",
        "elapsed_s": 2,
        "result": {"copied": 1},
        "error_code": "",
        "log": ["fixture"],
    }
    worker = Mock()
    worker.get_progress.return_value = state
    lookup = Mock(return_value=worker)
    monkeypatch.setattr(import_workers, "get_import_worker", lookup)
    assert getattr(api, progress_method)() == state
    assert getattr(api, cancel_method)() is None
    worker.cancel.assert_called_once_with()
    assert [call.args[1] for call in lookup.call_args_list] == [provider, provider]


@pytest.mark.parametrize(
    "method", ["pick_tg_tdata", "qqnt_pick_ini", "qqnt_pick_userdata", "qqnt_pick_base"]
)
def test_characterization_dialog_cancel(shell, method):
    # Cancelled native selection is distinct from a failed dialog.
    api, webui, dialog = shell
    dialog.file_dialog.return_value = ()
    assert getattr(api, method)() == {"ok": False, "cancelled": True}
    webui._cfg.save.assert_not_called()


def test_characterization_settings_main_sync_and_adb(shell, monkeypatch):
    # Main/settings defaults differ; mobile QQ must remain a direct host action.
    api, webui, _ = shell
    main = desktop.JsApi(webui, Mock(), None)
    webui._container.sync.push.return_value = {"uploaded": 2, "skipped": 1}
    assert api.sync_push() == {"ok": True, "uploaded": 2, "skipped": 1}
    webui._container.sync.push.assert_called_once_with(delete_remote=None)
    webui._container.sync.push.reset_mock()
    assert main.sync_push() == {"ok": True, "uploaded": 2, "skipped": 1}
    webui._container.sync.push.assert_called_once_with()
    worker = Mock()
    monkeypatch.setattr(desktop.adb_qq, "start_qq_import", worker)
    assert api.start_qq_import() == {"ok": True}
    worker.assert_called_once_with()


def _descriptors():
    # Load the sole canonical manifest, without provider imports or discovery.
    root = Path(__file__).resolve().parents[2]
    return validate_manifest(
        json.loads((root / "config/plugin-manifest.json").read_text()),
        ENTRY_POINT_GROUP,
    )


def test_wechat_picker_zero_argument_contract(shell):
    # The actual settings caller invokes the picker with no arguments.
    api, _, dialog = shell
    dialog.file_dialog.return_value = ()
    assert api.pick_wechat_root() == {"ok": False, "cancelled": True}
    dialog.file_dialog.assert_called_once_with("settings", "folder")


@pytest.mark.parametrize("mode", ["missing", "disabled", "incompatible", "boolean_api"])
def test_registry_unavailable_returns_sentinel_without_other_provider(
    shell, monkeypatch, mode
):
    # Explicit registry absence/disablement must not fall back to the old worker.
    api, webui, _ = shell
    descriptors = _descriptors()
    if mode in ("incompatible", "boolean_api"):
        descriptors = tuple(
            (
                d._replace(api_version=99 if mode == "incompatible" else True)
                if d.id == "source.telegram"
                else d
            )
            for d in descriptors
        )
    factory = Mock(return_value=object())
    builtins = {"source.douyin": Mock(return_value=object())}
    if mode != "missing":
        builtins["source.telegram"] = factory
    webui._plugin_action_registry = PluginRegistry(descriptors, builtins, ())
    webui._enabled_import_plugins = () if mode == "disabled" else None
    assert api.start_tg_import() == {"ok": False}
    assert api.get_tg_import_progress() == {}
    assert api.cancel_tg_import() is None
    factory.assert_not_called()
    builtins["source.douyin"].assert_not_called()


def test_qqnt_check_env_requires_active_worker_before_legacy_helper(shell, monkeypatch):
    # Environment inspection must not succeed through the legacy module alone.
    api, webui, _ = shell
    lookup = Mock(side_effect=ValueError("source.qqnt: provider_unavailable"))
    monkeypatch.setattr(import_workers, "get_import_worker", lookup)
    legacy_probe = Mock(return_value={"ok": True})
    monkeypatch.setattr(desktop.qqnt, "get_extract_status", legacy_probe)

    assert api.qqnt_check_env() == {}
    assert lookup.call_args.args[1] == "source.qqnt"
    legacy_probe.assert_not_called()


def test_qqnt_default_dir_requires_active_worker_before_legacy_helper(
    shell, monkeypatch
):
    # Output projection also belongs to the fixed source.qqnt action boundary.
    api, webui, _ = shell
    lookup = Mock(side_effect=ValueError("source.qqnt: provider_unavailable"))
    monkeypatch.setattr(import_workers, "get_import_worker", lookup)
    legacy_projection = Mock(return_value="chosen-output")
    monkeypatch.setattr(desktop.qqnt, "get_default_output_dir", legacy_projection)

    assert api.qqnt_default_dir("base", "10001") == {"ok": False}
    assert lookup.call_args.args[1] == "source.qqnt"
    legacy_projection.assert_not_called()


def test_pick_tg_tdata_requires_active_worker_before_legacy_helper(
    shell, monkeypatch, tmp_path
):
    # The picker validates through the active source provider construction seam.
    api, webui, dialog = shell
    lookup = Mock(side_effect=ValueError("source.telegram: provider_unavailable"))
    monkeypatch.setattr(import_workers, "get_import_worker", lookup)
    path = tmp_path / "tdata"
    path.mkdir()
    dialog.file_dialog.return_value = (str(path),)
    legacy_validator = Mock(return_value=True)
    monkeypatch.setattr(desktop.telegram, "is_valid_tdata", legacy_validator)

    assert api.pick_tg_tdata() == {"ok": False}
    assert lookup.call_args.args[1] == "source.telegram"
    legacy_validator.assert_not_called()
    webui._cfg.set.assert_not_called()


@pytest.mark.parametrize(
    "action,args",
    [
        ("execute", []),
        ("<script>run()</script>", []),
        ([], []),
        ("start_tg_import", [None, "", "false"]),
        ("start_tg_import", [None]),
        ("start_tg_import", {"tdata_path": None}),
    ],
)
def test_bounded_dispatch_rejects_malformed_action_before_registry(action, args):
    # Host data cannot select arbitrary attributes or coerce malformed arguments.
    from ohmymeme.presentation.desktop.api.plugin_dispatch import HostDispatcher

    registry = Mock()
    dispatcher = HostDispatcher("settings", registry)
    with pytest.raises(ValueError):
        dispatcher.dispatch(action, args)
    registry.get.assert_not_called()


@pytest.mark.parametrize(
    "change",
    [
        {"action": "execute"},
        {"args": [None, "", "false"]},
        {"html": "<img onerror=run()>"},
        {"script": "run()"},
        {"label": "<script>run()</script>"},
        {"provider": "source.douyin"},
    ],
)
def test_contributions_reject_unknown_fields_actions_args_and_labels(change):
    # Contribution metadata is checked as data and never installed on the Bridge.
    from ohmymeme.presentation.desktop.api.plugin_dispatch import validate_contribution

    contribution = {
        "provider": "source.telegram",
        "action": "start_tg_import",
        "label": "开始导入",
        "args": [None, "", True],
    }
    contribution.update(change)
    with pytest.raises(ValueError):
        validate_contribution(contribution)


@pytest.mark.parametrize(
    "result",
    [
        None,
        "PASS",
        {"ok": "false"},
        {"ok": 1},
        {"ok": True, "html": "<script>run()</script>"},
    ],
)
def test_invalid_provider_result_does_not_become_success(shell, result):
    # A stale or misleading provider object must project the historical failure.
    from ohmymeme.presentation.desktop.api.plugin_dispatch import HostActionAdapter

    api, webui, _ = shell
    action = Mock(return_value=result)
    adapter = HostActionAdapter("source.telegram", {"start_tg_import": action})
    other = Mock()
    webui._plugin_action_registry = PluginRegistry(
        _descriptors(), {"source.telegram": lambda: adapter, "source.douyin": other}, ()
    )
    assert api.start_tg_import() == {"ok": False}
    action.assert_called_once_with(None, "", True)
    other.assert_not_called()


def test_registry_adapter_receives_only_fixed_arguments(shell):
    # The real facade traverses the real registry and narrow host adapter.
    from ohmymeme.presentation.desktop.api.plugin_dispatch import HostActionAdapter

    api, webui, _ = shell
    action = Mock(return_value={"ok": True})
    adapter = HostActionAdapter("source.telegram", {"start_tg_import": action})
    webui._plugin_action_registry = PluginRegistry(
        _descriptors(), {"source.telegram": lambda: adapter}, ()
    )
    assert api.start_tg_import("selected-tdata", "ephemeral-passcode", False) == {
        "ok": True
    }
    action.assert_called_once_with("selected-tdata", "ephemeral-passcode", False)
    assert not hasattr(api, "dispatch")
    assert not hasattr(api, "execute")


def test_host_adapter_rejects_other_provider_and_dynamic_actions():
    # A registry adapter cannot add methods to another provider or to the Bridge.
    from ohmymeme.presentation.desktop.api.plugin_dispatch import HostActionAdapter

    for action in ("execute", "start_douyin_import", "<script>run()</script>"):
        with pytest.raises(ValueError):
            HostActionAdapter("source.telegram", {action: Mock()})


def test_progress_stale_result_and_provider_exception(shell):
    # Bad progress and provider exceptions stay isolated, including credential text.
    from ohmymeme.presentation.desktop.api.plugin_dispatch import HostActionAdapter

    api, webui, _ = shell
    progress = Mock(return_value={"status": "done", "progress": "100"})
    start = Mock(side_effect=RuntimeError("ephemeral-secret"))
    adapter = HostActionAdapter(
        "source.telegram",
        {"get_tg_import_progress": progress, "start_tg_import": start},
    )
    webui._plugin_action_registry = PluginRegistry(
        _descriptors(), {"source.telegram": lambda: adapter}, ()
    )
    assert api.start_tg_import() == {"ok": False}
    assert "ephemeral-secret" not in repr(api._plugin_dispatcher.last_error)
    assert api.get_tg_import_progress() == {}


def test_real_provider_idle_progress_shapes(tmp_path):
    # Read actual idle states without launching threads, devices or network access.
    from ohmymeme.app.container import Container

    container = Container(tmp_path / "host")
    try:
        for provider in ("qqnt", "telegram", "douyin", "wechat"):
            install_official(container.config.data_dir, "source." + provider)
        webui = container.create_webui()
        api = desktop.SettingsApi(webui, container.settings)
        for provider, method in (
            ("qqnt", api.qqnt_get_progress),
            ("telegram", api.get_tg_import_progress),
            ("douyin", api.get_douyin_import_progress),
            ("wechat", api.get_wechat_import_progress),
        ):
            module = importlib.import_module("ohmymeme_plugin_" + provider)
            assert method() == module.create_plugin().get_progress()
            worker = import_workers.get_import_worker(api, "source." + provider)
            method()
            assert import_workers.get_import_worker(api, "source." + provider) is worker
    finally:
        container.close()


def test_real_qqnt_probe_and_native_picker_success(shell, tmp_path):
    # Actual provider inspection reads only the empty selected directory.
    from ohmymeme.core.plugins.runtime import PluginRuntimeManager

    api, webui, dialog = shell
    manager = PluginRuntimeManager(tmp_path / "runtime")
    install_official(tmp_path / "runtime", "source.qqnt")
    install_official(tmp_path / "runtime", "source.telegram")
    webui._container.plugin_runtime = manager
    try:
        webui._cfg.get.side_effect = lambda key, default=None: (
            str(tmp_path) if key == "qqnt_userdata_path" else default
        )
        assert api.qqnt_check_env() == {
            "ok": True,
            "error": "",
            "message": "",
            "userdata_save_path": str(tmp_path),
            "accounts": [],
        }
        dialog.file_dialog.return_value = (str(tmp_path),)
        assert api.pick_wechat_root() == {"ok": True, "path": str(tmp_path)}
        assert api.qqnt_pick_base() == {"ok": True, "base": str(tmp_path)}
        (tmp_path / "key_datas").write_bytes(b"fixture")
        assert api.pick_tg_tdata() == {"ok": True, "path": str(tmp_path)}
        webui._cfg.set.assert_called_once_with("tg_tdata_path", str(tmp_path))
        webui._cfg.save.assert_called_once_with()
    finally:
        manager.shutdown()


def test_lan_and_adb_remain_host_actions_with_empty_registry(shell, monkeypatch):
    # Import absence must not disturb existing LAN/ADB compatibility dispatch.
    api, webui, _ = shell
    webui._plugin_action_registry = PluginRegistry(_descriptors(), {}, ())
    service = webui._container.lan
    service.start.return_value = True
    service.get_status.return_value = {
        "status": "running",
        "allow_secret_config": False,
    }
    assert api.lan_start(17852, "") == {
        "ok": True,
        "status": service.get_status.return_value,
    }
    service.start.assert_called_once_with(17852, "")
    assert api.lan_stop() == {"ok": True, "status": service.get_status.return_value}
    service.stop.assert_called_once_with()
    worker = Mock()
    monkeypatch.setattr(desktop.adb_qq, "start_qq_import", worker)
    assert api.start_qq_import() == {"ok": True}
    worker.assert_called_once_with()


@pytest.mark.parametrize("case", ["valid", "invalid", "malformed", "dirty_worktree"])
def test_direct_cli_reports_observations_not_fixture_expected(tmp_path, case):
    # Run the real CLI and preserve an unrelated dirty file and prior failure evidence.
    root = Path(__file__).resolve().parents[2]
    abi = root / "docs/plugin-abi-matrix.json"
    actions = root / "docs/plugin-action-matrix.json"
    report = tmp_path / "report.json"
    report.write_text('{"status":"PASS","errors":[]}', encoding="utf-8")
    dirty = tmp_path / "user-note.txt"
    dirty.write_bytes(b"user-owned-change\n")
    if case == "invalid":
        abi = root / "fixtures/plugin-parity/abi-invalid.json"
        actions = root / "fixtures/plugin-parity/action-invalid.json"
    elif case == "malformed":
        abi = tmp_path / "truncated.json"
        abi.write_text('{"methods":', encoding="utf-8")
    elif case == "dirty_worktree":
        data = json.loads(actions.read_text(encoding="utf-8"))
        data["actions"][6]["arguments"] = [
            {"name": "execute", "schema": {"type": "string"}, "required": True}
        ]
        data["expected"] = {"status": "PASS"}
        actions = tmp_path / "edited-actions.json"
        actions.write_text(json.dumps(data), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/plugin_abi_matrix.py",
            "--check",
            "--abi",
            str(abi),
            "--actions",
            str(actions),
            "--report",
            str(report),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    measured = json.loads(report.read_text(encoding="utf-8"))
    assert dirty.read_bytes() == b"user-owned-change\n"
    if case == "valid":
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert measured["status"] == "PASS"
        assert len(measured["runtime"]) == 40
        assert all(
            row["accepted"] and row["provider_calls"] for row in measured["runtime"]
        )
    else:
        assert completed.returncode != 0
        assert measured["status"] == "REJECTED"
        assert measured["verdict"] == "changes_requested"
        assert measured["errors"]
        assert "expected" not in measured
    if case == "invalid":
        assert all(
            not row["accepted"] and row["provider_calls"] == []
            for row in measured["runtime"]
        )
        errors = "\n".join(measured["errors"])
        assert "args[2].convert_webm" in errors
        assert ".html" in errors and ".script" in errors and ".label" in errors


def test_bridge_schema_models_match_existing_generator():
    # The method-table correction does not change generated payload schemas or DTOs.
    from scripts.generate_bridge_schemas import SCHEMA_PATH, _schema_bytes

    assert SCHEMA_PATH.read_bytes() == _schema_bytes()
