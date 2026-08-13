"""启动流程测试 - pytest风格"""

import os
import re
import subprocess
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


def test_ordinary_show_clears_existing_hotkey_session():
    ui = _fake_webui(True)
    ui.toggle_hotkey_safe()
    ui._paste_target = object()

    ui.show()

    assert not ui._hotkey_session
    assert ui._paste_target is None


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


def test_non_hotkey_copy_completion_releases_pending_paste_state():
    ui = _fake_webui(True)
    ui._copy_pending = True
    ui._pending_paste_target = object()

    result = ui.schedule_copy_hide()

    assert result["ok"]
    assert result["status"] == "copied"
    assert not ui._copy_pending
    assert ui._pending_paste_target is None


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
    result = ui._api.copy_meme(1)
    assert result["ok"]
    assert result["status"] == "copied"
    assert ui._visible is True
    assert not ui._copy_pending
    assert ui._pending_paste_target is None

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


def test_sorting_visual_feedback_static_contract():
    root = Path(__file__).resolve().parent.parent
    index_js = (root / "src" / "webui" / "index.js").read_text(encoding="utf-8")
    index_css = (root / "src" / "webui" / "index.css").read_text(encoding="utf-8")

    assert re.search(
        r"let\s+collections\s*=\s*\[\]\s*,\s*activeCollection\s*=\s*null\s*;",
        index_js,
    ), "the initial view must remain the all-memes view"

    grid_wrap = re.search(r"#grid-wrap\s*\{(?:(?!\}).)*?\}", index_css, re.DOTALL)
    assert grid_wrap, "grid wrapper styles must remain locally inspectable"
    assert re.search(r"overflow-y\s*:\s*scroll", grid_wrap.group(0))
    assert re.search(r"overflow-x\s*:\s*hidden", grid_wrap.group(0))

    meme_grid = re.search(r"#meme-grid\s*\{(?:(?!\}).)*?\}", index_css, re.DOTALL)
    assert meme_grid, "meme grid styles must remain locally inspectable"
    grid_padding = re.search(r"padding\s*:\s*([^;]+)", meme_grid.group(0))
    assert grid_padding, "meme grid must reserve space for sorting outlines"
    padding_values = [
        float(value)
        for value in re.findall(r"(?:^|\s)(\d+(?:\.\d+)?)px", grid_padding.group(1))
    ]
    assert len(padding_values) in (1, 2, 3, 4)
    if len(padding_values) == 1:
        padding_top = padding_right = padding_bottom = padding_left = padding_values[0]
    elif len(padding_values) == 2:
        padding_top = padding_bottom = padding_values[0]
        padding_right = padding_left = padding_values[1]
    elif len(padding_values) == 3:
        padding_top, padding_right, padding_bottom = padding_values
        padding_left = padding_right
    else:
        padding_top, padding_right, padding_bottom, padding_left = padding_values
    assert padding_top >= 6
    assert padding_right >= 6
    assert padding_left >= 6
    assert padding_bottom >= 6

    card_rule = re.search(r"\.meme-card\s*\{(?:(?!\}).)*?\}", index_css, re.DOTALL)
    assert card_rule, "meme card base styles must remain locally inspectable"
    assert re.search(r"outline\s*:\s*0\s+solid\s+transparent", card_rule.group(0))
    assert re.search(r"outline-offset\s*:\s*3px", card_rule.group(0))
    transition = re.search(r"transition\s*:\s*([^;]+)", card_rule.group(0))
    assert transition, "meme card transitions must remain locally inspectable"
    transition_value = transition.group(1)
    for property_name in ("transform", "outline-color", "outline-width"):
        assert re.search(rf"\b{property_name}\s+var\(--transition\)", transition_value)

    render_grid = re.search(
        r"function renderGrid\(\)\s*\{(?:(?!\n\}).)*\n\}", index_js, re.DOTALL
    )
    assert render_grid, "renderGrid must remain locally inspectable"
    render_grid_body = render_grid.group(0)
    assert re.search(r"const\s+sortEnabled\s*=\s*canReorderMemes\(\)", render_grid_body)
    remove_sort = re.search(
        r"grid\.classList\.remove\(\s*['\"]sort-enabled['\"]\s*\)",
        render_grid_body,
    )
    clear_grid = re.search(r"grid\.innerHTML\s*=\s*['\"]['\"]", render_grid_body)
    assert remove_sort and clear_grid
    assert remove_sort.start() < clear_grid.start()

    animation = re.search(
        r"requestAnimationFrame\(\s*\(\)\s*=>\s*\{(?P<body>.*?)\}\s*\)\s*;",
        render_grid_body,
        re.DOTALL,
    )
    assert animation, "sorting state must be applied in requestAnimationFrame"
    animation_body = animation.group("body")
    assert re.search(
        r"if\s*\(\s*renderToken\s*!==\s*gridRenderToken\s*\)\s*return\s*;",
        animation_body,
    ), "stale render callbacks must be ignored"
    assert re.search(
        r"grid\.classList\.toggle\(\s*['\"]sort-enabled['\"]\s*,\s*sortEnabled\s*\)",
        animation_body,
    )

    can_reorder = re.search(
        r"function canReorderMemes\(\)\s*\{(?:(?!\n\}).)*\n\}", index_js, re.DOTALL
    )
    assert can_reorder, "sorting eligibility must remain locally inspectable"
    can_reorder_body = can_reorder.group(0)
    assert re.search(
        r"if\s*\(\s*q\s*\|\|\s*activeTags\.size\s*>\s*0\s*\)\s*return\s*false",
        can_reorder_body,
    )
    assert re.search(
        r"if\s*\(\s*!dragSortEnabled\s*\)\s*return\s*false", can_reorder_body
    )
    assert re.search(
        r"return\s+activeCollection\s*===\s*null\s*\|\|\s*" r"activeCollection\s*>\s*0",
        can_reorder_body,
    )
    assert re.search(
        r"if\s*\(\s*activeCollection\s*>\s*0\s*\)\s*\{\s*"
        r"ok\s*=\s*await\s+api\(\s*['\"]reorder_collection_members['\"]\s*,\s*"
        r"activeCollection",
        index_js,
        re.DOTALL,
    ), "sortable collections must persist their member order through the active collection"
    assert re.search(
        r"else\s*\{\s*ok\s*=\s*await\s+api\(\s*['\"]reorder_memes['\"]\s*,\s*"
        r"memes\.map\(\s*x\s*=>\s*x\.id\s*\)",
        index_js,
        re.DOTALL,
    ), "the all-memes view must persist its global order through reorder_memes"

    normal_card_selector = (
        "#meme-grid.sort-enabled .meme-card:not(.folder-card):not(.dragging)"
    )
    sorting_rule = re.search(
        re.escape(normal_card_selector) + r"\s*\{(?:(?!\}).)*?\}",
        index_css,
        re.DOTALL,
    )
    assert (
        sorting_rule
    ), "sorting feedback must target only ordinary, non-dragging cards"
    assert re.search(r"transform\s*:\s*scale\(0\.95\)", sorting_rule.group(0))
    assert re.search(
        r"outline\s*:\s*3px\s+solid\s+var\(--border-light\)", sorting_rule.group(0)
    )
    assert re.search(r"outline-offset\s*:\s*[^;]+", sorting_rule.group(0))

    shake_selector = (
        "#meme-grid.sort-enabled:not(.drag-active) "
        ".meme-card:not(.folder-card):not(.dragging):not(.sort-enter)"
    )
    shake_rule = re.search(
        re.escape(shake_selector) + r"\s*\{(?:(?!\}).)*?\}",
        index_css,
        re.DOTALL,
    )
    assert shake_rule, "sorting shake must exclude drag, FLIP, folder, and entry states"
    assert re.search(r"animation\s*:\s*sort-shake\s+[^;]+", shake_rule.group(0))
    assert "transform" not in shake_rule.group(0), (
        "sorting shake must use the independent rotate property so it cannot replace "
        "drag or FLIP transforms"
    )
    shake_keyframes = re.search(
        r"@keyframes\s+sort-shake\s*\{(?P<body>.*?)\n\}",
        index_css,
        re.DOTALL,
    )
    assert shake_keyframes, "sorting shake must define named keyframes"
    assert re.search(r"rotate\s*:\s*-?0\.75deg", shake_keyframes.group("body"))
    assert re.search(r"rotate\s*:\s*0\.75deg", shake_keyframes.group("body"))
    reduced_motion = re.search(
        r"@media\s*\(prefers-reduced-motion\s*:\s*reduce\)\s*\{(?P<body>.*?)\n\}",
        index_css,
        re.DOTALL,
    )
    assert reduced_motion, "sorting shake must respect reduced-motion preferences"
    assert shake_selector in reduced_motion.group("body")
    assert re.search(r"animation\s*:\s*none", reduced_motion.group("body"))
    assert re.search(r"rotate\s*:\s*0deg", reduced_motion.group("body"))

    toggle_sort = re.search(
        r"function toggleDragSort\(\)\s*\{(?P<body>.*?)\n\}",
        index_js,
        re.DOTALL,
    )
    assert toggle_sort, "toolbar sort toggle must remain locally inspectable"
    toggle_sort_body = toggle_sort.group("body")
    assert re.search(r"if\s*\(\s*dragSortEnabled\s*\)", toggle_sort_body)
    enable_branch = re.search(
        r"if\s*\(\s*dragSortEnabled\s*\)\s*\{(?P<body>.*?)\}",
        toggle_sort_body,
        re.DOTALL,
    )
    assert enable_branch, "enabling sort must have a distinct branch"
    assert re.search(r"refreshMemes\s*\(\s*\)", enable_branch.group("body"))

    disable_branch = toggle_sort_body[enable_branch.end() :]
    assert not re.search(r"refreshMemes\s*\(\s*\)", disable_branch)
    assert not re.search(r"grid\.innerHTML\s*=", disable_branch)
    assert re.search(r"\+\+\s*gridRenderToken", disable_branch)
    disable_animation = re.search(
        r"requestAnimationFrame\(\s*\(\)\s*=>\s*\{(?P<body>.*?)\}\s*\)",
        disable_branch,
        re.DOTALL,
    )
    assert disable_animation, "disabling sort must defer exit feedback removal"
    disable_animation_body = disable_animation.group("body")
    assert re.search(
        r"if\s*\(\s*\w+\s*!==\s*gridRenderToken\s*\|\|\s*dragSortEnabled\s*\)\s*return\s*;",
        disable_animation_body,
    )
    assert re.search(
        r"grid\.classList\.remove\(\s*['\"]sort-enabled['\"]\s*\)",
        disable_animation_body,
    )

    sort_enter_selector = (
        "#meme-grid.sort-enabled .meme-card.sort-enter:not(.folder-card):not(.dragging)"
    )
    sort_enter_rule = re.search(
        re.escape(sort_enter_selector) + r"\s*\{(?:(?!\}).)*?\}",
        index_css,
        re.DOTALL,
    )
    assert (
        sort_enter_rule
    ), "pagination entry feedback must have a matching CSS baseline"
    assert re.search(r"transform\s*:\s*scale\(1\)", sort_enter_rule.group(0))
    assert re.search(r"outline\s*:\s*0\s+solid\s+transparent", sort_enter_rule.group(0))
    assert re.search(r"outline-offset\s*:\s*3px", sort_enter_rule.group(0))

    load_more = re.search(
        r"async function loadMoreMemes\(\)\s*\{.*?\n\}\s*\n\s*"
        r"async function refreshTags",
        index_js,
        re.DOTALL,
    )
    assert load_more, "pagination loader must remain locally inspectable"
    load_more_body = load_more.group(0)
    assert re.search(r"if\s*\(\s*sortEnabled\s*\)\s*cards\.forEach\(", load_more_body)
    assert re.search(
        r"cards\.forEach\(\s*card\s*=>\s*card\.classList\.add\(\s*['\"]sort-enter['\"]\s*\)\s*\)",
        load_more_body,
    )
    assert re.search(
        r"requestAnimationFrame\(\s*\(\)\s*=>\s*\{\s*cards\.forEach\(\s*card\s*=>\s*card\.classList\.remove\(\s*['\"]sort-enter['\"]\s*\)\s*\)\s*;?\s*\}\s*\)",
        load_more_body,
        re.DOTALL,
    )
    layout_read = (
        r"(?:getBoundingClientRect\(\)|offset(?:Width|Height)|client(?:Width|Height))"
    )
    pagination_append = re.search(
        r"cards\.forEach\(\s*card\s*=>\s*grid\.appendChild\(\s*card\s*\)\s*\)",
        load_more_body,
    )
    pagination_animation = re.search(r"requestAnimationFrame\(", load_more_body)
    assert pagination_append and pagination_animation
    assert re.search(
        layout_read,
        load_more_body[pagination_append.end() : pagination_animation.start()],
    ), "pagination sort baseline must commit layout before requestAnimationFrame"

    drag_scales = [
        float(scale)
        for scale in re.findall(
            r"d\.card\.style\.transform\s*=\s*['\"][^'\"]*?translate\([^)]*\)\s*"
            r"scale\((0?\.\d+)\)",
            index_js,
        )
    ]
    assert drag_scales == [0.90, 0.90]
    assert re.search(
        r"c\.style\.transform\s*=\s*[^;]+?scale\(0\.95\)",
        index_js,
    ), "FLIP displacement must preserve the sorting-mode baseline scale"
    assert not re.search(r"scale\([^)]*\)\s*scale\(", index_js)
    assert (
        "#meme-grid.drag-active .meme-card:not(.folder-card):not(.dragging)"
        in index_css
    )

    grid_metrics = re.search(
        r"function gridMetrics\(\)\s*\{(?:(?!\n\}).)*\n\}", index_js, re.DOTALL
    )
    assert grid_metrics, "grid slot metrics must remain locally inspectable"
    assert "offsetWidth" in grid_metrics.group(0)
    assert "offsetHeight" in grid_metrics.group(0), (
        "grid slot geometry must use untransformed layout dimensions so sorting scale "
        "cannot shift drag insertion slots"
    )
    grid_metrics_body = grid_metrics.group(0)
    assert re.search(r"getComputedStyle\(\s*grid\s*\)", grid_metrics_body)
    assert re.search(r"padding(?:Left|Right)", grid_metrics_body)
    assert re.search(
        r"(?:grid\.clientWidth|(?:gRect|gridRect)\.width)\s*-\s*"
        r"[^;]*padding(?:Left|left)[^;]*padding(?:Right|right)",
        grid_metrics_body,
    ), "grid columns must use usable width after computed horizontal padding"

    grid_slot = re.search(
        r"function gridSlotIndex\(x, y\)\s*\{(?:(?!\n\}).)*\n\}",
        index_js,
        re.DOTALL,
    )
    assert grid_slot, "grid slot index must remain locally inspectable"
    grid_slot_body = grid_slot.group(0)
    assert "originX" in grid_metrics_body and "originY" in grid_metrics_body
    assert re.search(r"x\s*-\s*originX", grid_slot_body)
    assert re.search(r"y\s*-\s*originY", grid_slot_body)
    assert not re.search(r"gRect\.left|gRect\.top", grid_slot_body)
    initial_append = re.search(
        r"memes\.forEach\(\s*m\s*=>\s*grid\.appendChild\(\s*renderMemeCard\(\s*m\s*\)\s*\)\s*\)",
        render_grid_body,
    )
    initial_animation = re.search(r"requestAnimationFrame\(", render_grid_body)
    assert initial_append and initial_animation
    assert re.search(
        layout_read,
        render_grid_body[initial_append.end() : initial_animation.start()],
    ), "initial sort baseline must commit layout before requestAnimationFrame"


def test_grid_slot_hit_testing_stays_aligned_when_layout_moves_and_scrolls():
    root = Path(__file__).resolve().parent.parent
    probe = r"""
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('src/webui/index.js', 'utf8');
const start = source.indexOf('function memeCardsInGrid()');
const end = source.indexOf('function moveInArray(', start);
if (start < 0 || end < 0) throw new Error('drag geometry helpers not found');

const folder = { classList: { contains: name => name === 'folder-card' } };
const meme = () => ({
  offsetWidth: 100,
  offsetHeight: 80,
  classList: { contains: () => false },
});
const memes = [meme(), meme(), meme(), meme(), meme()];
const allCards = [folder, ...memes];
const layout = { left: 200, top: 100 };
const grid = {
  clientLeft: 0,
  clientTop: 0,
  clientWidth: 340,
  getBoundingClientRect: () => ({ left: layout.left, top: layout.top }),
};
folder.offsetLeft = 218;
folder.offsetTop = 110;

const context = {
  document: {
    getElementById: id => {
      if (id !== 'meme-grid') throw new Error('unexpected element id: ' + id);
      return grid;
    },
    querySelectorAll: selector => selector.includes(':not(.folder-card)') ? memes : allCards,
  },
  getComputedStyle: () => ({
    paddingLeft: '10px',
    paddingRight: '10px',
    paddingTop: '10px',
    columnGap: '10px',
    rowGap: '20px',
  }),
};
vm.createContext(context);
vm.runInContext(source.slice(start, end), context);

function assertSlot(label, x, y, expected) {
  const actual = context.gridSlotIndex(x, y);
  if (actual !== expected) {
    throw new Error(label + ': expected meme index ' + expected + ', got ' + actual);
  }
}

function assertVisibleSlots(label) {
  const originX = layout.left + 10;
  const originY = layout.top + 10;
  assertSlot(label + ' first meme after folder', originX + 110 + 50, originY + 40, 0);
  assertSlot(label + ' third meme on next row', originX + 50, originY + 100 + 40, 2);
}

assertVisibleSlots('expanded sidebar');
layout.left = 20;
assertVisibleSlots('collapsed sidebar');
layout.top = -90;
assertVisibleSlots('scrolled grid');
assertSlot('head clamp', -1000, -1000, 0);
assertSlot('tail clamp', 10000, 10000, 4);
console.log('grid slot behavior: PASS');
"""
    result = subprocess.run(
        ["node", "-e", probe],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "grid slot behavior: PASS"


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
