"""插件系统单元测试：manifest 校验、加载隔离、熔断、权限门控、状态持久化、注入"""

import json
from pathlib import Path

import pytest

from src import config as config_mod
from src import plugin_manager as pm_mod
from src.config import Config
from src.plugin_manager import PluginManager

ENTRY_IMPORT = "def on_load(ctx):\n    pass\n"


def _write_plugin(
    base: Path,
    pid: str,
    manifest_extra: dict = None,
    entry_src: str = None,
    files: dict = None,
):
    """在 base/<pid> 写 plugin.json（+ entry/资产文件）"""
    d = base / pid
    d.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": pid,
        "name": pid.upper(),
        "version": "1.0.0",
        "repo": f"https://github.com/example/{pid}",
        "api_version": 1,
        "entry": "",
        "windows": ["main"],
        "permissions": [],
    }
    if manifest_extra:
        manifest.update(manifest_extra)
    (d / "plugin.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    if entry_src is not None:
        (d / "main.py").write_text(entry_src, encoding="utf-8")
    for rel, content in (files or {}).items():
        target = d / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
    return d


@pytest.fixture
def env(tmp_path, monkeypatch):
    """隔离数据目录 + 可用插件目录的 Config"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config_mod, "_get_data_dir", lambda: data_dir)
    cfg = Config(tmp_path / "config" / "config.json")
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    cfg.set("plugin_dirs", [str(plugins)])
    return types_ns(cfg=cfg, plugins=plugins, data_dir=data_dir)


def types_ns(**kw):
    import types

    return types.SimpleNamespace(**kw)


def _status(pm: PluginManager, pid: str):
    for info in pm.list_info():
        if info["id"] == pid:
            return info
    return None


def test_manifest_validation_skips_bad_plugins(env):
    _write_plugin(env.plugins, "good", {"entry": "main.py"}, ENTRY_IMPORT)
    _write_plugin(env.plugins, "bad-id", {"id": "Bad ID"})
    _write_plugin(env.plugins, "no-name", {"name": ""})
    _write_plugin(
        env.plugins, "old-api", {"api_version": 99, "entry": "main.py"}, ENTRY_IMPORT
    )
    _write_plugin(env.plugins, "bad-repo", {"repo": "file:///etc/passwd"})

    pm = PluginManager()
    pm.init(env.cfg)
    assert _status(pm, "good")["status"] == "loaded"
    assert _status(pm, "bad-id") is None  # id 非法不注册
    assert _status(pm, "no-name") is None  # 缺 name/version 结构性无效不注册
    assert _status(pm, "old-api")["status"] == "failed"
    assert "api_version" in _status(pm, "old-api")["reason"]
    assert _status(pm, "bad-repo")["status"] == "failed"


def test_missing_id_manifest_skipped(env):
    d = env.plugins / "noid"
    d.mkdir()
    (d / "plugin.json").write_text(json.dumps({"name": "x"}), encoding="utf-8")
    (env.plugins / "broken").mkdir()
    (env.plugins / "broken" / "plugin.json").write_text("{oops", encoding="utf-8")
    pm = PluginManager()
    pm.init(env.cfg)
    assert pm.list_info() == []


def test_sandbox_true_skipped(env):
    _write_plugin(
        env.plugins,
        "boxed",
        {"entry": "main.py", "sandbox": True},
        ENTRY_IMPORT,
    )
    pm = PluginManager()
    pm.init(env.cfg)
    info = _status(pm, "boxed")
    assert info["status"] == "failed"
    assert "沙箱" in info["reason"]


def test_missing_dependency_skips(env):
    _write_plugin(
        env.plugins,
        "deps",
        {"entry": "main.py", "dependencies": ["ohmm_definitely_missing_pkg_xyz"]},
        ENTRY_IMPORT,
    )
    pm = PluginManager()
    pm.init(env.cfg)
    info = _status(pm, "deps")
    assert info["status"] == "failed"
    assert "ohmm_definitely_missing_pkg_xyz" in info["reason"]


def test_entry_exception_isolated(env):
    _write_plugin(
        env.plugins, "boom", {"entry": "main.py"}, "def on_load(ctx):\n    raise 1/0\n"
    )
    _write_plugin(env.plugins, "fine", {"entry": "main.py"}, ENTRY_IMPORT)
    pm = PluginManager()
    pm.init(env.cfg)
    assert _status(pm, "boom")["status"] == "failed"
    assert _status(pm, "fine")["status"] == "loaded"


def test_unknown_permission_warned_not_fatal(env):
    _write_plugin(
        env.plugins,
        "perm",
        {"entry": "main.py", "permissions": ["route", "totally:unknown"]},
        ENTRY_IMPORT,
    )
    pm = PluginManager()
    pm.init(env.cfg)
    info = _status(pm, "perm")
    assert info["status"] == "loaded"
    assert info["permissions"] == ["route"]


def test_permission_gate_blocks_registration(env):
    src = "def on_load(ctx):\n" "    ctx.register_route('/x', lambda p: 'x')\n"
    _write_plugin(env.plugins, "noperm", {"entry": "main.py"}, src)
    pm = PluginManager()
    pm.init(env.cfg)
    info = _status(pm, "noperm")
    assert info["status"] == "failed"
    assert "PermissionError" in info["reason"]


def test_callback_exception_disables_plugin(env):
    src = (
        "def on_load(ctx):\n"
        "    ctx.register_main_api('bad', lambda: 1 / 0)\n"
        "    ctx.register_main_api('good', lambda: 'ok')\n"
    )
    _write_plugin(
        env.plugins, "cb", {"entry": "main.py", "permissions": ["main_api"]}, src
    )
    pm = PluginManager()
    pm.init(env.cfg)
    assert pm.call_main("cb", "good", []) == "ok"
    r = pm.call_main("cb", "bad", [])
    assert r["ok"] is False
    info = _status(pm, "cb")
    assert info["status"] == "disabled"
    assert info["reason"] == "exception"
    # 熔断后逻辑注销：普通方法也不再分发
    assert pm.call_main("cb", "good", [])["error"] == "plugin_disabled"


def test_guard_timeout_disables_plugin(env, monkeypatch):
    src = (
        "import time\n"
        "def on_load(ctx):\n"
        "    ctx.register_main_api('slow', lambda: time.sleep(3) or 'late')\n"
    )
    _write_plugin(
        env.plugins, "slow", {"entry": "main.py", "permissions": ["main_api"]}, src
    )
    monkeypatch.setattr(pm_mod, "HANDLER_TIMEOUT", 0.2)
    monkeypatch.setattr(pm_mod, "_API_TIMEOUT", 0.2)
    pm = PluginManager()
    pm.init(env.cfg)
    r = pm.call_main("slow", "slow", [])
    assert r["error"] == "handler_timeout"
    assert _status(pm, "slow")["status"] == "disabled"


def test_on_load_timeout_fails_plugin(env, monkeypatch):
    src = "import time\ndef on_load(ctx):\n    time.sleep(3)\n"
    _write_plugin(env.plugins, "hang", {"entry": "main.py"}, src)
    monkeypatch.setattr(pm_mod, "LOAD_TIMEOUT", 0.2)
    pm = PluginManager()
    pm.init(env.cfg)
    info = _status(pm, "hang")
    assert info["status"] == "failed"
    assert "on_load" in info["reason"]


def test_disable_immediate_enable_restart(env):
    src = (
        "def on_load(ctx):\n"
        "    ctx.register_route('/ping', lambda p: {'ok': True})\n"
    )
    _write_plugin(
        env.plugins,
        "toggle",
        {"entry": "main.py", "permissions": ["route"]},
        src,
    )
    pm = PluginManager()
    pm.init(env.cfg)
    assert pm.custom_routes()

    r = pm.set_enabled("toggle", False)
    assert r["ok"] and r["restart"] is False and r["enabled"] is False
    assert pm.custom_routes() == []
    assert _status(pm, "toggle")["status"] == "disabled"

    # 用户禁用后重启：不加载 entry
    pm2 = PluginManager()
    pm2.init(env.cfg)
    assert _status(pm2, "toggle")["status"] == "disabled"
    assert pm2.custom_routes() == []

    r = pm2.set_enabled("toggle", True)
    assert r["restart"] is True
    pm3 = PluginManager()
    pm3.init(env.cfg)
    assert _status(pm3, "toggle")["status"] == "loaded"


def test_settings_roundtrip_atomic_state(env):
    _write_plugin(env.plugins, "s", {"entry": "main.py"}, ENTRY_IMPORT)
    pm = PluginManager()
    pm.init(env.cfg)
    r = pm.save_settings("s", {"a": 1})
    assert r["ok"]
    assert pm.get_settings("s") == {"a": 1}
    r = pm.save_settings("s", {"b": 2})
    assert pm.get_settings("s") == {"a": 1, "b": 2}

    settings_path = env.cfg.config_dir / "plugins" / "s" / "settings.json"
    assert settings_path.exists()
    assert not (env.data_dir / "plugins" / "s" / "settings.json").exists()
    raw = json.loads(settings_path.read_text(encoding="utf-8"))
    assert raw == {"a": 1, "b": 2}
    # 重启后仍可读
    pm2 = PluginManager()
    pm2.init(env.cfg)
    assert pm2.get_settings("s") == {"a": 1, "b": 2}

    # 非法 id / 非 dict 设置拒绝
    assert pm.save_settings("../evil", {"a": 1})["ok"] is False
    assert pm.save_settings("s", "nope")["ok"] is False


def test_legacy_settings_migrated_to_plugin_folder(env):
    """旧版 plugins_state.json 内嵌设置自动迁移到 config_dir/plugins/<id>/settings.json"""
    _write_plugin(env.plugins, "m", {"entry": "main.py"}, ENTRY_IMPORT)
    state_path = env.data_dir / "plugins_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"disabled": [], "settings": {"m": {"k": "v"}}}),
        encoding="utf-8",
    )
    pm = PluginManager()
    pm.init(env.cfg)
    assert pm.get_settings("m") == {"k": "v"}
    settings_path = env.cfg.config_dir / "plugins" / "m" / "settings.json"
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"k": "v"}
    # 状态文件被重写为不含 settings
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    assert "settings" not in raw
    assert raw["disabled"] == []


def test_settings_moved_from_data_dir_to_config_dir(env):
    """旧位置 data_dir/plugins/<id>/settings.json 首次 init 迁移到 config_dir"""
    # 插件装在 data_dir（代码 + 旧设置）→ 设置迁出、代码目录保留
    _write_plugin(env.data_dir / "plugins", "mig", {"entry": "main.py"}, ENTRY_IMPORT)
    old = env.data_dir / "plugins" / "mig" / "settings.json"
    old.write_text(json.dumps({"a": 1}), encoding="utf-8")
    # 仅有设置的目录 → 迁移后整个目录移除
    ghost = env.data_dir / "plugins" / "ghost"
    ghost.mkdir(parents=True, exist_ok=True)
    (ghost / "settings.json").write_text(json.dumps({"g": 1}), encoding="utf-8")
    # 新位置已存在 → 保留新位置，丢弃旧文件
    _write_plugin(env.plugins, "dup", {"entry": "main.py"}, ENTRY_IMPORT)
    dup_new = env.cfg.config_dir / "plugins" / "dup" / "settings.json"
    dup_new.parent.mkdir(parents=True, exist_ok=True)
    dup_new.write_text(json.dumps({"n": 1}), encoding="utf-8")
    dup_old = env.data_dir / "plugins" / "dup"
    dup_old.mkdir(parents=True, exist_ok=True)
    (dup_old / "settings.json").write_text(json.dumps({"o": 9}), encoding="utf-8")

    pm = PluginManager()
    pm.init(env.cfg)

    mig_new = env.cfg.config_dir / "plugins" / "mig" / "settings.json"
    assert json.loads(mig_new.read_text(encoding="utf-8")) == {"a": 1}
    assert not old.exists()
    assert (env.data_dir / "plugins" / "mig" / "plugin.json").exists()
    assert pm.get_settings("mig") == {"a": 1}
    ghost_new = env.cfg.config_dir / "plugins" / "ghost" / "settings.json"
    assert json.loads(ghost_new.read_text(encoding="utf-8")) == {"g": 1}
    assert not ghost.exists()
    assert json.loads(dup_new.read_text(encoding="utf-8")) == {"n": 1}
    assert not (dup_old / "settings.json").exists()


def test_settings_changed_callback_invoked(env):
    src = (
        "calls = []\n"
        "def on_load(ctx):\n"
        "    pass\n"
        "def on_settings_changed(data):\n"
        "    calls.append(data)\n"
    )
    _write_plugin(env.plugins, "sc", {"entry": "main.py"}, src)
    pm = PluginManager()
    pm.init(env.cfg)
    pm.save_settings("sc", {"x": 1})
    # 回调在独立线程执行，_invoke 已同步 join；模块对象可查
    mod = pm._plugins["sc"].module
    assert mod.calls == [{"x": 1}]


def test_asset_resolution_and_traversal(env):
    _write_plugin(
        env.plugins,
        "a",
        {"entry": "main.py", "permissions": ["assets:serve"]},
        ENTRY_IMPORT,
        files={"style.css": "body{}", "sub/app.js": "1;"},
    )
    pm = PluginManager()
    pm.init(env.cfg)
    path, ctype = pm.resolve_asset("a", "style.css")
    assert path == (env.plugins / "a" / "style.css").resolve()
    assert ctype == "text/css"
    assert pm.resolve_asset("a", "sub/app.js")[1] == "text/javascript"
    assert pm.resolve_asset("a", "../plugin.json") is None
    assert pm.resolve_asset("a", "sub/../../plugin.json") is None
    assert pm.resolve_asset("a", "nope.css") is None
    assert pm.resolve_asset("missing", "style.css") is None

    # data/ 前缀解析到插件数据目录（启动动画等经 settings_api 复制的媒体）
    data_dir = env.cfg.data_dir / "plugins_data" / "a"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "intro.gif").write_bytes(b"GIF89a")
    got = pm.resolve_asset("a", "data/intro.gif")
    assert got and got[0] == (data_dir / "intro.gif").resolve()
    assert got[1] == "image/gif"
    assert pm.resolve_asset("a", "data/") is None
    assert pm.resolve_asset("a", "data/../style.css") is None
    assert pm.resolve_asset("a", "data/../../plugin.json") is None

    # 禁用后不可访问
    pm.set_enabled("a", False)
    assert pm.resolve_asset("a", "style.css") is None
    assert pm.resolve_asset("a", "data/intro.gif") is None


def test_asset_tags_and_sections_injection_order(env):
    sec1 = '<div class="section" data-group="plugin">1</div>'
    sec2 = '<div class="section" data-group="plugin">2</div>'
    src = (
        "def on_load(ctx):\n"
        "    ctx.register_css('main', 'a.css')\n"
        "    ctx.register_js('main', 'a.js')\n"
        "    ctx.register_css('settings', 'a.css')\n"
        "    ctx.register_js('settings', 'b.js')\n"
        "    ctx.register_settings_section(%r)\n" % sec1
    )
    _write_plugin(
        env.plugins,
        "a",
        {
            "entry": "main.py",
            "permissions": ["assets:serve", "settings:section"],
            "windows": ["main", "settings"],
        },
        src,
        files={"a.css": "", "a.js": "", "b.js": ""},
    )
    _write_plugin(
        env.plugins,
        "b",
        {
            "entry": "main.py",
            "permissions": ["settings:section"],
            "windows": ["settings"],
        },
        "def on_load(ctx):\n    ctx.register_settings_section(%r)\n" % sec2,
    )
    pm = PluginManager()
    pm.init(env.cfg)
    tags = pm.asset_tags("main")
    assert '<link rel="stylesheet" href="/plugins/a/a.css?v=1.0.0-' in tags
    assert '<script defer src="/plugins/a/a.js?v=1.0.0-' in tags
    # b 仅 settings 窗口
    assert "/plugins/b/" not in pm.asset_tags("main")
    stags = pm.asset_tags("settings")
    assert "/plugins/a/a.css" in stags and "/plugins/b/b.js" not in stags
    # 按 id 排序拼接 section
    secs = pm.settings_sections()
    assert secs.index("1</div>") < secs.index("2</div>")

    # 禁用 a 后不再注入
    pm.set_enabled("a", False)
    assert pm.asset_tags("main") == ""


def test_asset_version_changes_with_settings(env):
    _write_plugin(
        env.plugins,
        "a",
        {"entry": "main.py", "permissions": ["assets:serve"]},
        ENTRY_IMPORT,
        files={"a.css": ""},
    )
    pm = PluginManager()
    pm.init(env.cfg)
    pm._plugins["a"].assets["main"] = {"css": ["a.css"], "js": []}
    before = pm.asset_tags("main")
    pm.save_settings("a", {"k": "v"})
    after = pm.asset_tags("main")
    assert before != after, "设置变化须改变资产版本号防缓存"


def test_custom_routes_dispatch_and_gate(env):
    src = (
        "def on_load(ctx):\n"
        "    ctx.register_route('/ping', lambda p: {'echo': p.get('q')})\n"
        "    ctx.register_route('/style.css', lambda p: 'body{}')\n"
    )
    _write_plugin(
        env.plugins,
        "r",
        {"entry": "main.py", "permissions": ["route"]},
        src,
    )
    pm = PluginManager()
    pm.init(env.cfg)
    routes = pm.custom_routes()
    assert [rule for _pid, rule, _fn in routes] == ["/ping", "/style.css"]
    assert routes[0][0] == "r"
    ok, val = pm.call_route("r", routes[0][2], {"q": "hi"})
    assert ok and val == {"echo": "hi"}
    assert pm_mod.route_content_type("/style.css") == "text/css"
    assert pm_mod.route_content_type("/ping") is None

    pm.set_enabled("r", False)
    assert pm.custom_routes() == []
    assert pm.call_route("r", routes[0][2], {})[0] is False


def test_startup_and_window_overrides_sorted(env):
    for pid in ("zz", "aa"):
        src = (
            "def on_load(ctx):\n"
            "    ctx.set_startup_override(video_src='/plugins/%s/v.mp4',"
            " bg_color='#ff0000')\n"
            "    ctx.set_window_params(width=1100, height=700)\n" % pid
        )
        _write_plugin(
            env.plugins,
            pid,
            {
                "entry": "main.py",
                "permissions": ["startup", "window"],
                "version": "1.0.0",
            },
            src,
        )
    pm = PluginManager()
    pm.init(env.cfg)
    # 按 id 排序，后者（zz）覆盖
    fields = pm.init_fields()
    assert fields["startup_video_src"] == "/plugins/zz/v.mp4"
    assert fields["startup_bg_color"] == "#ff0000"
    assert pm.window_params() == {"width": 1100, "height": 700}


def test_startup_media_duration_and_type(env):
    """启动动画媒体元数据（时长/类型）透传给 init_fields（图片按 duration 收起）"""
    src = (
        "def on_load(ctx):\n"
        "    ctx.set_startup_override(video_src='/plugins/a/data/intro.gif',"
        " bg_color='#000000', duration_ms=1234, media_type='image')\n"
    )
    _write_plugin(
        env.plugins,
        "a",
        {"entry": "main.py", "permissions": ["startup"]},
        src,
    )
    pm = PluginManager()
    pm.init(env.cfg)
    fields = pm.init_fields()
    assert fields["startup_video_src"] == "/plugins/a/data/intro.gif"
    assert fields["startup_media_duration_ms"] == 1234
    assert fields["startup_media_type"] == "image"


def test_button_registration_and_constraints(env):
    src = (
        "def on_load(ctx):\n"
        "    ctx.register_button("
        "{'key': 'hello', 'label': '你好', 'icon': 'i.svg', 'order': 5})\n"
        "    ctx.register_button_handler(lambda key: 'got:' + key)\n"
        "    ctx.register_button_constraints(hide=['upload'], order={'settings': 90})\n"
    )
    _write_plugin(
        env.plugins,
        "btn",
        {"entry": "main.py", "permissions": ["buttons"]},
        src,
        files={"i.svg": "<svg/>"},
    )
    _write_plugin(env.plugins, "btn2", {"entry": "main.py"}, ENTRY_IMPORT)
    pm = PluginManager()
    pm.init(env.cfg)
    buttons = pm.buttons_for_frontend()
    assert len(buttons) == 1
    assert buttons[0]["key"] == "hello"
    assert buttons[0]["icon"].startswith("/plugins/btn/i.svg?v=")
    con = pm.button_constraints()
    assert con["hide"] == ["upload"]
    assert con["order"] == {"settings": 90}
    assert pm.call_button("btn", "hello") == {"ok": True, "result": "got:hello"}
    assert pm.call_button("btn2", "any")["error"] == "no_button_handler"
    assert pm.call_button("missing", "any")["error"] == "plugin_disabled"

    # 重复 key 拒绝
    ctx = pm_mod.PluginContext(pm, pm._plugins["btn"])
    with pytest.raises(ValueError):
        ctx.register_button({"key": "hello", "label": "x"})


def test_vendor_path_appended_and_removed(env):
    _write_plugin(
        env.plugins,
        "v",
        {"entry": "main.py"},
        ENTRY_IMPORT,
        files={"vendor/thirdlib.py": "X = 1\n"},
    )
    pm = PluginManager()
    pm.init(env.cfg)
    vendor = str(env.plugins / "v" / "vendor")
    assert vendor in __import__("sys").path
    pm.set_enabled("v", False)
    assert vendor not in __import__("sys").path


def test_asset_only_plugin_without_entry(env):
    _write_plugin(env.plugins, "css-only", {"entry": ""}, None, files={"a.css": ""})
    pm = PluginManager()
    pm.init(env.cfg)
    assert _status(pm, "css-only")["status"] == "loaded"


def test_entry_outside_plugin_dir_rejected(env):
    _write_plugin(env.plugins, "esc", {"entry": "../outside.py"})
    outside = env.plugins / "outside.py"
    outside.write_text(ENTRY_IMPORT, encoding="utf-8")
    pm = PluginManager()
    pm.init(env.cfg)
    assert _status(pm, "esc")["status"] == "failed"


# --- webui 注入辅助 ---


def test_html_injection_helpers():
    from src import webui

    html = "<html><body>A</body></html>"
    out = webui._inject_before(html, "</body>", "<script src='x'></script>")
    assert out.index("<script") < out.index("</body>")
    out2 = webui._inject_after(
        '<div id="settings-content">', '<div id="settings-content">', "<b>s</b>"
    )
    assert out2.startswith('<div id="settings-content">\n<b>s</b>')
    # marker 不存在时原样返回
    assert webui._inject_before(html, "</head>", "x") == html
    assert webui._inject_after(html, "nope", "x") == html

    links, scripts = webui._split_asset_tags(
        '<link rel="stylesheet" href="a.css">\n<script defer src="b.js"></script>'
    )
    assert links == '<link rel="stylesheet" href="a.css">'
    assert scripts == '<script defer src="b.js"></script>'


def test_settings_page_has_plugin_group_and_anchor():
    from src import webui

    html = (webui.HTML_DIR / "settings.html").read_text(encoding="utf-8")
    assert 'data-group="plugin"' in html
    assert "switchSettingsGroup('plugin')" in html
    assert "<!-- plugin-sections -->" in html
    assert 'id="plugin-list"' in html
    js = (webui.HTML_DIR / "settings.js").read_text(encoding="utf-8")
    assert "initPlugins" in js
    assert "plugin_save_settings" in js
    assert "ommPluginRefresh" in js
    assert "pluginToggleCollapse" in js
    # 桥接未就绪时的重试与回填完成事件（修复插件列表为空导致折叠栏不生成）
    assert "initPluginRetries" in js
    assert "omm-plugin-section-filled" in js
    # 窗口大小开关区块 + 边框拖拽（8 向）
    assert 'id="s-window-resize"' in html
    assert "applyWindowResizeHandles" in js
    assert "win-resize-handle" in (
        webui.HTML_DIR.parent / "vue-src" / "style.css"
    ).read_text(encoding="utf-8")


def test_settings_route_injection(tmp_path, monkeypatch):
    """settings_page 在有插件时注入 asset tags/section，无插件时走静态快路径"""
    from src import webui

    sec = '<div class="section" data-group="plugin">P</div>'
    src = (
        "def on_load(ctx):\n"
        "    ctx.register_css('settings', 'p.css')\n"
        "    ctx.register_js('settings', 'p.js')\n"
        "    ctx.register_settings_section(%r)\n" % sec
    )
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config_mod, "_get_data_dir", lambda: data_dir)
    cfg = Config(tmp_path / "config" / "config.json")
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    cfg.set("plugin_dirs", [str(plugins)])
    _write_plugin(
        plugins,
        "p",
        {
            "entry": "main.py",
            "permissions": ["assets:serve", "settings:section"],
            "windows": ["main", "settings"],
        },
        src,
        files={"p.css": "", "p.js": ""},
    )
    pm = PluginManager()
    pm.init(cfg)
    monkeypatch.setattr(webui, "get_plugin_manager", lambda: pm)

    html = (webui.HTML_DIR / "settings.html").read_text(encoding="utf-8")
    links, scripts = webui._split_asset_tags(pm.asset_tags("settings"))
    sections = pm.settings_sections()
    out = webui._inject_before(html, "</head>", links)
    out = webui._inject_after(out, "<!-- plugin-sections -->", sections)
    out = webui._inject_before(out, "</body>", scripts)
    assert "/plugins/p/p.css?v=" in out
    assert out.index("<link") < out.index("</head>")
    assert "/plugins/p/p.js?v=" in out
    assert out.index('data-group="plugin">P') > out.index("plugin-sections")
    # 插件脚本在 settings.js 之后（defer 文档序）
    assert out.index("/settings.js") < out.index("/plugins/p/p.js")

    # 注入标记完整存在于真实文件
    assert "</head>" in html and "</body>" in html


def test_main_window_tags_injected_before_body():
    from src import webui

    html = (webui.HTML_DIR / "vue.html").read_text(encoding="utf-8")
    tags = '<link rel="stylesheet" href="/plugins/x/a.css?v=1">'
    out = webui._inject_before(html, "</body>", tags)
    assert "/plugins/x/a.css" in out
    assert out.index("/plugins/x/a.css") < out.index("</body>")
    # dist 脚本在插件标签之前（插件脚本 defer 晚于阻塞的 ohmymeme.js 执行）
    assert out.index("/dist/ohmymeme.js") < out.index("/plugins/x/a.css")


def test_webui_resolve_window_size(monkeypatch):
    import src.webui as webui_module

    class FakeCfg:
        def __init__(self, w=0, h=0):
            self.w, self.h = w, h

        def get(self, key, default=None):
            if key == "window_width":
                return self.w
            if key == "window_height":
                return self.h
            return default

    ui = webui_module.WebUI.__new__(webui_module.WebUI)
    ui._cfg = FakeCfg()
    empty_pm = PluginManager()
    monkeypatch.setattr(webui_module, "get_plugin_manager", lambda: empty_pm)
    assert ui._resolve_window_size() == (960, 640)

    ui._cfg = FakeCfg(1200, 800)
    assert ui._resolve_window_size() == (1200, 800)

    # 非法值回退默认
    ui._cfg = FakeCfg(-5, 99999)
    assert ui._resolve_window_size() == (960, 640)

    # 插件覆盖优先
    empty_pm._plugins["x"] = pm_mod.PluginInfo(Path("x"), {"id": "x"})
    empty_pm._plugins["x"].status = "loaded"
    empty_pm._plugins["x"].window = {"width": 1440, "height": 900}
    ui._cfg = FakeCfg(1200, 800)
    assert ui._resolve_window_size() == (1440, 900)


def test_jsapi_plugin_dispatch():
    import src.webui as webui_module

    class FakeCfg:
        def get(self, key, default=None):
            return default

    pm = PluginManager()
    # 直接构造已加载插件（跳过文件系统）
    info = pm_mod.PluginInfo(Path("p"), {"id": "p", "api_version": 1})
    info.status = "loaded"
    info.main_api["ping"] = lambda x: "pong:" + str(x)
    info.button_handler = lambda k: k.upper()
    pm._plugins["p"] = info

    js = webui_module.JsApi.__new__(webui_module.JsApi)
    monkey = webui_module.get_plugin_manager
    webui_module.get_plugin_manager = lambda: pm
    try:
        assert js.plugin_call("p", "ping", ["1"]) == "pong:1"
        assert js.plugin_call("p", "nope", [])["error"] == "method_not_found"
        assert js.plugin_call("ghost", "ping", [])["error"] == "plugin_disabled"
        assert js.plugin_button_click("p", "go") == {"ok": True, "result": "GO"}
    finally:
        webui_module.get_plugin_manager = monkey


def test_settings_api_plugin_methods(tmp_path, monkeypatch):
    import src.webui as webui_module

    data_dir = tmp_path / "data"
    monkeypatch.setattr(config_mod, "_get_data_dir", lambda: data_dir)
    cfg = Config(tmp_path / "config" / "config.json")
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    cfg.set("plugin_dirs", [str(plugins)])
    _write_plugin(plugins, "api", {"entry": "main.py"}, ENTRY_IMPORT)
    pm = PluginManager()
    pm.init(cfg)
    monkeypatch.setattr(webui_module, "get_plugin_manager", lambda: pm)

    api = webui_module.SettingsApi.__new__(webui_module.SettingsApi)
    listing = api.plugin_list()
    assert listing and listing[0]["id"] == "api"
    r = api.plugin_save_settings("api", {"k": "v"})
    assert r["ok"]
    assert api.plugin_get_settings("api") == {"k": "v"}
    assert api.plugin_set_enabled("api", False)["enabled"] is False
    assert api.plugin_set_enabled("api", True)["restart"] is True
    assert api.plugin_call("missing", "x", [])["error"] == "plugin_disabled"
    assert api.plugin_list()[0]["id"] == "api"


def test_config_window_size_defaults_and_migration(tmp_path):
    # DEFAULTS 含窗口宽高与插件目录
    assert "window_width" in Config.DEFAULTS
    assert "window_height" in Config.DEFAULTS
    assert Config.DEFAULTS["plugin_dirs"] == []

    # 旧版本配置带窗口尺寸：_migrate 不得清除
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "version": "0.1.0",
                "window_width": 1234,
                "window_height": 567,
                "hotkey": "Ctrl+Shift+P",
            }
        ),
        encoding="utf-8",
    )
    cfg = Config(path)
    assert cfg.get("window_width") == 1234
    assert cfg.get("window_height") == 567
    assert cfg.get("hotkey") == "Ctrl+Shift+P"


def test_plugin_state_isolation_from_real_datadir(tmp_path, monkeypatch):
    """确保测试与真实 LOCALAPPDATA 数据目录隔离"""
    data_dir = tmp_path / "data"
    monkeypatch.setattr(config_mod, "_get_data_dir", lambda: data_dir)
    cfg = Config(tmp_path / "config" / "config.json")
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    cfg.set("plugin_dirs", [str(plugins)])
    _write_plugin(plugins, "iso", {"entry": "main.py"}, ENTRY_IMPORT)
    pm = PluginManager()
    pm.init(cfg)
    pm.set_enabled("iso", False)
    assert (data_dir / "plugins_state.json").exists()
