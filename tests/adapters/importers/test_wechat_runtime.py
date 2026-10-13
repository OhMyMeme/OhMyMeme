# pyright: basic

"""微信插件子进程 runtime 集成测试：真实假 helper，网络保持离线。"""

import json
import os
import shlex
import socket
import sys
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugin_fixtures import install_official  # noqa: E402
from plugin_wechat_qa import source_database  # noqa: E402

from ohmymeme.app.container import Container
from ohmymeme.core.domain import TaskKind
from ohmymeme.integrations.imports import wechat
from ohmymeme.presentation.desktop.window_manager import SettingsApi


@pytest.fixture(autouse=True)
def install_wechat_plugin(tmp_path):
    # 官方插件不再自动种子，显式经真实安装事务装入宿主 data_dir
    install_official(tmp_path / "host" / "data", "source.wechat")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    # worker 只通过管道通信；宿主不解析 DNS、不外连
    monkeypatch.setattr(
        socket, "getaddrinfo", Mock(side_effect=AssertionError("offline DNS"))
    )
    monkeypatch.setattr(
        socket.socket, "connect", Mock(side_effect=AssertionError("offline socket"))
    )
    monkeypatch.setattr(wechat.platform, "system", lambda: "Windows")
    monkeypatch.setenv("OHMYMEME_INSECURE_SKIP_HELPER_HASH", "0")


# 写一个忽略参数、输出 JSON 并可选睡眠的假 helper
def _fake_helper(root, payload, sleep=0):
    body = json.dumps(payload, ensure_ascii=False)
    if os.name == "nt":
        lines = ["@echo off"]
        if sleep:
            lines.append("ping -n %d 127.0.0.1 >nul" % (int(sleep) + 1))
        lines.append("@echo " + body)
        if payload.get("ok") is False:
            lines.append("@exit /b 1")
        script = root / "wechat_keyfinder.cmd"
        script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    else:
        lines = ["#!/bin/sh"]
        if sleep:
            lines.append("sleep %d" % int(sleep))
        lines.append("echo " + shlex.quote(body))
        if payload.get("ok") is False:
            lines.append("exit 1")
        script = root / "wechat_keyfinder.sh"
        script.write_text("\n".join(lines) + "\n", encoding="utf-8")
        script.chmod(0o755)
    return script


# 让宿主 helper RPC 返回测试生成的假二进制
def _mount_helper(monkeypatch, tmp_path, payload, sleep=0):
    helper_dir = tmp_path / "helper"
    helper_dir.mkdir()
    helper = _fake_helper(helper_dir, payload, sleep=sleep)
    offsets = helper_dir / "offsets.json"
    offsets.write_bytes(b'{"versions":{}}')
    monkeypatch.setattr(
        wechat,
        "prepare_wechat_helper",
        lambda operation, cancelled: (str(helper), str(offsets)),
    )
    return helper


def test_wechat_inspect_and_list_through_worker(tmp_path):
    # 明文库走 worker 查询与列表，不经 helper 也不联网
    source_database(tmp_path / "source", "happy")
    root = str(tmp_path / "source")
    container = Container(tmp_path / "host")
    try:
        api = SettingsApi(container.create_webui(), container.settings)
        env = api.inspect_wechat_environment(root)
        assert env["status"] == "supported"
        assert [account["id"] for account in env["accounts"]] == ["wxid_fixture"]
        listed = api.list_wechat_stickers(root)
        assert listed["status"] == "supported"
        assert listed["total"] == 1
        assert listed["account"] == "wxid_fixture"
    finally:
        container.close()


def test_wechat_helper_failure_is_redacted_through_worker(tmp_path, monkeypatch):
    # helper 返回的密钥与错误详情都不得出现在宿主进度中
    secret = "ab" * 32
    source_database(tmp_path / "source", "helper_failure")
    _mount_helper(
        monkeypatch,
        tmp_path,
        {
            "ok": False,
            "key": secret,
            "reason": "key_not_found",
            "detail": "failure " + secret,
        },
        sleep=1,
    )
    container = Container(tmp_path / "host")
    try:
        api = SettingsApi(container.create_webui(), container.settings)
        assert api.start_wechat_import(str(tmp_path / "source")) == {"ok": True}
        container.operations.wait(TaskKind.IMPORT_WECHAT, 30)
        state = api.get_wechat_import_progress()
        assert state["error_code"] == "key_not_found"
        assert "[REDACTED]" in state["error"]
        assert secret not in json.dumps(state)
        assert not container.db.search()
    finally:
        container.close()


def test_wechat_cancel_during_key_extraction_stops_sleeping_helper(
    tmp_path, monkeypatch
):
    # 取消应终止 worker 内的 helper，并保持 worker 可继续服务
    source_database(tmp_path / "source", "helper_failure")
    _mount_helper(
        monkeypatch,
        tmp_path,
        {"ok": True, "key": "00" * 32},
        sleep=5,
    )
    container = Container(tmp_path / "host")
    try:
        webui = container.create_webui()
        api = SettingsApi(webui, container.settings)
        assert api.start_wechat_import(str(tmp_path / "source")) == {"ok": True}
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if api.get_wechat_import_progress().get("status") == "extracting_key":
                break
            time.sleep(0.1)
        assert api.cancel_wechat_import() is None
        container.operations.wait(TaskKind.IMPORT_WECHAT, 30)
        assert api.get_wechat_import_progress()["status"] == "cancelled"
        assert not container.db.search()
        worker = webui._runtime_import_workers["source.wechat"]
        assert worker._handle is None and worker._active is False
    finally:
        container.close()


def test_wechat_worker_remains_usable_after_failed_import(tmp_path, monkeypatch):
    # 失败后同一 worker 仍能响应查询，不需重启
    source_database(tmp_path / "source", "helper_failure")
    _mount_helper(
        monkeypatch,
        tmp_path,
        {"ok": False, "key": "", "reason": "key_not_found", "detail": "no key"},
        sleep=1,
    )
    container = Container(tmp_path / "host")
    try:
        api = SettingsApi(container.create_webui(), container.settings)
        assert api.start_wechat_import(str(tmp_path / "source")) == {"ok": True}
        container.operations.wait(TaskKind.IMPORT_WECHAT, 30)
        assert api.get_wechat_import_progress()["status"] == "error"
        env = api.inspect_wechat_environment(str(tmp_path / "source"))
        assert env["status"] == "encrypted_index"
    finally:
        container.close()
