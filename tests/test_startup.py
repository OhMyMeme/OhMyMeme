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
    # 现用主窗口前端为 Vue：排序/框选语义读取 MainWindow.vue/useMemes.ts/useDragSort.ts/gridInteraction.ts/style.css
    root = Path(__file__).resolve().parent.parent
    main = root / "src" / "ohmymeme" / "presentation" / "frontend" / "main"
    style_css = (main / "app" / "style.css").read_text(encoding="utf-8")
    main_window = (main / "app" / "MainWindow.vue").read_text(encoding="utf-8")
    main_ts = (main / "app" / "main.ts").read_text(encoding="utf-8")
    use_memes = (main / "features" / "memes" / "useMemes.ts").read_text(
        encoding="utf-8"
    )
    use_drag = (main / "features" / "sorting" / "useDragSort.ts").read_text(
        encoding="utf-8"
    )
    grid_interaction = (main / "features" / "sorting" / "gridInteraction.ts").read_text(
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

    # 网格容器：唯一滚动容器 + 关闭浏览器滚动锚定（virtua 前置要求）
    grid_wrap = rule("#grid-wrap")
    assert re.search(r"overflow-y\s*:\s*auto", grid_wrap)
    assert re.search(r"padding\s*:\s*10px", grid_wrap)
    assert re.search(r"overflow-anchor\s*:\s*none", grid_wrap)

    # folder 网格不虚拟化：保留最小卡宽 112px 与 10px 间隙契约
    folder_grid = rule(".meme-grid")
    assert re.search(
        r"grid-template-columns\s*:\s*repeat\(auto-fill, minmax\(112px, 1fr\)\)",
        folder_grid,
    )
    assert re.search(r"gap\s*:\s*10px", folder_grid)

    # 外层网格容器改为 block（真实排版在虚拟行内），保留几何 gap 供拖拽引擎读取
    outer_grid = rule("#meme-grid")
    assert re.search(r"display\s*:\s*block", outer_grid)
    assert re.search(r"column-gap\s*:\s*10px", outer_grid)
    assert re.search(r"row-gap\s*:\s*10px", outer_grid)

    # 虚拟行：按脚本列数切分并保留 10px 列间隙
    virtual_row = rule(".virtual-meme-row")
    assert re.search(
        r"grid-template-columns\s*:\s*repeat\(var\(--meme-cols\), minmax\(0, 1fr\)\)",
        virtual_row,
    )
    assert re.search(r"column-gap\s*:\s*10px", virtual_row)

    # 排序模式卡片：缩放 + 描边
    sorting_rule = rule("#meme-grid.sort-enabled .meme-card")
    assert re.search(r"transform\s*:\s*scale\(0\.95\)", sorting_rule)
    assert re.search(
        r"outline\s*:\s*3px\s+solid\s+var\(--gray-7\)", sorting_rule
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

    # FLIP 让位：行级 TransitionGroup name="meme-list" + .meme-list-move 过渡
    assert re.search(r'name="meme-list"', main_window)
    flip = rule(".meme-list-move")
    assert re.search(r"transition\s*:\s*transform\s+0\.2s\s+ease", flip)
    # 行级 TransitionGroup 位于 Virtualizer 默认插槽内；#meme-grid 仍是唯一外层节点
    assert "<Virtualizer" in main_window
    assert main_window.index("<Virtualizer") < main_window.index('name="meme-list"')
    assert re.search(r'<TransitionGroup\s+:key="row\.key"', main_window)

    # 拖动预览在引擎内固定 scale(0.90)；不得叠加 scale
    assert re.search(r"scale\(0\.90\)", use_drag)
    assert not re.search(r"scale\([^)]*\)\s+scale\(", use_drag)

    # 全局槽位与原点数学在纯 helper：不读 DOM、不做 DOM 卡数 clamp
    assert "slotOrigin" in grid_interaction
    assert "slotOrigin(" in main_window, (
        "visible-card FLIP must use the untransformed slot origin"
    )
    assert "getBoundingClientRect" not in grid_interaction
    assert "querySelectorAll" not in grid_interaction

    # 网格几何：由 MainWindow 采集未变换布局尺寸与客户区（scale 不进入槽位数学）
    assert "offsetWidth" in main_window
    assert "offsetHeight" in main_window, (
        "grid slot geometry must use untransformed layout dimensions so sorting scale "
        "cannot shift drag insertion slots"
    )
    assert re.search(r"getComputedStyle\(\s*wrap\s*\)", main_window)
    assert re.search(r"getComputedStyle\(\s*grid\s*\)", main_window)
    assert re.search(r"wrap\.clientWidth", main_window)
    assert re.search(r"startMargin\.value\s*-\s*wrap\.scrollTop", main_window)

    grid_slot = re.search(
        r"export function gridSlotIndex\([^)]*\)[^{]*\{(?P<body>.*?)\n\}",
        grid_interaction,
        re.DOTALL,
    )
    assert grid_slot, "grid slot index must remain locally inspectable"
    grid_slot_body = grid_slot.group("body")
    assert re.search(r"clientX\s*-\s*originX", grid_slot_body)
    assert re.search(r"clientY\s*-\s*originY", grid_slot_body)
    assert re.search(r"row\s*\*\s*cols\s*\+\s*col", grid_slot_body)
    assert "return null" in grid_slot_body
    assert "querySelectorAll" not in grid_slot_body

    # 持久化：分组内走 reorder_collection_members；全部/未分类走 reorder_memes
    assert re.search(r"reorder_collection_members", use_memes)
    assert re.search(r"reorder_memes", use_memes)
    assert re.search(
        r"state\.activeCollection\s*&&\s*state\.activeCollection\s*>\s*0",
        use_memes,
    )
    assert re.search(r"persistFn\(ids\)", use_drag)
    # 提交取自扩展后的完整连续窗口，且保存期间冻结事件与分页（不可变副本）
    assert re.search(r"getWindow\(\)\.items\.map", use_drag)
    assert "freezeForPersist" in use_drag
    assert "invalidateRequests" in use_drag
    assert "dragState.saving" in use_drag

    # 排序资格：搜索/标签禁用；全部/未分类/正 ID 可排
    assert re.search(r"q\s*\|\|\s*state\.activeTags\.size\s*>\s*0", use_memes)
    assert re.search(
        r"state\.activeCollection\s*===\s*null\s*\|\|\s*"
        r"state\.activeCollection\s*===\s*-4\s*\|\|\s*"
        r"state\.activeCollection\s*>\s*0",
        use_memes,
    )

    # MainWindow 绑定：sort-enabled 仅在可排序时启用；整理模式点选/拖拽/框选合并；复制被整理模式守卫
    assert re.search(
        r"'sort-enabled':\s*sortEnabled\s*&&\s*canReorder\(\)", main_window
    )
    assert re.search(r"'select-enabled':\s*sortEnabled", main_window)
    # folder 头块先于虚拟列表起点，且不包含 Virtualizer；依赖库已彻底移除
    virtualizer_tag = re.search(r"<Virtualizer(?![A-Za-z])", main_window)
    assert virtualizer_tag, "virtual list tag must remain locally inspectable"
    assert 'class="meme-card folder-card"' in main_window[: virtualizer_tag.start()]
    assert main_window.index('class="meme-grid folder-grid"') < virtualizer_tag.start()
    assert "drag-select" not in main_window
    assert "drag-select" not in main_ts
    toggle_sort = re.search(
        r"function toggleSort\(\)\s*\{(?P<body>.*?)\n\}", main_window, re.DOTALL
    )
    assert toggle_sort, "toolbar sort toggle must remain locally inspectable"
    assert re.search(r"if\s*\(sortEnabled\.value\)\s*drag\.enable\(\)", toggle_sort.group("body"))
    assert re.search(r"if\s*\(sortEnabled\.value\)\s*return", main_window)
    assert re.search(r"function onCardClick\(meme: Meme\)", main_window)
    assert re.search(r"function toggleSelected\(id: number\)", main_window)
    # ESC 优先级：LAN 确认 → 右键菜单 → 活动框选/排序手势（第一次不退出整理）→ 退出整理 → 隐藏窗口
    esc = re.search(
        r"function onDocKeydown\(e: KeyboardEvent\)\s*\{(?P<body>.*?)\n\}",
        main_window,
        re.DOTALL,
    )
    assert esc, "ESC ordering must remain locally inspectable"
    esc_body = esc.group("body")
    assert esc_body.index("lanConfirmVisible") < esc_body.index("ctx.visible")
    assert esc_body.index("marqueeSession") < esc_body.index("sortEnabled.value")
    assert esc_body.index("drag.dragState.active") < esc_body.index("sortEnabled.value")


def test_virtual_meme_grid_static_contract():
    root = Path(__file__).resolve().parent.parent
    main = root / "src" / "ohmymeme" / "presentation" / "frontend" / "main"
    main_window = (main / "app" / "MainWindow.vue").read_text(encoding="utf-8")
    style_css = (main / "app" / "style.css").read_text(encoding="utf-8")
    use_memes = (main / "features" / "memes" / "useMemes.ts").read_text(
        encoding="utf-8"
    )

    # 行级 Virtualizer：virtua/vue + 外部滚动容器 + 固定行距/缓冲/不 shift
    assert "from 'virtua/vue'" in main_window
    virtualizer = main_window[
        main_window.index("<Virtualizer") : main_window.index("</Virtualizer>")
    ]
    assert ':data="rows"' in virtualizer
    assert ':scroll-ref="gridWrapRef' in virtualizer
    assert ':start-margin="startMargin"' in virtualizer
    assert ':item-size="rowPitch"' in virtualizer
    assert ':buffer-size="200"' in virtualizer
    assert ':shift="false"' in virtualizer
    assert ':item-props="rowItemProps"' in virtualizer

    # 行外壳：单根行级 TransitionGroup，key 非行号，行起点可定位
    assert re.search(r'<TransitionGroup\s+:key="row\.key"', virtualizer)
    assert ':data-row-start="row.start"' in virtualizer

    # 未加载槽位生成同尺寸静态骨架：行内 template v-for 按「真卡 Meme.id / 骨架槽位」分键，无 img/事件/真实 id
    assert re.search(
        r'<template v-for="entry in rowSlots\(row\)" :key="entry\.meme \? \'m\' \+ entry\.meme\.id : \'s\' \+ entry\.index">',
        virtualizer,
    )
    # 真卡直接作为虚拟行 grid 子项（不再包依赖库 option），保留槽位/模型 id 与整理模式 aria
    assert re.search(r'<div\s+v-if="entry\.meme"\s+class="meme-card"', virtualizer)
    assert ':data-slot-index="entry.index"' in virtualizer
    assert ':data-meme-id="entry.meme.id"' in virtualizer
    assert ':aria-pressed="sortEnabled ? state.selectedIds.has(entry.meme.id) : undefined"' in virtualizer
    assert '<div v-else class="meme-card skeleton" aria-hidden="true"></div>' in virtualizer
    assert re.search(r"\.meme-card\.skeleton\s*\{", style_css)

    # 真卡保留原事件/图片/名称/徽标
    for token in (
        "onCardClick",
        "onMemeRightClick",
        "onCardPointerDown",
        "onCardMouseEnter",
        "memeSrc",
        "gif-badge",
        "meme-name",
    ):
        assert token in virtualizer
    assert "drag-select" not in virtualizer
    # 仅为 registry 重挂保存的 cache 与 selectionEpoch 已随依赖库移除
    assert ":cache=" not in virtualizer
    assert "selectionEpoch" not in main_window

    # footer：共 N 项 + 加载/失败状态位 + aria-live（S4：失败态为可重试按钮）
    assert 'class="grid-foot" aria-live="polite"' in main_window
    assert "共 {{ state.total }} 项" in main_window
    assert "加载中…" in main_window
    assert "加载失败" in main_window
    assert 'role="status" aria-atomic="true"' in main_window
    footer_start = main_window.index('class="grid-foot" aria-live="polite"')
    footer = main_window[footer_start : main_window.index("</div>", footer_start)]
    # 加载分支优先，错误分支互斥且为精确文案的实际按钮（不是整块可点击 div）
    assert re.search(
        r'<template v-if="state\.loading \|\| state\.rangeLoading">加载中…</template>',
        footer,
    )
    assert '<NButton v-else-if="state.loadError"' in footer
    assert "加载失败，点击重试" in footer
    assert 'aria-label="重新加载表情包"' in footer
    assert '@click="retryFailedRange"' in footer
    assert ':disabled="retryDisabled"' in footer
    # handler 只重放当前失败目标（分页/首屏/初始化/计数），由本地单飞与票号门禁包裹
    retry_handler = re.search(
        r"async function retryFailedRange\(\)\s*\{(?P<body>.*?)\n\}",
        main_window,
        re.DOTALL,
    )
    assert retry_handler, "footer retry handler must remain locally inspectable"
    retry_body = retry_handler.group("body")
    assert "await retryRange()" in retry_body
    assert "retryDisabled.value" in retry_body
    assert "retryPending" in retry_body
    assert "retryTicket" in retry_body
    assert "windowUnmounted" in retry_body
    assert re.search(
        r"const retryDisabled = computed\(\(\) => retryPending\.value "
        r"\|\| gridActionBusy\.value \|\| state\.loading \|\| state\.rangeLoading\)",
        main_window,
    )

    # 旧顺序加载驱动彻底移除，两套加载逻辑不得并存
    for removed in (
        "loadMore",
        "spacerHeight",
        "measureGrid",
        "ensureFilled",
        "onGridScroll",
        "gridFootRef",
        "hasMore",
        "loadingMore",
    ):
        assert removed not in main_window
        assert removed not in use_memes
    assert "grid-spacer" not in main_window
    assert ".grid-spacer" not in style_css

    # 连续区间模型与查询/窗口代次接线
    assert re.search(r"lo:\s*0", use_memes)
    assert re.search(r"hi:\s*0", use_memes)
    assert "slots:" in use_memes
    assert "queryGen:" in use_memes
    assert "rangeGen:" in use_memes
    for token in ("ensureRange", "setLoadedSlice", "pinLoadedRange", "loadedSlice"):
        assert token in use_memes
    assert "loadedSlice()" in main_window
    assert "setLoadedSlice(" in main_window
    assert "ensureRange(" in main_window
    assert "pinLoadedRange()" in main_window
    assert "pinLoadedRange({ allowExtension: true })" in main_window
    assert "invalidateRangeRequests" in main_window
    assert "state.queryGen" in main_window
    assert "browseKey" in main_window
    # 拖拽失效判据不依赖普通补页推进的 rangeGen：扩展 pin 生命周期只由查询/布局/浏览键/总数约束
    assert "state.rangeGen" not in main_window


def test_virtual_grid_experience_static_contract():
    # S4 体验收尾静态契约：footer 重试与回顶按钮的接线、位置与样式；
    # 只读源码断言，不执行前端，也不声称证明不同 DPI 下的实际排版结果
    root = Path(__file__).resolve().parent.parent
    main = root / "src" / "ohmymeme" / "presentation" / "frontend" / "main"
    main_window = (main / "app" / "MainWindow.vue").read_text(encoding="utf-8")
    style_css = (main / "app" / "style.css").read_text(encoding="utf-8")

    def block(pattern):
        match = re.search(pattern, main_window, re.DOTALL)
        assert match, f"S4 experience block must remain locally inspectable: {pattern}"
        return match.group("body")

    def rule(selector):
        match = re.search(
            re.escape(selector) + r"\s*\{(?:(?!\}).)*?\}", style_css, re.DOTALL
        )
        assert match, f"experience styles must remain locally inspectable: {selector}"
        return match.group(0)

    # 显隐只读滚动容器：0 视口不显示，超过两屏（恰两屏不显示）才显示
    sync_body = block(r"function syncBackToTopVisibility\(\)\s*\{(?P<body>.*?)\n\}")
    assert re.search(r"wrap\.clientHeight\s*>\s*0", sync_body)
    assert re.search(r"wrap\.scrollTop\s*>\s*2\s*\*\s*wrap\.clientHeight", sync_body)
    assert "showBackToTop" in sync_body

    # 回顶：卸载/手势/虚拟化门禁、wrap 判空、优先 handle.scrollTo(0) 且异常回退、
    # 焦点归宿、普通 requestVisibleRange 收尾（不 search、不重试、不新建定时器）
    back_body = block(r"function backToTop\(\)\s*\{(?P<body>.*?)\n\}")
    assert "windowUnmounted" in back_body
    assert "gridActionBusy" in back_body
    assert "virtualReady" in back_body
    assert re.search(r"if\s*\(!wrap\s*\|\|\s*!wrap\.isConnected\)\s*return", back_body)
    assert "handle.scrollTo(0)" in back_body
    assert "wrap.scrollTop = 0" in back_body
    assert "restoreFocusFromRemovedButton" in back_body
    assert "requestVisibleRange()" in back_body
    assert "requestVisibleRangeNow" not in back_body
    assert "search(" not in back_body
    assert "retryRange" not in back_body
    assert "setTimeout" not in back_body
    focus_body = block(
        r"function restoreFocusFromRemovedButton\([^)]*\)\s*\{(?P<body>.*?)\n\}"
    )
    assert re.search(
        r"gridWrapRef\.value\?\.focus\(\{\s*preventScroll:\s*true\s*\}\)", focus_body
    )
    # 结算时复核焦点归属：仅当焦点确实随按钮丢失（未被用户移走）才交还网格
    assert "document.activeElement" in focus_body
    assert "document.body" in focus_body
    assert 'tabindex="-1"' in main_window

    # 初始化失败时跳过后台 search（否则会清掉 init 重试入口），点击重试走 loadInitData
    assert "if (initOk) await search()" in main_window
    # 空库/加载中也显示 footer 状态：seed/init 重试期间保留“加载中…”与可重试入口
    assert (
        'v-if="virtualReady && (state.total > 0 || state.loadError '
        '|| state.loading || state.rangeLoading)"' in main_window
    )

    # 按钮为 #grid-wrap 之后的兄弟：footer（grid-wrap 内最后块）结束后、#main 收尾前
    back_index = main_window.index('id="back-to-top"')
    footer_close = main_window.index("</div>", main_window.index('class="grid-foot"'))
    assert footer_close < back_index
    button = main_window[
        main_window.rindex("<NButton", 0, back_index) : main_window.index(
            "</NButton>", back_index
        )
    ]
    assert "virtualReady" in button
    assert "state.total > 0" in button
    assert "showBackToTop" in button
    assert "with-organize-bar" in button
    assert ':disabled="gridActionBusy"' in button
    assert 'title="回到顶部"' in button
    assert 'aria-label="回到顶部"' in button
    assert '@click="backToTop"' in button
    assert "<ArrowUp" in button
    assert re.match(
        r"</NButton>\s*</div>\s*</div>",
        main_window[main_window.index("</NButton>", back_index) :],
    )

    # 样式：#back-to-top 绝对定位右下（z-20），整理模式抬到底部工具栏之上；
    # 既有布局基线保持：#main 定位上下文、底部居中工具栏不参与布局流
    back_rule = rule("#back-to-top")
    assert re.search(r"position\s*:\s*absolute", back_rule)
    assert re.search(r"right\s*:\s*14px", back_rule)
    assert re.search(r"bottom\s*:\s*14px", back_rule)
    assert re.search(r"z-index\s*:\s*20", back_rule)
    organize_rule = rule("#back-to-top.with-organize-bar")
    assert re.search(r"bottom\s*:\s*80px", organize_rule)
    assert re.search(r"\.grid-retry\s*\{", style_css)
    main_rule = rule("#main")
    assert re.search(r"position\s*:\s*relative", main_rule)
    bar_rule = rule("#organize-bar")
    assert re.search(r"position\s*:\s*absolute", bar_rule)
    assert re.search(r"bottom\s*:\s*14px", bar_rule)
    assert re.search(r"transform\s*:\s*translateX\(-50%\)", bar_rule)


def test_main_window_typecheck_scope_static_contract():
    # tsconfig 是带注释的 JSONC：不做整文件 json.loads，改按 include/exclude 局部块精确核对。
    # 该合同只核对配置文本集合，不等同于运行 vue-tsc 的结论。
    root = Path(__file__).resolve().parent.parent
    tsconfig = (root / "tsconfig.json").read_text(encoding="utf-8")

    assert '"strict": true' in tsconfig
    for flag in (
        "noUncheckedIndexedAccess",
        "exactOptionalPropertyTypes",
        "noFallthroughCasesInSwitch",
        "noPropertyAccessFromIndexSignature",
        "forceConsistentCasingInFileNames",
        "verbatimModuleSyntax",
    ):
        assert f'"{flag}": true' in tsconfig

    include_match = re.search(r'"include"\s*:\s*\[(?P<body>.*?)\]', tsconfig, re.DOTALL)
    exclude_match = re.search(r'"exclude"\s*:\s*\[(?P<body>.*?)\]', tsconfig, re.DOTALL)
    assert (
        include_match and exclude_match
    ), "tsconfig include/exclude must remain locally inspectable"
    include_items = re.findall(r'"([^"]+)"', include_match.group("body"))
    exclude_items = re.findall(r'"([^"]+)"', exclude_match.group("body"))
    assert include_items == [
        "src/ohmymeme/presentation/frontend/main/app/**/*.vue",
        "src/ohmymeme/presentation/frontend/main/app/**/*.ts",
        "src/ohmymeme/presentation/frontend/main/features/**/*.ts",
        "src/ohmymeme/presentation/frontend/main/features/**/*.vue",
        "src/ohmymeme/presentation/frontend/main/shared/**/*.ts",
        "src/ohmymeme/presentation/frontend/settings-vue/**/*.ts",
        "src/ohmymeme/presentation/frontend/settings-vue/**/*.vue",
        "tests/frontend/**/*.ts",
    ]
    assert exclude_items == [
        "node_modules",
        "src/ohmymeme/presentation/frontend/main/shared/bridge.ts",
        "src/ohmymeme/presentation/frontend/main/app/main.ts",
    ]
    # 接线测试临时排除已删除；bridge.ts/main.ts 仅作根文件排除（被 import 时仍进依赖图）
    assert "main_window_virtual" not in tsconfig
    assert "被纳管调用方 import 时仍进入依赖检查" in tsconfig
    assert "pywebview 注入入口暂不作为根文件" in tsconfig


def test_visible_marquee_static_contract():
    # 自研可见区框选：无依赖库 import/注册/option metrics/registry 残留；
    # 空白入口、overlay、快照 XOR、取消路径与键盘替代可静态检查（不在 Python 里模拟浏览器布局）
    root = Path(__file__).resolve().parent.parent
    main = root / "src" / "ohmymeme" / "presentation" / "frontend" / "main"
    main_window = (main / "app" / "MainWindow.vue").read_text(encoding="utf-8")
    main_ts = (main / "app" / "main.ts").read_text(encoding="utf-8")
    style_css = (main / "app" / "style.css").read_text(encoding="utf-8")
    grid_interaction = (main / "features" / "sorting" / "gridInteraction.ts").read_text(
        encoding="utf-8"
    )

    # 依赖库彻底移除：无 import、无注册、无 option metrics / registry 残留
    assert "vue-drag-select" not in main_ts
    assert "VueDragSelect" not in main_ts
    assert "drag-select" not in main_ts
    for removed in (
        "dragSelectRef",
        "drag-select-option",
        "installOptionMetrics",
        "optionMetricsInstalled",
        "selectionEpoch",
        "mountedRealCardFingerprint",
        "maybeResetSelectionRegistry",
        "flushPendingWork",
        "onBoxSelection",
        "boxSelecting",
        "dragSelectDisabled",
        "virtualCache",
        "SCROLL_END_CLEANUP_DELAY",
    ):
        assert removed not in main_window
    assert ".drag-select-option" not in style_css

    # 框选数学由纯 helper 提供，MainWindow 只组合（不扫描 slots 全库、不用 index 造选项）
    for helper in ("normalizeMarqueeRect", "rectIntersects", "applyMarqueeSelection"):
        assert helper in grid_interaction
    assert "normalizeMarqueeRect(" in main_window
    assert "rectIntersects(" in main_window
    assert "applyMarqueeSelection(" in main_window

    # 空白起手入口与会话处理
    assert '@pointerdown="onGridBlankPointerDown"' in main_window
    assert "function onGridBlankPointerDown(" in main_window
    assert "function onMarqueePointerMove(" in main_window
    assert "function onMarqueePointerUp(" in main_window
    assert "MARQUEE_THRESHOLD = 8" in main_window

    # overlay：独立固定层、不接收指针、无 tabindex、aria-hidden
    overlay = re.search(r"\.marquee-overlay\s*\{(?:(?!\}).)*?\}", style_css, re.DOTALL)
    assert overlay, "marquee overlay styles must remain locally inspectable"
    overlay_body = overlay.group(0)
    assert re.search(r"position\s*:\s*fixed", overlay_body)
    assert re.search(r"pointer-events\s*:\s*none", overlay_body)
    assert re.search(r"z-index\s*:\s*15", overlay_body)
    assert re.search(r"background\s*:\s*var\(--blue-a3\)", overlay_body)
    assert 'class="marquee-overlay"' in main_window
    assert 'aria-hidden="true"' in main_window

    # 快照 XOR / 单帧命中 / 骨架排除 / 取消回滚
    assert "baseSelected" in main_window
    assert "marqueeSessionValid(" in main_window
    assert "scheduleMarqueeFrame(" in main_window
    assert "cancelMarquee(" in main_window
    assert "pointHitsSkeleton(" in main_window
    # 工具栏统一忙碌态：活动框选/排序期间禁用全选/取消选择/批量删除
    assert "interactionBusy" in main_window
    # 滚动取消与手势仲裁（卡片起手不画框、框选不抢卡片 click）
    assert re.search(r"if\s*\(marqueeSession\)\s*cancelMarquee\('scroll'\)", main_window)
    assert re.search(r"if\s*\(marqueeSession\)\s*return", main_window)
    # 键盘替代：Enter/Space 勾选与工具栏按钮保持
    assert "function toggleSelected(id: number)" in main_window
    assert "全选" in main_window
    assert "batchDelete" in main_window


def test_drag_autoscroll_static_contract():
    # 拖拽引擎静态契约：单 rAF pump、稳定容器捕获、全局槽位/挂载真卡门禁、
    # 扩展 pin、整段提交与 saving 隔离；验证路径接线，不声称静态断言证明滚动体验
    root = Path(__file__).resolve().parent.parent
    main = root / "src" / "ohmymeme" / "presentation" / "frontend" / "main"
    main_window = (main / "app" / "MainWindow.vue").read_text(encoding="utf-8")
    style_css = (main / "app" / "style.css").read_text(encoding="utf-8")
    use_drag = (main / "features" / "sorting" / "useDragSort.ts").read_text(
        encoding="utf-8"
    )
    grid_interaction = (main / "features" / "sorting" / "gridInteraction.ts").read_text(
        encoding="utf-8"
    )

    # 单 rAF pump：自排队、结束/取消取消帧、dt clamp 32ms
    assert "function frameStep(" in use_drag
    assert "requestAnimationFrame(next => frameStep(s, next))" in use_drag
    assert "cancelAnimationFrame(" in use_drag
    assert "FRAME_MS = 32" in use_drag
    assert re.search(r"Math\.min\(FRAME_MS", use_drag)
    # 速度曲线与阈值来自纯 helper（64px 触发区、±800px/s 二次曲线，上下对称）
    assert "edgeScrollVelocity(" in use_drag
    assert "export function edgeScrollVelocity(" in grid_interaction
    assert re.search(r"EDGE_ZONE_MAX\s*=\s*64", grid_interaction)
    assert re.search(r"EDGE_SPEED_MAX\s*=\s*800", grid_interaction)

    # 稳定容器捕获 + 全局槽位/挂载真卡门禁 + 单飞扩页
    assert "setPointerCapture(" in use_drag
    assert "getScrollFrame" in use_drag
    assert re.search(r"getTarget:\s*getDragTarget", main_window)
    assert "data-slot-index" in main_window
    assert "gridSlotIndex(" in main_window
    assert "loadedScrollFrontier(" in main_window
    assert "function ensureDragRange(" in main_window

    # 双 pin：扩展许可 + 保存冻结；在途请求失效；saving 门禁拒绝新手势
    assert "acquireExtensionPin" in use_drag
    assert "freezeForPersist" in use_drag
    assert "invalidateRequests" in use_drag
    assert re.search(r"if\s*\(dragState\.saving \|\| session\)\s*return false", use_drag)
    assert "pinLoadedRange({ allowExtension: true })" in main_window
    assert "invalidateRangeRequests" in main_window

    # 结算副作用按原会话上下文门控；丢捕获取消；手势结束补发视口请求；图片禁用原生 HTML5 拖拽
    assert "contextLive" in use_drag
    assert "onGridLostPointerCapture" in main_window
    assert "restoreViewportBudget" in main_window
    assert 'draggable="false"' in main_window
    assert "pointerSlotLoadedAfter" in main_window

    # 独立固定预览、原位占位与拖拽期间禁双 FLIP
    ghost = re.search(r"\.drag-ghost\s*\{(?:(?!\}).)*?\}", style_css, re.DOTALL)
    assert ghost, "drag ghost styles must remain locally inspectable"
    assert re.search(r"position\s*:\s*fixed", ghost.group(0))
    assert re.search(r"pointer-events\s*:\s*none", ghost.group(0))
    assert "drag-placeholder" in style_css and "drag-placeholder" in main_window
    assert "meme-list-move-disabled" in style_css
    assert re.search(r"prefers-reduced-motion\s*:\s*reduce", style_css)

    # S2 临时适配彻底移除（无 live-card / deltaY / 可见段剪裁 / 保存标志残留）
    for removed in (
        "deltaY",
        "liveCard",
        "createLiveCard",
        "collectMountedSegment",
        "insideVisibleSegment",
        "normalizePointerEvent",
        "visibleDragSession",
        "persistInFlight",
    ):
        assert removed not in use_drag
        assert removed not in main_window


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
