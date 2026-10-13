# pyright: basic

"""子进程插件 runtime 的协议、种子与端到端测试。"""

import io
import sys
import textwrap
import time
from pathlib import Path

import pytest
from plugin_fixtures import install_official

from ohmymeme.core.plugins.runtime import protocol, seeding
from ohmymeme.core.plugins.runtime.channel import ChannelClosed
from ohmymeme.core.plugins.runtime.manager import (
    PluginRuntimeError,
    PluginRuntimeManager,
)
from ohmymeme.core.plugins.runtime.worker import PluginWorker

FAKE_QUICK = """
import time

from ohmymeme.core.imports import ImportPath


class QuickProvider:
    provider_id = "source.fake"
    api_version = 1

    def start(self, context):
        return True

    def stop(self):
        pass

    def finish(self):
        pass

    def get_progress(self):
        return {"status": "idle"}

    def inspect(self, ini_path=None, userdata_save_path=None, nickname_lookup=None):
        nickname = nickname_lookup("12345") if nickname_lookup else ""
        return {"ok": True, "ini_path": ini_path, "nickname": nickname}

    def import_media(self, context):
        staging = context.operation.temporary.path("out")
        staging.mkdir(parents=True, exist_ok=True)
        target = staging / "one.png"
        target.write_bytes(b"fake")
        context.progress({"status": "running", "progress": 50})
        result = context.sink.import_batch(
            (ImportPath(target, "one"),), cancelled=context.is_cancelled
        )
        context.operation.emit_log("done")
        return {"status": "done", "imported": len(result.imported_ids)}


def create_plugin():
    return QuickProvider()
"""

FAKE_SLOW = """
import time


class SlowProvider:
    provider_id = "source.slow"
    api_version = 1

    def start(self, context):
        return True

    def stop(self):
        pass

    def finish(self):
        pass

    def get_progress(self):
        return {"status": "idle"}

    def import_media(self, context):
        deadline = time.monotonic() + 30
        while not context.is_cancelled() and time.monotonic() < deadline:
            time.sleep(0.05)
        return {"status": "cancelled" if context.is_cancelled() else "timeout"}


def create_plugin():
    return SlowProvider()
"""

FAKE_CRASH = """
import os


class CrashProvider:
    provider_id = "source.crash"
    api_version = 1

    def start(self, context):
        return True

    def stop(self):
        pass

    def finish(self):
        pass

    def get_progress(self):
        return {"status": "idle"}

    def inspect(self, ini_path=None, userdata_save_path=None, nickname_lookup=None):
        os._exit(7)


def create_plugin():
    return CrashProvider()
"""


def _write_plugin(root, plugin_id, module_name, source):
    version_dir = seeding.plugins_dir(root) / plugin_id / "v1"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / (module_name + ".py")).write_text(
        textwrap.dedent(source), encoding="utf-8"
    )
    return version_dir


def _write_state(root, entries):
    state = {"schema_version": 1, "plugins": {}}
    for plugin_id, module_name in entries.items():
        state["plugins"][plugin_id] = {
            "origin": "installed",
            "active": "v1",
            "versions": {
                "v1": {
                    "version": "1.0",
                    "entry": module_name + ":create_plugin",
                    "kind": "source",
                    "package_root": module_name,
                    "capabilities": ["filesystem.read", "import.submit"],
                }
            },
        }
    seeding.write_state(root, state)


@pytest.fixture
def data_dir(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    return root


@pytest.fixture
def manager(data_dir):
    instance = PluginRuntimeManager(data_dir)
    try:
        yield instance
    finally:
        instance.shutdown()


# 帧编解码往返
def test_frame_round_trip():
    payload = {"jsonrpc": "2.0", "id": 1, "result": {"text": "中文"}}
    frame = protocol.encode_frame(payload)
    assert protocol.read_frame(io.BytesIO(frame)) == payload


# EOF 返回 None
def test_frame_eof():
    assert protocol.read_frame(io.BytesIO(b"")) is None


# 坏帧头被拒绝
def test_frame_bad_header():
    with pytest.raises(protocol.ProtocolError):
        protocol.read_frame(io.BytesIO(b"Content-Length: x\r\n\r\n{}"))


# 官方包经真实安装事务后可从嵌套版本目录加载
def test_load_plugin_from_installed_official(tmp_path):
    sys.modules.pop("ohmymeme_plugin_qqnt", None)
    data = tmp_path / "data"
    data.mkdir()
    install_official(data, "source.qqnt", version="0.0.0-test")
    spec = seeding.resolve_plugin(data, "source.qqnt")
    worker = PluginWorker("source.qqnt", "token")
    worker._load_plugin(
        {
            "id": spec["id"],
            "entry": spec["entry"],
            "package_dir": spec["package_dir"],
            "package_root": spec["package_root"],
            "capabilities": spec["capabilities"],
        }
    )
    module = sys.modules["ohmymeme_plugin_qqnt"]
    module_path = Path(module.__file__).resolve()
    assert module_path.is_relative_to(Path(spec["package_dir"]).resolve())


# 端到端：握手、查询、操作、sink 回调与结果
def test_operation_end_to_end(data_dir, manager):
    _write_plugin(data_dir, "source.fake", "fake_plugin", FAKE_QUICK)
    _write_state(data_dir, {"source.fake": "fake_plugin"})
    workspace = data_dir / "workspaces" / "op1"
    workspace.mkdir(parents=True)
    progress_values = []
    imported = []
    logs = []

    def sink_batch(requests):
        imported.extend(requests)
        return {"ids": [11], "rejected": 0}

    handle = manager.start_operation(
        "source.fake",
        "import",
        {"value": 1},
        workspace,
        progress=progress_values.append,
        log=logs.append,
        sink_batch=sink_batch,
    )
    outcome = handle.wait(timeout=30)
    assert outcome is not None and outcome["ok"] is True
    assert outcome["result"] == {"status": "done", "imported": 1}
    assert progress_values and progress_values[0]["progress"] == 50
    assert len(imported) == 1 and imported[0]["name"] == "one"
    assert logs == ["done"]

    queried = manager.query(
        "source.fake",
        "inspect",
        {"ini_path": "x.ini"},
        nickname_lookup=lambda qq: "nick-" + qq,
    )
    assert queried == {"ok": True, "ini_path": "x.ini", "nickname": "nick-12345"}


# 取消操作：worker 存活且操作收尾
def test_operation_cancel(data_dir, manager):
    _write_plugin(data_dir, "source.slow", "slow_plugin", FAKE_SLOW)
    _write_state(data_dir, {"source.slow": "slow_plugin"})
    workspace = data_dir / "workspaces" / "op2"
    workspace.mkdir(parents=True)
    handle = manager.start_operation("source.slow", "import", {}, workspace)
    time.sleep(0.3)
    handle.cancel()
    outcome = handle.wait(timeout=30)
    assert outcome is not None and outcome["ok"] is True
    assert outcome["result"]["status"] == "cancelled"


# worker 崩溃：在途调用失败且进程被回收
def test_worker_crash(data_dir, manager):
    _write_plugin(data_dir, "source.crash", "crash_plugin", FAKE_CRASH)
    _write_state(data_dir, {"source.crash": "crash_plugin"})
    with pytest.raises(PluginRuntimeError):
        manager.query("source.crash", "inspect", {})
    with pytest.raises(PluginRuntimeError):
        manager.query("source.crash", "inspect", {})


# 加载失败给出明确原因
def test_plugin_load_failure(data_dir, manager):
    _write_plugin(data_dir, "source.fake", "fake_plugin", FAKE_QUICK)
    _write_state(data_dir, {"source.fake": "missing_plugin"})
    with pytest.raises(PluginRuntimeError) as error:
        manager.ensure("source.fake")
    assert error.value.reason == "plugin_load_failed"


# 缺失插件解析失败
def test_plugin_missing(data_dir, manager):
    with pytest.raises(PluginRuntimeError) as error:
        manager.ensure("source.unknown")
    assert error.value.reason == "plugin_missing"


# 通道关闭后调用立即失败
def test_channel_closed(manager, data_dir):
    _write_plugin(data_dir, "source.fake", "fake_plugin", FAKE_QUICK)
    _write_state(data_dir, {"source.fake": "fake_plugin"})
    worker = manager.ensure("source.fake")
    worker.channel.close("test")
    with pytest.raises(ChannelClosed):
        worker.channel.call("ping", {})
