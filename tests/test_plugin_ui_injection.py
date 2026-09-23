# pyright: basic

"""ui.json 声明式贡献校验与 ui.action RPC 测试。"""

import json

import pytest

from ohmymeme.core.plugins.runtime import (
    PluginRuntimeManager,
    protocol,
    seeding,
    ui_injection,
)
from ohmymeme.core.plugins.runtime.channel import RpcError

FAKE_PLUGIN = """
class Provider:
    provider_id = "community.demo"
    api_version = 1

    def start(self, context):
        return True

    def stop(self):
        pass

    def finish(self):
        pass

    def get_progress(self):
        return {"status": "idle"}

    def handle_ui_action(self, name, payload):
        return {"echo": name, "value": payload.get("value")}


def create_plugin():
    return Provider()
"""


def _install(data_dir, ui_doc):
    version_dir = seeding.plugins_dir(data_dir) / "community.demo" / "1.0.0"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "demo_plugin.py").write_text(FAKE_PLUGIN, encoding="utf-8")
    if ui_doc is not None:
        (version_dir / "ui.json").write_text(
            json.dumps(ui_doc, ensure_ascii=False), encoding="utf-8"
        )
    seeding.write_state(
        data_dir,
        {
            "schema_version": 1,
            "plugins": {
                "community.demo": {
                    "origin": "installed",
                    "active": "1.0.0",
                    "versions": {
                        "1.0.0": {
                            "version": "1.0.0",
                            "entry": "demo_plugin:create_plugin",
                            "origin": "installed",
                            "name": "Demo",
                        }
                    },
                }
            },
        },
    )
    return version_dir


def _row(**overrides):
    injection = {
        "point": "imports.row",
        "label": "Demo 来源",
        "fields": [
            {
                "key": "source_dir",
                "type": "path_dir",
                "label": "源目录",
                "required": True,
            }
        ],
        "actions": [{"name": "run", "label": "运行", "kind": "import"}],
    }
    injection.update(overrides)
    return {"version": 1, "injections": [injection]}


def test_valid_import_row_loads_and_exposes_actions(tmp_path):
    data = tmp_path / "data"
    _install(data, _row())
    contributions = ui_injection.read_contributions(data, "community.demo")
    assert contributions[0]["point"] == "imports.row"
    assert contributions[0]["actions"] == [
        {"name": "run", "label": "运行", "kind": "import"}
    ]
    assert ui_injection.load_ui_actions(
        seeding.plugins_dir(data) / "community.demo" / "1.0.0"
    ) == frozenset({"run"})


@pytest.mark.parametrize(
    "doc",
    [
        {"version": 1, "injections": [{"point": "main.toolbar", "label": "x"}]},
        _row(extra="x"),
        _row(fields=[{"key": "a", "type": "text", "label": "A"}]),
        _row(fields=[{"key": "a", "type": "enum", "label": "A"}]),
        _row(actions=[{"name": "Run!", "label": "运行", "kind": "import"}]),
        {
            "version": 1,
            "injections": [{"point": "plugin_detail.iframe", "entry": "../x.html"}],
        },
    ],
)
def test_invalid_documents_are_rejected(tmp_path, doc):
    data = tmp_path / "data"
    _install(data, doc)
    with pytest.raises(seeding.PluginSeedError) as error:
        ui_injection.read_contributions(data, "community.demo")
    assert error.value.reason == "invalid_ui"


def test_ui_action_rpc_uses_declared_allowlist(tmp_path):
    data = tmp_path / "data"
    _install(data, _row())
    manager = PluginRuntimeManager(data)
    try:
        result = manager.call_ui_action("community.demo", "run", {"value": 7})
        assert result == {"echo": "run", "value": 7}
        with pytest.raises(RpcError) as error:
            manager.call_ui_action("community.demo", "other", {})
        assert error.value.code == protocol.ERROR_UNSUPPORTED
    finally:
        manager.shutdown()


def test_invalid_ui_document_leaves_plugin_running_without_actions(tmp_path):
    data = tmp_path / "data"
    _install(data, {"version": 1, "injections": [{"point": "nope"}]})
    manager = PluginRuntimeManager(data)
    try:
        handle = manager.ensure("community.demo")
        assert handle.ready_ok is True
        with pytest.raises(RpcError) as error:
            manager.call_ui_action("community.demo", "run", {})
        assert error.value.code == protocol.ERROR_UNSUPPORTED
    finally:
        manager.shutdown()


def test_missing_plugin_reports_seed_error(tmp_path):
    with pytest.raises(seeding.PluginSeedError) as error:
        ui_injection.read_contributions(tmp_path / "data", "community.missing")
    assert error.value.reason == "plugin_missing"
