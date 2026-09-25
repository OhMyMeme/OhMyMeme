"""复制时避免 WebP（动图转 GIF、静态转 JPG）单元测试"""

import os
import tempfile

import pytest
from PIL import Image

from src.clipboard_util import (
    _animated_webp_to_gif,
    _resize_static_to_webp,
    _static_webp_to_jpg,
    convert_avoid_webp,
)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """转换产物缓存到系统临时目录且不删除，测试必须隔离，否则会命中上次运行的残留"""
    cache = tmp_path / "conv_cache"
    cache.mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(cache))
    return cache


def _animated_webp(path, size=64, n=4, durations=None, loop=0, alpha=True):
    """生成测试用动画 WebP

    注意：Pillow 的 WebP 编码器仅在透明区域成片分布时才写入 alpha 平面
    （整幅画布全透明 + 小色块会被静默压平为 RGB），故这里保留大块透明区
    """
    frames = []
    for i in range(n):
        if alpha:
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            for x in range(size):
                for y in range(size // 2):
                    img.putpixel((x, y), (20, 120, 220, 255))
            img.putpixel((i % size, size - 4), (255, 0, 0, 255))
        else:
            img = Image.new("RGB", (size, size), (20, 120, 220))
        frames.append(img)
    frames[0].save(
        path,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=durations or [40] * n,
        loop=loop,
    )
    return path


def _static_webp(path, size=64, alpha=False, transparent=True):
    """生成测试用静态 WebP"""
    if alpha:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        for x in range(size // 4, size // 2):
            for y in range(size // 4, size // 2):
                img.putpixel((x, y), (20, 120, 220, 255))
    else:
        img = Image.new("RGB", (size, size), (20, 120, 220))
    img.save(path, format="WEBP", quality=90)
    return path


def test_animated_webp_to_gif_preserves_frames_and_durations(tmp_path):
    """动画 WebP 转 GIF 保留帧数与真实帧延时（不做 <50ms 钳制）"""
    src = _animated_webp(
        str(tmp_path / "a.webp"), n=5, durations=[30, 40, 50, 120, 200]
    )
    out = _animated_webp_to_gif(src)
    assert out and out.endswith(".gif")
    with Image.open(out) as im:
        assert im.format == "GIF"
        assert im.n_frames == 5
        durations = []
        for i in range(im.n_frames):
            im.seek(i)
            im.load()
            durations.append(im.info.get("duration"))
    # 30/40/50ms 必须保真，不能被旧实现的 <50ms→100ms 改成 100
    assert durations == [30, 40, 50, 120, 200]


def test_animated_webp_to_gif_quantizes_to_gif_centiseconds(tmp_path):
    """源延时不整除 10ms 时按 GIF 的厘秒精度就近量化，且绝不放大延时

    GIF 格式只能以 10ms 为单位存储帧延时（Pillow 写 int(duration/10) 厘秒），
    故 41ms 读回为 40ms 属格式固有限制；关键是不得像旧实现那样把 <50ms 抬到 100ms
    """
    src = _animated_webp(str(tmp_path / "q.webp"), n=3, durations=[41, 33, 127])
    out = _animated_webp_to_gif(src)
    with Image.open(out) as im:
        durations = []
        for i in range(im.n_frames):
            im.seek(i)
            im.load()
            durations.append(im.info.get("duration"))
    # 就近量化到厘秒：41->40, 33->30, 127->130（Pillow 取整规则）
    assert durations[0] == 40
    assert durations[1] == 30
    assert durations[2] in (120, 130)
    # 核心回归：不得被放大（旧实现会把 41/33 变成 100）
    assert all(d <= 130 for d in durations)


def test_animated_webp_to_gif_keeps_transparency(tmp_path):
    """动画 WebP 转 GIF 后透明区域仍透明（disposal=2 不留残影）"""
    src = _animated_webp(str(tmp_path / "t.webp"), size=64, n=3)
    with Image.open(src) as s:
        s.seek(0)
        s.load()
        assert s.mode in ("RGBA", "LA"), "fixture 必须真的带 alpha"
        assert s.convert("RGBA").getpixel((60, 60))[3] == 0
    out = _animated_webp_to_gif(src)
    with Image.open(out) as im:
        assert im.info.get("transparency") is not None
        im.seek(0)
        im.load()
        rgba = im.convert("RGBA")
    # 上半部分为不透明色块，下半部分应保持透明
    assert rgba.getpixel((60, 60))[3] == 0
    assert rgba.getpixel((10, 10))[3] > 0


def _ghosting_webp(path, size=64):
    """帧0 在大片透明区上有一个色块、后续帧该处恢复透明（残影检测样本）

    保留上半幅不透明区以满足 Pillow WebP 编码器写入 alpha 平面的条件
    """
    frames = []
    for i in range(2):
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        for x in range(size):
            for y in range(size // 3):
                img.putpixel((x, y), (20, 120, 220, 255))
        if i == 0:
            for x in range(40, size):
                for y in range(40, size):
                    img.putpixel((x, y), (255, 0, 0, 255))
        frames.append(img)
    frames[0].save(
        path,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=[40, 80],
        loop=0,
    )
    return path


def test_animated_webp_to_gif_uses_disposal_to_avoid_ghosting(tmp_path):
    """逐帧处置必须清空画布：帧0 的色块不得在后续帧以残影形式残留

    这正是当初 GIF 转换被撤下的原因（黑底/残影），回归保护点
    """
    src = _ghosting_webp(str(tmp_path / "ghost.webp"))
    with Image.open(src) as s:
        assert s.n_frames == 2
        s.seek(1)
        s.load()
        # 源文件第二帧该处应为透明，说明确实是「帧0 有、帧1 无」
        assert s.convert("RGBA").getpixel((50, 50))[3] == 0

    out = _animated_webp_to_gif(src)
    with Image.open(out) as im:
        assert im.n_frames == 2
        im.seek(1)
        im.load()
        px = im.convert("RGBA").getpixel((50, 50))
    # 帧1 该处必须透明；若退化为默认 disposal=0，这里会读到帧0 的红色
    assert px[3] == 0, f"残影未被清除: {px}"


def test_animated_webp_to_gif_respects_max_side(tmp_path):
    """GIF 体积随像素数增长，故按上限等比缩小；缩后仍是有效动画"""
    src = _animated_webp(str(tmp_path / "big.webp"), size=128, n=3)
    out = _animated_webp_to_gif(src, max_side=64)
    with Image.open(out) as im:
        assert max(im.size) == 64
        assert im.n_frames == 3


def test_animated_webp_to_gif_never_upscales_small(tmp_path):
    """小图不得被放大到上限（放大只会白涨体积并糊化）"""
    src = _animated_webp(str(tmp_path / "small.webp"), size=48, n=3)
    out = _animated_webp_to_gif(src, max_side=512)
    with Image.open(out) as im:
        assert max(im.size) == 48


def test_animated_webp_to_gif_no_cap_keeps_original_size(tmp_path):
    """上限为 0 时不缩放，保持原分辨率"""
    src = _animated_webp(str(tmp_path / "orig.webp"), size=128, n=3)
    out = _animated_webp_to_gif(src, max_side=0)
    with Image.open(out) as im:
        assert max(im.size) == 128


def test_animated_webp_to_gif_cap_scales_transparency(tmp_path):
    """缩放后透明区域仍保持透明"""
    src = _animated_webp(str(tmp_path / "ta.webp"), size=128, n=3)
    out = _animated_webp_to_gif(src, max_side=64)
    with Image.open(out) as im:
        assert im.info.get("transparency") is not None
        im.seek(0)
        im.load()
        rgba = im.convert("RGBA")
    # 下半幅为透明区
    assert rgba.getpixel((32, 60))[3] == 0


def test_convert_avoid_webp_cap_not_applied_to_static(tmp_path):
    """上限只作用于动图转 GIF，静态 WebP 转 JPG 保持原分辨率（不处理模式不缩放原图）"""
    big = tmp_path / "bigstatic.webp"
    Image.new("RGB", (900, 700), (40, 80, 160)).save(big, format="WEBP", quality=90)
    out = convert_avoid_webp(str(big), max_side=200)
    assert out.endswith(".jpg")
    with Image.open(out) as im:
        assert im.size == (900, 700)


def test_animated_webp_to_gif_keeps_loop(tmp_path):
    """动画 WebP 的 loop 值透传到 GIF"""
    src = _animated_webp(str(tmp_path / "l.webp"), n=3, loop=2)
    out = _animated_webp_to_gif(src)
    with Image.open(out) as im:
        assert im.info.get("loop") == 2


def test_animated_webp_to_gif_cache_reuse(tmp_path):
    """同一源文件重复转换命中缓存，返回同一路径且文件有效"""
    src = _animated_webp(str(tmp_path / "c.webp"), n=3)
    first = _animated_webp_to_gif(src)
    second = _animated_webp_to_gif(src)
    assert first == second
    assert os.path.isfile(first)


def test_animated_webp_to_gif_skips_static(tmp_path):
    """静态 WebP 不走动画转换路径"""
    src = _static_webp(str(tmp_path / "s.webp"))
    assert _animated_webp_to_gif(src) is None


def test_static_webp_to_jpg_flattens_alpha_to_white(tmp_path):
    """静态 WebP 转 JPG：透明区域合成为白色"""
    src = _static_webp(str(tmp_path / "st.webp"), alpha=True)
    out = _static_webp_to_jpg(src)
    assert out and out.endswith(".jpg")
    with Image.open(out) as im:
        assert im.format == "JPEG"
        assert im.mode == "RGB"
        # 左上角原为全透明，应被合成为白底
        assert im.getpixel((2, 2)) == (255, 255, 255)


def test_static_webp_to_jpg_skips_animated(tmp_path):
    """动画 WebP 不走静态转换路径"""
    src = _animated_webp(str(tmp_path / "an.webp"))
    assert _static_webp_to_jpg(src) is None


def test_convert_avoid_webp_leaves_other_formats_untouched(tmp_path):
    """非 WebP 文件原样返回，不做任何转换"""
    png = tmp_path / "x.png"
    Image.new("RGB", (32, 32), (1, 2, 3)).save(png, format="PNG")
    assert convert_avoid_webp(str(png)) == str(png)


def test_convert_avoid_webp_routes_by_animation(tmp_path):
    """收口函数按动画与否分别产出 GIF 与 JPG"""
    anim = _animated_webp(str(tmp_path / "ra.webp"))
    static = _static_webp(str(tmp_path / "rs.webp"))
    assert convert_avoid_webp(anim).endswith(".gif")
    assert convert_avoid_webp(static).endswith(".jpg")


def test_convert_avoid_webp_falls_back_on_broken_file(tmp_path):
    """损坏文件转换失败时回退原路径，不抛异常"""
    bad = tmp_path / "broken.webp"
    bad.write_bytes(b"RIFF\x00\x00\x00\x00WEBPnot-a-real-image")
    assert convert_avoid_webp(str(bad)) == str(bad)


def test_resize_avoid_webp_never_outputs_webp(tmp_path):
    """超限缩放开启避免 WebP 后，不透明图产出 JPG、带透明图产出 PNG"""
    opaque = tmp_path / "big.jpg"
    Image.new("RGB", (600, 400), (10, 20, 30)).save(opaque, format="JPEG")
    out = _resize_static_to_webp(str(opaque), 200, avoid_webp=True)
    assert out and out.endswith(".jpg")
    with Image.open(out) as im:
        assert im.format == "JPEG"
        assert max(im.size) == 200

    semi = tmp_path / "big.png"
    img = Image.new("RGBA", (600, 400), (0, 0, 0, 0))
    for x in range(100, 300):
        for y in range(100, 200):
            img.putpixel((x, y), (200, 30, 30, 255))
    img.save(semi, format="PNG")
    out2 = _resize_static_to_webp(str(semi), 200, avoid_webp=True)
    assert out2 and out2.endswith(".png")
    with Image.open(out2) as im:
        assert im.format == "PNG"
        assert max(im.size) == 200


def test_resize_avoid_webp_jpg_cache_key_includes_quality(tmp_path, monkeypatch):
    """JPG 质量参数必须进入缓存键，改质量后不得命中旧产物（避免静默stale）"""
    import src.clipboard_util as cu

    src = tmp_path / "big.jpg"
    Image.new("RGB", (600, 400), (10, 20, 30)).save(src, format="JPEG")
    first = cu._resize_static_to_webp(str(src), 200, avoid_webp=True)
    assert first and "_q90_" in os.path.basename(first)

    monkeypatch.setattr(cu, "_RESIZE_JPG_QUALITY", 60)
    second = cu._resize_static_to_webp(str(src), 200, avoid_webp=True)
    assert second != first
    assert "_q60_" in os.path.basename(second)
    assert os.path.isfile(first) and os.path.isfile(second)


def test_resize_avoid_webp_png_cache_key_excludes_quality(tmp_path, monkeypatch):
    """PNG 无质量参数，其缓存键不应随 JPG 质量变化"""
    import src.clipboard_util as cu

    src = tmp_path / "big.png"
    img = Image.new("RGBA", (600, 400), (0, 0, 0, 0))
    for x in range(100, 300):
        for y in range(100, 200):
            img.putpixel((x, y), (200, 30, 30, 255))
    img.save(src, format="PNG")

    first = cu._resize_static_to_webp(str(src), 200, avoid_webp=True)
    monkeypatch.setattr(cu, "_RESIZE_JPG_QUALITY", 60)
    second = cu._resize_static_to_webp(str(src), 200, avoid_webp=True)
    assert first == second


def test_resize_without_flag_still_outputs_webp(tmp_path):
    """开关关闭时缩放产物维持 WebP，行为与改动前一致"""
    opaque = tmp_path / "keep.jpg"
    Image.new("RGB", (600, 400), (10, 20, 30)).save(opaque, format="JPEG")
    out = _resize_static_to_webp(str(opaque), 200)
    assert out and out.endswith(".webp")


def test_copy_avoid_webp_default_off():
    """新配置键默认关闭，升级后不改变既有复制行为"""
    from src.config import Config

    assert Config.DEFAULTS.get("copy_avoid_webp") is False


def test_copy_meme_converts_only_when_enabled(monkeypatch, tmp_path):
    """copy_meme 仅在开关开启时把 WebP 转为 GIF/JPG 后再复制"""
    import src.webui as webui_module
    from src.webui import JsApi

    src = _animated_webp(str(tmp_path / "cm.webp"))
    copied = {}

    class _Db:
        def get_by_id(self, meme_id):
            return {"id": meme_id, "filename": "cm.webp", "mime_type": "image/webp"}

        def record_use(self, meme_id):
            pass

    class _Ui:
        def schedule_hide(self):
            pass

    api = JsApi(_Ui())
    api._db = _Db()
    monkeypatch.setattr(api, "_find_meme_file", lambda filename: src)
    monkeypatch.setattr(
        webui_module,
        "copy_image_to_clipboard",
        lambda path: copied.update(p=path) or True,
    )

    monkeypatch.setattr(
        api._cfg, "_data", {"copy_avoid_webp": False, "copy_resize_mode": 0}
    )
    api.copy_meme(1)
    assert copied["p"].endswith(".webp")

    monkeypatch.setattr(
        api._cfg, "_data", {"copy_avoid_webp": True, "copy_resize_mode": 0}
    )
    api.copy_meme(1)
    assert copied["p"].endswith(".gif")


def test_copy_meme_static_webp_becomes_jpg(monkeypatch, tmp_path):
    """开关开启时静态 WebP 复制产出 JPG"""
    import src.webui as webui_module
    from src.webui import JsApi

    src = _static_webp(str(tmp_path / "sm.webp"))
    copied = {}

    class _Db:
        def get_by_id(self, meme_id):
            return {"id": meme_id, "filename": "sm.webp", "mime_type": "image/webp"}

        def record_use(self, meme_id):
            pass

    class _Ui:
        def schedule_hide(self):
            pass

    api = JsApi(_Ui())
    api._db = _Db()
    monkeypatch.setattr(api, "_find_meme_file", lambda filename: src)
    monkeypatch.setattr(
        webui_module,
        "copy_image_to_clipboard",
        lambda path: copied.update(p=path) or True,
    )
    monkeypatch.setattr(
        api._cfg, "_data", {"copy_avoid_webp": True, "copy_resize_mode": 0}
    )
    assert api.copy_meme(1)["ok"]
    assert copied["p"].endswith(".jpg")


def test_copy_meme_oversized_static_webp_scales_to_jpg(monkeypatch, tmp_path):
    """核心承诺：mode1 缩放 + 开关开启时，超限静态图产物必须是 JPG 而非 WebP

    直接覆盖 webui -> convert_image_mode_1 -> _resize_static_to_webp 整条接线
    """
    import src.webui as webui_module
    from src.webui import JsApi

    src = tmp_path / "big.webp"
    img = Image.new("RGB", (800, 600), (30, 90, 200))
    img.save(src, format="WEBP", quality=90)
    copied = {}

    class _Db:
        def get_by_id(self, meme_id):
            return {"id": meme_id, "filename": src.name, "mime_type": "image/webp"}

        def record_use(self, meme_id):
            pass

    class _Ui:
        def schedule_hide(self):
            pass

    api = JsApi(_Ui())
    api._db = _Db()
    monkeypatch.setattr(api, "_find_meme_file", lambda filename: str(src))
    monkeypatch.setattr(
        webui_module,
        "copy_image_to_clipboard",
        lambda path: copied.update(p=path) or True,
    )

    # 开关关闭：维持既有行为，缩放产物是 WebP
    monkeypatch.setattr(
        api._cfg,
        "_data",
        {"copy_avoid_webp": False, "copy_resize_mode": 1, "copy_resize_max": 200},
    )
    assert api.copy_meme(1)["ok"]
    assert copied["p"].endswith(".webp"), copied["p"]
    with Image.open(copied["p"]) as im:
        assert max(im.size) == 200

    # 开关开启：产物不得再是 WebP
    monkeypatch.setattr(
        api._cfg,
        "_data",
        {"copy_avoid_webp": True, "copy_resize_mode": 1, "copy_resize_max": 200},
    )
    assert api.copy_meme(1)["ok"]
    assert not copied["p"].endswith(".webp"), copied["p"]
    assert copied["p"].endswith(".jpg"), copied["p"]
    with Image.open(copied["p"]) as im:
        assert im.format == "JPEG"
        assert max(im.size) == 200


def test_copy_meme_no_webp_product_for_any_mode(monkeypatch, tmp_path):
    """开关开启时，任一模式与尺寸组合的复制产物都不含 WebP"""
    import src.webui as webui_module
    from src.webui import JsApi

    anim = _animated_webp(str(tmp_path / "m_anim.webp"), size=64, n=3)
    small = _static_webp(str(tmp_path / "m_small.webp"), size=64)
    big = tmp_path / "m_big.webp"
    Image.new("RGB", (700, 500), (10, 10, 10)).save(big, format="WEBP", quality=90)
    transparent = tmp_path / "m_alpha.png"
    im = Image.new("RGBA", (700, 500), (0, 0, 0, 0))
    for x in range(200):
        for y in range(200):
            im.putpixel((x, y), (200, 30, 30, 255))
    im.save(transparent, format="PNG")

    copied = {}

    class _Db:
        def __init__(self, name):
            self._name = name

        def get_by_id(self, meme_id):
            return {"id": meme_id, "filename": self._name, "mime_type": ""}

        def record_use(self, meme_id):
            pass

    class _Ui:
        def schedule_hide(self):
            pass

    monkeypatch.setattr(
        webui_module,
        "copy_image_to_clipboard",
        lambda path: copied.update(p=path) or True,
    )

    cases = [
        (anim, {"copy_resize_mode": 0}),
        (anim, {"copy_resize_mode": 2}),
        (small, {"copy_resize_mode": 0}),
        (small, {"copy_resize_mode": 1}),
        (big, {"copy_resize_mode": 0}),
        (big, {"copy_resize_mode": 1, "copy_resize_max": 200}),
        (big, {"copy_resize_mode": 2, "copy_resize_max": 200}),
        (transparent, {"copy_resize_mode": 1, "copy_resize_max": 200}),
    ]
    for path, extra in cases:
        api = JsApi(_Ui())
        api._db = _Db(os.path.basename(path))
        monkeypatch.setattr(api, "_find_meme_file", lambda filename, p=path: str(p))
        cfg = {"copy_avoid_webp": True}
        cfg.update(extra)
        monkeypatch.setattr(api._cfg, "_data", cfg)
        assert api.copy_meme(1)["ok"]
        produced = copied["p"]
        assert not produced.lower().endswith(
            ".webp"
        ), f"{path.name} {extra} -> {produced}"
        assert produced != str(path) or path.suffix.lower() != ".webp"


def test_copy_meme_mode1_passes_avoid_webp_to_resizer(monkeypatch, tmp_path):
    """mode1 必须把 avoid_webp 透传给缩放函数（否则先转 WebP 再转 JPG 会二次有损编码）"""
    import src.clipboard_util as cu
    import src.webui as webui_module
    from src.webui import JsApi

    src = tmp_path / "w.webp"
    Image.new("RGB", (700, 500), (10, 20, 30)).save(src, format="WEBP", quality=90)
    seen = {}
    real = cu._resize_static_to_webp

    def spy(image_path, max_side, avoid_webp=False):
        seen["avoid_webp"] = avoid_webp
        return real(image_path, max_side, avoid_webp)

    monkeypatch.setattr(cu, "_resize_static_to_webp", spy)

    class _Db:
        def get_by_id(self, meme_id):
            return {"id": meme_id, "filename": src.name, "mime_type": "image/webp"}

        def record_use(self, meme_id):
            pass

    class _Ui:
        def schedule_hide(self):
            pass

    api = JsApi(_Ui())
    api._db = _Db()
    monkeypatch.setattr(api, "_find_meme_file", lambda filename: str(src))
    monkeypatch.setattr(webui_module, "copy_image_to_clipboard", lambda path: True)
    monkeypatch.setattr(
        api._cfg,
        "_data",
        {"copy_avoid_webp": True, "copy_resize_mode": 1, "copy_resize_max": 200},
    )
    assert api.copy_meme(1)["ok"]
    assert seen.get("avoid_webp") is True, "mode1 未开启 avoid_webp，会产生二次有损编码"


@pytest.mark.parametrize("ext", [".png", ".jpg", ".gif"])
def test_copy_meme_non_webp_untouched(monkeypatch, tmp_path, ext):
    """非 WebP 源即使开关开启也不产生转换副本"""
    import src.webui as webui_module
    from src.webui import JsApi

    src = tmp_path / f"plain{ext}"
    Image.new("RGB", (32, 32), (9, 9, 9)).save(src)
    copied = {}

    class _Db:
        def get_by_id(self, meme_id):
            return {"id": meme_id, "filename": src.name, "mime_type": "image/x"}

        def record_use(self, meme_id):
            pass

    class _Ui:
        def schedule_hide(self):
            pass

    api = JsApi(_Ui())
    api._db = _Db()
    monkeypatch.setattr(api, "_find_meme_file", lambda filename: str(src))
    monkeypatch.setattr(
        webui_module,
        "copy_image_to_clipboard",
        lambda path: copied.update(p=path) or True,
    )
    monkeypatch.setattr(
        api._cfg, "_data", {"copy_avoid_webp": True, "copy_resize_mode": 0}
    )
    assert api.copy_meme(1)["ok"]
    assert copied["p"] == str(src)
