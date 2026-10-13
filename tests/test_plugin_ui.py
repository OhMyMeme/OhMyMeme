import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ohmymeme.presentation.desktop.api import plugin_dispatch

ROOT = Path(__file__).resolve().parents[1]
OBSERVATIONS = []


@pytest.fixture(scope="module", autouse=True)
def record_ui_observations():
    # Optional evidence contains measured calls/results, not fixture verdicts.
    yield
    if os.environ.get("OHMM_UI_PY_REPORT"):
        path = ROOT / os.environ["OHMM_UI_PY_REPORT"]
        path.write_text(json.dumps(OBSERVATIONS, ensure_ascii=False, indent=2), "utf-8")


def test_characterize_fixed_ui_and_bundle():
    # 历史兼容基线：旧 Vanilla settings.html 冻结为只读 fixture，独立于新投影输出。
    html = (ROOT / "fixtures/plugin-parity/settings-ui-baseline.html").read_text(
        encoding="utf-8"
    )
    for handler, label in (
        ("startQQImport", "手机版 QQ（ADB 拉取）"),
        ("startQQNTWizard", "电脑版 QQ（QQNT 本地缓存）"),
        ("openTGImportDialog", "Telegram Desktop"),
        ("openDYImportDialog", "抖音"),
        ("openWechatImportDialog", "微信"),
    ):
        assert f'onclick="{handler}()"' in html
        assert f'<span class="import-name">{label}</span>' in html
    for value, label in (
        ("ftp", "FTP"),
        ("s3", "S3 兼容存储"),
        ("r2", "Cloudflare R2"),
        ("webdav", "WebDAV"),
    ):
        assert f'<option value="{value}">{label}</option>' in html
    assert '<div class="section-title">局域网互联</div>' in html
    assert plugin_dispatch.IMPORT_ACTIONS["start_tg_import"][1] == (
        "tdata_path",
        "passcode",
        "convert_webm",
    )
    assert plugin_dispatch.HOST_ACTIONS["settings"]["sync_push"][1] == (
        "delete_remote",
    )
    assert "start_qq_import" not in plugin_dispatch.ACTIONS["settings"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("label", "Not the original label"),
        ("label", ""),
        ("label", True),
        ("icon", "<svg onload=run()>"),
        ("provider", "source.unknown"),
        ("provider", "qq.mobile"),
        ("handler", "eval"),
        ("script", "run()"),
        ("html", "<img onerror=run()>"),
        ("javascript", "run()"),
        ("bridge_methods", ["execute"]),
        ("extra", {}),
    ],
)
def test_reject_ui_before_projection(field, value):
    # A malformed record cannot produce a partially accepted projection.
    from ohmymeme.presentation.desktop.api.ui_contributions import (
        fixed_ui_document,
        project_ui,
    )

    document = fixed_ui_document()
    document["contributions"][0][field] = value
    with pytest.raises(ValueError, match=field):
        project_ui(document)


@pytest.mark.parametrize("version", [True, 1.0, 1.5, "1"])
def test_reject_non_integer_schema_version(version):
    # Python equality must not accept bool/float as the version integer.
    from ohmymeme.presentation.desktop.api.ui_contributions import (
        fixed_ui_document,
        project_ui,
    )

    document = fixed_ui_document()
    document["schema_version"] = version
    with pytest.raises(ValueError, match="schema_version"):
        project_ui(document)


@pytest.mark.parametrize(
    "field,value",
    [
        ("action", "execute"),
        ("label", "Misleading PASS"),
        ("arguments", [{"name": "script", "schema": {"type": "string"}}]),
        ("progress_fields", ["html"]),
        ("args", [True]),
        ("script", "run()"),
    ],
)
def test_reject_action_metadata(field, value):
    # Expected metadata comes from frozen host definitions, not submitted fixtures.
    from ohmymeme.presentation.desktop.api.ui_contributions import (
        fixed_ui_document,
        project_ui,
    )

    document = fixed_ui_document()
    document["contributions"][0]["actions"][0][field] = value
    with pytest.raises(ValueError, match=field):
        project_ui(document)


def test_action_matrix_and_input_snapshot():
    # An input copy is consumed without becoming mutable global host state.
    from ohmymeme.presentation.desktop.api.ui_contributions import (
        fixed_ui_document,
        project_ui,
    )

    actions = json.loads((ROOT / "docs/plugin-action-matrix.json").read_text("utf-8"))
    document = fixed_ui_document()
    observed = project_ui(document, actions)
    assert len(observed["contributions"]) == 9
    assert observed == document and observed is not document
    document["contributions"][0]["label"] = "changed"
    assert observed["contributions"][0]["label"] == "电脑版 QQ（QQNT 本地缓存）"
    stale = copy.deepcopy(actions)
    stale["actions"][0]["label"] = "Misleading PASS"
    with pytest.raises(ValueError, match="actions.*label"):
        project_ui(fixed_ui_document(), stale)


def test_real_bottle_consumer_and_no_provider_execution(monkeypatch, tmp_path):
    # Call the registered production route without starting a server or provider.
    from ohmymeme.presentation.desktop import window_manager as desktop

    registry_get = Mock(side_effect=AssertionError("must not load provider"))
    monkeypatch.setattr(plugin_dispatch.PluginRegistry, "get", registry_get)
    app = desktop.WebUI.build_bottle_app(
        SimpleNamespace(_port=17899, _html_dir=ROOT / "src/webui")
    )
    route = next(
        route.callback for route in app.routes if route.rule == "/api/plugin-ui"
    )
    observed = route()
    assert len(observed["contributions"]) == 9
    assert observed == json.loads(
        (ROOT / "fixtures/plugin-parity/ui-valid.json").read_text("utf-8")
    )
    invalid = json.loads(
        (ROOT / "fixtures/plugin-parity/ui-invalid.json").read_text("utf-8")
    )
    (tmp_path / "plugin-ui.json").write_text(json.dumps(invalid), "utf-8")
    app = desktop.WebUI.build_bottle_app(
        SimpleNamespace(_port=17899, _html_dir=tmp_path)
    )
    route = next(
        route.callback for route in app.routes if route.rule == "/api/plugin-ui"
    )
    assert route() == {"error": "ui: host contribution data rejected"}
    assert desktop.bottle.response.status_code == 503
    registry_get.assert_not_called()
    OBSERVATIONS.append(
        {
            "case": "production-bottle-route",
            "route": "/api/plugin-ui",
            "projection": observed,
            "invalid_status": desktop.bottle.response.status_code,
            "provider_calls": registry_get.call_count,
        }
    )


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "invalid",
        "malformed",
        "bool",
        "float",
        "stale",
        "schema",
        "unknown_key",
        "wrong_args",
        "duplicate",
    ],
)
def test_cli_observations_replace_misleading_pass(tmp_path, case):
    # Exercise literal argv and an existing misleading report, not fixture verdicts.
    fixture = (
        ROOT
        / "fixtures/plugin-parity"
        / ("ui-invalid.json" if case == "invalid" else "ui-valid.json")
    )
    actions_path = ROOT / "docs/plugin-action-matrix.json"
    if case in ("malformed", "duplicate"):
        fixture = tmp_path / "input.json"
        fixture.write_text(
            (
                '{"schema_version":'
                if case == "malformed"
                else '{"schema_version":1,"schema_version":1}'
            ),
            "utf-8",
        )
    elif case in ("bool", "float", "stale", "schema", "unknown_key", "wrong_args"):
        actions = json.loads(actions_path.read_text("utf-8"))
        if case in ("bool", "float"):
            actions["schema_version"] = True if case == "bool" else 1.0
        elif case == "stale":
            actions["actions"][0]["label"] = "Misleading PASS"
        elif case == "schema":
            actions["actions"][5]["arguments"][0]["schema"] = {"type": "string"}
        elif case == "wrong_args":
            actions["actions"][5]["sample_args"] = [1, ""]
        else:
            actions["expected"] = {"status": "PASS"}
        actions_path = tmp_path / "actions.json"
        actions_path.write_text(json.dumps(actions), "utf-8")
    report_path = tmp_path / "report.json"
    report_path.write_text('{"status":"PASS"}', "utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "scripts/plugin_ui_dispatch.py",
            "--check",
            "--actions",
            str(actions_path),
            "--fixture",
            str(fixture),
            "--report",
            str(report_path),
        ],
        cwd=ROOT,
        capture_output=True,
        timeout=30,
    )
    report = json.loads(report_path.read_text("utf-8"))
    OBSERVATIONS.append(
        {"case": case, "argv": result.args, "exit": result.returncode, "report": report}
    )
    assert result.returncode == (0 if case == "valid" else 1), result.stdout
    assert report["status"] == ("PASS" if case == "valid" else "REJECTED")
    assert bool(report["errors"]) == (case != "valid")
    assert report["execution"]["provider_calls"] == []
    assert report["execution"]["bridge_calls"] == []
    assert report["execution"]["dom_calls"] == []
    if case != "valid":
        assert report["library_projection"] is None
        assert report["host_asset_projection"] is None
    if case == "invalid":
        for field in (
            "label",
            "icon",
            "action",
            "args",
            "script",
            "html",
            "provider",
            "expected",
        ):
            assert field in " ".join(report["errors"])


@pytest.mark.parametrize("seam", ["project_ui", "load_ui_projection"])
def test_cli_projection_exception_replaces_stale_pass(tmp_path, seam):
    # A real CLI process must replace stale success even for unexpected exceptions.
    report_path = tmp_path / "report.json"
    seeded = {
        "status": "PASS",
        "verdict": "approved",
        "seed": "independent-stale-pass",
    }
    report_path.write_text(json.dumps(seeded), "utf-8")
    probe = """
import sys
from unittest.mock import patch
sys.path.insert(0, "scripts")
import plugin_ui_dispatch as cli
with patch.object(cli, sys.argv[1],
                  side_effect=RuntimeError("independent projection failure")):
    sys.exit(cli.main(sys.argv[2:]))
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            probe,
            seam,
            "--check",
            "--actions",
            "docs/plugin-action-matrix.json",
            "--fixture",
            "fixtures/plugin-parity/ui-valid.json",
            "--report",
            str(report_path),
        ],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )
    observed = json.loads(report_path.read_text("utf-8"))
    OBSERVATIONS.append(
        {
            "case": "projection-exception",
            "seam": seam,
            "argv": result.args,
            "exit": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "report_before": seeded,
            "report_after": observed,
        }
    )
    assert result.returncode == 1
    assert observed["status"] == "REJECTED"
    assert observed["verdict"] == "changes_requested"
    assert observed["errors"] == ["independent projection failure"]
    assert observed["exception"] == {
        "type": "RuntimeError",
        "message": "independent projection failure",
    }
    assert json.loads(result.stderr) == {
        "status": "REJECTED",
        "verdict": "changes_requested",
        "exception": observed["exception"],
    }
    assert observed["library_projection"] is None
    assert observed["host_asset_projection"] is None
    assert "seed" not in observed
    assert not list(tmp_path.glob(".report.json.*.tmp"))


def test_ui_is_not_settings_or_public_bridge_data():
    # Host-only UI metadata never becomes an arbitrary persisted setup field.
    from ohmymeme.core.schemas.bridge import SettingsPatch
    from ohmymeme.presentation.desktop.api.settings_facade import SettingsBridgeFacade

    with pytest.raises(ValueError):
        SettingsPatch.model_validate({"plugin_ui": {"label": "PASS"}})
    for name in ("plugin_ui", "get_plugin_ui", "execute", "dispatch"):
        assert not hasattr(SettingsBridgeFacade, name)
    config = Mock()
    webui = SimpleNamespace(
        _cfg=config, _library=Mock(), _container=SimpleNamespace(sync=Mock())
    )
    api = SettingsBridgeFacade(webui, Mock())
    assert api.save_settings({"plugin_ui": {"label": "PASS"}}) is None
    config.set.assert_not_called()
    config.save.assert_not_called()
    OBSERVATIONS.append(
        {
            "case": "settings-not-persisted",
            "config_calls": len(config.mock_calls),
            "bridge_error": api._last_bridge_error.code,
        }
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("required", 1),
        ("required", 1.0),
        ("default", 0),
        ("schema", {"type": "boolean", "script": "run()"}),
    ],
)
def test_nested_argument_schema_strict_types(field, value):
    # JSON boolean/default types cannot silently compare equal to integer/float.
    from ohmymeme.presentation.desktop.api.ui_contributions import (
        fixed_ui_document,
        project_ui,
    )

    document = fixed_ui_document()
    action = next(
        row
        for row in document["contributions"][1]["actions"]
        if row["action"] == "start_tg_import"
    )
    action["arguments"][2][field] = value
    with pytest.raises(ValueError, match=field) as rejected:
        project_ui(document)
    OBSERVATIONS.append(
        {
            "case": "nested-argument-" + field,
            "value": value,
            "error": str(rejected.value),
        }
    )


def test_schema_and_stale_host_asset_rejected(monkeypatch, tmp_path):
    # Exercise real schema/asset inputs without editing the user's current files.
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import plugin_ui_dispatch as cli
    finally:
        sys.path.pop(0)
    schema = json.loads(cli.SCHEMA.read_text("utf-8"))
    schema["properties"]["schema_version"]["type"] = "boolean"
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema), "utf-8")
    with monkeypatch.context() as changed:
        changed.setattr(cli, "SCHEMA", path)
        report = cli.check(
            ROOT / "docs/plugin-action-matrix.json",
            ROOT / "fixtures/plugin-parity/ui-valid.json",
        )
    assert report["status"] == "REJECTED"
    assert any(
        "schema.properties.schema_version.type" in error for error in report["errors"]
    )
    OBSERVATIONS.append({"case": "stale-schema", "report": report})
    path = tmp_path / "NetworkGroup.vue"
    path.write_text(
        cli.RUNTIME.read_text("utf-8").replace("pluginProgressValue", ""),
        "utf-8",
    )
    with monkeypatch.context() as changed:
        changed.setattr(cli, "RUNTIME", path)
        report = cli.check(
            ROOT / "docs/plugin-action-matrix.json",
            ROOT / "fixtures/plugin-parity/ui-valid.json",
        )
    assert report["status"] == "REJECTED"
    assert any("pluginProgressValue" in error for error in report["errors"]), report[
        "errors"
    ]
    assert report["library_projection"] is None
    OBSERVATIONS.append({"case": "broken-consumer-wiring", "report": report})
    asset = json.loads(cli.ASSET.read_text("utf-8"))
    asset["contributions"][0]["label"] = "stale asset"
    path = tmp_path / "asset.json"
    path.write_text(json.dumps(asset), "utf-8")
    monkeypatch.setattr(cli, "ASSET", path)
    with pytest.raises(ValueError, match="label") as rejected:
        cli.check(
            ROOT / "docs/plugin-action-matrix.json",
            ROOT / "fixtures/plugin-parity/ui-valid.json",
        )
    OBSERVATIONS.append({"case": "stale-asset", "error": str(rejected.value)})
