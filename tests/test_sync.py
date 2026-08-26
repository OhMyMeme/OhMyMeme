"""sync.push() 远端 manifest 一致性回归测试

覆盖 push() 的修复：
- 任一普通图片上传失败 → 抛 SyncError，且不上传新的远端 manifest
- manifest 上传失败 → 抛 SyncError
- 上传失败不删除远端文件
- delete_remote=False 时远端仍保留的文件合并进远端 manifest（避免孤儿）
- 删除失败 / 删除结果未知(unknown) 的远端文件保留在 manifest
- 合并用临时文件，上传后清理，本地 meme-index.json 不被污染

使用 FakeBackend 替换真实 FTP/S3/R2/WebDAV，不访问网络。
"""

import hashlib
import io
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

# 确保 src 在导入路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ohmymeme.core.config import Config
from ohmymeme.core.manifest import INDEX_FILENAME
from ohmymeme.services.sync import service as sync
from ohmymeme.services.sync.backends import get_backend
from ohmymeme.services.sync.service import (
    SyncError,
    SyncService,
    cleanup_remote_orphans,
    get_sync_progress,
)


class TestSyncJobAdapter(unittest.TestCase):
    def test_sync_service_uses_job_manager_single_flight(self):
        from ohmymeme.app.job_manager import JobManager

        manager = JobManager()
        started = threading.Event()
        release = threading.Event()
        calls = []
        service = SyncService(None, None, None, None, None, manager)

        def blocked(*_args, **_kwargs):
            calls.append(1)
            started.set()
            release.wait(2)
            return {"uploaded": 1, "errors": 0}

        with patch.object(sync, "push", side_effect=blocked):
            try:
                first = threading.Thread(target=service.push)
                first.start()
                self.assertTrue(started.wait(1))
                with self.assertRaises(SyncError):
                    service.push()
                self.assertEqual(calls, [1])
            finally:
                release.set()
                first.join(2)
                manager.shutdown(2)


class TestProviderMetadataFactory(unittest.TestCase):
    def test_factory_selects_each_configured_provider(self):
        expected = {
            "ftp": "_FtpBackend",
            "s3": "_S3Backend",
            "r2": "_R2Backend",
            "webdav": "_WebDAVBackend",
        }
        for sync_type, class_name in expected.items():
            backend = get_backend(
                type(
                    "Config",
                    (),
                    {
                        "get": lambda self, key, default=None, value=sync_type: (
                            value if key == "sync_type" else default
                        )
                    },
                )()
            )
            self.assertEqual(type(backend).__name__, class_name)

    def test_unknown_provider_keeps_compatible_error(self):
        with self.assertRaises(SyncError):
            get_backend(
                type(
                    "Config",
                    (),
                    {
                        "get": lambda self, key, default=None: (
                            "unknown" if key == "sync_type" else default
                        )
                    },
                )()
            )

    def test_delete_capability_guard_has_no_backend_side_effect(self):
        with patch.object(sync, "get_config") as get_config, patch.object(
            sync, "_get_backend"
        ) as get_backend:
            get_config.return_value.get.return_value = "unknown"
            result = sync.delete_all_remote()
        self.assertEqual(result["ok"], False)
        get_backend.assert_not_called()

    def test_sync_service_cancellation_reaches_operation(self):
        from ohmymeme.app.job_manager import JobManager

        manager = JobManager()
        started = threading.Event()
        service = SyncService(None, None, None, None, None, manager)

        def blocked(*_args, cancellation=None, **_kwargs):
            started.set()
            cancellation.wait(2)
            return {"cancelled": cancellation.is_set()}

        with patch.object(sync, "push", side_effect=blocked):
            result = {}
            worker = threading.Thread(target=lambda: result.update(service.push()))
            worker.start()
            self.assertTrue(started.wait(1))
            job = manager.active("sync")
            self.assertIsNotNone(job)
            self.assertTrue(manager.cancel(job.id))
            worker.join(2)
            self.assertEqual(result, {"cancelled": True})


def _entry(fname, sha256, size=1):
    return {
        "filename": fname,
        "name": fname,
        "sha256": sha256,
        "file_size": size,
        "mtime": "",
    }


def _remote_png():
    buffer = io.BytesIO()
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(buffer, "PNG")
    return buffer.getvalue()


REMOTE_PNG = _remote_png()
REMOTE_PNG_HASH = hashlib.sha256(REMOTE_PNG).hexdigest()


class _FakeBackend:
    """内存假后端：记录上传/删除与 manifest 载荷，可配置各操作成败"""

    def __init__(self, meme_ok=True, manifest_ok=True, remote_memes=None):
        self.meme_ok = meme_ok
        self.manifest_ok = manifest_ok
        self._remote_memes = {}
        self.remote_files = set()
        self.remote_memes = remote_memes or {}  # setter 同步 remote_files
        self.upload_paths = []
        self.delete_calls = []
        self.manifest_payload = None
        self.delete_ok = True
        self.exists_overrides = {}  # filename -> bool
        self.raise_on_exists = set()  # filename -> 抛异常(unknown)
        self.manifest_exists = True  # 远端 manifest 是否存在
        self.manifest_download_ok = True  # manifest 下载是否成功
        self.manifest_content = None  # 覆盖 manifest 下载内容（可注入损坏 JSON）
        self.empty_downloads = set()  # 下载后为空的文件
        self.download_paths = []
        self.list_calls = []
        self.upload_raises = set()  # 上传时抛异常的文件（触发 worker 异常路径）

    @property
    def remote_memes(self):
        return self._remote_memes

    @remote_memes.setter
    def remote_memes(self, value):
        self._remote_memes = value or {}
        self.remote_files = set(self._remote_memes.keys())

    @staticmethod
    def _basename(path):
        return str(path).rsplit("/", 1)[-1]

    def connect(self):
        pass

    def ensure_remote_dir(self, path):
        pass

    def file_exists(self, path):
        if str(path).endswith(INDEX_FILENAME):
            return self.manifest_exists
        fname = self._basename(path)
        if fname in self.raise_on_exists:
            raise RuntimeError("file_exists timeout")
        if fname in self.exists_overrides:
            return self.exists_overrides[fname]
        return fname in self.remote_files

    def download_file(self, remote_path, local_path):
        rp = str(remote_path)
        self.download_paths.append(rp)
        if rp.endswith(INDEX_FILENAME):
            if not self.manifest_download_ok:
                return False
            if self.manifest_content is None:
                content = json.dumps(
                    {"version": 3, "memes": list(self.remote_memes.values())}
                )
            else:
                content = self.manifest_content
            Path(local_path).write_text(content)
            return True
        fname = self._basename(rp)
        if fname not in self.remote_files:
            return False
        if fname in self.empty_downloads:
            Path(local_path).write_bytes(b"")
        else:
            Path(local_path).write_bytes(REMOTE_PNG)
        return True

    def upload_file(self, local_path, remote_path):
        rp = str(remote_path)
        self.upload_paths.append(rp)
        fname = self._basename(rp)
        if fname in self.upload_raises:
            raise RuntimeError("upload boom")
        if rp.endswith(INDEX_FILENAME):
            if self.manifest_ok:
                try:
                    self.manifest_payload = json.loads(
                        Path(local_path).read_text(encoding="utf-8")
                    )
                except Exception:
                    self.manifest_payload = None
            return self.manifest_ok
        if self.meme_ok:
            self.remote_files.add(self._basename(rp))
        return self.meme_ok

    def delete_file(self, path):
        self.delete_calls.append(str(path))
        if not self.delete_ok:
            return False
        self.remote_files.discard(self._basename(path))
        return True

    def list_files(self, path):
        self.list_calls.append(str(path))
        return sorted(self.remote_files)

    def close(self):
        pass


class _FakeDb:
    """build_manifest() 所需的假数据库，避免触碰真实数据"""

    def __init__(self, rows=None):
        self.rows = (
            list(rows)
            if rows
            else [
                {
                    "filename": "test.png",
                    "original_name": "test",
                    "file_hash": "abc",
                    "file_size": 16,
                }
            ]
        )
        self.order = []  # reorder_memes 记录的 id 顺序
        self.collections = []
        self.deleted_collections = []

    def search(self, keyword="", tags=None, limit=999999, collection_id=None):
        return list(self.rows)

    def get_collections(self):
        return list(self.collections)

    def delete_collection(self, collection_id):
        self.deleted_collections.append(collection_id)

    def get_by_filename(self, filename):
        for i, r in enumerate(self.rows):
            if r["filename"] == filename:
                return dict(r, id=i + 1)
        return None

    def get_by_hash(self, file_hash):
        for index, row in enumerate(self.rows):
            if row["file_hash"] == file_hash:
                return dict(row, id=index + 1)
        return None

    def reorder_memes(self, meme_ids):
        id_to_name = {i + 1: r["filename"] for i, r in enumerate(self.rows)}
        self.order = [id_to_name.get(i) for i in meme_ids]

    def add_meme(
        self,
        filename,
        file_hash="",
        width=0,
        height=0,
        file_size=0,
        mime_type="image/png",
        original_name="",
        tags=None,
    ):
        self.rows.append(
            {
                "filename": filename,
                "original_name": original_name,
                "file_hash": file_hash,
                "file_size": file_size,
            }
        )
        return len(self.rows)

    def delete_meme(self, meme_id):
        if 0 < meme_id <= len(self.rows):
            del self.rows[meme_id - 1]

    def create_collection(self, name, parent_id=None):
        return 1

    def add_to_collection(self, meme_id, collection_id):
        pass

    def apply_remote_metadata(self, remote_data):
        self.order = [meme["filename"] for meme in remote_data.get("memes", [])]


class TestSyncPush(unittest.TestCase):
    """push() manifest 一致性回归测试"""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

        self.data_dir = self.tmp_dir / "data"
        cache_dir = self.data_dir / "cache"
        thumb_dir = self.data_dir / "thumbnails"
        cache_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir.mkdir(parents=True, exist_ok=True)

        self.cfg = Config(self.tmp_dir / "config.json")
        self.cfg.set("sync_type", "ftp")
        self.cfg.set("sync_threads", 1)

        # 将 data_dir / get_config / get_db / _get_backend 全部指向临时环境
        self._start_patch(
            patch("ohmymeme.core.config._get_data_dir", return_value=self.data_dir)
        )
        for target in (
            "ohmymeme.services.sync.service.get_config",
            "ohmymeme.core.manifest.get_config",
        ):
            self._start_patch(patch(target, return_value=self.cfg))
        self.fake_db = _FakeDb()
        self._start_patch(
            patch("ohmymeme.core.manifest.get_db", return_value=self.fake_db)
        )
        self._start_patch(
            patch("ohmymeme.services.sync.service.get_db", return_value=self.fake_db)
        )

        self.fake_backend = _FakeBackend()
        self._start_patch(
            patch(
                "ohmymeme.services.sync.service._get_backend",
                return_value=self.fake_backend,
            )
        )

        # 默认一个本地文件 test.png
        self._set_local_memes([{"filename": "test.png", "sha256": "abc"}])

    def _start_patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

    def _set_local_memes(self, memes):
        """设置本地 memes（同步本地清单 / cache 文件 / FakeDb）"""
        manifest = {
            "version": 3,
            "memes": [
                {
                    "filename": m["filename"],
                    "name": m["filename"],
                    "sha256": m["sha256"],
                    "file_size": m.get("file_size", 8),
                    "mtime": "",
                }
                for m in memes
            ],
            "collections": [],
        }
        (self.data_dir / INDEX_FILENAME).write_text(json.dumps(manifest))
        for m in memes:
            fp = self.data_dir / "cache" / m["filename"]
            if not fp.exists():
                fp.write_bytes(b"x" * int(m.get("file_size", 8)))
        self.fake_db.rows = [
            {
                "filename": m["filename"],
                "original_name": m["filename"],
                "file_hash": m["sha256"],
                "file_size": m.get("file_size", 8),
            }
            for m in memes
        ]

    def _manifest_filenames(self):
        self.assertIsNotNone(self.fake_backend.manifest_payload)
        return {m["filename"] for m in self.fake_backend.manifest_payload["memes"]}

    # ─── 既有用例（止血修复） ───

    def test_meme_upload_failure_aborts_manifest(self):
        """普通图片上传失败时：抛 SyncError、不上传 manifest、状态为 error"""
        self.fake_backend.meme_ok = False
        with self.assertRaises(SyncError) as ctx:
            sync.push()
        self.assertIn("上传失败", str(ctx.exception))
        self.assertFalse(
            any(p.endswith(INDEX_FILENAME) for p in self.fake_backend.upload_paths)
        )
        self.assertEqual(get_sync_progress()["status"], "error")

    def test_manifest_upload_failure_raises(self):
        """图片上传成功但 manifest 上传失败时：抛 SyncError、状态为 error"""
        self.fake_backend.manifest_ok = False
        with self.assertRaises(SyncError) as ctx:
            sync.push()
        self.assertIn("manifest", str(ctx.exception))
        self.assertTrue(
            any(p.endswith(INDEX_FILENAME) for p in self.fake_backend.upload_paths)
        )
        self.assertEqual(get_sync_progress()["status"], "error")

    def test_delete_remote_not_called_on_error(self):
        """delete_remote=True 且图片上传失败时：不删除任何远端文件"""
        self.fake_backend.meme_ok = False
        self.fake_backend.remote_memes = {"ghost.png": _entry("ghost.png", "x")}
        self.cfg.set("sync_delete_remote", True)
        with self.assertRaises(SyncError):
            sync.push()
        self.assertEqual(self.fake_backend.delete_calls, [])

    def test_full_success_uploads_manifest(self):
        """全部上传成功时：正常返回、上传 manifest、状态为 done"""
        result = sync.push()
        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertTrue(
            any(p.endswith(INDEX_FILENAME) for p in self.fake_backend.upload_paths)
        )
        self.assertEqual(get_sync_progress()["status"], "done")

    # ─── PR1 新增用例 ───

    def test_push_keeps_remote_only_files_in_manifest(self):
        """远端 A,B 本地 B,C，push(delete_remote=False) → 远端 manifest=A,B,C"""
        self._set_local_memes(
            [
                {"filename": "b.png", "sha256": "abc"},
                {"filename": "c.png", "sha256": "def"},
            ]
        )
        self.fake_backend.remote_memes = {
            "a.png": _entry("a.png", "x"),
            "b.png": _entry("b.png", "abc"),
        }
        result = sync.push()
        self.assertEqual(result["uploaded"], 1)  # c.png
        self.assertEqual(result["skipped"], 1)  # b.png
        self.assertEqual(self._manifest_filenames(), {"a.png", "b.png", "c.png"})
        # 本地 meme-index.json 未被污染：仍只含本地文件
        local = json.loads((self.data_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual({m["filename"] for m in local["memes"]}, {"b.png", "c.png"})

    def test_push_delete_failure_keeps_remote_in_manifest(self):
        """delete_remote=True 且删除失败（复核仍在）→ 远端 manifest 保留该文件"""
        self.fake_backend.remote_memes = {"ghost.png": _entry("ghost.png", "x")}
        self.fake_backend.delete_ok = False
        self.fake_backend.exists_overrides["ghost.png"] = True
        self.cfg.set("sync_delete_remote", True)
        result = sync.push()
        self.assertIn("ghost.png", self._manifest_filenames())
        self.assertEqual(result["deleted"], 0)

    def test_push_delete_verified_absent_counts_deleted(self):
        """删除返回 False 但复核确认已删 → 计 deleted、不进 manifest"""
        self.fake_backend.remote_memes = {"ghost.png": _entry("ghost.png", "x")}
        self.fake_backend.delete_ok = False
        self.fake_backend.exists_overrides["ghost.png"] = False
        self.cfg.set("sync_delete_remote", True)
        result = sync.push()
        self.assertNotIn("ghost.png", self._manifest_filenames())
        self.assertEqual(result["deleted"], 1)

    def test_push_delete_unknown_keeps_remote_in_manifest(self):
        """删除复核异常(unknown) → 保留在远端 manifest，等待下次重查"""
        self.fake_backend.remote_memes = {"ghost.png": _entry("ghost.png", "x")}
        self.fake_backend.delete_ok = False
        self.fake_backend.raise_on_exists.add("ghost.png")
        self.cfg.set("sync_delete_remote", True)
        sync.push()
        self.assertIn("ghost.png", self._manifest_filenames())

    def test_push_manifest_failure_cleans_temp_merged(self):
        """manifest 上传失败时合并临时文件被清理，不残留"""
        self.fake_backend.remote_memes = {"a.png": _entry("a.png", "x")}
        self.fake_backend.manifest_ok = False
        with self.assertRaises(SyncError):
            sync.push()
        leftovers = [
            p for p in self.data_dir.iterdir() if p.name.startswith(".remote-merged-")
        ]
        self.assertEqual(leftovers, [])

    # ─── PR2 新增用例 ───

    def test_pull_partial_failure_raises(self):
        """pull 部分下载失败 → 抛 SyncError、status=error、本地清单不含失败项"""
        self.fake_backend.remote_memes = {
            "test.png": _entry("test.png", "abc"),
            "missing.png": _entry("missing.png", "x"),
        }
        self.fake_backend.remote_files = {"test.png"}  # missing.png 物理缺失
        with self.assertRaises(SyncError) as ctx:
            sync.pull()
        self.assertIn("下载失败", str(ctx.exception))
        self.assertEqual(get_sync_progress()["status"], "error")
        local = json.loads((self.data_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        self.assertNotIn("missing.png", {m["filename"] for m in local["memes"]})

    def test_pull_re_downloads_missing_local_cache(self):
        """本地清单有记录但 cache 缺失 → pull 重新下载"""
        (self.data_dir / "cache" / "test.png").unlink()
        self.fake_backend.remote_memes = {"test.png": _entry("test.png", "abc")}
        result = sync.pull()
        self.assertEqual(result["downloaded"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertTrue((self.data_dir / "cache" / "test.png").exists())

    def test_pull_applies_remote_manifest_order(self):
        """pull 按远端 manifest 顺序重排本地 sort_order，保留云端排序"""
        self._set_local_memes([])  # 本地空，pull 全部远端文件
        self.fake_backend.remote_memes = {
            "b.png": _entry("b.png", "2"),
            "a.png": _entry("a.png", "1"),
            "c.png": _entry("c.png", "3"),
        }
        sync.pull()
        # _apply_remote_order 按远端 memes 顺序调用 reorder_memes
        self.assertEqual(self.fake_db.order, ["b.png", "a.png", "c.png"])
        # 本地清单重建后顺序与远端一致
        local = json.loads((self.data_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(
            [m["filename"] for m in local["memes"]], ["b.png", "a.png", "c.png"]
        )

    def test_push_uploads_manifest_in_local_sort_order(self):
        """push 上传的远端 manifest 顺序与本地清单顺序一致"""
        # 本地清单顺序 b,a（拖拽排序结果）
        manifest = {
            "version": 3,
            "memes": [
                {
                    "filename": "b.png",
                    "name": "b",
                    "sha256": "2",
                    "file_size": 8,
                    "mtime": "",
                },
                {
                    "filename": "a.png",
                    "name": "a",
                    "sha256": "1",
                    "file_size": 8,
                    "mtime": "",
                },
            ],
            "collections": [],
        }
        (self.data_dir / INDEX_FILENAME).write_text(json.dumps(manifest))
        self._set_local_memes(
            [
                {"filename": "b.png", "sha256": "2"},
                {"filename": "a.png", "sha256": "1"},
            ]
        )
        self.fake_backend.remote_memes = {}
        sync.push()
        order = [m["filename"] for m in self.fake_backend.manifest_payload["memes"]]
        self.assertEqual(order, ["b.png", "a.png"])

    def test_pull_manifest_corrupted_raises(self):
        """远端 manifest 损坏 JSON → pull 抛 SyncError，不做文件操作"""
        self.fake_backend.manifest_content = "{ this is not json"
        with self.assertRaises(SyncError):
            sync.pull()
        self.assertFalse(
            any(
                not p.endswith(INDEX_FILENAME) for p in self.fake_backend.download_paths
            )
        )

    def test_push_manifest_corrupted_raises(self):
        """远端 manifest 损坏 JSON → push 抛 SyncError，不上传任何文件"""
        self.fake_backend.manifest_content = "{ this is not json"
        with self.assertRaises(SyncError):
            sync.push()
        self.assertEqual(self.fake_backend.upload_paths, [])

    def test_push_no_remote_manifest_first_sync(self):
        """首次同步（远端无 manifest）→ push 正常上传全部本地文件"""
        self.fake_backend.manifest_exists = False
        result = sync.push()
        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(get_sync_progress()["status"], "done")

    def test_push_manifest_download_failure_raises(self):
        """远端 manifest 存在但下载失败 → push 抛 SyncError（区分于首次同步）"""
        self.fake_backend.manifest_download_ok = False
        with self.assertRaises(SyncError):
            sync.push()
        self.assertEqual(self.fake_backend.upload_paths, [])

    def test_pull_empty_download_counts_error(self):
        """远端下载到空文件 → 计 error，不入本地 manifest"""
        self.fake_backend.remote_memes = {"empty.png": _entry("empty.png", "x")}
        self.fake_backend.empty_downloads.add("empty.png")
        with self.assertRaises(SyncError):
            sync.pull()
        self.assertEqual(get_sync_progress()["status"], "error")
        local = json.loads((self.data_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        self.assertNotIn("empty.png", {m["filename"] for m in local["memes"]})

    def test_pull_rejects_malformed_image_through_shared_import_service(self):
        self._set_local_memes([])
        self.fake_backend.remote_memes = {"bad.png": _entry("bad.png", "bad")}
        self.fake_backend.remote_files = {"bad.png"}
        original_download = self.fake_backend.download_file

        def malformed(remote_path, local_path):
            if str(remote_path).endswith(INDEX_FILENAME):
                return original_download(remote_path, local_path)
            Path(local_path).write_bytes(b"not an image")
            return True

        self.fake_backend.download_file = malformed

        result = sync.pull()

        self.assertEqual(result["skipped"], 1)
        self.assertFalse((self.data_dir / "cache" / "bad.png").exists())
        self.assertIsNone(self.fake_db.get_by_filename("bad.png"))

    def test_pull_failure_does_not_apply_metadata_or_rebuild_manifest(self):
        self.fake_backend.remote_memes = {
            "test.png": _entry("test.png", "abc"),
            "missing.png": _entry("missing.png", "x"),
        }
        self.fake_backend.remote_files = {"test.png"}
        original_manifest = (self.data_dir / INDEX_FILENAME).read_bytes()

        with patch(
            "ohmymeme.services.sync.service._apply_remote_collections"
        ) as collections, patch(
            "ohmymeme.services.sync.service._apply_remote_order"
        ) as order, patch(
            "ohmymeme.services.sync.service.build_manifest"
        ) as rebuild:
            with self.assertRaises(SyncError):
                sync.pull()

        collections.assert_not_called()
        order.assert_not_called()
        rebuild.assert_not_called()
        self.assertEqual(
            (self.data_dir / INDEX_FILENAME).read_bytes(), original_manifest
        )

    def test_pull_cancel_after_metadata_restores_manifest_and_local_state(self):
        """Cancellation after publish preserves the old state."""
        self._set_local_memes(
            [
                {"filename": "test.png", "sha256": "abc"},
                {"filename": "old.png", "sha256": "old"},
            ]
        )
        remote_data = {
            "version": 3,
            "memes": [_entry("test.png", "abc")],
            "collections": [],
        }
        cancellation = threading.Event()
        original_manifest = (self.data_dir / INDEX_FILENAME).read_bytes()

        class _PullLibrary:
            def __init__(self):
                self._assets = type("Assets", (), {})()
                self._assets.manifest_path = self_outer.data_dir / INDEX_FILENAME

            def apply_remote_metadata(self, data):
                self.fake_db.apply_remote_metadata(data)
                cancellation.set()
                return True

            def replace_manifest(self, data):
                self._assets.manifest_path.write_text(json.dumps(data))
                return True

            def delete_meme(self, meme_id):
                path = (
                    self_outer.data_dir
                    / "cache"
                    / self.fake_db.rows[meme_id - 1]["filename"]
                )
                path.unlink(missing_ok=True)
                self.fake_db.delete_meme(meme_id)
                return True

            def restore_manifest(self, snapshot):
                self._assets.manifest_path.write_bytes(snapshot)

            def rollback_delete(self, meme_id):
                return True

        self_outer = self
        library = _PullLibrary()
        library.fake_db = self.fake_db
        with patch.object(
            sync, "download_index", return_value=remote_data
        ), patch.object(sync, "_default_library", return_value=library):
            with self.assertRaises(SyncError):
                sync.pull(remove_local=True, cancellation=cancellation)

        self.assertEqual(
            (self.data_dir / INDEX_FILENAME).read_bytes(), original_manifest
        )
        self.assertIsNotNone(self.fake_db.get_by_filename("old.png"))
        self.assertTrue((self.data_dir / "cache" / "old.png").exists())

    def test_pull_cancel_during_delete_does_not_publish_or_succeed(self):
        """Cancellation observed after deletion rolls back the local snapshot."""
        cancellation = threading.Event()
        original_manifest = (self.data_dir / INDEX_FILENAME).read_bytes()

        class Library:
            _assets = type(
                "Assets", (), {"manifest_path": self.data_dir / INDEX_FILENAME}
            )()

            def delete_meme(self, meme_id):
                self.fake_db.delete_meme(meme_id)
                cancellation.set()
                return True

            def rollback_delete(self, meme_id):
                return True

            def restore_manifest(self, snapshot):
                self._assets.manifest_path.write_bytes(snapshot)

            def apply_remote_metadata(self, data):
                return True

            def replace_manifest(self, data):
                self._assets.manifest_path.write_text(json.dumps(data))
                return True

        library = Library()
        library.fake_db = self.fake_db
        with patch.object(
            sync,
            "download_index",
            return_value={"version": 3, "memes": [], "collections": []},
        ):
            with self.assertRaises(SyncError):
                sync.pull(remove_local=True, library=library, cancellation=cancellation)
        self.assertEqual(
            (self.data_dir / INDEX_FILENAME).read_bytes(), original_manifest
        )

    def test_pull_partial_failure_keeps_new_rows_and_files_out_of_state(self):
        self._set_local_memes([])
        original_manifest = (self.data_dir / INDEX_FILENAME).read_bytes()
        self.fake_backend.remote_memes = {
            "new.png": _entry("new.png", "new"),
            "missing.png": _entry("missing.png", "missing"),
        }
        self.fake_backend.remote_files = {"new.png"}

        with self.assertRaises(SyncError):
            sync.pull()

        self.assertEqual(self.fake_db.rows, [])
        self.assertFalse((self.data_dir / "cache" / "new.png").exists())
        self.assertEqual(
            (self.data_dir / INDEX_FILENAME).read_bytes(), original_manifest
        )

    def test_pull_partial_failure_restores_overwritten_cache_bytes(self):
        original_cache = (self.data_dir / "cache" / "test.png").read_bytes()
        original_manifest = (self.data_dir / INDEX_FILENAME).read_bytes()
        original_rows = list(self.fake_db.rows)
        self.fake_backend.remote_memes = {
            "test.png": _entry("test.png", "changed"),
            "missing.png": _entry("missing.png", "missing"),
        }
        self.fake_backend.remote_files = {"test.png"}

        with self.assertRaises(SyncError):
            sync.pull()

        self.assertEqual(
            (self.data_dir / "cache" / "test.png").read_bytes(), original_cache
        )
        self.assertEqual(self.fake_db.rows, original_rows)
        self.assertEqual(
            (self.data_dir / INDEX_FILENAME).read_bytes(), original_manifest
        )

    def test_pull_metadata_failure_restores_manifest_and_new_state(self):
        original_manifest = (self.data_dir / INDEX_FILENAME).read_bytes()
        original_rows = list(self.fake_db.rows)
        original_order = list(self.fake_db.order)
        original_collections = list(self.fake_db.collections)
        self.fake_backend.remote_memes = {"new.png": _entry("new.png", "new")}
        self.fake_backend.remote_files = {"new.png"}

        with patch(
            "ohmymeme.services.sync.service._apply_remote_metadata",
            side_effect=RuntimeError("db failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "db failure"):
                sync.pull()

        self.assertEqual(self.fake_db.rows, original_rows)
        self.assertEqual(self.fake_db.order, original_order)
        self.assertEqual(self.fake_db.collections, original_collections)
        self.assertFalse((self.data_dir / "cache" / "new.png").exists())
        self.assertEqual(
            (self.data_dir / INDEX_FILENAME).read_bytes(), original_manifest
        )

    def test_pull_failure_does_not_remove_local_before_commit_boundary(self):
        self._set_local_memes([{"filename": "old.png", "sha256": "old"}])
        self.fake_backend.remote_memes = {
            "missing.png": _entry("missing.png", "missing")
        }
        self.fake_backend.remote_files = set()

        with self.assertRaises(SyncError):
            sync.pull(remove_local=True)

        self.assertIsNotNone(self.fake_db.get_by_filename("old.png"))
        self.assertTrue((self.data_dir / "cache" / "old.png").exists())

    def test_pull_remove_local_commits_remote_manifest_before_deleting(self):
        self._set_local_memes([{"filename": "old.png", "sha256": "old"}])
        self.fake_backend.remote_memes = {"remote.png": _entry("remote.png", "remote")}
        self.fake_backend.remote_files = {"remote.png"}

        result = sync.pull(remove_local=True)

        self.assertEqual(result["removed_local"], 1)
        self.assertIsNone(self.fake_db.get_by_filename("old.png"))
        self.assertFalse((self.data_dir / "cache" / "old.png").exists())
        local = json.loads((self.data_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual([m["filename"] for m in local["memes"]], ["remote.png"])

    def test_manifest_replace_failure_keeps_empty_collections(self):
        self.fake_db.rows = []
        self.fake_db.collections = [(1, "empty", None, 0)]
        with patch(
            "ohmymeme.core.manifest.os.replace", side_effect=OSError("disk full")
        ):
            from ohmymeme.core.manifest import build as _build

            with self.assertRaises(OSError):
                _build()

        self.assertEqual(self.fake_db.deleted_collections, [])

    def test_pull_manifest_replace_failure_reverts_new_rows_and_files(self):
        self._set_local_memes([])
        original_manifest = (self.data_dir / INDEX_FILENAME).read_bytes()
        self.fake_backend.remote_memes = {"new.png": _entry("new.png", "new")}
        with patch(
            "ohmymeme.core.manifest.os.replace", side_effect=OSError("disk full")
        ):
            with self.assertRaises(OSError):
                sync.pull()

        self.assertEqual(self.fake_db.rows, [])
        self.assertFalse((self.data_dir / "cache" / "new.png").exists())
        self.assertEqual(
            (self.data_dir / INDEX_FILENAME).read_bytes(), original_manifest
        )

    def test_build_manifest_atomic_replace_preserves_old_on_failure(self):
        """build_manifest 原子替换：os.replace 失败时旧清单完好"""
        old = json.loads((self.data_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        with patch(
            "ohmymeme.core.manifest.os.replace", side_effect=OSError("disk full")
        ):
            from ohmymeme.core.manifest import build as _build

            with self.assertRaises(OSError):
                _build()
        after = json.loads((self.data_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(after, old)

    def test_build_manifest_replace_failure_propagates_and_cleans_temp(self):
        old = (self.data_dir / INDEX_FILENAME).read_bytes()
        with patch(
            "ohmymeme.core.manifest.os.replace", side_effect=OSError("disk full")
        ):
            from ohmymeme.core.manifest import build as _build

            with self.assertRaises(OSError):
                _build()

        self.assertEqual((self.data_dir / INDEX_FILENAME).read_bytes(), old)
        self.assertFalse((self.data_dir / f"{INDEX_FILENAME}.tmp").exists())

    # ─── PR3 新增用例 ───

    def test_push_skips_consistent_remote_file(self):
        """远端真实存在且 hash 一致 → 跳过"""
        self.fake_backend.remote_memes = {"test.png": _entry("test.png", "abc")}
        result = sync.push()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["uploaded"], 0)

    def test_push_reuploads_when_remote_file_missing(self):
        """远端清单声称一致但真实文件缺失 → push 重新上传（污染自愈）"""
        # 远端清单有 test.png(同hash)，但物理文件缺失
        self.fake_backend.remote_memes = {"test.png": _entry("test.png", "abc")}
        self.fake_backend.remote_files = set()  # 物理缺失
        result = sync.push()
        self.assertEqual(result["uploaded"], 1)  # 重新上传而非 skip
        self.assertEqual(result["skipped"], 0)
        self.assertIn("test.png", self.fake_backend.remote_files)  # 已补传

    def test_push_reuploads_when_existence_check_fails(self):
        """file_exists 复核异常 → 保守重传（不依赖污染清单）"""
        self.fake_backend.remote_memes = {"test.png": _entry("test.png", "abc")}
        self.fake_backend.raise_on_exists.add("test.png")
        result = sync.push()
        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(result["skipped"], 0)

    # ─── PR4 新增用例 ───

    def test_cleanup_remote_orphans_lists(self):
        """远端真实文件多于清单 → 识别孤儿（不删除）"""
        self.fake_backend.remote_memes = {"a.png": _entry("a.png", "x")}
        self.fake_backend.remote_files.add("orphan.png")  # 真实存在但清单无记录
        result = cleanup_remote_orphans(delete=False)
        self.assertTrue(result["ok"])
        self.assertIn("orphan.png", result["orphans"])
        self.assertNotIn("a.png", result["orphans"])

    def test_cleanup_remote_orphans_deletes(self):
        """清理孤儿：delete=True 删除真实孤儿文件"""
        self.fake_backend.remote_memes = {"a.png": _entry("a.png", "x")}
        self.fake_backend.remote_files.add("orphan.png")
        result = cleanup_remote_orphans(delete=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["removed"], 1)
        self.assertNotIn("orphan.png", self.fake_backend.remote_files)

    def test_cleanup_remote_orphans_degraded(self):
        """后端无 list_files → 降级返回空孤儿，不影响主同步"""
        self.fake_backend.remote_memes = {"a.png": _entry("a.png", "x")}
        with patch.object(
            self.fake_backend, "list_files", side_effect=NotImplementedError
        ):
            result = cleanup_remote_orphans(delete=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["orphans"], [])

    # ─── PR5 新增用例 ───

    def test_cleanup_stale_temp_files(self):
        """启动清理：删除中断遗留临时文件，保留正式清单"""
        (self.data_dir / ".remote-index-abc.json").write_text("x")
        (self.data_dir / ".remote-merged-def.json").write_text("x")
        (self.data_dir / "meme-index.json.tmp").write_text("x")
        from ohmymeme.services.sync.service import cleanup_stale_temp_files

        count = cleanup_stale_temp_files()
        self.assertEqual(count, 3)
        self.assertFalse((self.data_dir / ".remote-index-abc.json").exists())
        self.assertFalse((self.data_dir / ".remote-merged-def.json").exists())
        self.assertFalse((self.data_dir / "meme-index.json.tmp").exists())
        self.assertTrue((self.data_dir / "meme-index.json").exists())

    def test_cleanup_stale_temp_files_covers_cache(self):
        """启动清理：cache 子目录下的 *.tmp 也被清理"""
        cache = self.data_dir / "cache"
        (cache / "abc.png.tmp").write_text("x")
        from ohmymeme.services.sync.service import cleanup_stale_temp_files

        count = cleanup_stale_temp_files()
        self.assertGreaterEqual(count, 1)
        self.assertFalse((cache / "abc.png.tmp").exists())

    def test_download_index_leaves_no_temp(self):
        """download_index 使用唯一临时文件且结束后清理，无残留"""
        self.fake_backend.remote_memes = {"a.png": _entry("a.png", "x")}
        from ohmymeme.services.sync.service import download_index

        data = download_index()
        self.assertIsNotNone(data)
        leftovers = [
            p for p in self.data_dir.iterdir() if p.name.startswith(".remote-")
        ]
        self.assertEqual(leftovers, [])

    def test_fetch_remote_memes_download_failure_leaves_no_temp(self):
        """远端 manifest 存在但下载失败 → 无 .remote-index-* 残留"""
        self.fake_backend.manifest_download_ok = False
        with self.assertRaises(SyncError):
            sync.push()
        leftovers = [
            p for p in self.data_dir.iterdir() if p.name.startswith(".remote-index-")
        ]
        self.assertEqual(leftovers, [])

    # ─── PR6 新增用例 ───

    def test_concurrent_push_rejected(self):
        """运行锁被占用时第二次 push 抛"同步正在进行中" """
        from ohmymeme.services.sync.service import _sync_run_lock

        self.assertTrue(_sync_run_lock.acquire(blocking=False))
        try:
            with self.assertRaises(SyncError) as ctx:
                sync.push()
            self.assertIn("同步正在进行中", str(ctx.exception))
        finally:
            _sync_run_lock.release()

    def test_concurrent_pull_rejected(self):
        """运行锁被占用时 pull 抛"同步正在进行中" """
        from ohmymeme.services.sync.service import _sync_run_lock

        self.assertTrue(_sync_run_lock.acquire(blocking=False))
        try:
            with self.assertRaises(SyncError) as ctx:
                sync.pull()
            self.assertIn("同步正在进行中", str(ctx.exception))
        finally:
            _sync_run_lock.release()

    def test_push_worker_stats_no_overcount(self):
        """worker 异常路径：errors 不重复计数（2 个文件各计 1 次）"""
        self._set_local_memes(
            [
                {"filename": "a.png", "sha256": "a"},
                {"filename": "b.png", "sha256": "b"},
            ]
        )
        self.fake_backend.meme_ok = False  # 上传失败
        self.fake_backend.upload_raises.add("b.png")  # b.png 上传时抛异常
        with self.assertRaises(SyncError) as ctx:
            sync.push()
        # 旧实现会把 b.png 抛异常的剩余条目重复计数成 3
        self.assertIn("2 个文件上传失败", str(ctx.exception))

    def test_push_get_backend_failure_releases_lock(self):
        """_get_backend 抛异常后运行锁被释放，后续 push 可正常执行"""
        from ohmymeme.services.sync.service import _sync_run_lock

        with patch(
            "ohmymeme.services.sync.service._get_backend",
            side_effect=SyncError("No sync type configured"),
        ):
            with self.assertRaises(SyncError):
                sync.push()
        self.assertFalse(_sync_run_lock.locked())
        # 锁已释放，可再次正常 push
        result = sync.push()
        self.assertEqual(result["uploaded"], 1)

    # ─── PR8 新增用例 ───

    def test_push_failed_items_reported(self):
        """push 上传失败 → _sync_state.failed_items 记录失败文件"""
        self._set_local_memes(
            [
                {"filename": "a.png", "sha256": "a"},
                {"filename": "b.png", "sha256": "b"},
            ]
        )
        self.fake_backend.meme_ok = False
        with self.assertRaises(SyncError):
            sync.push()
        failed = get_sync_progress().get("failed_items", [])
        self.assertEqual(len(failed), 2)
        for item in failed:
            self.assertEqual(item["status"], "error")
            self.assertIn(item["filename"], {"a.png", "b.png"})

    def test_push_delete_unknown_reported(self):
        """delete_remote=True 删除复核异常 → failed_files 记录 unknown 状态"""
        self.fake_backend.remote_memes = {"ghost.png": _entry("ghost.png", "x")}
        self.fake_backend.delete_ok = False
        self.fake_backend.raise_on_exists.add("ghost.png")
        self.cfg.set("sync_delete_remote", True)
        result = sync.push()
        unknowns = [
            f for f in result.get("failed_files", []) if f["status"] == "unknown"
        ]
        self.assertEqual(len(unknowns), 1)
        self.assertEqual(unknowns[0]["filename"], "ghost.png")

    def test_pull_failed_items_reported(self):
        """pull 部分下载失败 → _sync_state.failed_items 记录失败文件"""
        self.fake_backend.remote_memes = {
            "test.png": _entry("test.png", "abc"),
            "missing.png": _entry("missing.png", "x"),
        }
        self.fake_backend.remote_files = {"test.png"}
        with self.assertRaises(SyncError):
            sync.pull()
        failed = get_sync_progress().get("failed_items", [])
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["filename"], "missing.png")
        self.assertEqual(failed[0]["status"], "error")


class TestSafeRemoteFname(unittest.TestCase):
    """远端 manifest 文件名安全校验（防路径穿越）"""

    def test_accepts_normal_filenames(self):
        for name in (
            "a.png",
            "abc123.png",
            "表情.webp",
            "a b.gif",
            "ohmm_stego_abcdef.gif",
        ):
            self.assertTrue(sync._safe_remote_fname(name), name)

    def test_rejects_traversal_and_absolute(self):
        for name in (
            "../evil.png",
            "..",
            ".",
            "a/../../b.png",
            "dir/file.png",
            "/etc/passwd",
            "\\windows\\system32\\cmd.exe",
            "~/secret.png",
            "",
            ".hidden",
            123,
            None,
        ):
            self.assertFalse(sync._safe_remote_fname(name), name)


if __name__ == "__main__":
    unittest.main()
