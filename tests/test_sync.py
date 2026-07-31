"""sync.push() 远端 manifest 一致性回归测试

覆盖 push() 的止血修复：
- 任一普通图片上传失败 → 抛 SyncError，且不上传新的远端 manifest
- manifest 上传失败 → 抛 SyncError
- 全部上传成功 → 正常返回并置 done 状态

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


class _FakeBackend:
    """内存假后端：只记录上传路径，可按需让 meme/manifest 上传失败"""

    def __init__(self, meme_ok=True, manifest_ok=True, remote_memes=None):
        self.meme_ok = meme_ok
        self.manifest_ok = manifest_ok
        self.remote_memes = remote_memes or {}
        self.upload_paths = []
        self.delete_calls = []

    def connect(self):
        pass

    def ensure_remote_dir(self, path):
        pass

    def file_exists(self, path):
        # 远端 manifest 存在 → 让 _fetch_remote_memes 走下载分支
        return str(path).endswith(INDEX_FILENAME)

    def download_file(self, remote_path, local_path):
        if str(remote_path).endswith(INDEX_FILENAME):
            data = {"version": 3, "memes": list(self.remote_memes.values())}
            Path(local_path).write_text(json.dumps(data))
            return True
        return False

    def upload_file(self, local_path, remote_path):
        self.upload_paths.append(str(remote_path))
        if str(remote_path).endswith(INDEX_FILENAME):
            return self.manifest_ok
        return self.meme_ok

    def delete_file(self, path):
        self.delete_calls.append(str(path))
        return True

    def close(self):
        pass


class _FakeDb:
    """build_manifest() 所需的假数据库，避免触碰真实数据"""

    def search(self, keyword="", tags=None, limit=999999, collection_id=None):
        return [
            {
                "filename": "test.png",
                "original_name": "test",
                "file_hash": "abc",
                "file_size": 16,
            }
        ]

    def get_collections(self):
        return []


class TestSyncPush(unittest.TestCase):
    """push() manifest 一致性回归测试"""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

        # 临时数据目录：cache 里有图片文件，data 里有本地 manifest
        self.data_dir = self.tmp_dir / "data"
        cache_dir = self.data_dir / "cache"
        thumb_dir = self.data_dir / "thumbnails"
        cache_dir.mkdir(parents=True, exist_ok=True)
        thumb_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "test.png").write_bytes(b"fake image bytes")

        manifest = {
            "version": 3,
            "memes": [
                {
                    "filename": "test.png",
                    "name": "test",
                    "sha256": "abc",
                    "file_size": 16,
                    "mtime": "",
                }
            ],
            "collections": [],
        }
        (self.data_dir / INDEX_FILENAME).write_text(json.dumps(manifest))

        self.cfg = Config(self.tmp_dir / "config.json")
        self.cfg.set("sync_type", "ftp")
        self.cfg.set("sync_threads", 1)

        # 将 data_dir / get_config / get_db / _get_backend 全部指向临时环境
        self._start_patch(patch("src.config._get_data_dir", return_value=self.data_dir))
        for target in ("src.sync.get_config", "src.manifest.get_config"):
            self._start_patch(patch(target, return_value=self.cfg))
        self._start_patch(patch("src.manifest.get_db", return_value=_FakeDb()))

        self.fake_backend = _FakeBackend()
        self._start_patch(
            patch("src.sync._get_backend", return_value=self.fake_backend)
        )

    def _start_patch(self, patcher):
        patcher.start()
        self.addCleanup(patcher.stop)

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
        self.fake_backend.remote_memes = {
            "ghost.png": {
                "filename": "ghost.png",
                "sha256": "x",
                "file_size": 1,
                "mtime": "",
            }
        }
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


if __name__ == "__main__":
    unittest.main()
