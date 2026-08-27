"""WebDAV 后端单元测试 — mock urllib.request，不访问网络"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import urllib.error

from src import sync
from src.sync import SyncError, _WebDAVBackend


class _FakeResp:
    """模拟 HTTP 响应：支持 with、可读一次正文"""

    def __init__(self, status=207, body=b""):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, *a, **k):
        data, self.body = self.body, b""
        return data


def _make_backend(url="https://dav.example.com", user="u", password="p", path=""):
    cfg = {
        "webdav_url": url,
        "webdav_user": user,
        "webdav_password": password,
        "webdav_path": path,
    }
    bk = _WebDAVBackend(cfg)
    bk.connect()
    return bk


class TestWebDAVURL(unittest.TestCase):
    def test_url_quotes_path_segments(self):
        bk = _make_backend()
        self.assertEqual(
            bk._url("memes/a b.png"), "https://dav.example.com/memes/a%20b.png"
        )
        self.assertEqual(
            bk._url("memes/表情.png"),
            "https://dav.example.com/memes/%E8%A1%A8%E6%83%85.png",
        )
        self.assertEqual(
            bk._url("memes/a#b.png"), "https://dav.example.com/memes/a%23b.png"
        )
        self.assertEqual(
            bk._url("memes/a?b.png"), "https://dav.example.com/memes/a%3Fb.png"
        )
        self.assertEqual(bk._url(""), "https://dav.example.com")

    def test_connect_normalizes_base_url_path(self):
        bk = _make_backend(url="https://host/dav/my folder")
        self.assertEqual(bk.base_url, "https://host/dav/my%20folder")
        self.assertEqual(
            bk._url("memes/a.png"), "https://host/dav/my%20folder/memes/a.png"
        )

    def test_connect_no_double_encode(self):
        bk = _make_backend(url="https://host/dav/%E8%A1%A8%E6%83%85")
        self.assertEqual(bk.base_url, "https://host/dav/%E8%A1%A8%E6%83%85")

    def test_connect_rejects_bad_scheme(self):
        with self.assertRaises(SyncError):
            _make_backend(url="not-a-url")

    def test_connect_rejects_missing_host(self):
        with self.assertRaises(SyncError):
            _make_backend(url="http:///dav")

    def test_connect_non_numeric_timeout_defaults(self):
        cfg = {
            "webdav_url": "https://host",
            "webdav_user": "u",
            "webdav_password": "p",
            "webdav_path": "",
            "webdav_timeout": "abc",
        }
        bk = _WebDAVBackend(cfg)
        bk.connect()
        self.assertEqual(bk.timeout, 30)


class TestWebDAVFileExists(unittest.TestCase):
    def setUp(self):
        self.bk = _make_backend()

    @patch("src.sync.urllib.request.urlopen")
    def test_404_returns_false(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("u", 404, "nf", {}, None)
        self.assertFalse(self.bk.file_exists("memes/a.png"))

    @patch("src.sync.urllib.request.urlopen")
    def test_207_returns_true(self, urlopen):
        urlopen.return_value = _FakeResp(207)
        self.assertTrue(self.bk.file_exists("memes/a.png"))

    @patch("src.sync.urllib.request.urlopen")
    def test_401_raises(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("u", 401, "auth", {}, None)
        with self.assertRaises(SyncError):
            self.bk.file_exists("memes/a.png")

    @patch("src.sync.urllib.request.urlopen")
    def test_500_raises(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("u", 500, "boom", {}, None)
        with self.assertRaises(SyncError):
            self.bk.file_exists("memes/a.png")

    @patch("src.sync.urllib.request.urlopen")
    def test_timeout_raises(self, urlopen):
        urlopen.side_effect = urllib.error.URLError("timed out")
        with self.assertRaises(SyncError):
            self.bk.file_exists("memes/a.png")

    @patch("src.sync.urllib.request.urlopen")
    def test_405_falls_back_to_head(self, urlopen):
        def fake_open(req, timeout=30):
            if req.method == "PROPFIND":
                raise urllib.error.HTTPError("u", 405, "method", {}, None)
            return _FakeResp(200)

        urlopen.side_effect = fake_open
        self.assertTrue(self.bk.file_exists("memes/a.png"))

    @patch("src.sync.urllib.request.urlopen")
    def test_405_head_404_returns_false(self, urlopen):
        def fake_open(req, timeout=30):
            if req.method == "PROPFIND":
                raise urllib.error.HTTPError("u", 405, "method", {}, None)
            raise urllib.error.HTTPError("u", 404, "nf", {}, None)

        urlopen.side_effect = fake_open
        self.assertFalse(self.bk.file_exists("memes/a.png"))


class TestWebDAVUpload(unittest.TestCase):
    def setUp(self):
        self.bk = _make_backend()
        fd, name = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        with Path(name).open("wb") as f:
            f.write(b"fake image")
        self.local = Path(name)

    def tearDown(self):
        self.local.unlink(missing_ok=True)

    @patch("src.sync.urllib.request.urlopen")
    def test_3xx_returns_false(self, urlopen):
        for code in (301, 302, 303):
            urlopen.side_effect = urllib.error.HTTPError(
                "u", code, "redirect", {}, None
            )
            self.assertFalse(self.bk.upload_file(self.local, "memes/a.png"))

    @patch("src.sync.urllib.request.urlopen")
    def test_sets_content_type(self, urlopen):
        seen = {}

        def fake_open(req, timeout=30):
            seen["req"] = req
            return _FakeResp(201)

        urlopen.side_effect = fake_open
        self.assertTrue(self.bk.upload_file(self.local, "memes/a.png"))
        # Request.add_header 内部 capitalize：Content-Type -> Content-type
        self.assertEqual(
            seen["req"].get_header("Content-type"), "application/octet-stream"
        )


class TestWebDAVDownload(unittest.TestCase):
    def setUp(self):
        self.bk = _make_backend()
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp_dir, ignore_errors=True)

    @patch("src.sync.urllib.request.urlopen")
    def test_download_streams_and_replaces(self, urlopen):
        urlopen.return_value = _FakeResp(200, b"0123456789")
        target = self.tmp_dir / "a.png"
        self.assertTrue(self.bk.download_file("memes/a.png", target))
        self.assertEqual(target.read_bytes(), b"0123456789")
        self.assertFalse(Path(str(target) + ".tmp").exists())

    @patch("src.sync.urllib.request.urlopen")
    def test_download_failure_cleans_tmp(self, urlopen):
        urlopen.side_effect = urllib.error.URLError("boom")
        target = self.tmp_dir / "a.png"
        self.assertFalse(self.bk.download_file("memes/a.png", target))
        self.assertFalse(Path(str(target) + ".tmp").exists())
        self.assertFalse(target.exists())


class TestWebDAVTestConnection(unittest.TestCase):
    @patch("src.sync.urllib.request.urlopen")
    def test_ok_on_207(self, urlopen):
        urlopen.return_value = _FakeResp(207)
        bk = _make_backend(path="memes")
        bk.test_connection()

    @patch("src.sync.urllib.request.urlopen")
    def test_401_raises(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("u", 401, "auth", {}, None)
        bk = _make_backend(path="memes")
        with self.assertRaises(SyncError):
            bk.test_connection()

    @patch("src.sync.urllib.request.urlopen")
    def test_404_raises(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("u", 404, "nf", {}, None)
        bk = _make_backend(path="memes")
        with self.assertRaises(SyncError) as ctx:
            bk.test_connection()
        self.assertIn("首次上传将自动创建", str(ctx.exception))

    @patch("src.sync.urllib.request.urlopen")
    def test_timeout_raises(self, urlopen):
        urlopen.side_effect = urllib.error.URLError("timed out")
        bk = _make_backend(path="memes")
        with self.assertRaises(SyncError):
            bk.test_connection()


class TestSyncTestWebDAV(unittest.TestCase):
    @patch("src.sync._get_backend")
    def test_sync_test_probes_connection(self, get_backend):
        class _Bk:
            def connect(self):
                pass

            def close(self):
                pass

            def test_connection(self):
                raise SyncError("boom")

        get_backend.return_value = _Bk()
        self.assertEqual(sync.sync_test(), "boom")


class TestWebDAVList(unittest.TestCase):
    @patch("src.sync.urllib.request.urlopen")
    def test_unquotes_href(self, urlopen):
        body = (
            b'<?xml version="1.0"?><D:multistatus xmlns:D="DAV:">'
            b"<D:response><D:href>/dav/memes/a%20b.png</D:href></D:response>"
            b"<D:response><D:href>/dav/memes/%E8%A1%A8%E6%83%85.png</D:href></D:response>"
            b"</D:multistatus>"
        )
        urlopen.return_value = _FakeResp(207, body)
        bk = _make_backend(url="https://host/dav")
        self.assertEqual(bk.list_files("memes"), ["a b.png", "表情.png"])

    @patch("src.sync.urllib.request.urlopen")
    def test_invalid_xml_raises(self, urlopen):
        urlopen.return_value = _FakeResp(207, b"<not-xml")
        bk = _make_backend(url="https://host/dav")
        with self.assertRaises(SyncError):
            bk.list_files("memes")

    @patch("src.sync.urllib.request.urlopen")
    def test_405_raises(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("u", 405, "method", {}, None)
        bk = _make_backend(url="https://host/dav")
        with self.assertRaises(SyncError):
            bk.list_files("memes")


class TestWebDAVEnsureDir(unittest.TestCase):
    def setUp(self):
        # 进程级 `_dav_dirs` 目录缓存会跨测试残留，逐个测试清空以保证独立
        sync._dav_dirs.clear()

    @patch("src.sync.urllib.request.urlopen")
    def test_405_ok(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("u", 405, "exists", {}, None)
        bk = _make_backend()
        self.assertTrue(bk.ensure_remote_dir("memes"))

    @patch("src.sync.urllib.request.urlopen")
    def test_second_call_skips_mkcol(self, urlopen):
        urlopen.side_effect = urllib.error.HTTPError("u", 405, "exists", {}, None)
        bk = _make_backend()
        self.assertTrue(bk.ensure_remote_dir("memes"))
        self.assertEqual(urlopen.call_count, 1)
        # 目录已缓存存在，第二次调用不再发 MKCOL（避免触发远端锁）
        self.assertTrue(bk.ensure_remote_dir("memes"))
        self.assertEqual(urlopen.call_count, 1)

    @patch("src.sync.urllib.request.urlopen")
    def test_success_also_caches_and_single_mkcol(self, urlopen):
        urlopen.return_value = _FakeResp(207)
        bk = _make_backend()
        # 成功创建也写缓存：第二次调用不应再发 MKCOL
        self.assertTrue(bk.ensure_remote_dir("memes"))
        self.assertEqual(urlopen.call_count, 1)
        self.assertTrue(bk.ensure_remote_dir("memes"))
        self.assertEqual(urlopen.call_count, 1)

    @patch("src.sync.urllib.request.urlopen")
    def test_301_existing_collection_ok(self, urlopen):
        # MKCOL 301，PROPFIND 复核确认集合存在 → 幂等继续
        urlopen.side_effect = [
            urllib.error.HTTPError("u", 301, "moved", {}, None),
            _FakeResp(207),
        ]
        bk = _make_backend()
        self.assertTrue(bk.ensure_remote_dir("memes"))

    @patch("src.sync.urllib.request.urlopen")
    def test_301_missing_collection_raises(self, urlopen):
        # MKCOL 301，PROPFIND 复核确认集合不存在 → 判失败
        urlopen.side_effect = [
            urllib.error.HTTPError("u", 301, "moved", {}, None),
            urllib.error.HTTPError("u", 404, "nf", {}, None),
        ]
        bk = _make_backend()
        with self.assertRaises(SyncError):
            bk.ensure_remote_dir("memes")


if __name__ == "__main__":
    unittest.main()
