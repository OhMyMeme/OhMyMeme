"""updater 模块单测：非阻塞版本检查缓存机制"""

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import updater

_SLOW_RESULT = {
    "latest": "9.9.9",
    "download_url": "http://example.com/x",
    "has_update": False,
    "notes": "",
    "error": "",
}


class TestCheckLatestCached(unittest.TestCase):
    def setUp(self):
        updater.reset_check_cache()

    def tearDown(self):
        updater.reset_check_cache()

    def test_first_call_returns_pending_without_blocking(self):
        """首次调用触发后台检查，立即返回 pending，不阻塞"""

        def slow():
            time.sleep(2)
            return dict(_SLOW_RESULT)

        with mock.patch.object(updater, "check_latest", side_effect=slow):
            t0 = time.time()
            r = updater.check_latest_cached()
            dt = time.time() - t0
            self.assertIs(r.get("pending"), True)
            self.assertLess(dt, 0.5)  # 不应阻塞 2s

    def test_cached_result_after_background_finishes(self):
        """后台完成后再次调用命中缓存，返回真实 latest"""

        def fast():
            return dict(_SLOW_RESULT)

        with mock.patch.object(updater, "check_latest", side_effect=fast):
            self.assertIs(updater.check_latest_cached().get("pending"), True)
            # 等待后台线程写入缓存
            deadline = time.time() + 5
            while time.time() < deadline:
                r = updater.check_latest_cached()
                if not r.get("pending"):
                    break
                time.sleep(0.05)
            self.assertIsNone(r.get("pending"))
            self.assertEqual(r.get("latest"), "9.9.9")

    def test_idempotent_single_background_start(self):
        """并发多次调用只启动一次后台检查（不重复请求）"""
        calls = []

        def tracking():
            calls.append(1)
            return dict(_SLOW_RESULT)

        with mock.patch.object(updater, "check_latest", side_effect=tracking):
            for _ in range(5):
                updater.check_latest_cached()
            time.sleep(0.3)
            self.assertEqual(len(calls), 1)  # 只启动了一次


if __name__ == "__main__":
    unittest.main()
