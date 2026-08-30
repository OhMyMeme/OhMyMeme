import os
import platform

import pytest

from src import wechat_probe

pytestmark = pytest.mark.skipif(
    platform.system() != "Windows", reason="微信导入仅支持 Windows"
)


def _make_account(root, name, with_db=True, plaintext=True):
    """构造账号目录，db_storage/emoticon/emoticon.db 可选明文/加密"""
    db_dir = os.path.join(str(root), name, "db_storage", "emoticon")
    os.makedirs(db_dir, exist_ok=True)
    if with_db:
        header = b"SQLite format 3\x00" if plaintext else b"\x00" * 16
        with open(os.path.join(db_dir, "emoticon.db"), "wb") as f:
            f.write(header + b"\x00" * 32)


def test_account_without_wxid_prefix_detected(tmp_path):
    _make_account(tmp_path, "custom_nickname")
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "supported"
    assert [a["id"] for a in r["accounts"]] == ["custom_nickname"]


def test_wxid_prefix_account_still_detected(tmp_path):
    _make_account(tmp_path, "wxid_abc123")
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "supported"
    assert [a["id"] for a in r["accounts"]] == ["wxid_abc123"]


def test_selected_account_dir_without_wxid_prefix(tmp_path):
    _make_account(tmp_path, "my_account")
    r = wechat_probe.inspect_wechat_environment(str(tmp_path) + os.sep + "my_account")
    assert r["status"] == "supported"
    assert r["accounts"][0]["id"] == "my_account"


def test_dir_without_emoticon_db_not_account(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), "random_folder"))
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "no_accounts"
    assert r["accounts"] == []


def test_encrypted_index_without_wxid_prefix(tmp_path):
    _make_account(tmp_path, "old_wechat", plaintext=False)
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "encrypted_index"


def test_non_wxid_dir_without_db_ignored_alongside_valid_account(tmp_path):
    os.makedirs(os.path.join(str(tmp_path), "backup_old"))
    _make_account(tmp_path, "wxid_one")
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert [a["id"] for a in r["accounts"]] == ["wxid_one"]


def test_wide_fallback_db_in_other_subdir(tmp_path):
    _make_account(tmp_path, "acc", with_db=False)
    db_dir = os.path.join(str(tmp_path), "acc", "db_storage", "emoticon_backup")
    os.makedirs(db_dir)
    with open(os.path.join(db_dir, "emoticon.db"), "wb") as f:
        f.write(b"SQLite format 3\x00" + b"\x00" * 32)
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "supported"


def test_wide_fallback_db_directly_under_db_storage(tmp_path):
    _make_account(tmp_path, "acc", with_db=False)
    storage = os.path.join(str(tmp_path), "acc", "db_storage")
    with open(os.path.join(storage, "emoticon.db"), "wb") as f:
        f.write(b"SQLite format 3\x00" + b"\x00" * 32)
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "supported"


def test_no_database_reports_existing_db_files(tmp_path):
    _make_account(tmp_path, "wxid_x", with_db=False)
    fav_dir = os.path.join(str(tmp_path), "wxid_x", "db_storage", "favorite")
    os.makedirs(fav_dir)
    with open(os.path.join(fav_dir, "favorite.db"), "wb") as f:
        f.write(b"SQLite format 3\x00" + b"\x00" * 32)
    r = wechat_probe.inspect_wechat_environment(str(tmp_path))
    assert r["status"] == "no_database"
    assert r["accounts"][0]["db_files"] == ["favorite/favorite.db"]
