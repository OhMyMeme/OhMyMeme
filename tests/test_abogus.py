"""abogus.py 单测 — 纯签名算法，不发起网络请求"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.abogus import ABogus


class TestABogusInit(unittest.TestCase):
    def test_default_init(self):
        ab = ABogus()
        self.assertEqual(len(ab.ua_code), 32)
        self.assertEqual(ab.reg[0], 1937774191)

    def test_platform_init(self):
        ab = ABogus(platform="Win32")
        self.assertIn("Win32", ab.browser)


class TestSM3Hash(unittest.TestCase):
    def test_sm3_basic(self):
        result = ABogus.sm3_to_array("hello")
        self.assertIsInstance(result, list)
        self.assertTrue(all(0 <= x <= 255 for x in result))
        self.assertEqual(len(result), 32)

    def test_sm3_deterministic(self):
        a = ABogus.sm3_to_array("test_params")
        b = ABogus.sm3_to_array("test_params")
        self.assertEqual(a, b)

    def test_sm3_different_input(self):
        a = ABogus.sm3_to_array("input_a")
        b = ABogus.sm3_to_array("input_b")
        self.assertNotEqual(a, b)


class TestRC4(unittest.TestCase):
    def test_rc4_roundtrip(self):
        key = "testkey"
        plaintext = "Hello, World! 12345"
        cipher = ABogus.rc4_encrypt(plaintext, key)
        decrypted = ABogus.rc4_encrypt(cipher, key)
        self.assertEqual(decrypted, plaintext)

    def test_rc4_empty(self):
        result = ABogus.rc4_encrypt("", "key")
        self.assertEqual(result, "")


class TestBrowserInfo(unittest.TestCase):
    def test_default_browser(self):
        ab = ABogus()
        parts = ab.browser.split("|")
        self.assertEqual(len(parts), 17)
        self.assertEqual(parts[16], "MacIntel")

    def test_custom_platform(self):
        ab = ABogus(platform="Win32")
        self.assertTrue(ab.browser.endswith("Win32"))

    def test_browser_dimensions_valid(self):
        ab = ABogus()
        parts = ab.browser.split("|")
        inner_w, inner_h = int(parts[0]), int(parts[1])
        outer_w, outer_h = int(parts[2]), int(parts[3])
        self.assertGreaterEqual(outer_w, inner_w)
        self.assertGreaterEqual(outer_h, inner_h)


class TestGetSignature(unittest.TestCase):
    def test_returns_string(self):
        ab = ABogus()
        params = {"aid": "1128", "device_platform": "webapp"}
        result = ab.get_value(params, "GET")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_output_is_base64_like(self):
        ab = ABogus()
        params = {"aid": "1128"}
        result = ab.get_value(params, "GET")
        import re

        self.assertTrue(re.match(r"^[A-Za-z0-9+/=_-]+$", result))

    def test_post_method(self):
        ab = ABogus()
        params = {"aid": "1128"}
        result = ab.get_value(params, "POST")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_different_params_different_output(self):
        ab = ABogus()
        r1 = ab.get_value({"aid": "1128"}, "GET")
        r2 = ab.get_value({"aid": "6383"}, "GET")
        self.assertNotEqual(r1, r2)

    def test_urlencoded_params(self):
        ab = ABogus()
        params_str = "aid=1128&device_platform=webapp"
        result = ab.get_value(params_str, "GET")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


class TestGenerateString1(unittest.TestCase):
    def test_length(self):
        result = ABogus.generate_string_1()
        self.assertEqual(len(result), 12)


class TestCharCodeAt(unittest.TestCase):
    def test_basic(self):
        result = ABogus.char_code_at("ABC")
        self.assertEqual(result, [65, 66, 67])


class TestEndCheckNum(unittest.TestCase):
    def test_xor(self):
        result = ABogus.end_check_num([1, 2, 3])
        self.assertEqual(result, 0)
        result2 = ABogus.end_check_num([255, 0])
        self.assertEqual(result2, 255)


if __name__ == "__main__":
    unittest.main()
