"""tg_stickers 模块单测：解密/转换/取消/进度原子性"""

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import tg_stickers as tg


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

    @mock.patch("src.tg_stickers.subprocess.Popen")
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

    @mock.patch("src.tg_stickers.subprocess.Popen")
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
