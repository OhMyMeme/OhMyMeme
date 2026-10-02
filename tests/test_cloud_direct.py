"""云端直接使用 - sync 侧测试

覆盖：config 默认开关、cloud_missing 差集与容错、cloud-index 缓存原子读写、
download_single 原子落盘、prefetch_thumbs 预取、push 缩略图差集上传与远端删除联动；
webui 侧：云条目混入主网格分页、过滤与计数、云态刷新、cloud_download 校验/去重/后补。
"""

import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_sync import _entry, _FakeBackend, _FakeDb

from src import config as config_module
from src import sync
from src.config import Config
from src.manifest import INDEX_FILENAME
from src.sync import (
    _push_thumbs,
    cloud_missing,
    download_single,
    load_cloud_manifest,
    prefetch_thumbs,
    save_cloud_manifest,
)

SHA_A = "aa" * 32
SHA_B = "bb" * 32
SHA_C = "cc" * 32
SHA_D = "dd" * 32


# ─── config 默认值 ───


def test_cloud_direct_default_true(tmp_path):
    cfg = Config(tmp_path / "config.json")
    assert cfg.get("cloud_direct") is True
    assert cfg.get("cloud_thumb_auto_push") is True
    cfg.update_from_dict({"cloud_direct": False})
    assert cfg.get("cloud_direct") is False
    cfg.update_from_dict({"cloud_thumb_auto_push": False})
    assert cfg.get("cloud_thumb_auto_push") is False


# ─── cloud_missing 差集 ───


def test_cloud_missing_diff_fields():
    manifest = {
        "version": 3,
        "memes": [
            {"filename": "local.png", "name": "local", "sha256": SHA_A},
            {
                "filename": "cloud.png",
                "name": "云端图",
                "sha256": SHA_B,
                "tags": ["表情"],
            },
        ],
        "favorite": ["cloud.png"],
        "collections": [],
    }
    out = cloud_missing(manifest, {"local.png"})
    assert [m["filename"] for m in out] == ["cloud.png"]
    assert out[0]["sha256"] == SHA_B
    assert out[0]["tags"] == ["表情"]
    assert out[0]["favorited"] is True
    assert out[0]["collections"] == []


def test_cloud_missing_nested_collections():
    manifest = {
        "memes": [{"filename": "c.png", "name": "c", "sha256": SHA_A}],
        "collections": [
            {
                "name": "动物",
                "filenames": [],
                "children": [
                    {"name": "猫", "filenames": ["c.png"], "children": []},
                ],
            }
        ],
    }
    out = cloud_missing(manifest, set())
    assert out[0]["collections"] == ["动物/猫"]


def test_cloud_missing_skips_invalid_entries():
    manifest = {
        "memes": [
            "not-a-dict",
            {"filename": "bad.png", "name": "bad"},
            {"filename": "../evil.png", "name": "evil", "sha256": SHA_A},
            {"filename": "good.png", "name": "good", "sha256": "AB" * 32},
            {"filename": "fine.png", "name": "fine", "sha256": SHA_C},
        ]
    }
    out = cloud_missing(manifest, set())
    assert [m["filename"] for m in out] == ["fine.png"]


def test_cloud_missing_tolerates_legacy_manifest():
    manifest = {"memes": [{"filename": "old.png", "sha256": SHA_A}]}
    out = cloud_missing(manifest, set())
    assert out[0]["name"] == "old"
    assert out[0]["tags"] == []
    assert out[0]["favorited"] is False
    assert out[0]["collections"] == []
    assert cloud_missing(None, set()) == []
    assert cloud_missing({"memes": "oops"}, set()) == []


# ─── cloud-index 缓存读写 ───


@pytest.fixture
def cloud_cfg(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config_module, "_get_data_dir", lambda: data_dir)
    cfg = Config(tmp_path / "config.json")
    monkeypatch.setattr(sync, "get_config", lambda: cfg)
    return cfg


def test_cloud_manifest_roundtrip(cloud_cfg):
    manifest = {"version": 3, "memes": [{"filename": "a.png", "sha256": SHA_A}]}
    assert save_cloud_manifest(manifest) is True
    assert load_cloud_manifest() == manifest
    assert not list(cloud_cfg.data_dir.glob(".cloud-index-*"))


def test_cloud_manifest_missing_or_corrupt(cloud_cfg):
    assert load_cloud_manifest() is None
    (cloud_cfg.data_dir / "cloud-index.json").write_text("{broken", encoding="utf-8")
    assert load_cloud_manifest() is None


# ─── download_single ───


@pytest.fixture
def fake_bk(monkeypatch):
    bk = _FakeBackend()
    monkeypatch.setattr(sync, "_get_backend", lambda: bk)
    return bk


def test_download_single_success_atomic(fake_bk, tmp_path):
    fake_bk.remote_files.add("a.webp")
    dest = tmp_path / "thumbs" / "a.webp"
    assert download_single("thumbs/a.webp", dest) is True
    assert dest.read_bytes() == b"fake image content"
    assert not (dest.parent / "a.webp.part").exists()


def test_download_single_not_exists(fake_bk, tmp_path):
    dest = tmp_path / "thumbs" / "missing.webp"
    assert download_single("thumbs/missing.webp", dest) is False
    assert not dest.exists()
    assert fake_bk.download_paths == []


def test_download_single_fail_cleans_part(fake_bk, tmp_path):
    fake_bk.exists_overrides["a.webp"] = True  # 存在判定为真但下载失败
    dest = tmp_path / "thumbs" / "a.webp"
    assert download_single("thumbs/a.webp", dest) is False
    assert not dest.exists()
    assert not (dest.parent / "a.webp.part").exists()


# ─── prefetch_thumbs ───


@pytest.fixture
def sync_env(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "thumbnails").mkdir(parents=True, exist_ok=True)
    cfg = Config(tmp_path / "config.json")
    cfg.set("sync_type", "ftp")
    cfg.set("sync_threads", 1)
    monkeypatch.setattr(config_module, "_get_data_dir", lambda: data_dir)
    monkeypatch.setattr(sync, "get_config", lambda: cfg)
    import src.manifest as manifest_module

    monkeypatch.setattr(manifest_module, "get_config", lambda: cfg)
    db = _FakeDb()
    monkeypatch.setattr("src.manifest.get_db", lambda: db)
    monkeypatch.setattr("src.sync.get_db", lambda: db)
    bk = _FakeBackend()
    monkeypatch.setattr(sync, "_get_backend", lambda: bk)
    (data_dir / INDEX_FILENAME).write_text(
        json.dumps(
            {
                "version": 3,
                "memes": [_entry("test.png", SHA_A)],
                "collections": [],
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "cache" / "test.png").write_bytes(b"x" * 8)
    return SimpleNamespace(cfg=cfg, db=db, bk=bk, data_dir=data_dir)


def test_prefetch_downloads_and_skips(sync_env):
    thumb_dir = sync_env.data_dir / "thumbnails"
    sync_env.bk.remote_files.add(SHA_B + ".webp")
    (thumb_dir / f"{SHA_C}.webp").write_bytes(b"RIFF0000WEBPcached")
    missing = [
        {"sha256": SHA_B},  # 远端有 → 下载
        {"sha256": SHA_C},  # 本地已有 → 直接就绪
        {"sha256": "not-a-sha"},  # 非法 → 跳过
        {"sha256": SHA_A},  # 远端无 → 不就绪
    ]
    ready = prefetch_thumbs(missing, thumb_dir)
    assert ready == 2
    assert (thumb_dir / f"{SHA_B}.webp").read_bytes() == b"fake image content"
    assert (thumb_dir / f"{SHA_C}.webp").read_bytes() == b"RIFF0000WEBPcached"
    assert not (thumb_dir / f"{SHA_A}.webp").exists()
    assert not list(thumb_dir.glob("*.part"))


def test_prefetch_empty_missing_no_connect(sync_env):
    assert prefetch_thumbs([], sync_env.data_dir / "thumbnails") == 0


def test_prefetch_retries_failed_once(sync_env, monkeypatch):
    """首遍下载失败的缩略图在第二遍重试成功"""
    thumb_dir = sync_env.data_dir / "thumbnails"
    sync_env.bk.remote_files.add(SHA_B + ".webp")
    orig = sync_env.bk.file_exists
    calls = {"n": 0}

    def flaky(path):
        if str(path).endswith(SHA_B + ".webp"):
            calls["n"] += 1
            if calls["n"] == 1:
                return False
        return orig(path)

    monkeypatch.setattr(sync_env.bk, "file_exists", flaky)
    ready = prefetch_thumbs([{"sha256": SHA_B}], thumb_dir)
    assert ready == 1
    assert (thumb_dir / f"{SHA_B}.webp").exists()
    assert calls["n"] >= 2


# ─── push 缩略图差集上传与删除联动 ───


def test_push_thumbs_diff_upload(sync_env):
    sync_env.cfg.set("cloud_direct", True)
    thumb_dir = sync_env.data_dir / "thumbnails"
    (thumb_dir / f"{SHA_A}.webp").write_bytes(b"RIFF0000WEBPnew")
    (thumb_dir / f"{SHA_B}.webp").write_bytes(b"RIFF0000WEBPexist")
    (thumb_dir / "legacy_150.png").write_bytes(b"x")  # 旧命名跳过
    sync_env.bk.remote_files.add(SHA_B + ".webp")  # 远端已有 B

    sync.push()

    thumb_uploads = [p for p in sync_env.bk.upload_paths if "/thumbnails/" in p]
    root = sync._remote_root(sync_env.cfg).rstrip("/")
    assert thumb_uploads == [root + "/thumbnails/" + SHA_A + ".webp"]


def test_push_thumbs_off_when_cloud_direct_disabled(sync_env):
    sync_env.cfg.set("cloud_direct", False)
    thumb_dir = sync_env.data_dir / "thumbnails"
    (thumb_dir / f"{SHA_A}.webp").write_bytes(b"RIFF0000WEBPnew")

    sync.push()

    assert not any("/thumbnails/" in p for p in sync_env.bk.upload_paths)


def test_push_thumbs_upload_failure_does_not_fail_push(sync_env):
    sync_env.cfg.set("cloud_direct", True)
    thumb_dir = sync_env.data_dir / "thumbnails"
    (thumb_dir / f"{SHA_A}.webp").write_bytes(b"RIFF0000WEBPnew")
    sync_env.bk.upload_raises.add(SHA_A + ".webp")

    result = sync.push()

    assert result["errors"] == 0
    assert sync.get_sync_progress()["status"] == "done"


def test_push_deletes_remote_thumb_on_delete_remote(sync_env):
    sync_env.cfg.set("sync_delete_remote", True)
    sync_env.bk.remote_memes = {"ghost.png": _entry("ghost.png", SHA_A)}

    result = sync.push()

    assert result["deleted"] == 1
    assert any(
        p.endswith("/thumbnails/" + SHA_A + ".webp")
        for p in sync_env.bk.delete_calls
    )


# ─── 启动静默补传（cloud_thumb_auto_push） ───


def test_auto_push_thumbs_diff_upload(sync_env):
    sync_env.cfg.set("cloud_direct", True)
    thumb_dir = sync_env.data_dir / "thumbnails"
    (thumb_dir / f"{SHA_A}.webp").write_bytes(b"RIFF0000WEBPnew")
    (thumb_dir / f"{SHA_B}.webp").write_bytes(b"RIFF0000WEBPexist")
    (thumb_dir / "legacy_150.png").write_bytes(b"x")  # 旧命名跳过
    sync_env.bk.remote_files.add(SHA_B + ".webp")  # 远端已有 B

    n = sync.auto_push_thumbs()

    assert n == 1
    root = sync._remote_root(sync_env.cfg).rstrip("/")
    assert sync_env.bk.upload_paths == [root + "/thumbnails/" + SHA_A + ".webp"]


def test_auto_push_thumbs_gates(sync_env):
    sync_env.cfg.set("cloud_direct", False)
    assert sync.auto_push_thumbs() == 0
    sync_env.cfg.set("cloud_direct", True)
    sync_env.cfg.set("cloud_thumb_auto_push", False)
    assert sync.auto_push_thumbs() == 0
    sync_env.cfg.set("cloud_thumb_auto_push", True)
    sync_env.cfg.set("sync_type", "")
    assert sync.auto_push_thumbs() == 0
    assert sync_env.bk.upload_paths == []  # 门控在建连之前，未发生任何上传


def test_start_thumb_autopush_single_flight():
    import threading

    from src import webui as webui_module

    release = threading.Event()
    assert webui_module._start_thumb_autopush(release.wait) is True
    assert webui_module._start_thumb_autopush(lambda: None) is False  # 运行中去重
    release.set()
    for _ in range(200):
        with webui_module._thumb_autopush_lock:
            if not webui_module._thumb_autopush_running:
                break
        time.sleep(0.01)
    with webui_module._thumb_autopush_lock:
        assert webui_module._thumb_autopush_running is False  # 结束复位可再起


def test_push_thumbs_list_fallback_uses_file_exists(sync_env, monkeypatch):
    """list_files 不可用（NotImplementedError）时逐个 file_exists 降级"""

    class _NoListBackend(_FakeBackend):
        def list_files(self, path):
            raise NotImplementedError

    bk = _NoListBackend()
    monkeypatch.setattr(sync, "_get_backend", lambda: bk)
    thumb_dir = sync_env.data_dir / "thumbnails"
    (thumb_dir / f"{SHA_A}.webp").write_bytes(b"RIFF0000WEBPnew")
    bk.remote_files.add(SHA_A + ".webp")  # 远端已有 → 跳过
    (thumb_dir / f"{SHA_B}.webp").write_bytes(b"RIFF0000WEBPnew")

    uploaded = _push_thumbs(bk, "/root", thumb_dir)

    assert uploaded == 1
    assert bk.upload_paths == ["/root/thumbnails/" + SHA_B + ".webp"]


# ─── webui 侧：混入主网格 / 过滤 / 计数 ───


@pytest.fixture(autouse=True)
def _reset_cloud_state():
    from src import webui as webui_module

    def _reset():
        with webui_module._cloud_lock:
            webui_module._cloud_state.update(
                manifest=None,
                missing=[],
                local=frozenset(),
                loaded=False,
                refreshing=False,
            )
        with webui_module._cloud_inflight_lock:
            webui_module._cloud_inflight.clear()

    _reset()
    yield
    _reset()


@pytest.fixture
def js(monkeypatch, tmp_path):
    import src.manifest as manifest_module
    from src import webui as webui_module
    from src.database import MemeDB
    from src.webui import JsApi

    data_dir = tmp_path / "data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "thumbnails").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config_module, "_get_data_dir", lambda: data_dir)
    cfg = Config(tmp_path / "config.json")
    cfg.set("sync_type", "ftp")
    cfg.set("cloud_direct", True)
    monkeypatch.setattr(sync, "get_config", lambda: cfg)
    monkeypatch.setattr(webui_module, "get_config", lambda: cfg)
    monkeypatch.setattr(webui_module, "guide_ok", lambda: True)
    db = MemeDB(tmp_path / "memes.db")
    monkeypatch.setattr(webui_module, "get_db", lambda: db)
    monkeypatch.setattr(manifest_module, "get_config", lambda: cfg)
    monkeypatch.setattr(manifest_module, "get_db", lambda: db)
    api = JsApi(SimpleNamespace(schedule_hide=lambda: None))
    return SimpleNamespace(api=api, cfg=cfg, db=db, data_dir=data_dir)


def _set_cloud(js, manifest):
    """直接装载云端清单（与刷新线程写入等价：按本地集合预算差集）"""
    from src import webui as webui_module

    local = frozenset(js.db.get_all_filenames())
    with webui_module._cloud_lock:
        webui_module._cloud_state.update(
            manifest=manifest,
            missing=cloud_missing(manifest, local),
            local=local,
            loaded=True,
        )


def _png_bytes():
    import io

    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _names(rows):
    return [r["filename"] for r in rows]


def test_search_memes_cloud_tail_paging(js):
    js.db.add_meme(filename="a.png", file_hash=SHA_A)
    _set_cloud(
        js,
        {
            "memes": [
                {"filename": "c.png", "name": "云端c", "sha256": SHA_C},
                {"filename": "d.png", "name": "云端d", "sha256": SHA_D},
            ]
        },
    )
    api = js.api
    rows = api.search_memes("", None, None, 0, 10)
    assert _names(rows) == ["a.png", "c.png", "d.png"]
    assert rows[1]["cloud"] is True
    assert rows[1]["file_hash"] == SHA_C
    assert "id" not in rows[1]
    assert _names(api.search_memes("", None, None, 1, 10)) == ["c.png", "d.png"]
    assert _names(api.search_memes("", None, None, 2, 10)) == ["d.png"]
    assert api.search_memes("", None, None, 3, 10) == []
    assert _names(api.search_memes("", None, None, 0, 1)) == ["a.png"]
    assert _names(api.search_memes("", None, None, 1, 1)) == ["c.png"]
    assert _names(api.search_memes("", None, None, 2, 1)) == ["d.png"]
    assert api.count_memes() == 3


def test_cloud_order_follows_manifest(js):
    """本地与云行统一按云端 manifest memes 序穿插（远端排序），不做文件名重排；
    不在清单的本地行置顶，分页切片对合并结果生效"""
    js.db.add_meme(filename="a.png", file_hash=SHA_A)
    _set_cloud(
        js,
        {
            "memes": [
                {"filename": "z.png", "name": "z", "sha256": SHA_B},
                {"filename": "m.png", "name": "m", "sha256": SHA_C},
                {"filename": "a.png", "name": "本地已有", "sha256": SHA_A},
                {"filename": "c.png", "name": "c", "sha256": SHA_D},
            ]
        },
    )
    api = js.api
    assert _names(api.search_memes("", None, None, 0, 10)) == [
        "z.png",
        "m.png",
        "a.png",
        "c.png",
    ]
    assert _names(api.search_memes("", None, None, 1, 2)) == ["m.png", "a.png"]
    assert _names(api.search_memes("", None, None, 3, 10)) == ["c.png"]
    assert api.count_memes() == 4


def test_cloud_merge_extras_first_and_collection_order(js):
    """不在清单的本地行排最前；分组视图按清单该分组子树 filenames 序穿插"""
    js.db.add_meme(filename="new.png", file_hash=SHA_A)  # 未入清单 → 置顶
    js.db.add_meme(filename="b.png", file_hash=SHA_B)
    js.db.add_meme(filename="a.png", file_hash=SHA_C)
    top = js.db.create_collection("动物")
    js.db.add_memes_to_collection(
        [r["id"] for r in js.db.search(keyword="b.png")], top
    )
    js.db.add_memes_to_collection(
        [r["id"] for r in js.db.search(keyword="a.png")], top
    )
    _set_cloud(
        js,
        {
            "memes": [
                {"filename": "x.png", "name": "x", "sha256": SHA_D},
                {"filename": "b.png", "name": "b", "sha256": SHA_B},
                {"filename": "a.png", "name": "a", "sha256": SHA_C},
            ],
            "collections": [
                {"name": "动物", "filenames": ["b.png", "a.png"], "children": []}
            ],
        },
    )
    api = js.api
    # 全局视图：清单序 x,b,a；new.png 不在清单置顶
    assert _names(api.search_memes("", None, None, 0, 10)) == [
        "new.png",
        "x.png",
        "b.png",
        "a.png",
    ]
    # 分组视图：按清单分组子树 filenames 序（b,a），new.png 不在分组不出现
    assert _names(api.search_memes("", None, top, 0, 10)) == ["b.png", "a.png"]
    assert api.count_memes(collection_id=top) == 2
    assert api.count_memes() == 4


def test_search_memes_recent_excludes_cloud(js):
    js.db.add_meme(filename="a.png", file_hash=SHA_A)
    _set_cloud(
        js,
        {
            "memes": [{"filename": "c.png", "name": "c", "sha256": SHA_C}],
            "favorite": ["c.png"],
        },
    )
    assert js.api.search_memes("", None, -3, 0, 10) == []
    assert js.api.count_memes(collection_id=-3) == 0


def test_cloud_filters(js):
    js.db.add_meme(filename="local.png", file_hash=SHA_A)
    top = js.db.create_collection("动物")
    child = js.db.create_collection("猫", parent_id=top)
    _set_cloud(
        js,
        {
            "memes": [
                {
                    "filename": "fav.png",
                    "name": "云端收藏",
                    "sha256": SHA_B,
                    "tags": ["表情"],
                },
                {"filename": "grp.png", "name": "分组图", "sha256": SHA_C},
            ],
            "favorite": ["fav.png"],
            "collections": [
                {
                    "name": "动物",
                    "filenames": [],
                    "children": [
                        {"name": "猫", "filenames": ["grp.png"], "children": []}
                    ],
                }
            ],
        },
    )
    api = js.api
    # 关键字命中云端名称 / 云端标签（本地无命中时仅云端结果）
    assert _names(api.search_memes("云端", None, None, 0, 10)) == ["fav.png"]
    assert _names(api.search_memes("表情", None, None, 0, 10)) == ["fav.png"]
    # 标签交集（与本地 IN 语义一致：须全含）
    assert _names(api.search_memes("", ["表情"], None, 0, 10)) == ["fav.png"]
    assert api.count_memes(tags=["表情"]) == 1
    # 收藏夹虚拟分组含云端收藏
    assert _names(api.search_memes("", None, -2, 0, 10)) == ["fav.png"]
    assert api.count_memes(collection_id=-2) == 1
    # 未分类 = 本地未归组 + 云端无分组条目
    assert _names(api.search_memes("", None, -4, 0, 10)) == ["local.png", "fav.png"]
    assert api.count_memes(collection_id=-4) == 2
    # 分组：父组按全路径前缀递归命中子组成员
    assert _names(api.search_memes("", None, top, 0, 10)) == ["grp.png"]
    assert _names(api.search_memes("", None, child, 0, 10)) == ["grp.png"]
    assert api.count_memes(collection_id=top) == 1


def test_cloud_direct_disabled_hides_everything(js):
    js.db.add_meme(filename="a.png", file_hash=SHA_A)
    _set_cloud(js, {"memes": [{"filename": "c.png", "name": "c", "sha256": SHA_C}]})
    js.cfg.set("cloud_direct", False)
    rows = js.api.search_memes("", None, None, 0, 10)
    assert [r["filename"] for r in rows] == ["a.png"]
    assert js.api.count_memes() == 1
    assert js.api.get_tags() == []


def test_init_data_and_collection_counts_include_cloud(js):
    js.db.add_meme(filename="local.png", file_hash=SHA_A)
    top = js.db.create_collection("动物")
    _set_cloud(
        js,
        {
            "memes": [
                {
                    "filename": "fav.png",
                    "name": "fav",
                    "sha256": SHA_B,
                    "tags": ["云端tag"],
                },
                {"filename": "grp.png", "name": "grp", "sha256": SHA_C},
            ],
            "favorite": ["fav.png"],
            "collections": [
                {"name": "动物", "filenames": ["grp.png"], "children": []}
            ],
        },
    )
    init = js.api.get_init_data()
    assert [m["filename"] for m in init["memes"]] == ["local.png", "fav.png", "grp.png"]
    assert init["tags"] == ["云端tag"]
    sys_cols = {c["id"]: c for c in init["collections"] if c["id"] < 0}
    assert sys_cols[-2]["count"] == 1  # 云端收藏计入收藏夹
    assert sys_cols[-3]["count"] == 0
    assert sys_cols[-4]["count"] == 2  # local.png + fav.png 未分类
    top_node = next(c for c in init["collections"] if c["id"] == top)
    assert top_node["count"] == 1  # 云端成员计入分组计数


def test_cloud_view_excludes_when_local_gains_file(js):
    _set_cloud(js, {"memes": [{"filename": "c.png", "name": "c", "sha256": SHA_C}]})
    api = js.api
    assert len(api.search_memes("", None, None, 0, 10)) == 1
    js.db.add_meme(filename="c.png", file_hash=SHA_C)
    rows = api.search_memes("", None, None, 0, 10)
    assert len(rows) == 1
    assert "cloud" not in rows[0]
    assert api.count_memes() == 1


# ─── webui 侧：云态刷新 ───


def test_cloud_refresh_worker_success(js, monkeypatch):
    from src import webui as webui_module

    manifest = {
        "version": 3,
        "memes": [{"filename": "c.png", "name": "c", "sha256": SHA_C}],
    }
    monkeypatch.setattr(sync, "download_index", lambda: manifest)
    prefetched = {}
    monkeypatch.setattr(
        sync,
        "prefetch_thumbs",
        lambda missing, d: prefetched.update(n=len(missing)) or 0,
    )
    notified = []
    monkeypatch.setattr(webui_module, "_notify_cloud_ready", lambda: notified.append(1))

    webui_module._cloud_refresh_worker(None)

    with webui_module._cloud_lock:
        assert webui_module._cloud_state["manifest"] == manifest
        assert webui_module._cloud_state["loaded"] is True
        assert webui_module._cloud_state["refreshing"] is False
    assert (js.data_dir / "cloud-index.json").exists()
    assert prefetched["n"] == 1
    assert notified == [1]


def test_cloud_refresh_worker_fetch_fail_keeps_cache(js, monkeypatch):
    from src import webui as webui_module

    stale = {"memes": [{"filename": "old.png", "sha256": SHA_A}]}
    _set_cloud(js, stale)
    monkeypatch.setattr(sync, "download_index", lambda: None)
    monkeypatch.setattr(
        webui_module,
        "_notify_cloud_ready",
        lambda: pytest.fail("拉取失败不应通知前端"),
    )

    webui_module._cloud_refresh_worker(None)

    with webui_module._cloud_lock:
        assert webui_module._cloud_state["manifest"] == stale
        assert webui_module._cloud_state["refreshing"] is False


def test_start_cloud_refresh_gated(js, monkeypatch):
    from src import webui as webui_module

    js.cfg.set("cloud_direct", False)
    assert webui_module._start_cloud_refresh() is False
    js.cfg.set("cloud_direct", True)
    with webui_module._cloud_lock:
        webui_module._cloud_state["refreshing"] = True
    assert webui_module._start_cloud_refresh() is False  # 刷新中去重，不起新线程


def test_run_auto_sync_cloud_hook(js, monkeypatch):
    from src import webui as webui_module

    js.cfg.set("sync_auto_sync", False)
    js.cfg.set("sync_auto_fetch_index", False)
    calls = []
    monkeypatch.setattr(
        webui_module,
        "_start_cloud_refresh",
        lambda fetched=None: calls.append(fetched) or True,
    )
    autopush = []
    monkeypatch.setattr(
        webui_module,
        "_start_thumb_autopush",
        lambda w: autopush.append(w) or True,
    )

    result = js.api.run_auto_sync()

    assert result["error"] == ""
    assert calls == [None]  # fetch 关闭 → 线程内自拉
    assert autopush == [js.api._auto_push_thumbs]  # 启动挂缩略图补传

    manifest = {"memes": []}
    monkeypatch.setattr(sync, "download_index", lambda: manifest)
    js.cfg.set("sync_auto_fetch_index", True)

    result = js.api.run_auto_sync()

    assert result["fetched"] is True
    assert calls == [None, manifest]  # fetch 结果复用
    assert len(autopush) == 2

    # 关闭自动补传开关则不再挂线程
    js.cfg.set("cloud_thumb_auto_push", False)
    js.api.run_auto_sync()
    assert len(autopush) == 2


def test_cloud_refresh_api_calls_start(js, monkeypatch):
    from src import webui as webui_module

    calls = []
    monkeypatch.setattr(
        webui_module,
        "_start_cloud_refresh",
        lambda fetched=None: calls.append(1) or True,
    )
    assert js.api.cloud_refresh() is True
    assert calls == [1]


def test_serve_thumb_404_enqueues_cloud_fetch(js, monkeypatch):
    """云缺失行缩略图 404 → 入队后台补拉；未知 sha 不入队"""
    from test_thumbnails import _build_app, _request

    from src import webui as webui_module

    ui = webui_module.WebUI.__new__(webui_module.WebUI)
    ui._cfg = js.cfg
    ui._port = 17997
    enqueued = []
    monkeypatch.setattr(
        webui_module, "_enqueue_thumb_fetch", lambda sha: enqueued.append(sha)
    )
    _set_cloud(js, {"memes": [{"filename": "c.png", "name": "c", "sha256": SHA_C}]})
    app = _build_app(monkeypatch, ui)

    status, _ = _request(app, f"/api/thumb/{SHA_C}", port=17997)
    assert status.startswith("404")
    assert enqueued == [SHA_C]

    status, _ = _request(app, f"/api/thumb/{'9' * 64}", port=17997)
    assert status.startswith("404")
    assert enqueued == [SHA_C]  # 不在云端缺失集 → 不入队


# ─── webui 侧：cloud_download ───


def test_cloud_download_success(js, monkeypatch):
    from src import webui as webui_module

    data = _png_bytes()
    sha = hashlib.sha256(data).hexdigest()
    _set_cloud(
        js,
        {
            "memes": [
                {
                    "filename": "c.png",
                    "name": "云端c",
                    "sha256": sha,
                    "tags": ["t1"],
                }
            ],
            "favorite": ["c.png"],
        },
    )
    monkeypatch.setattr(
        sync,
        "download_single",
        lambda remote_path, local_path, bk=None: (
            Path(local_path).write_bytes(data) or True
        ),
    )
    copied = {}
    monkeypatch.setattr(
        js.api, "copy_meme", lambda mid: copied.update(id=mid) or {"ok": True}
    )
    notified = []
    monkeypatch.setattr(webui_module, "_notify_cloud_ready", lambda: notified.append(1))

    result = js.api.cloud_download("c.png")

    assert result["ok"] is True
    assert result["status"] == "copied"
    row = js.db.get_by_hash(sha)
    assert row is not None
    assert row["filename"] == "c.png"
    assert (js.data_dir / "cache" / "c.png").read_bytes() == data
    assert copied["id"] == row["id"]
    assert not list((js.data_dir / "cache").glob("cloud-*"))
    with webui_module._cloud_inflight_lock:
        assert "c.png" not in webui_module._cloud_inflight
    rows = js.api.search_memes("", None, None, 0, 10)
    assert len(rows) == 1
    assert rows[0]["id"] == row["id"]
    assert "cloud" not in rows[0]
    # 等异步后补结束（通知为最后一步），防线程跨测试残留
    for _ in range(200):
        if notified:
            break
        time.sleep(0.01)
    assert notified == [1]
    assert js.db.get_meme_tags(row["id"]) == ["t1"]
    assert js.db.is_favorite(row["id"]) is True


def test_cloud_download_sha_mismatch(js, monkeypatch):
    from src import webui as webui_module

    data = b"corrupted-bytes"
    _set_cloud(js, {"memes": [{"filename": "c.png", "name": "c", "sha256": SHA_A}]})
    monkeypatch.setattr(
        sync,
        "download_single",
        lambda remote_path, local_path, bk=None: (
            Path(local_path).write_bytes(data) or True
        ),
    )
    monkeypatch.setattr(
        webui_module,
        "_notify_cloud_ready",
        lambda: pytest.fail("校验失败不应通知前端"),
    )

    result = js.api.cloud_download("c.png")

    assert result["ok"] is False
    assert result["status"] == "sha_mismatch"
    assert js.db.get_by_hash(SHA_A) is None
    assert not (js.data_dir / "cache" / "c.png").exists()
    assert not list((js.data_dir / "cache").glob("cloud-*"))
    with webui_module._cloud_inflight_lock:
        assert "c.png" not in webui_module._cloud_inflight


def test_cloud_download_dedup_existing(js, monkeypatch):
    from src import webui as webui_module

    data = _png_bytes()
    sha = hashlib.sha256(data).hexdigest()
    js.db.add_meme(filename="local_copy.png", file_hash=sha)
    _set_cloud(js, {"memes": [{"filename": "c.png", "name": "c", "sha256": sha}]})
    monkeypatch.setattr(
        sync,
        "download_single",
        lambda remote_path, local_path, bk=None: (
            Path(local_path).write_bytes(data) or True
        ),
    )
    monkeypatch.setattr(js.api, "copy_meme", lambda mid: {"ok": True})
    notified = []
    monkeypatch.setattr(webui_module, "_notify_cloud_ready", lambda: notified.append(1))

    result = js.api.cloud_download("c.png")

    assert result["ok"] is True
    assert js.db.get_by_hash(sha)["filename"] == "local_copy.png"
    assert js.db.count() == 1
    assert not (js.data_dir / "cache" / "c.png").exists()  # 去重不重复落盘
    # 云条目即时移除（本地集合未变，靠显式移除）
    assert js.api.count_memes() == 1
    rows = js.api.search_memes("", None, None, 0, 10)
    assert "cloud" not in rows[0]
    for _ in range(200):
        if notified:
            break
        time.sleep(0.01)
    assert notified == [1]


def test_cloud_download_inflight_busy(js):
    from src import webui as webui_module

    _set_cloud(js, {"memes": [{"filename": "c.png", "name": "c", "sha256": SHA_C}]})
    with webui_module._cloud_inflight_lock:
        webui_module._cloud_inflight.add("c.png")
    result = js.api.cloud_download("c.png")
    assert result["ok"] is False
    assert result["status"] == "busy"


def test_cloud_download_gates(js):
    _set_cloud(js, {"memes": [{"filename": "c.png", "name": "c", "sha256": SHA_C}]})
    js.cfg.set("cloud_direct", False)
    assert js.api.cloud_download("c.png")["status"] == "disabled"
    js.cfg.set("cloud_direct", True)
    js.cfg.set("sync_type", "")
    assert js.api.cloud_download("c.png")["status"] == "no_sync"
    js.cfg.set("sync_type", "ftp")
    assert js.api.cloud_download("missing.png")["status"] == "not_found"


def test_cloud_backfill_metadata(js, monkeypatch):
    from src import webui as webui_module

    mid = js.db.add_meme(filename="x.png", file_hash=SHA_A)
    entry = {
        "filename": "c.png",
        "name": "c",
        "sha256": SHA_C,
        "tags": ["标签1", "标签2"],
        "favorited": True,
        "collections": ["动物/猫"],
    }
    notified = []
    monkeypatch.setattr(webui_module, "_notify_cloud_ready", lambda: notified.append(1))

    js.api._cloud_backfill(mid, entry)

    assert sorted(js.db.get_meme_tags(mid)) == ["标签1", "标签2"]
    assert js.db.is_favorite(mid) is True
    cols = dict((r[1], r[0]) for r in js.db.get_collections())
    assert "动物" in cols and "猫" in cols
    assert js.db.count(collection_id=[cols["猫"]]) == 1
    assert notified == [1]
