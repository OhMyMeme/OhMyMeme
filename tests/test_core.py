"""OhMyMeme 核心模块测试"""

import re
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_save_replace_failure_preserves_original_bytes_and_cleans_temp(self):
        self.config_path.write_bytes(b'{"hotkey":"old"}\n')
        cfg = Config(self.config_path)
        cfg.set("hotkey", "new")

        with patch("src.config.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                cfg.save()

        self.assertEqual(self.config_path.read_bytes(), b'{"hotkey":"old"}\n')
        self.assertFalse(self.config_path.with_name("config.json.tmp").exists())
        self.assertTrue(cfg._dirty)

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

    def test_add_meme_tag_failure_rolls_back_meme(self):
        original = self.db._set_tags

        def fail_tags(conn, meme_id, tags):
            original(conn, meme_id, tags)
            raise sqlite3.OperationalError("tags disk full")

        with patch.object(self.db, "_set_tags", side_effect=fail_tags):
            with self.assertRaises(sqlite3.OperationalError):
                self.db.add_meme("partial.png", tags=["broken"])

        self.assertIsNone(self.db.get_by_filename("partial.png"))
        self.assertEqual(self.db.get_all_tags(), [])

    def test_init_db_raises_for_non_duplicate_migration_error(self):
        db_path = self.tmp_dir / "broken-migration.db"
        original_connect = sqlite3.connect

        class BrokenConnection:
            def __init__(self, connection):
                self.connection = connection

            def execute(self, sql, *args):
                if sql.startswith("ALTER TABLE"):
                    raise sqlite3.OperationalError("database disk image is malformed")
                return self.connection.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self.connection, name)

        with patch(
            "src.database.sqlite3.connect",
            side_effect=lambda *args, **kwargs: BrokenConnection(
                original_connect(*args, **kwargs)
            ),
        ):
            with self.assertRaisesRegex(sqlite3.OperationalError, "malformed"):
                MemeDB(db_path)

    def test_empty_search(self):
        results = self.db.search()
        self.assertEqual(len(results), 0)
        self.assertEqual(self.db.count(), 0)


if __name__ == "__main__":
    unittest.main()
