"""# _do_import 并发去重测试

核心保障：并发导入同一字节图只产生 1 条记录；不同图并发都能入库。
说明：隔离 DB 与 cache_dir，`WebUI` 实例可安全构造（test_startup 已验证不启 GUI）。
"""

import concurrent.futures
import shutil

import pytest
from PIL import Image

from src import webui
from src.database import MemeDB


class _IsoCfg:
    """隔离 config：仅暴露 _do_import 用到的 cache_dir 等"""

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir
        self.data_dir = cache_dir.parent / "data"
        self.thumbnail_dir = cache_dir.parent / "thumbs"

    def get(self, key, default=None):
        return default


@pytest.fixture
def env(monkeypatch, tmp_path):
    """隔离 DB/cache 并 patch 模块级 get_db/get_config，返回 (db, cache_dir, WebUI)"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    db = MemeDB(tmp_path / "test.db")
    cfg = _IsoCfg(cache_dir)
    monkeypatch.setattr(webui, "get_db", lambda: db)
    monkeypatch.setattr(webui, "get_config", lambda: cfg)
    # _do_import 成功路径会调 build_manifest；manifest 单独导入 config/database，
    # 需在 manifest 命名空间也 patch，否则会读写真实 data_dir
    import src.manifest as _manifest

    monkeypatch.setattr(_manifest, "get_db", lambda: db)
    monkeypatch.setattr(_manifest, "get_config", lambda: cfg)
    ui = webui.WebUI()
    ui._cfg = None  # 隔离模式下不依赖真实 cfg（_do_import 用模块级 get_config）
    return db, cache_dir, ui


def _make_img(path, color, size=96):
    Image.new("RGB", (size, size), color).save(path)


def test_concurrent_same_image_yields_single_row(env):
    db, cache_dir, ui = env
    same = cache_dir / "_con_same.png"
    _make_img(str(same), (200, 30, 40))
    copies = [cache_dir / f"same{i}.png" for i in range(2)]
    for c in copies:
        shutil.copy2(str(same), c)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(lambda c: ui._do_import([str(c)], ["same"]), copies))

    assert len(db.get_all()) == 1


def test_concurrent_different_images_both_imported(env):
    db, cache_dir, ui = env
    a = cache_dir / "a.png"
    b = cache_dir / "b.png"
    _make_img(str(a), (10, 200, 30))
    _make_img(str(b), (30, 40, 200))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(lambda p: ui._do_import([str(p)], [p.stem]), (a, b)))

    assert len(db.get_all()) == 2


def test_ensure_collection_same_name_reused(env):
    """同名分组复用：两次 ensure 返回同一 cid，且不产生重复空分组"""
    db, cache_dir, ui = env
    # 造 2 条 meme 记录拿 id
    ids = []
    for i in range(2):
        mid = db.add_meme(
            filename=f"g{i}.png",
            file_hash=f"h{i}",
            width=8,
            height=8,
            file_size=100,
            mime_type="image/png",
            original_name=f"g{i}",
        )
        ids.append(mid)
    c1 = ui.ensure_import_collection(ids, "Telegram")
    # 不同时间再次导入新图并 ensure 同名 → cid 一致
    ids2 = [
        db.add_meme(
            filename="g2.png",
            file_hash="h9",
            width=8,
            height=8,
            file_size=100,
            mime_type="image/png",
            original_name="g2",
        )
    ]
    c2 = ui.ensure_import_collection(ids2, "Telegram")
    assert c1 == c2 and c1 > 0
    # collections 无重复空分组
    conn = db._get_conn()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM collections WHERE name='Telegram'"
    ).fetchone()[0]
    assert cnt == 1  # 不是 2！


def test_ensure_collection_empty_args(env):
    """空 ids / 空 group_name 返回 -1，不建任何分组"""
    db, cache_dir, ui = env
    assert ui.ensure_import_collection([], "Telegram") == -1
    assert ui.ensure_import_collection([1], "") == -1
    assert ui.ensure_import_collection([], "") == -1
