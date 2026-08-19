"""OhMyMeme 核心模块测试"""

import base64
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 确保 src 在导入路径中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import __app_name__, __version__, ai_util, chat_client, manifest, webui
from src.config import Config
from src.crypto_util import decrypt_data, encrypt_data
from src.database import MemeDB


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class TestAiUtil(unittest.TestCase):
    @patch("src.ai_util.urllib.request.urlopen")
    def test_image_edit_posts_multipart_and_parses_url(self, urlopen):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "source.png"
            image_path.write_bytes(b"image-bytes")
            urlopen.return_value = _FakeResponse(
                {"data": [{"url": "https://example.com/edited.png"}]}
            )
            result = ai_util.image_edit(
                "https://api.example.com/",
                "secret",
                "image-model",
                str(image_path),
                "加上墨镜",
            )

        self.assertEqual(result, {"url": "https://example.com/edited.png"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.example.com/v1/images/edits")
        self.assertIn(b'name="prompt"', request.data)
        self.assertIn("multipart/form-data", request.get_header("Content-type"))

    def test_image_edit_rejects_missing_file(self):
        with self.assertRaisesRegex(ValueError, "原始图片不存在"):
            ai_util.image_edit(
                "https://api.example.com",
                "secret",
                "image-model",
                "missing.png",
                "test",
            )

    @patch("src.ai_util.urllib.request.urlopen")
    def test_image_generation_posts_expected_payload_and_parses_base64(self, urlopen):
        urlopen.return_value = _FakeResponse(
            {"data": [{"b64_json": "aW1hZ2UtYnl0ZXM="}]}
        )

        result = ai_util.image_generation(
            "https://api.example.com/", "secret", "image-model", "猫猫表情"
        )

        self.assertEqual(result, {"b64": "aW1hZ2UtYnl0ZXM="})
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://api.example.com/v1/images/generations"
        )
        self.assertEqual(
            json.loads(request.data),
            {
                "model": "image-model",
                "prompt": "猫猫表情",
                "n": 1,
                "size": "1024x1024",
            },
        )


class TestAiWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.db = MemeDB(self.tmp_dir / "memes.db")
        self.meme_id = self.db.add_meme("meme.png", file_hash="workflow-hash")
        self.previous_suggestions = webui._AI_SUGGESTIONS
        webui._AI_SUGGESTIONS = {}

    def tearDown(self):
        self.db.close()
        webui._AI_SUGGESTIONS = self.previous_suggestions
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_ai_suggestions_apply_only_after_confirmation(self):
        api = object.__new__(webui.JsApi)
        api._db = self.db
        task_id = "test-task"
        webui._AI_SUGGESTIONS[task_id] = {
            str(self.meme_id): {
                "id": self.meme_id,
                "tags": ["开心", "猫猫"],
                "collection": "日常",
                "description": "开心的猫",
                "ocr_text": "好耶",
            }
        }

        with patch("src.webui.get_db", return_value=self.db), patch(
            "src.webui.build_manifest"
        ) as build:
            result = api.apply_ai_suggestions(task_id)

        self.assertEqual(result, {"ok": True, "applied": 1})
        self.assertEqual(set(self.db.get_meme_tags(self.meme_id)), {"开心", "猫猫"})
        self.assertEqual(self.db.get_by_id(self.meme_id)["ai_description"], "开心的猫")
        self.assertEqual(self.db.get_by_id(self.meme_id)["ai_ocr_text"], "好耶")
        collection_id = self.db.get_collections()[0][0]
        self.assertEqual(
            self.db.search(collection_id=collection_id)[0]["id"], self.meme_id
        )
        self.assertEqual(webui._AI_SUGGESTIONS[task_id], {})
        build.assert_called_once()

    def test_ai_pending_filter_includes_categorized_incomplete_memes(self):
        collection_id = self.db.create_collection("已分组")
        self.db.add_to_collection(self.meme_id, collection_id)
        self.assertEqual(
            [m["id"] for m in self.db.search(ai_pending_only=True)], [self.meme_id]
        )
        self.db.update_meme(self.meme_id, ai_description="猫咪表情", ai_ocr_text="好耶")
        self.db.set_meme_tags(self.meme_id, ["开心"])
        self.assertEqual(self.db.search(ai_pending_only=True), [])

    def test_ai_generate_imports_through_api_webui(self):
        class FakeConfig:
            def get(self, key, default=""):
                values = {
                    "ai_image_base_url": "https://api.example.com",
                    "ai_image_api_key": "secret",
                    "ai_image_model": "image-model",
                }
                return values.get(key, default)

        class FakeWindow:
            def __init__(self):
                self.paths = []

            def _do_import(self, paths):
                self.paths.extend(paths)
                self.assertTrue(all(Path(path).is_file() for path in paths))
                return {"ids": [101], "rejected": 0}

            def assertTrue(self, value):
                if not value:
                    raise AssertionError("临时图片应在导入前存在")

        class FakeApi:
            def __init__(self):
                self._webui = FakeWindow()

        old_state = dict(webui._AI_STATE)
        old_cancel = webui._AI_CANCEL
        api = FakeApi()
        png = base64.b64encode(b"\x89PNG\r\n\x1a\nmock").decode("ascii")
        try:
            with patch("src.webui.get_config", return_value=FakeConfig()), patch(
                "src.webui.ai_util.image_generation", return_value={"b64": png}
            ):
                webui._AI_CANCEL = False
                webui._ai_generate_worker(api, "测试", 1)
            self.assertEqual(webui._AI_STATE["status"], "done")
            self.assertEqual(webui._AI_STATE["message"], "生成并导入 1 张")
            self.assertEqual(len(api._webui.paths), 1)
            self.assertFalse(Path(api._webui.paths[0]).exists())
        finally:
            webui._AI_STATE.clear()
            webui._AI_STATE.update(old_state)
            webui._AI_CANCEL = old_cancel

    def test_ai_generate_reports_missing_api_importer(self):
        with self.assertRaisesRegex(RuntimeError, "AI 图片导入器不可用"):
            webui._import_ai_temp_files(object(), [])

    def test_pack_path_validation_rejects_traversal(self):
        api = object.__new__(webui.JsApi)

        self.assertTrue(api._safe_pack_member("images/0.png"))
        self.assertFalse(api._safe_pack_member("../config.json"))
        self.assertFalse(api._safe_pack_member("/absolute.png"))

    def test_ai_suggestion_discard_does_not_change_meme(self):
        api = object.__new__(webui.JsApi)
        api._db = self.db
        task_id = "discard-task"
        webui._AI_SUGGESTIONS[task_id] = {
            str(self.meme_id): {"id": self.meme_id, "tags": ["不应写入"]}
        }

        result = api.discard_ai_suggestions(task_id)

        self.assertEqual(result, {"ok": True, "discarded": 1})
        self.assertEqual(self.db.get_meme_tags(self.meme_id), [])
        self.assertNotIn(task_id, webui._AI_SUGGESTIONS)


class TestFolderApi(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.db = MemeDB(self.tmp_dir / "folders.db")
        self.api = object.__new__(webui.JsApi)
        self.api._db = self.db
        self.api._cfg = type(
            "FakeConfig", (), {"get": lambda _, key, default=None: default}
        )()
        self.first = self.db.add_meme("first.png")
        self.second = self.db.add_meme("second.png")

    def tearDown(self):
        self.db.close()
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_folder_copy_move_and_automatic_tag(self):
        with patch("src.webui.build_manifest"):
            first = self.api.create_folder("收藏图")
            second = self.api.create_folder("常用图")
            copied = self.api.add_to_folder(self.first, first["id"], "copy")
            moved = self.api.add_to_folder(self.first, second["id"], "move")

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertTrue(copied["ok"])
        self.assertTrue(moved["ok"])
        self.assertEqual(self.db.search(collection_id=first["id"]), [])
        self.assertEqual(
            [row["id"] for row in self.db.search(collection_id=second["id"])],
            [self.first],
        )
        self.assertEqual(set(self.db.get_meme_tags(self.first)), {"收藏图", "常用图"})

    def test_batch_move_replaces_all_memberships_atomically(self):
        with patch("src.webui.build_manifest") as build:
            source = self.api.create_folder("来源")
            target = self.api.create_folder("目标")
            self.assertTrue(
                self.api.batch_add_to_folder(
                    [self.first, self.second], source["id"], "copy"
                )["ok"]
            )
            result = self.api.batch_add_to_folder(
                [self.first, self.second], target["id"], "move"
            )

        self.assertEqual(result["count"], 2)
        self.assertEqual(result["mode"], "move")
        self.assertEqual(self.db.search(collection_id=source["id"]), [])
        self.assertEqual(
            {row["id"] for row in self.db.search(collection_id=target["id"])},
            {self.first, self.second},
        )
        self.assertEqual(set(self.db.get_meme_tags(self.first)), {"来源", "目标"})
        self.assertEqual(set(self.db.get_meme_tags(self.second)), {"来源", "目标"})
        self.assertEqual(build.call_count, 4)

    def test_folder_duplicate_remove_and_delete_preserve_meme_and_tags(self):
        with patch("src.webui.build_manifest"):
            folder = self.api.create_folder("表情")
            duplicate = self.api.create_folder("表情")
            self.assertTrue(
                self.api.add_to_folder(self.second, folder["id"], "copy")["ok"]
            )
            self.assertTrue(self.api.remove_from_folder(self.second, folder["id"]))
            self.assertTrue(
                self.api.add_to_folder(self.second, folder["id"], "copy")["ok"]
            )
            self.assertTrue(self.api.delete_folder(folder["id"]))

        self.assertFalse(duplicate["ok"])
        self.assertIsNotNone(self.db.get_by_id(self.second))
        self.assertEqual(self.db.get_meme_tags(self.second), ["表情"])
        self.assertEqual(self.db.search(collection_id=folder["id"]), [])

    def test_folder_list_flattens_legacy_nested_records(self):
        parent = self.db.create_collection("旧父级")
        child = self.db.create_collection("旧子级", parent)
        items = self.api._folder_items()

        self.assertEqual(
            {(item["id"], item["name"]) for item in items},
            {(parent, "旧父级"), (child, "旧子级")},
        )


class TestManifestFolders(unittest.TestCase):
    def test_manifest_collection_builder_is_flat(self):
        tmp_dir = Path(tempfile.mkdtemp())
        db = MemeDB(tmp_dir / "manifest.db")
        try:
            first = db.add_meme("first.png")
            parent = db.create_collection("父文件夹")
            child = db.create_collection("旧子文件夹", parent)
            db.add_to_collection(first, child)

            folders = manifest._build_folder_list(db)

            self.assertEqual(
                {item["name"]: item["filenames"] for item in folders},
                {"父文件夹": [], "旧子文件夹": ["first.png"]},
            )
        finally:
            db.close()
            import shutil

            shutil.rmtree(tmp_dir, ignore_errors=True)


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


class TestChatClient(unittest.TestCase):
    def test_native_drag_keeps_main_window_visible(self):
        source = Path(webui.__file__).read_text(encoding="utf-8")
        section = source.split("def start_native_drag", 1)[1].split("def copy_meme", 1)[
            0
        ]
        self.assertIn("return bool(_start(p))", section)
        self.assertNotIn("schedule_hide", section)

    def test_non_windows_requires_manual_paste(self):
        with patch("src.chat_client.os.name", "posix"):
            self.assertEqual(
                chat_client.capture_foreground_target("qq")["status"],
                "manual_paste_required",
            )
            self.assertEqual(
                chat_client.paste_to_target("qq", {"hwnd": 1})["status"],
                "manual_paste_required",
            )

    def test_ctrl_v_never_contains_enter(self):
        source = Path(chat_client.__file__).read_text(encoding="utf-8")
        section = source.split("def _send_ctrl_v", 1)[1].split(
            "def paste_to_target", 1
        )[0]
        self.assertIn("control = 0x11", section)
        self.assertIn("v_key = 0x56", section)
        self.assertNotIn("0x0D", section)
        self.assertNotIn("VK_RETURN", section)


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

    def test_chat_client_mode_persists_and_resets(self):
        cfg = Config(self.config_path)
        self.assertEqual(cfg.get("chat_client_mode"), "manual")
        cfg.set("chat_client_mode", "wechat")
        cfg.save()
        self.assertEqual(Config(self.config_path).get("chat_client_mode"), "wechat")
        cfg.reset()
        cfg.save()
        self.assertEqual(Config(self.config_path).get("chat_client_mode"), "manual")

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

    def test_ai_services_are_independent_and_encrypted(self):
        cfg = Config(self.config_path)
        cfg.set("ai_chat_base_url", "https://chat.example.com")
        cfg.set("ai_chat_api_key", "chat_secret")
        cfg.set("ai_chat_model", "vision-model")
        cfg.set("ai_organize_style", "anime")
        cfg.set("ai_image_base_url", "https://image.example.com")
        cfg.set("ai_image_api_key", "image_secret")
        cfg.set("ai_image_model", "image-model")
        cfg.save()

        loaded = Config(self.config_path)
        self.assertEqual(loaded.get("ai_chat_base_url"), "https://chat.example.com")
        self.assertEqual(loaded.get("ai_chat_api_key"), "chat_secret")
        self.assertEqual(loaded.get("ai_chat_model"), "vision-model")
        self.assertEqual(loaded.get("ai_organize_style"), "anime")
        self.assertEqual(loaded.get("ai_image_base_url"), "https://image.example.com")
        self.assertEqual(loaded.get("ai_image_api_key"), "image_secret")
        self.assertEqual(loaded.get("ai_image_model"), "image-model")
        self.assertNotEqual(loaded._data["ai_chat_api_key"], "chat_secret")
        self.assertNotEqual(loaded._data["ai_image_api_key"], "image_secret")

    def test_old_ai_service_config_migrates_to_both_services(self):
        self.config_path.write_text(
            '{"ai_base_url":"https://legacy.example.com",'
            '"ai_api_key":"legacy_secret","ai_chat_model":"vision-model",'
            '"ai_image_model":"image-model"}',
            encoding="utf-8",
        )

        cfg = Config(self.config_path)

        self.assertEqual(cfg.get("ai_chat_base_url"), "https://legacy.example.com")
        self.assertEqual(cfg.get("ai_image_base_url"), "https://legacy.example.com")
        self.assertEqual(cfg.get("ai_chat_api_key"), "legacy_secret")
        self.assertEqual(cfg.get("ai_image_api_key"), "legacy_secret")

    def test_ai_service_settings_survive_multiple_restarts(self):
        values = {
            "ai_chat_base_url": "https://chat.example.com/v1",
            "ai_chat_api_key": "chat-secret",
            "ai_chat_model": "vision-model",
            "ai_organize_style": "gaming",
            "ai_image_base_url": "https://image.example.com/v1",
            "ai_image_api_key": "image-secret",
            "ai_image_model": "image-model",
        }
        cfg = Config(self.config_path)
        cfg.update_from_dict(values)
        cfg.save()

        first_restart = Config(self.config_path)
        first_restart.save()
        second_restart = Config(self.config_path)

        for key, value in values.items():
            self.assertEqual(second_restart.get(key), value)

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

    def test_search_matches_tags_and_ai_description(self):
        tag_id = self.db.add_meme("plain.png", tags=["搞笑"])
        description_id = self.db.add_meme("other.png", ai_description="一只戴墨镜的猫")
        ocr_id = self.db.add_meme("ocr.png", ai_ocr_text="你好世界")

        self.assertEqual([r["id"] for r in self.db.search("搞笑")], [tag_id])
        self.assertEqual([r["id"] for r in self.db.search("墨镜")], [description_id])
        self.assertEqual([r["id"] for r in self.db.search("世界")], [ocr_id])
        self.assertEqual(self.db.count("猫"), 1)

    def test_batch_ai_metadata(self):
        first = self.db.add_meme("first.png")
        second = self.db.add_meme("second.png")
        self.db.update_ai_descriptions({first: "第一张", second: "第二张"})

        self.db.set_meme_ai_text(first, "更新描述", "识别文本")
        self.assertEqual(self.db.get_by_id(first)["ai_description"], "更新描述")
        self.assertEqual(self.db.get_by_id(first)["ai_ocr_text"], "识别文本")
        self.assertEqual(self.db.get_by_id(second)["ai_description"], "第二张")

    def test_old_database_migrates_search_metadata(self):
        self.db.close()
        self.db_path.unlink()
        import sqlite3

        conn = sqlite3.connect(self.db_path)
        conn.execute("""CREATE TABLE memes (
            id INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            file_hash TEXT NOT NULL DEFAULT '',
            original_name TEXT NOT NULL DEFAULT '',
            width INTEGER DEFAULT 0,
            height INTEGER DEFAULT 0,
            file_size INTEGER DEFAULT 0,
            mime_type TEXT DEFAULT 'image/png',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )""")
        conn.execute("INSERT INTO memes (filename) VALUES ('old.png')")
        conn.commit()
        conn.close()
        self.db = MemeDB(self.db_path)

        meme = self.db.get_by_filename("old.png")
        self.assertIn("ai_description", meme)
        self.assertIn("ai_ocr_text", meme)

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

    def test_move_to_collection_replaces_other_memberships(self):
        meme_id = self.db.add_meme("move.png")
        first = self.db.create_collection("第一文件夹")
        second = self.db.create_collection("第二文件夹")
        self.db.add_to_collection(meme_id, first)
        self.db.add_to_collection(meme_id, second)

        self.db.move_to_collection(meme_id, second)

        self.assertEqual(self.db.search(collection_id=first), [])
        self.assertEqual(
            [row["id"] for row in self.db.search(collection_id=second)], [meme_id]
        )

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


if __name__ == "__main__":
    unittest.main()
