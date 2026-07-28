"""启动流程测试 - pytest风格"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["OHMYMEME_TEST"] = "1"

from src.config import Config
from src.database import MemeDB
from src.hotkey import GlobalHotkey
from src.tray import _create_default_icon
from src.clipboard_util import copy_image_to_clipboard, copy_text
from src.crypto_util import encrypt_data, decrypt_data


def test_config_io(tmp_path):
    cfg = Config(tmp_path / "config.json")
    cfg.set("hotkey", "Ctrl+Shift+X")
    cfg.set("s3_secret_key", "test_secret_123")
    cfg.set("auto_start", True)
    cfg.save()

    cfg2 = Config(tmp_path / "config.json")
    assert cfg2.get("hotkey") == "Ctrl+Shift+X"
    assert cfg2.get("s3_secret_key") == "test_secret_123"
    assert cfg2.get("auto_start") == True


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
    assert result == True
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
    icon_path = Path(__file__).resolve().parent.parent / "src" / "resources" / "icon.png"
    if icon_path.exists():
        result = copy_image_to_clipboard(str(icon_path))
        assert isinstance(result, bool)


def test_webui_import():
    from src.webui import WebUI, JsApi
    w = WebUI()
    assert w._port > 0
    assert w._window is None
    assert w.is_visible == False
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
