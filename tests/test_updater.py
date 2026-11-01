"""updater 模块单测：非阻塞版本检查缓存机制"""

import os
import sys
import tempfile
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
    # 每个用例前后重置版本检查缓存
    def setUp(self):
        updater.reset_check_cache()

    def tearDown(self):
        updater.reset_check_cache()

    # 首次调用触发后台检查，立即返回 pending 不阻塞
    def test_first_call_returns_pending_without_blocking(self):

        def slow():
            # 模拟慢网络：阻塞 2s 后返回结果
            time.sleep(2)
            return dict(_SLOW_RESULT)

        with mock.patch.object(updater, "check_latest", side_effect=slow):
            t0 = time.time()
            r = updater.check_latest_cached()
            dt = time.time() - t0
            self.assertIs(r.get("pending"), True)
            self.assertLess(dt, 0.5)  # 不应阻塞 2s

    # 后台完成后再次调用命中缓存，返回真实 latest
    def test_cached_result_after_background_finishes(self):

        def fast():
            # 立即返回，模拟快速检查
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

    # 并发多次调用只启动一次后台检查（不重复请求）
    def test_idempotent_single_background_start(self):
        calls = []

        def tracking():
            # 记录每次真实请求次数
            calls.append(1)
            return dict(_SLOW_RESULT)

        with mock.patch.object(updater, "check_latest", side_effect=tracking):
            for _ in range(5):
                updater.check_latest_cached()
            time.sleep(0.3)
            self.assertEqual(len(calls), 1)  # 只启动了一次

    # force=True 时即使有新鲜缓存也触发重新检查
    def test_force_triggers_recheck_despite_fresh_cache(self):
        calls = []

        def tracking():
            # 记录每次真实请求次数
            calls.append(1)
            return dict(_SLOW_RESULT)

        with mock.patch.object(updater, "check_latest", side_effect=tracking):
            # 先完成一次后台检查，得到缓存
            self.assertIs(updater.check_latest_cached().get("pending"), True)
            deadline = time.time() + 5
            while time.time() < deadline:
                if not updater.check_latest_cached().get("pending"):
                    break
                time.sleep(0.05)
            cached = updater.check_latest_cached()
            self.assertIsNone(cached.get("pending"))
            # 缓存新鲜时非 force 直接命中缓存，不再启动检查
            updater.check_latest_cached()
            self.assertEqual(len(calls), 1)
            # force=True：立即触发再一次后台检查（fresh 缓存被忽略）
            self.assertIs(updater.check_latest_cached(force=True).get("pending"), True)
            time.sleep(0.2)
            self.assertEqual(len(calls), 2)

    # 缓存超 24h 后非 force 也触发重新检查
    def test_expired_cache_triggers_recheck(self):
        calls = []

        def fast():
            # 记录每次真实请求次数
            calls.append(1)
            return dict(_SLOW_RESULT)

        with mock.patch.object(updater, "check_latest", side_effect=fast):
            # 伪造一份 25 小时前的缓存
            updater.reset_check_cache()
            with updater._check_lock:
                updater._check_result = dict(_SLOW_RESULT)
                updater._check_result_at = time.time() - (updater._CHECK_TTL + 3600)
            r = updater.check_latest_cached()  # 非 force
            self.assertIs(r.get("pending"), True)  # 过期 → 触发重查

    # reset 后启动的在途后台任务不得覆盖 reset 状态（generation 防护）
    def test_reset_generation_discards_stale_task_result(self):
        import threading as _threading

        started = _threading.Event()  # 后台任务真正进入 blocked 的信号
        release = _threading.Event()  # 放行 blocked 任务

        def blocked():
            # 同步：进入阻塞态通知主测试，等待放行
            started.set()
            release.wait(3)
            return dict(_SLOW_RESULT)

        with mock.patch.object(updater, "check_latest", side_effect=blocked):
            r = updater.check_latest_cached()
            self.assertIs(r.get("pending"), True)
            # 等待后台线程真正进入 blocked（确保 _check_running=True 且任务已启动）
            self.assertTrue(started.wait(2))
            # reset 清空缓存并推进 generation
            updater.reset_check_cache()
            self.assertIsNone(updater._check_result)
            # 放行旧任务，让其完成
            release.set()
            # 等 worker 写完（若有的话），再断言旧结果未被缓存
            deadline = time.time() + 2
            while time.time() < deadline and updater._check_result is None:
                time.sleep(0.02)
            # 旧任务完成，但因 generation 不匹配，不得写入缓存
            self.assertIsNone(updater._check_result)
            # reset 本身已把 _check_running 置 False，旧任务也不得改它
            with updater._check_lock:
                self.assertFalse(updater._check_running)

    # force 刷新进行中，非 force 调用返回 pending 而非旧缓存
    def test_force_in_flight_nonforce_returns_pending(self):
        import threading as _threading

        started = _threading.Event()
        release = _threading.Event()

        def blocked():
            # 同步：进入阻塞态通知主测试，等待放行
            started.set()
            release.wait(3)
            return dict(_SLOW_RESULT)

        with mock.patch.object(updater, "check_latest", side_effect=blocked):
            # 先完成一次检查，留下新鲜缓存
            updater.reset_check_cache()
            with updater._check_lock:
                updater._check_result = dict(_SLOW_RESULT)
                updater._check_result_at = time.time()
            # 缓存新鲜：非 force 应命中缓存
            fresh = updater.check_latest_cached()
            self.assertIsNone(fresh.get("pending"))
            self.assertEqual(fresh.get("latest"), "9.9.9")
            # force 发起新检查（此时旧缓存仍在 _check_result，_check_running=True）
            self.assertIs(updater.check_latest_cached(force=True).get("pending"), True)
            self.assertTrue(started.wait(2))
            # 检查进行中，非 force 调用不得命中旧缓存，必须 pending
            r = updater.check_latest_cached()
            self.assertIs(r.get("pending"), True)
            # 放行，等后台完成
            release.set()
            deadline = time.time() + 2
            while time.time() < deadline:
                r2 = updater.check_latest_cached()
                if not r2.get("pending"):
                    break
                time.sleep(0.05)
            self.assertIsNone(r2.get("pending"))


class TestPickAssetUrl(unittest.TestCase):
    # 发布资产按上传顺序返回：ffmpeg.exe 排在安装包前面时不得被选为更新包
    def test_prefers_setup_exe_over_other_exes(self):
        assets = [
            {
                "name": "ffmpeg.exe",
                "browser_download_url": "http://x/ffmpeg.exe",
            },
            {
                "name": "OhMyMeme-0.7.0-setup.exe",
                "browser_download_url": "http://x/setup.exe",
            },
            {
                "name": "OhMyMeme-0.7.0.msix",
                "browser_download_url": "http://x/app.msix",
            },
        ]
        with mock.patch.object(updater.platform, "system", return_value="Windows"):
            self.assertEqual(updater._pick_asset_url(assets), "http://x/setup.exe")

    # 没有 -setup.exe 时回退首个 .exe（保持旧行为）
    def test_falls_back_to_first_exe(self):
        assets = [
            {"name": "a.exe", "browser_download_url": "http://x/a.exe"},
            {"name": "b.exe", "browser_download_url": "http://x/b.exe"},
        ]
        with mock.patch.object(updater.platform, "system", return_value="Windows"):
            self.assertEqual(updater._pick_asset_url(assets), "http://x/a.exe")

    # 非 Windows 系统不选 exe
    def test_no_exe_on_other_platforms(self):
        assets = [{"name": "ffmpeg.exe", "browser_download_url": "http://x/ffmpeg"}]
        with mock.patch.object(updater.platform, "system", return_value="Darwin"):
            self.assertEqual(updater._pick_asset_url(assets), "")


class TestRunInstaller(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    # 镜像返回 HTML 错误页时不得当安装包启动
    def test_rejects_non_pe_file(self):
        path = os.path.join(self._tmp.name, "bad-setup.exe")
        with open(path, "wb") as f:
            f.write(b"<!DOCTYPE html><html>404</html>")
        with mock.patch.object(updater.platform, "system", return_value="Windows"):
            self.assertFalse(updater.run_installer(path))

    # 合法 PE 头通过校验（ShellExecute 打桩）
    def test_accepts_pe_and_calls_shell_execute(self):
        path = os.path.join(self._tmp.name, "good-setup.exe")
        with open(path, "wb") as f:
            f.write(b"MZ" + b"\x00" * 62)
        with mock.patch.object(updater.platform, "system", return_value="Windows"):
            with mock.patch.object(updater, "_shell_execute", return_value=True) as m:
                self.assertTrue(updater.run_installer(path))
        self.assertEqual(m.call_args[0][0], path)

    # 未下载完成时 last_downloaded_path 返回空串
    def test_last_downloaded_path_empty(self):
        with updater._download_lock:
            updater._download_state["path"] = None
        self.assertEqual(updater.last_downloaded_path(), "")

    # 已下载文件存在时 last_downloaded_path 返回路径
    def test_last_downloaded_path_hits_file(self):
        path = os.path.join(self._tmp.name, "kept-setup.exe")
        with open(path, "wb") as f:
            f.write(b"MZ")
        with updater._download_lock:
            updater._download_state["path"] = path
        self.addCleanup(self._reset_download_state)
        self.assertEqual(updater.last_downloaded_path(), path)

    # 还原下载状态，避免污染其他用例
    def _reset_download_state(self):
        with updater._download_lock:
            updater._download_state["path"] = None
            updater._download_state["status"] = "idle"


if __name__ == "__main__":
    unittest.main()
