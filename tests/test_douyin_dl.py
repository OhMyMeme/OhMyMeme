"""douyin_dl.py 单测 — 纯本地逻辑，不发起网络请求"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.douyin_dl import gen_random_str, gen_verify_fp, sign_url


class TestGenRandomStr(unittest.TestCase):
    def test_default_length(self):
        s = gen_random_str()
        self.assertEqual(len(s), 126)

    def test_custom_length(self):
        s = gen_random_str(50)
        self.assertEqual(len(s), 50)

    def test_alphanumeric(self):
        s = gen_random_str(100)
        self.assertTrue(s.isalnum())


class TestGenVerifyFp(unittest.TestCase):
    def test_format(self):
        fp = gen_verify_fp()
        self.assertTrue(fp.startswith("verify_"))
        # format: verify_<base36>_<36-char-uuid>
        # last 36 chars are the uuid (contains underscores at 8,13,18,23)
        uuid = fp[-36:]
        self.assertEqual(len(uuid), 36)

    def test_contains_4_at_14(self):
        fp = gen_verify_fp()
        uuid = fp[-36:]
        self.assertEqual(uuid[14], "4")

    def test_underscores_in_uuid(self):
        fp = gen_verify_fp()
        uuid = fp[-36:]
        self.assertEqual(uuid[8], "_")
        self.assertEqual(uuid[13], "_")
        self.assertEqual(uuid[18], "_")
        self.assertEqual(uuid[23], "_")

    def test_uuid_segments_lengths(self):
        fp = gen_verify_fp()
        uuid = fp[-36:]
        # XXXXXXXX_XXXX_XXXX_XXXX_XXXXXXXXXXXX
        segs = uuid.split("_")
        self.assertEqual(len(segs), 5)
        self.assertEqual(len(segs[0]), 8)
        self.assertEqual(len(segs[1]), 4)
        self.assertEqual(len(segs[2]), 4)
        self.assertEqual(len(segs[3]), 4)
        self.assertEqual(len(segs[4]), 12)

    def test_unique(self):
        a = gen_verify_fp()
        b = gen_verify_fp()
        self.assertNotEqual(a, b)


class TestSignUrl(unittest.TestCase):
    def test_contains_abogus(self):
        params = {"aid": "1128", "device_platform": "webapp"}
        url = sign_url("https://example.com/api", params)
        self.assertIn("a_bogus=", url)

    def test_contains_params(self):
        params = {"aid": "1128", "device_platform": "webapp"}
        url = sign_url("https://example.com/api", params)
        self.assertIn("aid=1128", url)
        self.assertIn("device_platform=webapp", url)

    def test_abogus_not_empty(self):
        params = {"aid": "1128"}
        url = sign_url("https://example.com/api", params)
        abogus_idx = url.index("a_bogus=") + len("a_bogus=")
        abogus_val = url[abogus_idx:]
        self.assertTrue(len(abogus_val) > 10)

    def test_different_params_different_abogus(self):
        url1 = sign_url("https://example.com/api", {"aid": "1128"})
        url2 = sign_url("https://example.com/api", {"aid": "6383"})
        a1 = url1.split("a_bogus=")[1]
        a2 = url2.split("a_bogus=")[1]
        self.assertNotEqual(a1, a2)


if __name__ == "__main__":
    unittest.main()
