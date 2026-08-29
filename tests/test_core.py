"""OhMyMeme 核心模块测试"""

import re
import sys
import tempfile
import threading
import time
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
        rows = (
            self.db._get_conn()
            .execute("SELECT 1 FROM meme_collections WHERE meme_id=?", (m1,))
            .fetchall()
        )
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

    def test_add_tags_to_memes_missing_ids(self):
        # 混合有效与不存在的 id：只对存在的表情生效，不抛异常、不部分写入
        mid = self.db.add_meme("a.png")
        count = self.db.add_tags_to_memes([mid, 99999], ["t1"])
        self.assertEqual(count, 1)
        self.assertEqual(set(self.db.get_meme_tags(mid)), {"t1"})
        self.assertEqual(set(self.db.get_all_tags()), {"t1"})
        # 全部 id 不存在：返回 0 且不产生任何标签
        self.assertEqual(self.db.add_tags_to_memes([88888, 99999], ["t2"]), 0)
        self.assertEqual(set(self.db.get_all_tags()), {"t1"})

    def test_add_memes_to_collection_batch(self):
        mid1 = self.db.add_meme("a.png")
        mid2 = self.db.add_meme("b.png")
        cid = self.db.create_collection("g")
        # 混合有效与不存在的 id：只对存在的表情生效
        count = self.db.add_memes_to_collection([mid1, mid2, 99999], cid)
        self.assertEqual(count, 2)
        self.assertEqual(len(self.db.search(collection_id=cid)), 2)
        # 重复加入同一分组：不产生重复关联，计数为 0
        self.assertEqual(self.db.add_memes_to_collection([mid1], cid), 0)
        self.assertEqual(len(self.db.search(collection_id=cid)), 2)
        # 目标分组不存在：抛异常且不产生部分写入
        with self.assertRaises(ValueError):
            self.db.add_memes_to_collection([mid1], 424242)
        self.assertEqual(len(self.db.search(collection_id=cid)), 2)

    def test_move_memes_to_collection_scope_and_dedup(self):
        mid1 = self.db.add_meme("a.png")  # 属于源分组
        mid2 = self.db.add_meme("b.png")  # 不属于源分组，仅属于其他分组
        mid3 = self.db.add_meme("c.png")  # 属于源分组且已在目标分组
        src = self.db.create_collection("src")
        other = self.db.create_collection("other")
        target = self.db.create_collection("t")
        self.db.add_to_collection(mid1, src)
        self.db.add_to_collection(mid3, src)
        self.db.add_to_collection(mid3, target)
        self.db.add_to_collection(mid2, other)

        moved = self.db.move_memes_to_collection([mid1, mid2, mid3], [src], target)
        # 仅 mid1 实际新增目标关联；mid3 重复加入不计；mid2 非源成员不受影响
        self.assertEqual(moved, 1)
        self.assertEqual(self.db.search(collection_id=src), [])
        self.assertEqual(len(self.db.search(collection_id=target)), 2)
        self.assertEqual(len(self.db.search(collection_id=other)), 1)

    def test_move_cascades_empty_group_cleanup(self):
        mid1 = self.db.add_meme("a.png")
        mid2 = self.db.add_meme("b.png")
        parent = self.db.create_collection("p")
        child = self.db.create_collection("c", parent_id=parent)
        keep = self.db.create_collection("keep")  # 源子树外的空分组
        target = self.db.create_collection("t")
        self.db.add_to_collection(mid1, child)
        self.db.add_to_collection(mid2, parent)

        moved = self.db.move_memes_to_collection([mid1, mid2], [parent, child], target)
        self.assertEqual(moved, 2)
        # 源子树内 child 先空、parent 后空，级联清理；子树外的空分组保留
        ids = {c[0] for c in self.db.get_collections()}
        self.assertEqual(ids, {target, keep})

    def test_move_memes_to_collection_batch(self):
        mid1 = self.db.add_meme("a.png")
        mid2 = self.db.add_meme("b.png")  # 仅属于子分组
        parent = self.db.create_collection("p")
        child = self.db.create_collection("c", parent_id=parent)
        self.db.add_to_collection(mid1, parent)
        self.db.add_to_collection(mid2, child)
        target = self.db.create_collection("t")
        # 从源子树整体移出：仅属于子分组的成员也会被移走
        count = self.db.move_memes_to_collection(
            [mid1, mid2, 99999], [parent, child], target
        )
        self.assertEqual(count, 2)
        self.assertEqual(self.db.search(collection_id=parent), [])
        self.assertEqual(self.db.search(collection_id=child), [])
        self.assertEqual(len(self.db.search(collection_id=target)), 2)
        # 目标分组不存在：抛异常且不产生部分写入
        with self.assertRaises(ValueError):
            self.db.move_memes_to_collection([mid1], [parent], 424242)
        self.assertEqual(len(self.db.search(collection_id=target)), 2)

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

    def _fake_keyboard_module(self, should_raise=False, hook_raises=False):
        class FakeModule(object):
            add_raises = False
            hook_raises = False
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

            @classmethod
            def hook(cls, *a, **kw):
                if cls.hook_raises:
                    raise RuntimeError("hook-fail")

            @classmethod
            def unhook(cls, *a, **kw):
                pass

        FakeModule.add_raises = should_raise
        FakeModule.hook_raises = hook_raises
        return FakeModule

    @mock.patch.dict("sys.modules", {"keyboard": None}, clear=False)
    def test_file_logger_disabled_under_pytest(self):
        """pytest 下禁用热键文件日志，测试夹具错误不得写入真实 hotkey.log。"""
        from src import hotkey

        self.assertIs(hotkey._get_file_logger(), hotkey.logger)

    def _fresh_hotkey(self):
        from src.hotkey import GlobalHotkey

        hk = GlobalHotkey()
        hk._hotkey = "Ctrl+Alt+N"
        hk._safe_callback = lambda: None
        hk._backend = "keyboard"
        hk._watchdog_stop = threading.Event()
        hk._hook_last_seen = 0.0
        hk._last_probe_at = 0.0
        hk._probe_pending_at = None
        hk._hook_observer = lambda event: None  # 模拟观察者已注册
        return hk

    def test_hook_health_check_probe_timeout_detects_dead_hook(self):
        """探针注入后超时未见任何键盘事件判死；用户按键即视为存活。"""
        from src.hotkey import KEYBOARD_PROBE_TIMEOUT

        hk = self._fresh_hotkey()
        calls = []
        hk._inject_probe_key = lambda: calls.append(1)

        # 第一轮：注入探针，待确认
        self.assertFalse(hk._hook_health_check(now=100.0))
        self.assertEqual(len(calls), 1)
        self.assertEqual(hk._probe_pending_at, 100.0)
        # 用户按键（或探针事件）上报 → 存活
        hk._hook_last_seen = 100.5
        self.assertFalse(hk._hook_health_check(now=105.0))
        self.assertIsNone(hk._probe_pending_at)
        # 距上次探针满间隔再次注入
        self.assertFalse(hk._hook_health_check(now=130.0))
        self.assertEqual(len(calls), 2)
        # 注入后超时无任何事件 → 判死
        hk._hook_last_seen = 0.0
        self.assertTrue(hk._hook_health_check(now=130.0 + KEYBOARD_PROBE_TIMEOUT))
        self.assertIsNone(hk._probe_pending_at)

    def test_restart_keyboard_listener_reinstalls_hook(self):
        """钩子失效重启：结束旧线程→重装钩子→重挂热键；成功后清 pending。"""
        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0
        fake_mod.remove_calls = 0

        class FakeThread(object):
            def is_alive(self):
                return False

        class FakeListener(object):
            listening = True
            listening_thread = FakeThread()
            started = False

            def start_if_necessary(self):
                self.started = True

        hk = self._fresh_hotkey()
        hk._reregister_pending = True  # 此前一次重启失败遗留
        hk._kill_listening_thread = lambda listener: None

        listener = FakeListener()
        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            ok = hk._restart_keyboard_listener(listener)

        self.assertTrue(ok)
        self.assertFalse(hk._reregister_pending)
        self.assertEqual(fake_mod.remove_calls, 1)
        self.assertTrue(listener.started)
        self.assertEqual(fake_mod.add_calls, 1)

    def test_restart_keyboard_listener_keeps_healthy_processing_thread(self):
        """处理线程健康时仅替换监听线程，不产生重复的事件消费者。"""
        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0
        fake_mod.remove_calls = 0

        class FakeThread(object):
            def __init__(self, alive):
                self._alive = alive

            def is_alive(self):
                return self._alive

        class FakeListener(object):
            listening = True
            listening_thread = FakeThread(False)  # kill 之后的残留状态
            processing_thread = FakeThread(True)
            started = False
            listened = False

            def start_if_necessary(self):
                self.started = True

            def listen(self):
                self.listened = True

        hk = self._fresh_hotkey()
        hk._kill_listening_thread = lambda listener: None
        original_pt = FakeListener.processing_thread

        listener = FakeListener()
        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            ok = hk._restart_keyboard_listener(listener)
            if listener.listening_thread is not None:
                listener.listening_thread.join(timeout=2)

        self.assertTrue(ok)
        self.assertFalse(listener.started)  # 未走 start_if_necessary
        self.assertTrue(listener.listening)
        self.assertTrue(listener.listened)  # 新监听线程已启动
        # 原处理线程对象被保留（未新建重复消费者）
        self.assertIs(listener.processing_thread, original_pt)
        self.assertEqual(fake_mod.add_calls, 1)

    @mock.patch.dict("sys.modules", {"keyboard": None}, clear=False)
    @mock.patch("sys.platform", "win32")
    def test_try_keyboard_hook_failure_degrades_gracefully(self):
        """hook 观察者注册失败：保留 keyboard 后端仅降级心跳，不回落 pynput
        造成双后端重复触发。"""
        from src.hotkey import GlobalHotkey

        fake_mod = self._fake_keyboard_module(hook_raises=True)
        hk = GlobalHotkey()
        try:
            with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
                ok = hk._try_keyboard("Ctrl+Alt+N", lambda: None)

            self.assertTrue(ok)
            self.assertEqual(hk._backend, "keyboard")
            self.assertIsNone(hk._hook_observer)
            self.assertEqual(fake_mod.add_calls, 1)
        finally:
            hk.unregister()

    def test_hook_health_check_disabled_without_observer(self):
        """降级模式（观察者未注册）下不注入探针、不判死，避免误判重启循环。"""
        hk = self._fresh_hotkey()
        hk._hook_observer = None
        calls = []
        hk._inject_probe_key = lambda: calls.append(1)

        self.assertFalse(hk._hook_health_check(now=1000.0))
        self.assertEqual(calls, [])
        self.assertIsNone(hk._probe_pending_at)

    def test_reregister_listening_only_death_starts_listen_thread(self):
        """仅监听线程死亡：保留处理线程，单独启动新监听线程（不重建存活线程）。"""
        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0
        fake_mod.remove_calls = 0

        class FakeThread(object):
            def __init__(self, alive):
                self._alive = alive

            def is_alive(self):
                return self._alive

        class FakeListener(object):
            listening = True
            listening_thread = FakeThread(False)  # 仅监听线程死亡
            processing_thread = FakeThread(True)  # 处理线程存活
            restarted = False
            listened = False

            def start_if_necessary(self):
                self.restarted = True

            def listen(self):
                self.listened = True

        hk = self._fresh_hotkey()
        original_pt = FakeListener.processing_thread

        listener = FakeListener()
        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            ok = hk._reregister_keyboard(listener)
            listener.listening_thread.join(timeout=2)

        self.assertTrue(ok)
        self.assertFalse(listener.restarted)  # 未全量重启
        self.assertTrue(listener.listened)  # 单独启动了新监听线程
        self.assertIs(listener.processing_thread, original_pt)  # 处理线程保留
        self.assertEqual(fake_mod.add_calls, 1)

    def test_reregister_processing_only_death_starts_process_thread(self):
        """仅处理线程死亡：保留监听线程（钩子仍在），单独启动新处理线程。"""
        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0
        fake_mod.remove_calls = 0

        class FakeThread(object):
            def __init__(self, alive):
                self._alive = alive

            def is_alive(self):
                return self._alive

        class FakeListener(object):
            listening = True
            listening_thread = FakeThread(True)  # 监听线程存活（钩子仍在）
            processing_thread = FakeThread(False)  # 仅处理线程死亡
            restarted = False
            processed = False

            def start_if_necessary(self):
                self.restarted = True

            def process(self):
                self.processed = True

        hk = self._fresh_hotkey()
        original_lt = FakeListener.listening_thread

        listener = FakeListener()
        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            ok = hk._reregister_keyboard(listener)
            listener.processing_thread.join(timeout=2)

        self.assertTrue(ok)
        self.assertFalse(listener.restarted)  # 未全量重启（避免双钩子）
        self.assertTrue(listener.processed)  # 单独启动了新处理线程
        self.assertIs(listener.listening_thread, original_lt)  # 监听线程未重建
        self.assertEqual(fake_mod.add_calls, 1)

    def test_watchdog_tick_retries_pending_reregistration(self):
        """add_hotkey 失败置 pending 后，看门狗轮询必须重试（否则热键永久失效）。"""
        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0
        fake_mod.remove_calls = 0

        class FakeThread(object):
            def is_alive(self):
                return True

        class FakeListener(object):
            listening = True
            listening_thread = FakeThread()  # 线程已补齐：pending 场景的常态
            processing_thread = FakeThread()

        hk = self._fresh_hotkey()
        hk._reregister_pending = True  # 上轮 add_hotkey 失败遗留

        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            hk._watchdog_tick(FakeListener(), hk._watchdog_gen)

        self.assertFalse(hk._reregister_pending)  # 重试成功
        self.assertEqual(fake_mod.add_calls, 1)

    def test_watchdog_tick_healthy_state_is_noop(self):
        """线程存活、无 pending、观察者存活时单轮检查不做任何动作。"""
        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0

        class FakeThread(object):
            def is_alive(self):
                return True

        class FakeListener(object):
            listening = True
            listening_thread = FakeThread()
            processing_thread = FakeThread()

        hk = self._fresh_hotkey()
        hk._reregister_pending = False
        # 模拟刚注入过探针：间隔未满，不应再次注入
        hk._last_probe_at = time.monotonic()
        probe_calls = []
        hk._inject_probe_key = lambda: probe_calls.append(1)

        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            hk._watchdog_tick(FakeListener(), hk._watchdog_gen)

        self.assertEqual(fake_mod.add_calls, 0)
        # 探针在间隔未满时不注入（刚注册不久）
        self.assertEqual(probe_calls, [])

    def test_restart_keyboard_listener_failure_sets_pending(self):
        """旧监听线程无法退出时中止重启（避免双钩子），置 pending 待下轮重试。"""
        fake_mod = self._fake_keyboard_module()
        fake_mod.add_calls = 0
        fake_mod.remove_calls = 0

        class FakeThread(object):
            def is_alive(self):
                return True

        class FakeListener(object):
            listening = True
            listening_thread = FakeThread()

            def start_if_necessary(self):
                raise AssertionError("不应重装钩子")

        hk = self._fresh_hotkey()

        def refuse(listener):
            raise RuntimeError("旧监听线程未能退出")

        hk._kill_listening_thread = refuse

        with mock.patch.dict("sys.modules", {"keyboard": fake_mod}):
            ok = hk._restart_keyboard_listener(FakeListener())

        self.assertFalse(ok)
        self.assertTrue(hk._reregister_pending)
        self.assertEqual(fake_mod.add_calls, 0)

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
