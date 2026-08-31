"""存储位置迁移三阶段幂等逻辑测试"""

import json
import os
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["OHMYMEME_TEST"] = "1"

from src import webui


class _FakeConfig:
    def __init__(self, data_dir, cache_dir):
        self.data_dir = data_dir
        self.cache_dir = cache_dir
        self.saved = {}

    def get(self, key, default=None):
        return self.saved.get(key, default)

    def set(self, key, value):
        self.saved[key] = value

    def save(self):
        self.saved["_saved"] = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    """隔离状态：假 config + 重置迁移状态，旧/新目录各含测试文件"""
    old = tmp_path / "old_cache"
    new = tmp_path / "new_cache"
    old.mkdir()
    (old / "a.gif").write_bytes(b"A" * 100)
    sub = old / "sub"
    sub.mkdir()
    (sub / "b.png").write_bytes(b"B" * 200)
    (old / "thumbnails").mkdir()
    (old / "thumbnails" / "t.png").write_bytes(b"T" * 10)
    cfg = _FakeConfig(tmp_path, old)
    monkeypatch.setattr(webui, "get_config", lambda: cfg)

    def _reset():
        with webui._STORAGE_MIGRATE_LOCK:
            webui._STORAGE_MIGRATE_STATE.update(
                status="idle",
                progress=0,
                moved=0,
                total=0,
                cancel_requested=False,
                error="",
                failed=[],
            )

    _reset()
    yield {"old": old, "new": new, "cfg": cfg, "tmp": tmp_path}
    _reset()


def _run_sync(env):
    """直接同步跑 worker（绕过线程），返回最终状态"""
    webui._storage_migrate_worker(env["old"], env["new"])
    with webui._STORAGE_MIGRATE_LOCK:
        return dict(webui._STORAGE_MIGRATE_STATE)


def _wait_thread():
    t = webui._STORAGE_MIGRATE_THREAD
    if t is not None:
        t.join(timeout=10)


def test_normal_migration(env):
    st = _run_sync(env)
    assert st["status"] == "done"
    assert (env["new"] / "a.gif").read_bytes() == b"A" * 100
    assert (env["new"] / "sub" / "b.png").read_bytes() == b"B" * 200
    assert not (env["old"] / "a.gif").exists()
    assert not (env["old"] / "sub" / "b.png").exists()
    assert (env["old"] / "thumbnails" / "t.png").exists()  # thumbnails 不迁移
    assert env["cfg"].saved["cache_dir"] == str(env["new"])
    assert env["cfg"].saved.get("_saved") is True
    assert not webui._storage_migrate_manifest_path().exists()


def test_idempotent_rerun_same_size_files(env):
    # 模拟上次复制中断：目标已有同大小 a.gif，源还在
    env["new"].mkdir()
    (env["new"] / "a.gif").write_bytes(b"A" * 100)
    st = _run_sync(env)
    assert st["status"] == "done"
    assert (env["new"] / "a.gif").read_bytes() == b"A" * 100
    assert not (env["old"] / "a.gif").exists()
    assert not (env["old"] / "sub" / "b.png").exists()


def test_conflict_keeps_source_intact(env):
    env["new"].mkdir()
    (env["new"] / "a.gif").write_bytes(b"X" * 999)  # 同名不同大小
    st = _run_sync(env)
    assert st["status"] == "error"
    assert "同名" in st["error"]
    assert (env["old"] / "a.gif").read_bytes() == b"A" * 100  # 源完好


def test_same_size_different_content_is_conflict(env):
    # 关键：仅比较大小时会被误判为"已复制"，哈希校验才能识别为冲突
    env["new"].mkdir()
    (env["new"] / "a.gif").write_bytes(b"X" * 100)  # 同大小但内容不同
    st = _run_sync(env)
    assert st["status"] == "error"
    assert "同名" in st["error"]
    assert (env["old"] / "a.gif").read_bytes() == b"A" * 100  # 源完好不删
    assert (env["old"] / "sub" / "b.png").exists()
    assert not env["cfg"].saved.get("cache_dir")  # 配置未切换
    assert (env["old"] / "sub" / "b.png").exists()
    assert not env["cfg"].saved.get("cache_dir")  # 配置未切换
    assert not webui._storage_migrate_manifest_path().exists()


def test_cancel_removes_new_copies_only(env, monkeypatch):
    env["new"].mkdir()
    (env["new"] / "a.gif").write_bytes(b"A" * 100)  # 上次留下的同大小文件

    import shutil

    original_copy = shutil.copyfileobj
    state = {"calls": 0}

    def _hook(dst, src, *a, **kw):
        state["calls"] += 1
        if state["calls"] >= 1:  # 首个需复制的文件即请求取消
            with webui._STORAGE_MIGRATE_LOCK:
                webui._STORAGE_MIGRATE_STATE["cancel_requested"] = True
        return original_copy(dst, src, *a, **kw)

    monkeypatch.setattr(shutil, "copyfileobj", _hook)
    st = _run_sync(env)
    assert st["status"] == "cancelled"
    assert not (env["new"] / "sub" / "b.png").exists()  # 本次新建副本已清理
    assert (env["old"] / "a.gif").exists()  # 源全部完好
    assert (env["old"] / "sub" / "b.png").read_bytes() == b"B" * 200
    # 上次留下的同大小目标（非本次新建）不被误删
    assert (env["new"] / "a.gif").read_bytes() == b"A" * 100


def test_manifest_written_and_cleared(env):
    webui.start_storage_migration_thread(env["new"])
    _wait_thread()
    with webui._STORAGE_MIGRATE_LOCK:
        assert webui._STORAGE_MIGRATE_STATE["status"] == "done"
    assert not webui._storage_migrate_manifest_path().exists()
    assert (env["new"] / "a.gif").exists()


def test_resume_pending_migration(tmp_path, monkeypatch, env):
    # 构造崩溃现场：清单存在，部分文件已复制到新目录，源文件还在
    manifest = tmp_path / "storage_migration.json"
    manifest.write_text(
        json.dumps({"old": str(env["old"]), "new": str(env["new"])}),
        encoding="utf-8",
    )
    monkeypatch.setattr(webui, "_storage_migrate_manifest_path", lambda: manifest)
    webui.resume_pending_storage_migration()
    for _ in range(200):
        with webui._STORAGE_MIGRATE_LOCK:
            if webui._STORAGE_MIGRATE_STATE["status"] in ("done", "error"):
                break
        threading.Event().wait(0.05)
    with webui._STORAGE_MIGRATE_LOCK:
        assert webui._STORAGE_MIGRATE_STATE["status"] == "done"
    assert not manifest.exists()
    assert not (env["old"] / "a.gif").exists()
    assert env["cfg"].saved["cache_dir"] == str(env["new"])


def test_phase2_crash_resume_only_cleans_source(env):
    # 阶段2后崩溃：配置已切换，新目录完整，旧目录残留待清理
    env["cfg"].saved["cache_dir"] = str(env["new"])
    env["new"].mkdir()
    (env["new"] / "a.gif").write_bytes(b"A" * 100)
    (env["new"] / "sub").mkdir()
    (env["new"] / "sub" / "b.png").write_bytes(b"B" * 200)
    st = _run_sync(env)
    assert st["status"] == "done"
    assert not (env["old"] / "a.gif").exists()
    assert not (env["old"] / "sub" / "b.png").exists()
