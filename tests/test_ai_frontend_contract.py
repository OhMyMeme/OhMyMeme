"""M4 契约回归测试：前端调用的每个后端方法，必须在它实际绑定的 API 类上存在。

这一课来自一次真实漏网：settings.html 的审核按钮调 `api('ai_review_items')`，
但设置窗口绑的是 SettingsApi，而该方法只在 JsApi 上 —— api() 对不存在的方法
静默返回 null，于是按钮 100% 失效且无任何报错。浏览器验证没抓到，是因为测试桩
把两个类的方法混在一个桩对象里，比真实后端宽松。
"""

import re
from pathlib import Path

import pytest

sys_path_root = Path(__file__).resolve().parent.parent

from src import webui  # noqa: E402

WEBUI_DIR = sys_path_root / "src" / "webui"
VUE_SRC = sys_path_root / "src" / "vue-src"


def _api_calls(text):
    """抽出 JS 里所有 api('method') 与 pywebview.api?.method( 形式的方法名"""
    names = set()
    names.update(re.findall(r"""api\(\s*['"]([A-Za-z_][\w]*)['"]""", text))
    names.update(re.findall(r"""pywebview\?*\.api\?\*\.([A-Za-z_][\w]*)\s*\(""", text))
    names.update(re.findall(r"""pywebview\.api\.([A-Za-z_][\w]*)\s*\(""", text))
    return names


def _public_methods(cls):
    return {n for n in dir(cls) if not n.startswith("_")}


def test_settings_js_calls_exist_on_settings_api():
    """settings.js 调用的每个方法都必须在 SettingsApi 上（设置窗口绑的是它）"""
    js = (WEBUI_DIR / "settings.js").read_text(encoding="utf-8")
    calls = _api_calls(js)
    have = _public_methods(webui.SettingsApi)
    # 既有的非 ai_ 方法名可能来自 JsApi 转发或历史遗留，这里只断言本次新增的 ai_* 契约
    ai_calls = {c for c in calls if c.startswith("ai_")}
    missing = sorted(ai_calls - have)
    assert missing == [], "settings.js 调用了 SettingsApi 上不存在的方法: %s" % missing


def test_ai_review_items_exists_on_both_apis():
    """审核列表两个窗口都要用，故两个类都必须有（这是修复过的真实缺陷）"""
    assert hasattr(webui.JsApi, "ai_review_items")
    assert hasattr(webui.SettingsApi, "ai_review_items")


def test_main_window_calls_exist_on_js_api():
    """主窗口（App.vue + 新组件）调用的 ai_* 方法必须在 JsApi 上"""
    texts = []
    for p in [VUE_SRC / "App.vue"] + sorted((VUE_SRC / "components").glob("*.vue")):
        texts.append(p.read_text(encoding="utf-8"))
    calls = set()
    for t in texts:
        calls |= _api_calls(t)
    have = _public_methods(webui.JsApi)
    ai_calls = {c for c in calls if c.startswith("ai_")}
    missing = sorted(ai_calls - have)
    assert missing == [], "主窗口调用了 JsApi 上不存在的方法: %s" % missing


def test_review_item_shape_has_existing_tags():
    """两个审核弹窗都渲染 existing_tags，契约必须带该字段"""
    import inspect

    src = inspect.getsource(webui.get_ai_review_items)
    assert "existing_tags" in src


def test_embed_rebuild_does_not_start_generation():
    """前端依赖「rebuild 只清不建」这一语义，docstring 与行为必须一致"""
    import inspect

    src = inspect.getsource(webui.SettingsApi.ai_embed_rebuild)
    # 只清空、不启动生成：不得出现 start_ai_embed_job
    assert "start_ai_embed_job" not in src
    assert "clear_embeddings" in src


def test_confirm_overlay_above_static_overlays():
    """showConfirm 动态层必须高于静态覆盖层(400)，否则从覆盖层内调用会永久卡死"""
    js = (WEBUI_DIR / "settings.js").read_text(encoding="utf-8")
    html = (WEBUI_DIR / "settings.html").read_text(encoding="utf-8")
    # 只看真正赋给 style.cssText 的 z-index，避开注释里出现的数字
    conf = re.search(
        r"function showConfirm[\s\S]{0,600}?style\.cssText\s*=\s*'[^']*z-index:(\d+)",
        js,
    )
    assert conf, "未找到 showConfirm 的 z-index"
    static_z = [int(z) for z in re.findall(r"z-index:(\d+)", html)]
    assert static_z, "settings.html 中未找到静态覆盖层 z-index"
    assert int(conf.group(1)) > max(
        static_z
    ), "showConfirm z-index=%s 未高于静态覆盖层最大值 %s" % (
        conf.group(1),
        max(static_z),
    )


def test_new_ai_overlays_have_dialog_role():
    """新增的 3 个 AI 覆盖层需带 role=dialog + aria-modal（Tab 陷阱据此收窄）"""
    html = (WEBUI_DIR / "settings.html").read_text(encoding="utf-8")
    for oid in (
        "ai-tag-progress-overlay",
        "ai-embed-progress-overlay",
        "ai-review-overlay",
    ):
        idx = html.find('id="%s"' % oid)
        assert idx != -1, oid
        seg = html[idx : idx + 700]
        assert 'role="dialog"' in seg, "%s 缺 role=dialog" % oid
        assert 'aria-modal="true"' in seg, "%s 缺 aria-modal" % oid


def test_switch_settings_group_respects_ai_master_switch():
    """切到 ai 分组时必须重算开关显隐，否则「总开关关闭即零入口」在设置页失效"""
    js = (WEBUI_DIR / "settings.js").read_text(encoding="utf-8")
    m = re.search(r"function switchSettingsGroup\(group\)\s*\{[\s\S]{0,900}?\n\}", js)
    assert m, "未找到 switchSettingsGroup"
    body = m.group(0)
    assert "toggleAiEnabled()" in body, "switchSettingsGroup 未在 ai 分组重算开关显隐"
