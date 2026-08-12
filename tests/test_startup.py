"""启动流程测试 - pytest风格"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["OHMYMEME_TEST"] = "1"

from src.clipboard_util import copy_image_to_clipboard, copy_text
from src.config import Config
from src.crypto_util import decrypt_data, encrypt_data
from src.database import MemeDB
from src.hotkey import GlobalHotkey
from src.tray import _create_default_icon


class _FakeConfig:
    def __init__(self, hotkey_show_at_mouse):
        self.hotkey_show_at_mouse = hotkey_show_at_mouse
        self.saved = {}

    def get(self, key, default=None):
        if key == "hotkey_show_at_mouse":
            return self.hotkey_show_at_mouse
        return default

    def set(self, key, value):
        self.saved[key] = value

    def save(self):
        pass


class _FakeWindow:
    def __init__(self):
        self.width = 700
        self.height = 500
        self.x = 10
        self.y = 20
        self.on_top = False
        self.calls = []

    def move(self, x, y):
        self.calls.append(("move", x, y))

    def show(self):
        self.calls.append(("show",))

    def focus(self):
        self.calls.append(("focus",))

    def hide(self):
        self.calls.append(("hide",))


class _FakeMemeDB:
    def get_by_id(self, meme_id):
        return {"filename": f"meme-{meme_id}.png"}

    def record_use(self, meme_id):
        pass


def _fake_webui(hotkey_show_at_mouse, visible=False):
    from src.webui import WebUI

    ui = WebUI()
    ui._cfg = _FakeConfig(hotkey_show_at_mouse)
    ui._window = _FakeWindow()
    ui._visible = visible
    return ui


def test_config_io(tmp_path):
    cfg = Config(tmp_path / "config.json")
    cfg.set("hotkey", "Ctrl+Shift+X")
    cfg.set("s3_secret_key", "test_secret_123")
    cfg.set("auto_start", True)
    cfg.save()

    cfg2 = Config(tmp_path / "config.json")
    assert cfg2.get("hotkey") == "Ctrl+Shift+X"
    assert cfg2.get("s3_secret_key") == "test_secret_123"
    assert cfg2.get("auto_start")


def test_database_operations(tmp_path):
    db = MemeDB(tmp_path / "test.db")
    mid = db.add_meme("test.png", file_hash="abc", width=100, height=200, tags=["test"])
    assert mid is not None
    assert db.count() == 1
    assert db.get_by_hash("abc") is not None
    results = db.search(keyword="test")
    assert len(results) == 1
    assert not db.is_favorite(mid)
    db.toggle_favorite(mid)
    assert db.is_favorite(mid)
    tags = db.get_meme_tags(mid)
    assert "test" in tags
    db.close()


def test_hotkey_init():
    hk = GlobalHotkey()
    result = hk.register("Ctrl+Alt+N", lambda: None)
    assert result
    hk.unregister()


def test_tray_icon():
    img = _create_default_icon()
    assert img is not None
    assert img.size == (64, 64)
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert len(buf.getvalue()) > 0


def test_crypto():
    secrets = ["my_secret_key", "AKID1234567890", "s3cr3t!@#$%"]
    for s in secrets:
        enc = encrypt_data(s)
        dec = decrypt_data(enc)
        assert dec == s


def test_clipboard():
    result = copy_text("test")
    assert isinstance(result, bool)
    icon_path = (
        Path(__file__).resolve().parent.parent / "src" / "resources" / "icon.png"
    )
    if icon_path.exists():
        result = copy_image_to_clipboard(str(icon_path))
        assert isinstance(result, bool)


def test_webui_import():
    from src.webui import JsApi, WebUI

    w = WebUI()
    assert w._port > 0
    assert w._window is None
    assert not w.is_visible
    assert hasattr(w, "toggle_safe")
    assert hasattr(w, "show")
    assert hasattr(w, "hide")
    # JsApi
    api = JsApi(w)
    assert hasattr(api, "search_memes")
    assert hasattr(api, "get_tags")
    assert hasattr(api, "copy_meme")
    assert hasattr(api, "import_memes")


def test_find_hotkey_window_position_candidate_order():
    from src.webui import _find_hotkey_window_position

    work_area = (0, 0, 100, 100)
    assert _find_hotkey_window_position((10, 10), work_area, 30, 20) == (10, 10)
    assert _find_hotkey_window_position((80, 10), work_area, 30, 20) == (70, 10)
    assert _find_hotkey_window_position((10, 90), work_area, 30, 20) == (10, 80)
    assert _find_hotkey_window_position((80, 90), work_area, 30, 20) == (70, 80)


def test_find_hotkey_window_position_edge_equality_allowed():
    from src.webui import _find_hotkey_window_position

    assert _find_hotkey_window_position((70, 80), (0, 0, 100, 100), 30, 20) == (
        70,
        80,
    )


def test_find_hotkey_window_position_none_when_window_cannot_fit():
    from src.webui import _find_hotkey_window_position

    work_area = (-100, -50, 100, 50)
    assert _find_hotkey_window_position((0, 0), work_area, 201, 50) is None
    assert _find_hotkey_window_position((0, 0), work_area, 100, 101) is None


def test_toggle_hotkey_safe_moves_then_shows_hidden_window(monkeypatch):
    ui = _fake_webui(True)
    monkeypatch.setattr(ui, "_get_hotkey_window_position", lambda: (40, 50))

    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("move", 40, 50), ("show",), ("focus",)]
    assert ui._visible
    assert ui._hotkey_session


def test_hide_clears_hotkey_session():
    ui = _fake_webui(True)
    ui.toggle_hotkey_safe()

    ui.hide()

    assert not ui._hotkey_session


def test_tray_toggle_show_does_not_mark_hotkey_session():
    ui = _fake_webui(True)

    ui.toggle_safe()

    assert ui._visible
    assert not ui._hotkey_session


def test_schedule_hide_only_hides_hotkey_session():
    ui = _fake_webui(True, visible=True)
    ui.schedule_hide()
    ui._process_pending_hide()
    assert ui._visible is True

    ui = _fake_webui(True)
    ui.toggle_hotkey_safe()
    ui.schedule_hide()
    ui._process_pending_hide()
    assert ui._visible is False


def test_toggle_hotkey_safe_hides_visible_window_without_placement(monkeypatch):
    ui = _fake_webui(True, visible=True)

    def fail_if_called():
        raise AssertionError("visible hotkey toggle must not calculate placement")

    monkeypatch.setattr(ui, "_get_hotkey_window_position", fail_if_called)

    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("hide",)]
    assert not ui._visible


def test_toggle_hotkey_safe_disabled_shows_without_placement(monkeypatch):
    ui = _fake_webui(False)

    def fail_if_called():
        raise AssertionError("disabled placement must not be calculated")

    monkeypatch.setattr(ui, "_get_hotkey_window_position", fail_if_called)

    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("show",), ("focus",)]
    assert ui._visible


def test_toggle_hotkey_safe_placement_exception_still_shows(monkeypatch):
    ui = _fake_webui(True)

    def fail_placement():
        raise RuntimeError("placement unavailable")

    monkeypatch.setattr(ui, "_get_hotkey_window_position", fail_placement)

    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("show",), ("focus",)]
    assert ui._visible


def test_successful_native_drag_requests_hide_only_for_hotkey_session(monkeypatch):
    import src.native_drag as native_drag
    from src.webui import JsApi

    ui = _fake_webui(True)
    ui._api = JsApi(ui)
    ui._api._db = _FakeMemeDB()
    monkeypatch.setattr(ui._api, "_find_meme_file", lambda filename: filename)
    monkeypatch.setattr(native_drag, "start_native_drag", lambda path: True)
    monkeypatch.setattr(ui, "_run_on_gui", lambda delay, func: func())

    ui.show()
    assert ui._api.start_native_drag(1)
    assert ui._visible is True

    ui.hide()
    ui.toggle_hotkey_safe()
    assert ui._api.start_native_drag(1)
    assert ui._visible is False


def test_successful_copy_requests_hide_only_for_hotkey_session(monkeypatch):
    import src.webui as webui_module
    from src.webui import JsApi

    ui = _fake_webui(True)
    ui._api = JsApi(ui)
    ui._api._db = _FakeMemeDB()
    monkeypatch.setattr(ui._api, "_find_meme_file", lambda filename: filename)
    monkeypatch.setattr(webui_module, "copy_image_to_clipboard", lambda path: True)
    monkeypatch.setattr(ui, "_run_on_gui", lambda delay, func: func())

    ui.show()
    assert ui._api.copy_meme(1)
    assert ui._visible is True

    ui.hide()
    ui.toggle_hotkey_safe()
    assert ui._api.copy_meme(1)
    assert ui._visible is False


def _start_fake_webui(monkeypatch, silent_start):
    import types

    import src.webui as webui_module

    created = []

    def create_window(*args, **kwargs):
        window = _FakeWindow()
        created.append((window, kwargs))
        return window

    monkeypatch.setattr(webui_module, "HAS_WEBVIEW", True)
    monkeypatch.setattr(webui_module, "HAS_BOTTLE", True)
    monkeypatch.setattr(
        webui_module,
        "webview",
        types.SimpleNamespace(
            create_window=create_window,
            start=lambda **kwargs: None,
        ),
    )
    monkeypatch.setattr(webui_module.time, "sleep", lambda _: None)

    from src.webui import WebUI

    ui = WebUI(silent_start=silent_start)
    ui._cfg = _FakeConfig(True)
    monkeypatch.setattr(ui, "_setup_bottle", lambda: None)
    monkeypatch.setattr(ui, "_init_lan", lambda: None)
    assert ui.start()
    return ui, created


def test_webui_start_normal_visibility_hides_without_placement(monkeypatch):
    ui, created = _start_fake_webui(monkeypatch, silent_start=False)
    assert created[0][1]["hidden"] is False
    assert ui._visible is True

    def fail_if_called():
        raise AssertionError("visible hotkey toggle must not calculate placement")

    monkeypatch.setattr(ui, "_get_hotkey_window_position", fail_if_called)
    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("hide",)]
    assert ui._visible is False


def test_webui_start_silent_visibility_allows_hotkey_placement(monkeypatch):
    ui, created = _start_fake_webui(monkeypatch, silent_start=True)
    assert created[0][1]["hidden"] is True
    assert ui._visible is False
    monkeypatch.setattr(ui, "_get_hotkey_window_position", lambda: (40, 50))

    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("move", 40, 50), ("show",), ("focus",)]
    assert ui._visible is True


def test_app_routes_hotkey_and_tray_to_separate_zero_argument_methods():
    import inspect

    from src.main import OhMyMemeApp

    class FakeWebUI:
        def __init__(self):
            self.calls = []

        def toggle_hotkey_safe(self):
            self.calls.append("hotkey")

        def toggle_safe(self):
            self.calls.append("tray")

    app = OhMyMemeApp.__new__(OhMyMemeApp)
    app._webui = FakeWebUI()

    app._on_hotkey()
    assert app._webui.calls == ["hotkey"]

    app._on_tray_show()

    assert app._webui.calls == ["hotkey", "tray"]
    assert len(inspect.signature(app._on_hotkey).parameters) == 0
    assert len(inspect.signature(app._on_tray_show).parameters) == 0


def test_webui_html_exists():
    from src.webui import HTML_DIR

    assert HTML_DIR.exists()
    assert (HTML_DIR / "index.html").exists()
    html = (HTML_DIR / "index.html").read_text(encoding="utf-8")
    assert "OhMyMeme" in html
    assert "search" in html
    # 前端样式/脚本已从 HTML 拆分为独立静态文件
    assert (HTML_DIR / "index.css").exists()
    assert (HTML_DIR / "index.js").exists()
    assert (HTML_DIR / "settings.html").exists()
    assert (HTML_DIR / "settings.css").exists()
    assert (HTML_DIR / "settings.js").exists()
    assert 'src="/index.js"' in html
    assert 'href="/index.css"' in html
    settings_html = (HTML_DIR / "settings.html").read_text(encoding="utf-8")
    assert 'src="/settings.js"' in settings_html
    assert 'href="/settings.css"' in settings_html
    assert 'id="s-hotkey-show-at-mouse"' in settings_html
    settings_js = (HTML_DIR / "settings.js").read_text(encoding="utf-8")
    assert settings_js.count("s.hotkey_show_at_mouse === true") == 2
    assert "hotkey_show_at_mouse," in settings_js


def test_webui_safe_serve_filename():
    from src.webui import _safe_serve_filename

    for name in ("a.png", "表情.webp", "a b.gif", "abc123.gif"):
        assert _safe_serve_filename(name)
    for name in (
        "../evil.png",
        "..",
        ".",
        "dir/file.png",
        "/etc/passwd",
        "\\win\\x.png",
        "~/x.png",
        "",
        ".hidden",
    ):
        assert not _safe_serve_filename(name)


def test_webui_host_allowed():
    from src.webui import _host_allowed

    assert _host_allowed("127.0.0.1", 12345)
    assert _host_allowed("127.0.0.1:12345", 12345)
    assert _host_allowed("localhost:12345", 12345)
    assert not _host_allowed("evil.example.com", 12345)
    assert not _host_allowed("evil.example.com:12345", 12345)
    assert not _host_allowed("127.0.0.1:9999", 12345)
    assert not _host_allowed("", 12345)


def test_storage_dir_validation(tmp_path):
    from src.webui import _storage_dir_validation

    old = tmp_path / "old"
    old.mkdir()
    (old / "sub").mkdir()
    assert _storage_dir_validation(None, str(old))[0] is False
    assert _storage_dir_validation("", str(old))[0] is False
    assert _storage_dir_validation("rel/path", str(old))[0] is False
    assert _storage_dir_validation(str(old), str(old))[0] is False
    assert _storage_dir_validation(str(old / "sub"), str(old))[0] is False
    assert _storage_dir_validation(str(tmp_path), str(old))[0] is False
    assert _storage_dir_validation(str(tmp_path / "new"), str(old))[0] is True

    data = tmp_path / "data"
    assert _storage_dir_validation(str(data), str(old), (data,))[0] is False
    assert _storage_dir_validation(str(data / "x"), str(old), (data,))[0] is False
    assert _storage_dir_validation(str(tmp_path), str(old), (data,))[0] is False
    assert _storage_dir_validation(str(tmp_path / "ok"), str(old), (data,))[0] is True
