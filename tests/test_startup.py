"""启动流程测试 - pytest风格"""

import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["OHMYMEME_TEST"] = "1"

from ohmymeme.core.config import Config
from ohmymeme.core.crypto import decrypt_data, encrypt_data
from ohmymeme.core.database import MemeDB
from ohmymeme.integrations.platform.clipboard import copy_image_to_clipboard, copy_text
from ohmymeme.integrations.platform.hotkey import GlobalHotkey
from ohmymeme.integrations.platform.tray import _create_default_icon

ROOT = Path(__file__).resolve().parent.parent


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


def _fake_webui(hotkey_show_at_mouse, root, visible=False):
    from ohmymeme.app.container import Container

    container = Container(root)
    ui = container.create_webui()
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
    from ohmymeme.app.container import Container

    container = Container()
    w = container.create_webui()
    assert w._port > 0
    assert w._window is None
    assert not w.is_visible
    assert hasattr(w, "toggle_safe")
    assert hasattr(w, "show")
    assert hasattr(w, "hide")
    # JsApi
    api = w._api
    assert hasattr(api, "search_memes")
    assert hasattr(api, "get_tags")
    assert hasattr(api, "copy_meme")
    assert hasattr(api, "import_memes")


def test_find_hotkey_window_position_candidate_order():
    from ohmymeme.presentation.desktop.window_manager import (
        _find_hotkey_window_position,
    )

    work_area = (0, 0, 100, 100)
    assert _find_hotkey_window_position((10, 10), work_area, 30, 20) == (10, 10)
    assert _find_hotkey_window_position((80, 10), work_area, 30, 20) == (70, 10)
    assert _find_hotkey_window_position((10, 90), work_area, 30, 20) == (10, 80)
    assert _find_hotkey_window_position((80, 90), work_area, 30, 20) == (70, 80)


def test_find_hotkey_window_position_edge_equality_allowed():
    from ohmymeme.presentation.desktop.window_manager import (
        _find_hotkey_window_position,
    )

    assert _find_hotkey_window_position((70, 80), (0, 0, 100, 100), 30, 20) == (
        70,
        80,
    )


def test_find_hotkey_window_position_none_when_window_cannot_fit():
    from ohmymeme.presentation.desktop.window_manager import (
        _find_hotkey_window_position,
    )

    work_area = (-100, -50, 100, 50)
    assert _find_hotkey_window_position((0, 0), work_area, 201, 50) is None
    assert _find_hotkey_window_position((0, 0), work_area, 100, 101) is None


def test_toggle_hotkey_safe_moves_then_shows_hidden_window(monkeypatch, tmp_path):
    ui = _fake_webui(True, tmp_path)
    monkeypatch.setattr(ui, "_get_hotkey_window_position", lambda: (40, 50))

    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("move", 40, 50), ("show",), ("focus",)]
    assert ui._visible
    assert ui._hotkey_session


def test_hide_clears_hotkey_session(tmp_path):
    ui = _fake_webui(True, tmp_path)
    ui.toggle_hotkey_safe()

    ui.hide()

    assert not ui._hotkey_session


def test_tray_toggle_show_does_not_mark_hotkey_session(tmp_path):
    ui = _fake_webui(True, tmp_path)

    ui.toggle_safe()

    assert ui._visible
    assert not ui._hotkey_session


def test_ordinary_show_clears_existing_hotkey_session(tmp_path):
    ui = _fake_webui(True, tmp_path)
    ui.toggle_hotkey_safe()

    ui.show()

    assert not ui._hotkey_session


def test_schedule_hide_only_hides_hotkey_session(tmp_path):
    ui = _fake_webui(True, tmp_path / "visible", visible=True)
    ui.schedule_hide()
    ui._process_pending_hide()
    assert ui._visible is True

    ui = _fake_webui(True, tmp_path / "hidden")
    ui.toggle_hotkey_safe()
    ui.schedule_hide()
    ui._process_pending_hide()
    assert ui._visible is False


def test_toggle_hotkey_safe_hides_visible_window_without_placement(monkeypatch, tmp_path):
    ui = _fake_webui(True, tmp_path, visible=True)

    def fail_if_called():
        raise AssertionError("visible hotkey toggle must not calculate placement")

    monkeypatch.setattr(ui, "_get_hotkey_window_position", fail_if_called)

    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("hide",)]
    assert not ui._visible


def test_toggle_hotkey_safe_disabled_shows_without_placement(monkeypatch, tmp_path):
    ui = _fake_webui(False, tmp_path)

    def fail_if_called():
        raise AssertionError("disabled placement must not be calculated")

    monkeypatch.setattr(ui, "_get_hotkey_window_position", fail_if_called)

    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("show",), ("focus",)]
    assert ui._visible


def test_toggle_hotkey_safe_placement_exception_still_shows(monkeypatch, tmp_path):
    ui = _fake_webui(True, tmp_path)

    def fail_placement():
        raise RuntimeError("placement unavailable")

    monkeypatch.setattr(ui, "_get_hotkey_window_position", fail_placement)

    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("show",), ("focus",)]
    assert ui._visible


def test_successful_native_drag_requests_hide_only_for_hotkey_session(monkeypatch, tmp_path):
    import ohmymeme.integrations.platform.native_drag as native_drag

    ui = _fake_webui(True, tmp_path)
    monkeypatch.setattr(ui._api._catalog, "get_meme_filename", lambda _meme_id: "meme.png")
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


def test_successful_copy_requests_hide_only_for_hotkey_session(monkeypatch, tmp_path):
    import ohmymeme.presentation.desktop.window_manager as webui_module

    ui = _fake_webui(True, tmp_path)
    monkeypatch.setattr(ui._api._catalog, "get_meme_filename", lambda _meme_id: "meme.png")
    monkeypatch.setattr(ui._api, "_find_meme_file", lambda filename: filename)
    monkeypatch.setattr(webui_module, "copy_image_to_clipboard", lambda path: True)
    monkeypatch.setattr(ui, "_run_on_gui", lambda delay, func: func())

    ui.show()
    result = ui._api.copy_meme(1)
    assert result["ok"]
    assert result["status"] == "copied"
    assert ui._visible is True

    ui.hide()
    ui.toggle_hotkey_safe()
    assert ui._api.copy_meme(1)
    assert ui._visible is False


def _start_fake_webui(monkeypatch, tmp_path, silent_start):
    import types

    import ohmymeme.presentation.desktop.window_manager as webui_module

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

    from ohmymeme.app.container import Container

    ui = Container(tmp_path / "app").create_webui(silent_start=silent_start)
    ui._cfg = _FakeConfig(True)
    monkeypatch.setattr(ui, "_setup_bottle", lambda: None)
    monkeypatch.setattr(ui, "_init_lan", lambda: None)
    assert ui.start()
    return ui, created


def test_webui_start_normal_visibility_hides_without_placement(monkeypatch, tmp_path):
    ui, created = _start_fake_webui(monkeypatch, tmp_path, silent_start=False)
    assert created[0][1]["hidden"] is False
    assert ui._visible is True

    def fail_if_called():
        raise AssertionError("visible hotkey toggle must not calculate placement")

    monkeypatch.setattr(ui, "_get_hotkey_window_position", fail_if_called)
    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("hide",)]
    assert ui._visible is False


def test_webui_start_silent_visibility_allows_hotkey_placement(monkeypatch, tmp_path):
    ui, created = _start_fake_webui(monkeypatch, tmp_path, silent_start=True)
    assert created[0][1]["hidden"] is True
    assert ui._visible is False
    monkeypatch.setattr(ui, "_get_hotkey_window_position", lambda: (40, 50))

    ui.toggle_hotkey_safe()

    assert ui._window.calls == [("move", 40, 50), ("show",), ("focus",)]
    assert ui._visible is True


def test_app_routes_hotkey_and_tray_to_separate_zero_argument_methods():
    import inspect

    from ohmymeme.app.bootstrap import OhMyMemeApp

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


def test_package_main_is_the_only_bootstrap_callable():
    from ohmymeme.app.bootstrap import main as package_main

    assert package_main.__module__ == "ohmymeme.app.bootstrap"


def test_module_entrypoint_help_matches_bootstrap_main():
    root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "src")

    result = subprocess.run(
        [sys.executable, "-m", "ohmymeme", "--help"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--silent" in result.stdout
    assert "--debug-update" in result.stdout


def test_bootstrap_preserves_unknown_arguments(monkeypatch):
    from ohmymeme.app import bootstrap

    created = []

    class FakeApp:
        def __init__(self):
            created.append(self)

        def run(self):
            return None

    monkeypatch.setattr("ohmymeme.app.bootstrap.compose_app", lambda args: FakeApp())
    monkeypatch.setattr(sys, "argv", ["ohmymeme", "--unknown-benign-flag"])

    bootstrap.main()

    assert len(created) == 1


def test_windows_auto_start_rewrites_legacy_source_command(monkeypatch):
    import types

    from ohmymeme.integrations.platform import system as platform_util

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    legacy_module = "src" + ".main"
    values = {"OhMyMeme": f'"C:\\Python\\python.exe" -m {legacy_module} --silent'}
    registry = types.SimpleNamespace(
        HKEY_CURRENT_USER=object(),
        KEY_QUERY_VALUE=1,
        KEY_SET_VALUE=2,
        REG_SZ=1,
        OpenKey=lambda *args: FakeKey(),
        QueryValueEx=lambda key, name: (values[name], 1),
        SetValueEx=lambda key, name, reserved, kind, value: values.__setitem__(
            name, value
        ),
    )
    monkeypatch.setitem(sys.modules, "winreg", registry)
    monkeypatch.setattr(platform_util.platform, "system", lambda: "Windows")
    monkeypatch.setattr(platform_util.sys, "executable", r"C:\Python\python.exe")
    monkeypatch.setattr(platform_util.sys, "frozen", False, raising=False)

    assert platform_util.is_auto_start_enabled()
    assert values["OhMyMeme"] == '"C:\\Python\\python.exe" -m ohmymeme --silent'


def test_webui_html_exists():
    from ohmymeme.presentation.desktop.window_manager import HTML_DIR

    root = Path(__file__).resolve().parent.parent
    frontend = root / "src" / "ohmymeme" / "presentation" / "frontend"
    assert HTML_DIR.exists()
    vue_html = (HTML_DIR / "vue.html").read_text(encoding="utf-8")
    assert 'id="app-mount"' in vue_html
    assert 'src="/dist/ohmymeme.js"' in vue_html
    settings_html = (HTML_DIR / "vue-settings.html").read_text(encoding="utf-8")
    assert 'id="app-mount"' in settings_html
    assert 'src="/dist/settings-vue.js"' in settings_html
    # 插件详情页 iframe 协议资产保留（非 Vue 入口也不删除）
    assert (HTML_DIR / "import-frame.js").exists()
    # 两窗口页面路由只返回 Vue 入口，产物缺失返回 503，不再回退旧 index/settings
    desktop = (
        root
        / "src"
        / "ohmymeme"
        / "presentation"
        / "desktop"
        / "window_manager.py"
    ).read_text(encoding="utf-8")
    assert '"vue.html"' in desktop and '"vue-settings.html"' in desktop
    assert '"index.html"' not in desktop
    assert '"settings.html"' not in desktop
    settings_vue = frontend / "settings-vue"
    assert (settings_vue / "app" / "SettingsShell.vue").exists()
    assert (settings_vue / "shared" / "bridge.ts").exists()
    assert (settings_vue / "shared" / "plugin-ui.ts").exists()
    assert (settings_vue / "shared" / "store.ts").exists()
    shell = (settings_vue / "app" / "SettingsShell.vue").read_text(encoding="utf-8")
    for label in (
        "基础设置",
        "导入",
        "联网",
        "危险操作",
        "日志",
        "备份与恢复",
        "插件",
        "关于",
    ):
        assert label in shell
    import_group = settings_vue / "features" / "import"
    for wizard in (
        "QqWizard.vue",
        "QqntWizard.vue",
        "TelegramWizard.vue",
        "DouyinWizard.vue",
        "WechatWizard.vue",
    ):
        assert (import_group / wizard).exists()
    assert (settings_vue / "features" / "network" / "NetworkGroup.vue").exists()
    assert (settings_vue / "features" / "plugins" / "PluginsGroup.vue").exists()
    package = (root / "package.json").read_text(encoding="utf-8")
    assert (
        '"build": "vite build && vite build --config vite.settings.config.ts"'
        in package
    )
    assert (
        '"build:settings": "vite build --config vite.settings.config.ts"' in package
    )
    assert "build_settings.mjs" not in package


def test_vue_main_window_feature_layout_static_contract():
    root = Path(__file__).resolve().parent.parent
    frontend = root / "src" / "ohmymeme" / "presentation" / "frontend" / "main"
    vite_config = (root / "vite.config.ts").read_text(encoding="utf-8")
    vue_html = (root / "src" / "webui" / "vue.html").read_text(encoding="utf-8")
    app_shell = (frontend / "app" / "App.vue").read_text(encoding="utf-8")
    main_window = (frontend / "app" / "MainWindow.vue").read_text(encoding="utf-8")
    entry = (frontend / "app" / "main.ts").read_text(encoding="utf-8")
    bridge = frontend / "shared" / "bridge.ts"

    assert "presentation/frontend/main/app/main.ts" in vite_config
    assert "src/webui/dist" in vite_config
    assert "entryFileNames: 'ohmymeme.js'" in vite_config
    assert "inlineDynamicImports: true" in vite_config
    assert "format: 'iife'" in vite_config
    assert 'id="app-mount"' in vue_html
    assert 'src="/dist/ohmymeme.js"' in vue_html
    assert "window.focusSearch" in entry
    assert "window.showLanDeviceConfirm" in entry
    assert 'v-for="c in visibleCollections"' in main_window
    assert "c.id !== -4 || (c.count || 0) > 0" in main_window
    assert "<MainWindow />" in app_shell
    assert "await loadInitData()" in main_window
    assert main_window.index("api('rescan_cache')") < main_window.index(
        "api('run_auto_sync')"
    )
    assert "setTimeout(runBackground, 300)" in main_window
    assert "pointercancel" in main_window
    assert "reorder_collection_members" in (
        frontend / "features" / "memes" / "useMemes.ts"
    ).read_text(encoding="utf-8")
    assert "start_native_drag" in (
        frontend / "features" / "memes" / "useMemes.ts"
    ).read_text(encoding="utf-8")

    raw_bridge_users = [
        path
        for path in frontend.rglob("*.*")
        if path.suffix in {".ts", ".vue"}
        and (
            "pywebview.api" in path.read_text(encoding="utf-8")
            or "window.pywebview" in path.read_text(encoding="utf-8")
        )
    ]
    assert raw_bridge_users == [bridge]


def test_sorting_visual_feedback_static_contract():
    # 现用主窗口前端为 Vue：排序/多选语义读取 MainWindow.vue/useMemes.ts/useDragSort.ts/style.css
    root = Path(__file__).resolve().parent.parent
    main = root / "src" / "ohmymeme" / "presentation" / "frontend" / "main"
    style_css = (main / "app" / "style.css").read_text(encoding="utf-8")
    main_window = (main / "app" / "MainWindow.vue").read_text(encoding="utf-8")
    use_memes = (main / "features" / "memes" / "useMemes.ts").read_text(
        encoding="utf-8"
    )
    use_drag = (main / "features" / "sorting" / "useDragSort.ts").read_text(
        encoding="utf-8"
    )

    def rule(selector):
        match = re.search(
            re.escape(selector) + r"\s*\{(?:(?!\}).)*?\}", style_css, re.DOTALL
        )
        assert match, f"sorting styles must remain locally inspectable: {selector}"
        return match.group(0)

    # 初始全视图：分组为空且 activeCollection 为 null
    assert re.search(r"\bcollections:\s*\[\]", use_memes)
    assert re.search(r"\bactiveCollection:\s*null\b", use_memes)

    # 网格容器：纵向滚动 + 预留排序描边空间
    grid_wrap = rule("#grid-wrap")
    assert re.search(r"overflow-y\s*:\s*auto", grid_wrap)
    assert re.search(r"padding\s*:\s*10px", grid_wrap)
    meme_grid = rule("#meme-grid,\n.meme-grid")
    assert re.search(
        r"grid-template-columns\s*:\s*repeat\(auto-fill, minmax\(112px, 1fr\)\)",
        meme_grid,
    )
    assert re.search(r"gap\s*:\s*10px", meme_grid)

    # 排序模式卡片：缩放 + 描边
    sorting_rule = rule("#meme-grid.sort-enabled .meme-card")
    assert re.search(r"transform\s*:\s*scale\(0\.95\)", sorting_rule)
    assert re.search(
        r"outline\s*:\s*3px\s+solid\s+var\(--border-light\)", sorting_rule
    )
    assert re.search(r"outline-offset\s*:\s*3px", sorting_rule)

    # 稳定卡晃动：排除拖拽/FLIP/入场态，用独立 rotate 属性（不得用 transform）
    shake_selector = (
        "#meme-grid.sort-enabled:not(.drag-active) "
        ".meme-card:not(.dragging):not(.sort-enter)"
    )
    shake_rule = rule(shake_selector)
    assert re.search(r"animation\s*:\s*sort-shake\s+", shake_rule)
    assert "transform" not in shake_rule, (
        "sorting shake must use the independent rotate property so it cannot replace "
        "drag or FLIP transforms"
    )
    shake_keyframes = re.search(
        r"@keyframes\s+sort-shake\s*\{(?P<body>.*?)\n\}",
        style_css,
        re.DOTALL,
    )
    assert shake_keyframes, "sorting shake must define named keyframes"
    assert re.search(r"rotate\s*:\s*-0\.75deg", shake_keyframes.group("body"))
    assert re.search(r"rotate\s*:\s*0\.75deg", shake_keyframes.group("body"))

    # reduced-motion 尊重
    reduced_motion = re.search(
        r"@media\s*\(prefers-reduced-motion\s*:\s*reduce\)\s*\{(?P<body>.*?)\n\}",
        style_css,
        re.DOTALL,
    )
    assert reduced_motion, "sorting shake must respect reduced-motion preferences"
    assert shake_selector in reduced_motion.group("body")
    assert re.search(r"animation\s*:\s*none", reduced_motion.group("body"))
    assert re.search(r"rotate\s*:\s*0deg", reduced_motion.group("body"))

    # 拖拽中取消过渡
    dragging = rule("#meme-grid.sort-enabled .meme-card.dragging")
    assert re.search(r"transition\s*:\s*none", dragging)

    # FLIP 让位：TransitionGroup name="meme-list" + .meme-list-move 过渡
    assert re.search(r'name="meme-list"', main_window)
    flip = rule(".meme-list-move")
    assert re.search(r"transition\s*:\s*transform\s+0\.2s\s+ease", flip)

    # 拖拽原位缩放 0.90；不得叠加 scale
    assert re.search(r"scale\(0\.90\)", use_drag)
    assert not re.search(r"scale\([^)]*\)\s+scale\(", use_drag)
    assert "slotOrigin" in use_drag

    # 网格几何：无变换布局尺寸 + 计算 padding + 客户端宽度
    assert "offsetWidth" in use_drag
    assert "offsetHeight" in use_drag, (
        "grid slot geometry must use untransformed layout dimensions so sorting scale "
        "cannot shift drag insertion slots"
    )
    assert re.search(r"getComputedStyle\(\s*grid\s*\)", use_drag)
    assert re.search(r"padding(?:Left|Right)", use_drag)
    assert re.search(r"grid\.clientWidth\s*-\s*paddingLeft", use_drag)

    grid_slot = re.search(
        r"function gridSlotIndex\([^)]*\)\s*\{(?P<body>.*?)\n\}",
        use_drag,
        re.DOTALL,
    )
    assert grid_slot, "grid slot index must remain locally inspectable"
    grid_slot_body = grid_slot.group("body")
    assert "originX" in use_drag and "originY" in use_drag
    assert re.search(r"x\s*-\s*m\.originX", grid_slot_body)
    assert re.search(r"y\s*-\s*m\.originY", grid_slot_body)
    assert not re.search(r"gRect\.(?:left|top)", grid_slot_body)

    # 持久化：分组内走 reorder_collection_members；全部/未分类走 reorder_memes
    assert re.search(r"reorder_collection_members", use_memes)
    assert re.search(r"reorder_memes", use_memes)
    assert re.search(
        r"state\.activeCollection\s*&&\s*state\.activeCollection\s*>\s*0",
        use_memes,
    )
    assert re.search(r"persistFn\(ids\)", use_drag)

    # 排序资格：搜索/标签禁用；全部/未分类/正 ID 可排
    assert re.search(r"q\s*\|\|\s*state\.activeTags\.size\s*>\s*0", use_memes)
    assert re.search(
        r"state\.activeCollection\s*===\s*null\s*\|\|\s*"
        r"state\.activeCollection\s*===\s*-4\s*\|\|\s*"
        r"state\.activeCollection\s*>\s*0",
        use_memes,
    )

    # MainWindow 绑定：sort-enabled 仅在可排序时启用；多选独立；复制被整理/多选守卫
    assert re.search(
        r"'sort-enabled':\s*sortEnabled\s*&&\s*canReorder\(\)", main_window
    )
    assert re.search(r"'select-enabled':\s*selectMode", main_window)
    assert 'class="meme-card folder-card"' in main_window.split("<drag-select", 1)[0]
    toggle_sort = re.search(
        r"function toggleSort\(\)\s*\{(?P<body>.*?)\n\}", main_window, re.DOTALL
    )
    assert toggle_sort, "toolbar sort toggle must remain locally inspectable"
    assert re.search(r"selectMode\.value\s*=\s*false", toggle_sort.group("body"))
    assert re.search(r"drag\.enable\(\)", toggle_sort.group("body"))
    assert re.search(
        r"if\s*\(sortEnabled\.value\s*\|\|\s*selectMode\.value\)\s*return",
        main_window,
    )


def test_grid_slot_hit_testing_stays_aligned_when_layout_moves_and_scrolls():
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        ["node", root / "tests" / "fixtures" / "grid_slot_probe.cjs"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "grid slot behavior: PASS"


def test_webui_safe_serve_filename():
    from ohmymeme.presentation.desktop.window_manager import _safe_serve_filename

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
    from ohmymeme.presentation.desktop.window_manager import _host_allowed

    assert _host_allowed("127.0.0.1", 12345)
    assert _host_allowed("127.0.0.1:12345", 12345)
    assert _host_allowed("localhost:12345", 12345)
    assert not _host_allowed("evil.example.com", 12345)
    assert not _host_allowed("evil.example.com:12345", 12345)
    assert not _host_allowed("127.0.0.1:9999", 12345)
    assert not _host_allowed("", 12345)


def test_storage_dir_validation(tmp_path):
    from ohmymeme.presentation.desktop.window_manager import _storage_dir_validation

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


def test_storage_move_save_failure_rolls_back_files_and_config(tmp_path):
    from ohmymeme.app.container import Container

    data_dir = tmp_path / "data"
    with patch("ohmymeme.core.config._get_data_dir", return_value=data_dir):
        cfg = Config(tmp_path / "config.json")
        old = cfg.cache_dir
        source = old / "nested" / "meme.png"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"meme")
        destination = tmp_path / "destination"
        container = Container(tmp_path / "container")
        api = container.create_webui()._settings_api
        api._cfg = cfg

        with patch(
            "ohmymeme.core.config.Config.save", side_effect=OSError("disk full")
        ):
            result = api.apply_storage_dir(str(destination), move_files=True)

    assert result["ok"] is False
    assert source.read_bytes() == b"meme"
    assert not (destination / "nested" / "meme.png").exists()
    assert cfg.get("cache_dir") == ""
