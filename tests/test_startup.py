"""启动流程测试 - pytest风格"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["OHMYMEME_TEST"] = "1"

from src.clipboard_util import copy_image_to_clipboard, copy_text
from src.config import Config
from src.crypto_util import decrypt_data, encrypt_data
from src.database import MemeDB
from src.hotkey import GlobalHotkey
from src.tray import _create_default_icon


def test_config_io(tmp_path):
    cfg = Config(tmp_path / "config.json")
    cfg.set("hotkey", "Ctrl+Shift+X")
    cfg.set("s3_secret_key", "test_secret_123")
    cfg.set("auto_start", True)
    cfg.save()

    cfg2 = Config(tmp_path / "config.json")
    assert cfg2.get("hotkey") == "Ctrl+Shift+X"
    assert cfg2.get("s3_secret_key") == "test_secret_123"
    assert cfg2.get("auto_start")


def test_database_operations(tmp_path):
    db = MemeDB(tmp_path / "test.db")
    mid = db.add_meme("test.png", file_hash="abc", width=100, height=200, tags=["test"])
    assert mid is not None
    assert db.count() == 1
    assert db.get_by_hash("abc") is not None
    results = db.search(keyword="test")
    assert len(results) == 1
    assert not db.is_favorite(mid)
    db.toggle_favorite(mid)
    assert db.is_favorite(mid)
    tags = db.get_meme_tags(mid)
    assert "test" in tags
    db.close()


def test_hotkey_init():
    hk = GlobalHotkey()
    result = hk.register("Ctrl+Alt+N", lambda: None)
    assert result
    hk.unregister()


def test_tray_icon():
    img = _create_default_icon()
    assert img is not None
    assert img.size == (64, 64)
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    assert len(buf.getvalue()) > 0


def test_crypto():
    secrets = ["my_secret_key", "AKID1234567890", "s3cr3t!@#$%"]
    for s in secrets:
        enc = encrypt_data(s)
        dec = decrypt_data(enc)
        assert dec == s


def test_clipboard():
    result = copy_text("test")
    assert isinstance(result, bool)
    icon_path = (
        Path(__file__).resolve().parent.parent / "src" / "resources" / "icon.png"
    )
    if icon_path.exists():
        result = copy_image_to_clipboard(str(icon_path))
        assert isinstance(result, bool)


def test_webui_import():
    from src.webui import JsApi, WebUI

    w = WebUI()
    assert w._port > 0
    assert w._window is None
    assert not w.is_visible
    assert hasattr(w, "toggle_safe")
    assert hasattr(w, "show")
    assert hasattr(w, "hide")
    # JsApi
    api = JsApi(w)
    assert hasattr(api, "search_memes")
    assert hasattr(api, "get_tags")
    assert hasattr(api, "copy_meme")
    assert hasattr(api, "import_memes")


def test_webui_html_exists():
    from src.webui import HTML_DIR

    assert HTML_DIR.exists()
    assert (HTML_DIR / "index.html").exists()
    html = (HTML_DIR / "index.html").read_text(encoding="utf-8")
    assert "OhMyMeme" in html
    assert "search" in html
    # 前端样式/脚本已从 HTML 拆分为独立静态文件
    assert (HTML_DIR / "index.css").exists()
    assert (HTML_DIR / "index.js").exists()
    assert (HTML_DIR / "settings.html").exists()
    assert (HTML_DIR / "settings.css").exists()
    assert (HTML_DIR / "settings.js").exists()
    assert 'src="/index.js"' in html
    assert 'href="/index.css"' in html
    settings_html = (HTML_DIR / "settings.html").read_text(encoding="utf-8")
    assert 'src="/settings.js"' in settings_html
    assert 'href="/settings.css"' in settings_html


def test_webui_safe_serve_filename():
    from src.webui import _safe_serve_filename

    for name in ("a.png", "表情.webp", "a b.gif", "abc123.gif"):
        assert _safe_serve_filename(name)
    for name in (
        "../evil.png",
        "..",
        ".",
        "dir/file.png",
        "/etc/passwd",
        "\\win\\x.png",
        "~/x.png",
        "",
        ".hidden",
    ):
        assert not _safe_serve_filename(name)


def test_webui_host_allowed():
    from src.webui import _host_allowed

    assert _host_allowed("127.0.0.1", 12345)
    assert _host_allowed("127.0.0.1:12345", 12345)
    assert _host_allowed("localhost:12345", 12345)
    assert not _host_allowed("evil.example.com", 12345)
    assert not _host_allowed("evil.example.com:12345", 12345)
    assert not _host_allowed("127.0.0.1:9999", 12345)
    assert not _host_allowed("", 12345)


def test_storage_dir_validation(tmp_path):
    from src.webui import _storage_dir_validation

    old = tmp_path / "old"
    old.mkdir()
    (old / "sub").mkdir()
    assert _storage_dir_validation(None, str(old))[0] is False
    assert _storage_dir_validation("", str(old))[0] is False
    assert _storage_dir_validation("rel/path", str(old))[0] is False
    assert _storage_dir_validation(str(old), str(old))[0] is False
    assert _storage_dir_validation(str(old / "sub"), str(old))[0] is False
    assert _storage_dir_validation(str(tmp_path), str(old))[0] is False
    assert _storage_dir_validation(str(tmp_path / "new"), str(old))[0] is True

    data = tmp_path / "data"
    assert _storage_dir_validation(str(data), str(old), (data,))[0] is False
    assert _storage_dir_validation(str(data / "x"), str(old), (data,))[0] is False
    assert _storage_dir_validation(str(tmp_path), str(old), (data,))[0] is False
    assert _storage_dir_validation(str(tmp_path / "ok"), str(old), (data,))[0] is True
