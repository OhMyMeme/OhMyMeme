"""自动粘贴表情测试"""

import ctypes
import platform
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _FakeConfig:
    def __init__(self, enabled=False):
        self.enabled = enabled

    def get(self, key, default=None):
        if key == "auto_paste_meme":
            return self.enabled
        if key == "copy_resize_mode":
            return 0
        return default


class _FakeDB:
    def __init__(self):
        self.recorded = []

    def get_by_id(self, meme_id):
        return {"filename": "meme.png"} if meme_id == 1 else None

    def record_use(self, meme_id):
        self.recorded.append(meme_id)


class _FakeWindow:
    def __init__(self):
        self.calls = []

    def hide(self):
        self.calls.append("hide")


def _fake_webui(enabled=False):
    from src.webui import WebUI

    ui = WebUI()
    ui._cfg = _FakeConfig(enabled)
    ui._window = _FakeWindow()
    ui._visible = False
    ui._save_window_position = lambda: None
    ui._run_on_gui = lambda _delay, _func: None
    return ui


def test_config_auto_paste_defaults_false_and_persists(tmp_path):
    from src.config import Config

    cfg = Config(tmp_path / "config.json")
    assert cfg.get("auto_paste_meme") is False

    cfg.set("auto_paste_meme", True)
    cfg.save()

    assert Config(tmp_path / "config.json").get("auto_paste_meme") is True


def test_try_paste_rejects_non_windows(monkeypatch):
    from src import platform_util

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    assert platform_util.try_paste_into_window(123) is False


def test_try_paste_requires_same_foreground_window(monkeypatch):
    from src import platform_util

    class User32:
        def IsWindow(self, _hwnd):
            return True

        def GetForegroundWindow(self):
            return 456

        def SendInput(self, *_args):
            raise AssertionError("must not send to a changed foreground window")

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform_util, "_get_windows_user32", lambda: User32())
    assert platform_util.try_paste_into_window(123) is False


def test_try_paste_sends_only_ctrl_v_and_requires_all_events(monkeypatch):
    from src import platform_util

    sent = []

    class User32:
        def IsWindow(self, _hwnd):
            return True

        def SetForegroundWindow(self, _hwnd):
            return 1

        def GetForegroundWindow(self):
            return 123

        def SendInput(self, count, inputs, size):
            sent.extend(inputs[index].ki.wVk for index in range(count))
            assert size == platform_util._input_size()
            return count

    input_type = platform_util._input_types()[2]

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform_util, "_get_windows_user32", lambda: User32())
    monkeypatch.setattr(
        platform_util,
        "_input_size",
        lambda: ctypes.sizeof(input_type),
    )
    assert platform_util.try_paste_into_window(123) is True
    assert sent == [0x11, 0x56, 0x56, 0x11]
    assert 0x0D not in sent


def test_hotkey_captures_target_only_when_enabled_and_hidden(monkeypatch):
    from src import platform_util

    ui = _fake_webui(enabled=True)
    monkeypatch.setattr(platform_util, "capture_foreground_window", lambda: 123)
    ui.toggle_hotkey_safe()
    assert ui._paste_target == 123

    ui._visible = True
    ui.toggle_hotkey_safe()
    assert ui._paste_target is None


def test_hotkey_does_not_capture_when_auto_paste_is_disabled(monkeypatch):
    from src import platform_util

    ui = _fake_webui(enabled=False)
    monkeypatch.setattr(
        platform_util,
        "capture_foreground_window",
        lambda: pytest.fail("disabled setting must not read the foreground window"),
    )
    ui.toggle_hotkey_safe()
    assert ui._paste_target is None


def test_tray_session_clears_hotkey_target():
    ui = _fake_webui(enabled=True)
    ui._paste_target = 123

    ui.toggle_safe()

    assert ui._paste_target is None


def test_copy_meme_hides_then_pastes_captured_target(monkeypatch):
    import src.webui as webui_module

    ui = _fake_webui(enabled=True)
    ui._paste_target = 123
    api = ui._api
    api._cfg = ui._cfg
    api._db = _FakeDB()
    monkeypatch.setattr(api, "_find_meme_file", lambda _name: "meme.png")
    monkeypatch.setattr(webui_module, "copy_image_to_clipboard", lambda _path: True)
    pasted = []
    monkeypatch.setattr(
        "src.platform_util.try_paste_into_window",
        lambda hwnd: pasted.append(hwnd) or True,
    )

    result = api.copy_meme(1)
    assert result == {"ok": True, "status": "copy_scheduled", "operation_id": 1}
    ui._process_pending_hide()

    assert ui._window.calls == ["hide"]
    assert pasted == [123]
    assert api.get_last_copy_result(1) == {
        "ok": True,
        "status": "pasted",
        "operation_id": 1,
    }


def test_copy_meme_without_target_keeps_copy_only(monkeypatch):
    import src.webui as webui_module

    ui = _fake_webui(enabled=True)
    api = ui._api
    api._cfg = ui._cfg
    api._db = _FakeDB()
    monkeypatch.setattr(api, "_find_meme_file", lambda _name: "meme.png")
    monkeypatch.setattr(webui_module, "copy_image_to_clipboard", lambda _path: True)
    monkeypatch.setattr(
        "src.platform_util.try_paste_into_window",
        lambda _hwnd: pytest.fail("copy-only path must not inject keys"),
    )

    result = api.copy_meme(1)
    assert result == {"ok": True, "status": "copied", "operation_id": 1}
    ui._process_pending_hide()
    assert api.get_last_copy_result(1) == result


def test_settings_api_returns_and_resets_auto_paste(monkeypatch):
    from src.webui import SettingsApi

    class Config:
        def __init__(self):
            self.data = {"auto_paste_meme": True, "cache_dir": ""}

        def to_dict(self):
            return dict(self.data)

        @property
        def cache_dir(self):
            return Path("cache")

        def get(self, key, default=None):
            return self.data.get(key, default)

        def reset(self):
            self.data = {"auto_paste_meme": False, "cache_dir": ""}

        def save(self):
            pass

    class WebUI:
        def _on_hotkey_change(self, _hotkey):
            pass

    monkeypatch.setattr("src.platform_util.is_auto_start_enabled", lambda: False)
    monkeypatch.setattr("src.platform_util.set_auto_start", lambda _enabled: True)
    api = SettingsApi.__new__(SettingsApi)
    api._cfg = Config()
    api._webui = WebUI()
    assert api.get_settings()["auto_paste_meme"] is True
    assert api.reset_settings()["auto_paste_meme"] is False
