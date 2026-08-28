"""OhMyMeme 核心模块测试"""

import re
import sys
import tempfile
import threading
import unittest
import unittest.mock as mock
from pathlib import Path

# 确保 src 在导入路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import __app_name__, __version__
from src.config import Config
from src.crypto_util import decrypt_data, encrypt_data
from src.database import MemeDB


class TestVersion(unittest.TestCase):
    def test_version(self):
        self.assertIsNotNone(re.match(r"\d+\.\d+\.\d+", __version__))
        self.assertEqual(__app_name__, "OhMyMeme")


class TestCrypto(unittest.TestCase):
    def test_encrypt_decrypt(self):
        original = "test_secret_key_123!@#"
        enc = encrypt_data(original)
        self.assertNotEqual(enc, original)
        dec = decrypt_data(enc)
        self.assertEqual(dec, original)

    def test_empty(self):
        self.assertEqual(decrypt_data(""), "")
        self.assertEqual(encrypt_data(""), "")

    def test_invalid(self):
        self.assertEqual(decrypt_data("invalid!@#base64!!"), "")


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.config_path = self.tmp_dir / "config.json"

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_defaults(self):
        cfg = Config(self.config_path)
        self.assertEqual(cfg.get("hotkey"), "Ctrl+Alt+N")
        self.assertIs(cfg.get("hotkey_show_at_mouse"), False)
        self.assertEqual(cfg.get("sync_auto_fetch_index"), False)
        self.assertEqual(cfg.get("sync_auto_sync"), False)
        self.assertEqual(cfg.get("sync_type"), "")
        self.assertEqual(cfg.get("ftp_host"), "")
        self.assertEqual(cfg.get("cache_max_size_mb"), 500)

    def test_set_get(self):
        cfg = Config(self.config_path)
        cfg.set("hotkey", "Ctrl+Shift+X")
        self.assertEqual(cfg.get("hotkey"), "Ctrl+Shift+X")

    def test_s3_path_persists_through_bulk_update(self):
        cfg = Config(self.config_path)
        cfg.update_from_dict({"s3_path": "memes"})
        cfg.save()

        self.assertEqual(Config(self.config_path).get("s3_path"), "memes")

    def test_encrypted_secret(self):
        cfg = Config(self.config_path)
        cfg.set("s3_secret_key", "my_secret")
        saved = cfg._data["s3_secret_key"]
        # 应该是加密后的字符串
        self.assertNotEqual(saved, "my_secret")
        self.assertTrue(len(saved) > 20)

    def test_save_load(self):
        cfg = Config(self.config_path)
        cfg.set("hotkey", "Ctrl+Alt+N")
        cfg.set("s3_access_key", "AKID123")
        cfg.save()

        cfg2 = Config(self.config_path)
        self.assertEqual(cfg2.get("hotkey"), "Ctrl+Alt+N")
        self.assertEqual(cfg2.get("s3_access_key"), "AKID123")

    def test_hotkey_show_at_mouse_old_config_defaults_false(self):
        self.config_path.write_text('{"hotkey": "Ctrl+Shift+X"}', encoding="utf-8")

        cfg = Config(self.config_path)

        self.assertIs(cfg.get("hotkey_show_at_mouse"), False)

    def test_hotkey_show_at_mouse_persists_and_resets(self):
        cfg = Config(self.config_path)
        cfg.set("hotkey_show_at_mouse", True)
        cfg.save()

        reloaded = Config(self.config_path)
        self.assertIs(reloaded.get("hotkey_show_at_mouse"), True)

        reloaded.reset()
        reloaded.save()

        reset = Config(self.config_path)
        self.assertIs(reset.get("hotkey_show_at_mouse"), False)

    def test_removed_auto_paste_setting_is_not_retained(self):
        self.config_path.write_text('{"auto_paste_meme": true}', encoding="utf-8")

        cfg = Config(self.config_path)

        self.assertNotIn("auto_paste_meme", cfg.to_dict())
        cfg.save()
        self.assertNotIn(
            "auto_paste_meme", self.config_path.read_text(encoding="utf-8")
        )

    def test_property_access(self):
        cfg = Config(self.config_path)
        cfg.auto_start = True
        self.assertTrue(cfg.auto_start)

    def test_cache_dir_default_empty(self):
        cfg = Config(self.config_path)
        self.assertEqual(cfg.get("cache_dir"), "")

    def test_cache_dir_custom(self):
        cfg = Config(self.config_path)
        custom = self.tmp_dir / "my_memes"
        cfg.set("cache_dir", str(custom))
        self.assertEqual(cfg.cache_dir, custom)
        self.assertTrue(custom.exists())
        cfg.save()
        cfg2 = Config(self.config_path)
        self.assertEqual(cfg2.cache_dir, custom)

    def test_cache_dir_resolve(self):
        cfg = Config(self.config_path)
        raw = self.tmp_dir / "a" / ".." / "my_memes"
        cfg.set("cache_dir", str(raw))
        self.assertEqual(cfg.cache_dir, (self.tmp_dir / "my_memes").resolve())
        self.assertTrue((self.tmp_dir / "my_memes").exists())


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.db_path = self.tmp_dir / "test.db"
        self.db = MemeDB(self.db_path)

    def tearDown(self):
        self.db.close()
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_add_meme(self):
        mid = self.db.add_meme("test.png", file_hash="abc123", width=100, height=200)
        self.assertIsNotNone(mid)
        meme = self.db.get_by_id(mid)
        self.assertEqual(meme["filename"], "test.png")
        self.assertEqual(meme["file_hash"], "abc123")

    def test_delete_meme(self):
        mid = self.db.add_meme("test.png")
        self.db.delete_meme(mid)
        self.assertIsNone(self.db.get_by_id(mid))

    def test_delete_memes(self):
        m1 = self.db.add_meme("a.png", tags=["shared", "only1"])
        m2 = self.db.add_meme("b.png", tags=["shared"])
        m3 = self.db.add_meme("c.png", tags=["only2"])
        cid = self.db.create_collection("g")
        self.db.add_to_collection(m1, cid)
        self.db.toggle_favorite(m2)
        self.db.delete_memes([m1, m2])
        self.assertIsNone(self.db.get_by_id(m1))
        self.assertIsNone(self.db.get_by_id(m2))
        self.assertIsNotNone(self.db.get_by_id(m3))
        # 孤儿标签一次性修剪
        self.assertEqual(set(self.db.get_all_tags()), {"only2"})
        # 外键级联清理分组成员关系
        rows = self.db._get_conn().execute(
            "SELECT 1 FROM meme_collections WHERE meme_id=?", (m1,)
        ).fetchall()
        self.assertEqual(len(rows), 0)
        self.assertFalse(self.db.is_favorite(m2))

    def test_delete_memes_empty_list(self):
        self.db.delete_memes([])  # 空列表不炸

    def test_search(self):
        self.db.add_meme("cat.png", tags=["cat", "funny"])
        self.db.add_meme("dog.png", tags=["dog"])
        self.db.add_meme("cat_dog.png", tags=["cat", "dog"])

        results = self.db.search(keyword="cat")
        self.assertEqual(len(results), 2)

        results = self.db.search(tags=["cat"])
        self.assertEqual(len(results), 2)

        results = self.db.search(keyword="dog")
        self.assertEqual(len(results), 2)

    def test_search_keyword_matches_tag(self):
        self.db.add_meme("img1.png", tags=["小猫"])
        self.db.add_meme("img2.png", tags=["小狗"])
        # 搜索词命中标签名也能搜到
        results = self.db.search(keyword="小猫")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["filename"], "img1.png")
        self.assertEqual(self.db.count(keyword="小狗"), 1)
        self.assertEqual(self.db.count(keyword="不存在的标签"), 0)

    def test_add_tags_to_memes_merge(self):
        mid1 = self.db.add_meme("a.png", tags=["old"])
        mid2 = self.db.add_meme("b.png")
        count = self.db.add_tags_to_memes([mid1, mid2], ["new", " old "])
        self.assertEqual(count, 2)
        self.assertEqual(set(self.db.get_meme_tags(mid1)), {"old", "new"})
        self.assertEqual(set(self.db.get_meme_tags(mid2)), {"old", "new"})
        self.assertEqual(set(self.db.get_all_tags()), {"old", "new"})
        # 空参数不产生变更
        self.assertEqual(self.db.add_tags_to_memes([], ["x"]), 0)
        self.assertEqual(self.db.add_tags_to_memes([mid1], []), 0)
        self.assertEqual(self.db.add_tags_to_memes([mid1], ["  "]), 0)

    def test_tags(self):
        mid = self.db.add_meme("test.png", tags=["a", "b", "c"])
        tags = self.db.get_meme_tags(mid)
        self.assertEqual(set(tags), {"a", "b", "c"})

        self.db.set_meme_tags(mid, ["x", "y"])
        tags = self.db.get_meme_tags(mid)
        self.assertEqual(set(tags), {"x", "y"})

    def test_tags_prune_orphans(self):
        mid1 = self.db.add_meme("a.png", tags=["shared", "only1"])
        mid2 = self.db.add_meme("b.png", tags=["shared"])
        # mid1 换成新标签：only1 成为孤儿被清理，shared 仍被 mid2 使用
        self.db.set_meme_tags(mid1, ["other"])
        self.assertEqual(set(self.db.get_all_tags()), {"shared", "other"})
        # 删除 mid2：shared 成为孤儿被清理
        self.db.delete_meme(mid2)
        self.assertEqual(self.db.get_all_tags(), ["other"])

    def test_favorites(self):
        mid = self.db.add_meme("test.png")
        self.assertFalse(self.db.is_favorite(mid))
        self.db.toggle_favorite(mid)
        self.assertTrue(self.db.is_favorite(mid))
        self.db.toggle_favorite(mid)
        self.assertFalse(self.db.is_favorite(mid))

    def test_collections(self):
        mid = self.db.add_meme("test.png")
        cid = self.db.create_collection("my_collection")
        self.db.add_to_collection(mid, cid)

        results = self.db.search(collection_id=cid)
        self.assertEqual(len(results), 1)

        collections = self.db.get_collections()
        self.assertEqual(len(collections), 1)

    def test_collection_member_reorder(self):
        # 分组内拖拽排序：按 meme_collections.sort_order 生效
        mid1 = self.db.add_meme("a.png")
        mid2 = self.db.add_meme("b.png")
        mid3 = self.db.add_meme("c.png")
        cid = self.db.create_collection("group")
        for m in (mid1, mid2, mid3):
            self.db.add_to_collection(m, cid)

        self.db.reorder_collection_members(cid, [mid3, mid1, mid2])
        results = self.db.search(collection_id=cid)
        self.assertEqual([r["id"] for r in results], [mid3, mid1, mid2])

        # 子分组独立排序，不影响父分组
        sub = self.db.create_collection("sub", cid)
        self.db.add_to_collection(mid2, sub)
        self.db.add_to_collection(mid3, sub)
        self.db.reorder_collection_members(sub, [mid3, mid2])
        parent_results = self.db.search(collection_id=cid)
        self.assertEqual([r["id"] for r in parent_results], [mid3, mid1, mid2])
        sub_results = self.db.search(collection_id=sub)
        self.assertEqual([r["id"] for r in sub_results], [mid3, mid2])

    def test_global_reorder_independent_of_collection(self):
        # 全局拖拽排序不受分组排序影响
        mid1 = self.db.add_meme("a.png")
        mid2 = self.db.add_meme("b.png")
        cid = self.db.create_collection("group")
        self.db.add_to_collection(mid1, cid)
        self.db.add_to_collection(mid2, cid)
        self.db.reorder_collection_members(cid, [mid2, mid1])
        self.db.reorder_memes([mid1, mid2])
        results = self.db.search()
        self.assertEqual([r["id"] for r in results], [mid1, mid2])

    def test_hash_dedup(self):
        mid1 = self.db.add_meme("a.png", file_hash="hash1")
        mid2 = self.db.add_meme("b.png", file_hash="hash1")
        # 允许重复hash入库，但上层应用应去重
        self.assertIsNotNone(mid1)
        self.assertIsNotNone(mid2)

    def test_empty_search(self):
        results = self.db.search()
        self.assertEqual(len(results), 0)
        self.assertEqual(self.db.count(), 0)


class TestHotkeyWatchdog(unittest.TestCase):
    """GlobalHotkey 键盘监听线程守护：自动重注册逻辑（mock keyboard 模块）"""

    def _fake_keyboard_module(self, should_raise=False):
        class FakeModule(object):
            add_raises = False
            add_calls = 0
            remove_calls = 0

            @classmethod
            def add_hotkey(cls, *a, **kw):
                cls.add_calls += 1
                if cls.add_raises:
                    raise RuntimeError("inject-fail")

            @classmethod
            def remove_hotkey(cls, *a, **kw):
                cls.remove_calls += 1

        if should_raise:
            FakeModule.add_raises = True
        return FakeModule

    @mock.patch.dict("sys.modules", {"keyboard": None}, clear=False)
    def test_reregister_restarts_listener_and_reattaches(self):
        from src.hotkey import GlobalHotkey

        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0
        fake_mod.remove_calls = 0

        class FakeListener(object):
            listening = True
            start_calls = 0

            def start_if_necessary(self):
                self.start_calls += 1

        listener = FakeListener()

        hk = GlobalHotkey()
        hk._hotkey = "Ctrl+Alt+N"
        hk._safe_callback = lambda: None
        hk._backend = "keyboard"
        hk._watchdog_stop = threading.Event()  # 模拟守护已启动

        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            ok = hk._reregister_keyboard(listener)

        self.assertTrue(ok)
        self.assertFalse(hk._reregister_pending)
        self.assertEqual(fake_mod.remove_calls, 1)
        self.assertEqual(listener.start_calls, 1)
        self.assertFalse(listener.listening)
        self.assertEqual(fake_mod.add_calls, 1)

    @mock.patch.dict("sys.modules", {"keyboard": None}, clear=False)
    def test_reregister_add_failure_sets_pending_and_not_success(self):
        """重注册 add_hotkey 失败：返回 False、置 pending，绝不记录成功/停止重试。"""
        from src.hotkey import GlobalHotkey

        fake_mod = self._fake_keyboard_module(should_raise=True)
        fake_mod.add_calls = 0
        fake_mod.remove_calls = 0

        class FakeListener(object):
            listening = True
            start_calls = 0

            def start_if_necessary(self):
                self.start_calls += 1

        hk = GlobalHotkey()
        hk._hotkey = "Ctrl+Alt+N"
        hk._safe_callback = lambda: None
        hk._backend = "keyboard"
        hk._watchdog_stop = threading.Event()

        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            ok = hk._reregister_keyboard(FakeListener())

        self.assertFalse(ok)
        self.assertTrue(hk._reregister_pending)  # 守护下轮会继续重试

    @mock.patch.dict("sys.modules", {"keyboard": None}, clear=False)
    def test_reregister_after_unregister_does_not_add(self):
        """注销后重注册不得重新挂热键（同锁 + 停止标志/回调清空兜底）。"""
        from src.hotkey import GlobalHotkey

        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0
        fake_mod.remove_calls = 0

        class FakeListener(object):
            listening = True

            def start_if_necessary(self):
                pass

        hk = GlobalHotkey()
        hk._hotkey = "Ctrl+Alt+N"
        hk._safe_callback = lambda: None
        hk._backend = "keyboard"

        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            # 1) 已注销：watchdog_stop 置位后 unregister 清空回调
            hk._watchdog_stop = threading.Event()
            hk.unregister()  # stop.set() + _safe_callback=None
            # 2) 守护线程若此刻想重注册，应直接返回 False 且不再 add
            ok = hk._reregister_keyboard(FakeListener())

        self.assertFalse(ok)
        self.assertEqual(fake_mod.add_calls, 0)  # 注销后不得重新挂热键

    @mock.patch.dict("sys.modules", {"keyboard": None}, clear=False)
    def test_stale_generation_cannot_touch_after_reregister(self):
        """注销后重新注册：旧代次 watchdog 的重注册操作不得作用到新生命周期。"""
        from src.hotkey import GlobalHotkey

        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0

        class FakeListener(object):
            listening = True

            def start_if_necessary(self):
                pass

        hk = GlobalHotkey()
        hk._backend = "keyboard"
        hk._hotkey = "Ctrl+Alt+N"

        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            # 第一次注册（代次 0）→ 注销（代次 -> 1）→ 立即重新注册（新代次 1）
            hk._watchdog_stop = threading.Event()
            hk.unregister()
            old_gen = 0  # 旧 watchdog 捕获的代次
            # 重新注册：赋新回调并启动新守护（当前代次已是 1）
            hk._safe_callback = lambda: None
            self.assertEqual(hk._watchdog_gen, 1)
            # 旧代次 watchdog 调重注册：应被拒，不得 add
            stale = hk._reregister_keyboard(FakeListener(), gen=old_gen)
            self.assertFalse(stale)
            self.assertEqual(fake_mod.add_calls, 0)
            # 新代次（当前 gen）可以正常重注册
            fresh = hk._reregister_keyboard(FakeListener(), gen=hk._watchdog_gen)
            self.assertTrue(fresh)
            self.assertEqual(fake_mod.add_calls, 1)

    @mock.patch.dict("sys.modules", {"keyboard": None}, clear=False)
    def test_unregister_stops_watchdog(self):
        from src.hotkey import GlobalHotkey

        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0

        hk = GlobalHotkey()
        hk._backend = "keyboard"
        hk._hotkey = "Ctrl+Alt+N"
        hk._safe_callback = lambda: None

        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            stop = mock.MagicMock()
            hk._watchdog_stop = stop
            hk.unregister()

        # watchdog 应被停止，safe_callback 清空，remove_hotkey 被调用
        stop.set.assert_called_once()
        self.assertIsNone(hk._watchdog_stop)
        self.assertIsNone(hk._safe_callback)
        self.assertEqual(fake_mod.remove_calls, 1)


if __name__ == "__main__":
    unittest.main()
