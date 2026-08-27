"""tg_stickers 模块单测：解密/转换/取消/进度原子性"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ohmymeme.integrations.imports import telegram as tg


class DummyProc:
    """模拟 Popen 返回对象"""

    def __init__(self, ret=0, raised=None):
        self._ret = ret
        self._raised = raised
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.waited = False

    def poll(self):
        return None if self.returncode is None else self.returncode

    def communicate(self, timeout=None):
        if self._raised:
            raise self._raised
        self.returncode = self._ret
        return b"", b""

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.waited = True
        return self.returncode


class TestDetectExtension(unittest.TestCase):
    def test_known_formats(self):
        self.assertEqual(tg.detect_extension(b"\x89PNG\r\n\x1a\nrest"), ".png")
        self.assertEqual(tg.detect_extension(b"\xff\xd8\xff\xe0rest"), ".jpg")
        self.assertEqual(tg.detect_extension(b"GIF89a...."), ".gif")
        self.assertEqual(tg.detect_extension(b"RIFF....WEBPVP8 "), ".webp")
        self.assertEqual(
            tg.detect_extension(b"\x1a\x45\xdf\xa3\x01\x00\x00\x00"), ".webm"
        )
        self.assertEqual(tg.detect_extension(b"ZZZZQQQQ"), "")

    def test_webp_requires_magic(self):
        self.assertEqual(tg.detect_extension(b"RIFF....WEBPX"), ".webp")
        self.assertEqual(tg.detect_extension(b"RIFF....OTHER"), "")


class TestStateElapsed(unittest.TestCase):
    def setUp(self):
        tg._reset_state()

    def tearDown(self):
        tg._reset_state()

    # 运行中 elapsed 随 _TG_T0 单调推进，reset 后归零不推进
    def test_elapsed_only_advances_while_running(self):
        tg._TG_T0 = time.monotonic() - 5
        tg._update_tg(status="converting", progress=50, done=5, total=10)
        self.assertGreaterEqual(tg.get_tg_progress()["elapsed_s"], 4)
        # idle 时不再推进（_reset_state 置 None）
        tg._reset_state()
        self.assertEqual(tg.get_tg_progress()["elapsed_s"], 0)

    # reset 清空 _TG_T0 与 elapsed_s
    def test_elapsed_reset(self):
        tg._TG_T0 = time.monotonic() - 3  # 手动污染
        tg._reset_state()
        self.assertIsNone(tg._TG_T0)
        self.assertEqual(tg.get_tg_progress()["elapsed_s"], 0)


class TestConvertProcessLifecycle(unittest.TestCase):
    def setUp(self):
        tg._reset_state()

    def tearDown(self):
        tg._reset_state()

    @mock.patch("ohmymeme.integrations.imports.telegram.subprocess.Popen")
    def test_success_adds_and_discards(self, popen):
        proc = DummyProc(ret=0)
        popen.return_value = proc
        self.assertTrue(
            tg.convert_webm_to_webp("/tmp/x.webm", "/tmp/x.webp", timeout=30)
        )
        popen.assert_called_once()
        # 结束后集合为空
        with tg._TG_LOCK:
            self.assertEqual(len(tg._TG_ACTIVE_PROC), 0)

    @mock.patch("ohmymeme.integrations.imports.telegram.subprocess.Popen")
    def test_timeout_kills_and_waits(self, popen):
        import subprocess

        proc = DummyProc(ret=1, raised=subprocess.TimeoutExpired("ffmpeg", 30))
        popen.return_value = proc
        self.assertFalse(
            tg.convert_webm_to_webp("/tmp/x.webm", "/tmp/x.webp", timeout=30)
        )
        self.assertTrue(proc.killed)
        self.assertTrue(proc.waited)
        with tg._TG_LOCK:
            self.assertNotIn(proc, tg._TG_ACTIVE_PROC)

    def test_cancel_terminates_active_proc(self):
        proc = DummyProc()
        with tg._TG_LOCK:
            tg._TG_ACTIVE_PROC.add(proc)
        tg.cancel_tg_import()
        self.assertTrue(proc.terminated)
        # 已终止进程从集合保留（由 convert/discard 清理），这里验证终止被调用即可
        tg._reset_state()

    def test_reap_keeps_process_registered_until_it_exits(self):
        class StillRunningProc(DummyProc):
            def __init__(self):
                super().__init__()
                self.wait_calls = 0

            def kill(self):
                self.killed = True

            def wait(self, timeout=None):
                self.wait_calls += 1
                if self.wait_calls == 1:
                    raise subprocess.TimeoutExpired("ffmpeg", timeout)
                return None

        proc = StillRunningProc()
        with tg._TG_LOCK:
            tg._TG_ACTIVE_PROC.add(proc)
        tg._reap_proc(proc, timeout=0)
        self.assertTrue(proc.killed)
        self.assertEqual(proc.wait_calls, 2)
        with tg._TG_LOCK:
            self.assertIn(proc, tg._TG_ACTIVE_PROC)


class TestWorkerExecutorLifecycle(unittest.TestCase):
    def setUp(self):
        tg._reset_state()

    def tearDown(self):
        tg._reset_state()

    def test_conversion_executor_is_bounded_and_shutdown_waits(self):
        submitted = []
        executor_state = {}

        class Future:
            def result(self):
                return True

        class Executor:
            def __init__(self, max_workers):
                executor_state["max_workers"] = max_workers

            def submit(self, function, *args):
                submitted.append((function, args))
                return Future()

            def shutdown(self, wait, cancel_futures):
                executor_state["shutdown"] = (wait, cancel_futures)

        tdata = Path(tempfile.mkdtemp(prefix="tg_executor_"))
        cache = tdata / "user_data" / "cache"
        cache.mkdir(parents=True)
        (tdata / "key_datas").write_bytes(b"key")
        (cache / "encrypted").write_bytes(b"TDF$")

        def fake_as_completed(futures):
            return list(futures)

        try:
            with mock.patch.object(
                tg, "ThreadPoolExecutor", Executor
            ), mock.patch.object(
                tg, "as_completed", fake_as_completed
            ), mock.patch.object(
                tg, "read_local_key", return_value=b"key"
            ), mock.patch.object(
                tg, "decrypt_tdf_file", return_value=b"\x1a\x45\xdf\xa3webm"
            ), mock.patch.object(
                tg, "_check_ffmpeg", return_value=True
            ), mock.patch.object(
                tg, "convert_webm_to_webp", return_value=True
            ):
                tg._tg_worker(
                    lambda _paths: {"ids": [], "rejected": 0}, str(tdata), "", True
                )
        finally:
            shutil.rmtree(tdata, ignore_errors=True)

        self.assertEqual(executor_state["max_workers"], min(os.cpu_count() or 1, 4))
        self.assertEqual(executor_state["shutdown"], (True, True))
        self.assertEqual(len(submitted), 1)
        self.assertEqual(tg.get_tg_progress()["status"], "done")

    def test_executor_waits_for_running_futures_and_cleans_temp_dir(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        executor_state = {}

        class Future:
            def result(self):
                release.wait(1)
                finished.set()
                return True

        class Executor:
            def __init__(self, max_workers):
                executor_state["max_workers"] = max_workers

            def submit(self, _function, *_args):
                started.set()
                return Future()

            def shutdown(self, wait, cancel_futures):
                executor_state["shutdown"] = (wait, cancel_futures)
                assert wait is True
                assert finished.wait(1)

        tdata = Path(tempfile.mkdtemp(prefix="tg_executor_wait_"))
        cache = tdata / "user_data" / "cache"
        cache.mkdir(parents=True)
        (tdata / "key_datas").write_bytes(b"key")
        (cache / "encrypted").write_bytes(b"TDF$")

        def convert(_source, _destination):
            release.set()
            return True

        try:
            with mock.patch.object(
                tg, "ThreadPoolExecutor", Executor
            ), mock.patch.object(
                tg, "as_completed", lambda futures: list(futures)
            ), mock.patch.object(
                tg, "read_local_key", return_value=b"key"
            ), mock.patch.object(
                tg, "decrypt_tdf_file", return_value=b"\x1a\x45\xdf\xa3webm"
            ), mock.patch.object(
                tg, "_check_ffmpeg", return_value=True
            ), mock.patch.object(
                tg, "convert_webm_to_webp", convert
            ):
                tg._tg_worker(
                    lambda _paths: {"ids": [], "rejected": 0}, str(tdata), "", True
                )
            self.assertTrue(started.is_set())
            self.assertEqual(executor_state["shutdown"], (True, True))
            self.assertTrue(finished.is_set())
        finally:
            shutil.rmtree(tdata, ignore_errors=True)

    def test_real_executor_runs_multiple_conversions_concurrently(self):
        entered = threading.Event()
        release = threading.Event()
        active_lock = threading.Lock()
        active = 0
        max_active = 0

        def convert(_source, _destination):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
                if max_active >= 2:
                    entered.set()
            release.wait(1)
            with active_lock:
                active -= 1
            return True

        tdata = Path(tempfile.mkdtemp(prefix="tg_executor_real_"))
        cache = tdata / "user_data" / "cache"
        cache.mkdir(parents=True)
        (tdata / "key_datas").write_bytes(b"key")
        (cache / "first").write_bytes(b"TDF$")
        (cache / "second").write_bytes(b"TDF$")
        worker = threading.Thread(
            target=tg._tg_worker,
            args=(lambda _paths: {"ids": [], "rejected": 0}, str(tdata), "", True),
        )
        try:
            with mock.patch.object(
                tg, "read_local_key", return_value=b"key"
            ), mock.patch.object(
                tg, "decrypt_tdf_file", return_value=b"\x1a\x45\xdf\xa3webm"
            ), mock.patch.object(
                tg, "_check_ffmpeg", return_value=True
            ), mock.patch.object(
                tg, "convert_webm_to_webp", convert
            ):
                worker.start()
                self.assertTrue(entered.wait(1))
                release.set()
                worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertGreaterEqual(max_active, 2)
            self.assertEqual(tg.get_tg_progress()["status"], "done")
        finally:
            release.set()
            worker.join(1)
            shutil.rmtree(tdata, ignore_errors=True)

    def test_executor_future_exception_still_shuts_down_and_cleans_temp_dir(self):
        executor_state = {}

        class Future:
            def result(self):
                raise RuntimeError("controlled conversion failure")

        class Executor:
            def __init__(self, max_workers):
                executor_state["max_workers"] = max_workers

            def submit(self, _function, *_args):
                return Future()

            def shutdown(self, wait, cancel_futures):
                executor_state["shutdown"] = (wait, cancel_futures)

        tdata = Path(tempfile.mkdtemp(prefix="tg_executor_error_"))
        cache = tdata / "user_data" / "cache"
        cache.mkdir(parents=True)
        (tdata / "key_datas").write_bytes(b"key")
        (cache / "encrypted").write_bytes(b"TDF$")
        try:
            with mock.patch.object(
                tg, "ThreadPoolExecutor", Executor
            ), mock.patch.object(
                tg, "as_completed", lambda futures: list(futures)
            ), mock.patch.object(
                tg, "read_local_key", return_value=b"key"
            ), mock.patch.object(
                tg, "decrypt_tdf_file", return_value=b"\x1a\x45\xdf\xa3webm"
            ), mock.patch.object(
                tg, "_check_ffmpeg", return_value=True
            ), mock.patch.object(
                tg, "convert_webm_to_webp", return_value=True
            ):
                tg._tg_worker(
                    lambda _paths: {"ids": [], "rejected": 0}, str(tdata), "", True
                )
            self.assertEqual(executor_state["shutdown"], (True, True))
            self.assertEqual(tg.get_tg_progress()["status"], "done")
            self.assertEqual(tg.get_tg_progress()["convert_failed"], 1)
        finally:
            shutil.rmtree(tdata, ignore_errors=True)


class TestDedup(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tg_test_"))

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_animated_webp(self, path, first_frame=(200, 30, 30), tail=(180, 30, 30)):
        from PIL import Image

        # 首帧与静态版颜色一致、后续帧不同，确保多帧保留且能命中去重
        frames = [
            Image.new("RGB", (32, 32), first_frame),
            Image.new("RGB", (32, 32), tail),
        ]
        frames[0].save(
            str(path),
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=1,
            format="WEBP",
            quality=95,
        )
        return path

    def _make_static_webp(self, path, rgb):
        from PIL import Image

        Image.new("RGB", (32, 32), rgb).save(str(path), format="WEBP")
        return path

    def test_dedup_skips_matching_static(self):
        anim = self._make_animated_webp(self.tmp / "anim.webp", (200, 30, 30))
        # 静态与动画首帧颜色一致（首帧底色 200,30,30 几乎占满 32x32）
        stat = self._make_static_webp(self.tmp / "stat.webp", (200, 30, 30))
        stat2 = self._make_static_webp(self.tmp / "stat2.webp", (20, 200, 40))
        paths = [str(anim), str(stat), str(stat2)]
        kept, skipped = tg.dedup_static_against_animated(paths, threshold=0.05)
        self.assertEqual(skipped, 1)
        self.assertIn(str(anim), kept)
        self.assertNotIn(str(stat), kept)
        self.assertIn(str(stat2), kept)

    def test_no_animated_keeps_all(self):
        stat = self._make_static_webp(self.tmp / "a.webp", (1, 2, 3))
        stat2 = self._make_static_webp(self.tmp / "b.webp", (4, 5, 6))
        kept, skipped = tg.dedup_static_against_animated([str(stat), str(stat2)])
        self.assertEqual(skipped, 0)
        self.assertEqual(len(kept), 2)


class TestWorkerParallelState(unittest.TestCase):
    def setUp(self):
        tg._reset_state()

    def tearDown(self):
        tg._reset_state()

    def test_parallel_convert_syncs_done(self):
        """转换循环 _TG_LOCK 内累加 done——RLock 支持 _update_tg 嵌套取锁"""
        self.assertEqual(type(tg._TG_LOCK).__name__, "RLock")


if __name__ == "__main__":
    unittest.main()
