import json
import os
import subprocess
import sys

from src import env_check
from src.env_check import (
    detect_checks,
    detect_webview2,
    is_done,
    mark_done,
    marker_path,
    min_webview2_version,
    parse_min_version,
    show_blocking,
    ui_command,
    version_at_least,
    version_tuple,
)

PYWEBVIEW_WINFORMS_SNIPPET = """
def _is_chromium():
    build = ...
    if _is_new_version('86.0.622.0', build):
        return True
"""


class TestVersion:
    def test_version_tuple_non_numeric(self):
        assert version_tuple("86.0.622.0") == (86, 0, 622, 0)
        assert version_tuple("1.2.beta") == (1, 2, 0)

    def test_at_least_equal(self):
        assert version_at_least("86.0.622.0", "86.0.622.0")

    def test_at_least_greater(self):
        assert version_at_least("120.0.2210.61", "86.0.622.0")
        assert not version_at_least("85.0.9999.99", "86.0.622.0")

    def test_at_least_pads_short_side(self):
        assert version_at_least("86.0.622", "86.0.622.0")
        assert version_at_least("86", "86.0.0.0")


class TestParseMinVersion:
    def test_hit(self):
        assert parse_min_version(PYWEBVIEW_WINFORMS_SNIPPET) == "86.0.622.0"

    def test_miss(self):
        assert parse_min_version("def foo(): pass") is None

    def test_real_env_at_least_project_floor(self):
        assert version_at_least(min_webview2_version(), env_check._PROJECT_MIN_WEBVIEW2)

    def test_fallback_keeps_project_floor(self, monkeypatch):
        monkeypatch.setattr(env_check, "parse_min_version", lambda _src: None)
        assert min_webview2_version() == env_check._PROJECT_MIN_WEBVIEW2

    def test_project_floor_applies_to_pywebview_threshold(self, monkeypatch):
        monkeypatch.setattr(env_check, "parse_min_version", lambda _src: "86.0.622.0")
        assert min_webview2_version() == env_check._PROJECT_MIN_WEBVIEW2

    def test_follows_higher_pywebview_threshold(self, monkeypatch):
        monkeypatch.setattr(env_check, "parse_min_version", lambda _src: "95.0.0.1")
        assert min_webview2_version() == "95.0.0.1"


class TestMarker:
    def test_marker_path_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(env_check, "_get_config_dir", lambda: tmp_path)
        assert marker_path() == tmp_path / "env_check.json"

    def test_lifecycle(self, tmp_path):
        p = tmp_path / "sub" / "env_check.json"
        assert not is_done(p)
        checks = [{"name": "x", "ok": True, "detail": "d"}]
        mark_done(checks, path=p)
        assert is_done(p)
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["checks"] == checks
        assert data["time"]

    def test_is_done_missing_file(self, tmp_path):
        assert not is_done(tmp_path / "nope.json")


class TestDetectChecksNonWindows:
    def test_placeholder(self):
        items = detect_checks(is_windows=False)
        assert len(items) == 1
        assert items[0]["ok"] is True
        assert "Windows" in items[0]["detail"]


class TestDetectChecksWindows:
    def _patch(self, monkeypatch, pv_map, dotnet):
        stable = dict(env_check._WV2_CLIENTS)["Stable"]
        monkeypatch.setattr(env_check, "min_webview2_version", lambda: "86.0.622.0")
        monkeypatch.setattr(env_check, "_read_pv", lambda guid: pv_map.get(guid, ""))
        monkeypatch.setattr(env_check, "_read_dotnet_release", lambda: dotnet)
        return stable

    def test_installed_ok(self, monkeypatch):
        self._patch(
            monkeypatch,
            {"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}": "120.0.2210.61"},
            533320,
        )
        items = detect_checks(is_windows=True)
        assert len(items) == 3
        assert all(i["ok"] for i in items)
        assert "WebView2 版本" in items[1]["name"]
        assert "120.0.2210.61" in items[0]["detail"]

    def test_installed_too_old(self, monkeypatch):
        self._patch(
            monkeypatch,
            {"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}": "85.0.9999.99"},
            533320,
        )
        items = detect_checks(is_windows=True)
        assert items[0]["ok"] is True
        assert items[1]["ok"] is False
        assert "低于" in items[1]["detail"]

    def test_not_installed(self, monkeypatch):
        self._patch(monkeypatch, {}, 533320)
        items = detect_checks(is_windows=True)
        assert items[0]["ok"] is False
        assert items[0]["detail"] == "未安装"
        assert items[1]["ok"] is False

    def test_dotnet_missing(self, monkeypatch):
        self._patch(
            monkeypatch, {"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}": "120.0.0.0"}, 0
        )
        items = detect_checks(is_windows=True)
        assert items[2]["ok"] is False
        assert "未检测到" in items[2]["detail"]

    def test_beta_channel_used_when_no_stable(self, monkeypatch):
        beta = dict(env_check._WV2_CLIENTS)["Beta"]
        self._patch(monkeypatch, {beta: "130.0.1.2"}, 533320)
        items = detect_checks(is_windows=True)
        assert items[0]["ok"] is True
        assert "Beta" in items[0]["detail"]


class TestDetectWebview2:
    def test_not_installed(self, monkeypatch):
        monkeypatch.setattr(env_check, "_read_pv", lambda guid: "")
        res = detect_webview2(minimum="86.0.622.0")
        assert res["installed"] is False
        assert res["ok"] is False
        assert res["version"] == ""


class TestUiCommand:
    def test_source_mode(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        cmd, cwd = ui_command()
        assert cmd[:2] == [sys.executable, "-m"]
        assert cmd[2] == "src.env_check"
        assert cwd is not None

    def test_frozen_mode(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        cmd, cwd = ui_command()
        assert cmd == [sys.executable, "--env-check-ui"]
        assert cwd is None


class TestShowBlocking:
    def test_spawn_failure_does_not_raise(self, monkeypatch):
        def _boom(*_a, **_k):
            raise OSError("nope")

        monkeypatch.setattr(env_check.subprocess, "run", _boom)
        show_blocking()

    def test_runs_with_no_window_flag(self, monkeypatch):
        captured = {}

        def _run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs

        monkeypatch.setattr(env_check.subprocess, "run", _run)
        monkeypatch.delattr(sys, "frozen", raising=False)
        show_blocking()
        assert captured["cmd"][1:3] == ["-m", "src.env_check"]
        if os.name == "nt":
            assert (
                captured["kwargs"].get("creationflags") == subprocess.CREATE_NO_WINDOW
            )
        else:
            assert "creationflags" not in captured["kwargs"]
        assert captured["kwargs"]["stdout"] == subprocess.DEVNULL
