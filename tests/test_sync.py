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

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 确保 src 在导入路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import sync
from src.config import Config
from src.manifest import INDEX_FILENAME
from src.sync import SyncError, get_sync_progress


def _entry(fname, sha256, size=1):
    return {
        "filename": fname,
        "name": fname,
        "sha256": sha256,
        "file_size": size,
        "mtime": "",
    }


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
            Path(local_path).write_bytes(b"fake image content")
        return True

    def upload_file(self, local_path, remote_path):
        rp = str(remote_path)
        self.upload_paths.append(rp)
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

    def search(self, keyword="", tags=None, limit=999999, collection_id=None):
        return list(self.rows)

    def get_collections(self):
        return []

    def get_by_filename(self, filename):
        for r in self.rows:
            if r["filename"] == filename:
                return dict(r)
        return None

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
        self._start_patch(patch("src.config._get_data_dir", return_value=self.data_dir))
        for target in ("src.sync.get_config", "src.manifest.get_config"):
            self._start_patch(patch(target, return_value=self.cfg))
        self.fake_db = _FakeDb()
        self._start_patch(patch("src.manifest.get_db", return_value=self.fake_db))
        self._start_patch(patch("src.sync.get_db", return_value=self.fake_db))

        self.fake_backend = _FakeBackend()
        self._start_patch(
            patch("src.sync._get_backend", return_value=self.fake_backend)
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
        """manifest 上传失败时 .remote-merged.json 被清理，不残留"""
        self.fake_backend.remote_memes = {"a.png": _entry("a.png", "x")}
        self.fake_backend.manifest_ok = False
        with self.assertRaises(SyncError):
            sync.push()
        self.assertFalse((self.data_dir / ".remote-merged.json").exists())

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

    def test_build_manifest_atomic_replace_preserves_old_on_failure(self):
        """build_manifest 原子替换：os.replace 失败时旧清单完好"""
        old = json.loads((self.data_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        with patch("src.manifest.os.replace", side_effect=OSError("disk full")):
            from src.manifest import build as _build

            _build()
        after = json.loads((self.data_dir / INDEX_FILENAME).read_text(encoding="utf-8"))
        self.assertEqual(after, old)

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


if __name__ == "__main__":
    unittest.main()
