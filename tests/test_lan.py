"""局域网互联测试 - pytest风格（回环 socket）"""

import hashlib
import hmac
import json
import os
import socket
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["OHMYMEME_TEST"] = "1"

import pytest

import src.config as config_module
import src.database as database
import src.lan as lan
from src.config import Config
from src.database import MemeDB

TEST_PORT = 17990
_IV_LEN = 12

# 1x1 透明 PNG（合法图片，PIL 可解码，宽高 1x1）
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049"
    "454e44ae426082"
)


def _valid_png(w=1, h=1):
    """构造合法小 PNG 字节"""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 0, 0)).save(buf, "PNG")
    return buf.getvalue()


# --- 协议客户端辅助 ---


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("closed")
        buf += chunk
    return buf


def _recv_plain(sock):
    (ln,) = struct.unpack(">I", _recv_exact(sock, 4))
    return json.loads(_recv_exact(sock, ln).decode("utf-8"))


def _send_plain(sock, obj):
    data = json.dumps(obj).encode("utf-8")
    sock.sendall(struct.pack(">I", len(data)) + data)


def _derive_client_key(secret):
    if not secret:
        return b"\x00" * 32
    return hashlib.pbkdf2_hmac(
        "sha256", secret.encode(), b"ohmy-meme-lan", 100000, dklen=32
    )


def _recv_frame(sock, key):
    (ln,) = struct.unpack(">I", _recv_exact(sock, 4))
    body = _recv_exact(sock, ln)
    iv, ct = body[:_IV_LEN], body[_IV_LEN:]
    plain = lan.AESGCM(key).decrypt(iv, ct, None)
    return json.loads(plain.decode("utf-8"))


def _send_frame(sock, key, obj):
    from os import urandom

    plain = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    iv = urandom(_IV_LEN)
    ct = lan.AESGCM(key).encrypt(iv, plain, None)
    sock.sendall(struct.pack(">I", _IV_LEN + len(ct)) + iv + ct)


def _handshake(sock, secret):
    """作为客户端完成握手，返回会话密钥"""
    msg = _recv_plain(sock)
    assert msg["t"] == "challenge"
    mac = hmac.new(secret.encode(), msg["nonce"].encode(), hashlib.sha256).hexdigest()
    _send_plain(sock, {"t": "proof", "mac": mac})
    assert _recv_plain(sock)["t"] == "ok"
    return _derive_client_key(secret)


def _connect(port=TEST_PORT):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(("127.0.0.1", port))
    return sock


@pytest.fixture()
def lan_env(tmp_path):
    """隔离 config/db/cache 并启动 lan 服务"""
    cfg = Config(tmp_path / "config.json")
    cfg.set("cache_dir", str(tmp_path / "cache"))
    cfg.set("lan_port", TEST_PORT)
    db = MemeDB(tmp_path / "test.db")

    old_cfg = config_module._config
    old_db = database._db
    old_cb = lan.set_confirm_callback(None)
    config_module._config = cfg
    database._db = db

    lan.stop()
    lan.set_allow_secret_config(False)
    assert lan.start(TEST_PORT, "test-secret")
    yield cfg, db, tmp_path

    lan.stop()
    lan.set_confirm_callback(old_cb)
    lan.set_allow_secret_config(False)
    config_module._config = old_cfg
    database._db = old_db


# --- 测试 ---


def test_udp_discovery(lan_env):
    cfg, db, tmp = lan_env
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.settimeout(5)
    udp.sendto(b'{"t":"discover"}', ("127.0.0.1", TEST_PORT))
    data, _ = udp.recvfrom(2048)
    udp.close()
    reply = json.loads(data.decode("utf-8"))
    assert reply["t"] == "hello"
    assert reply["need_secret"] is True
    assert reply["ver"]


def test_handshake_success(lan_env):
    sock = _connect()
    key = _handshake(sock, "test-secret")
    _send_frame(sock, key, {"cmd": "ping"})
    assert _recv_frame(sock, key)["ok"] is True
    sock.close()


def test_handshake_wrong_secret(lan_env):
    sock = _connect()
    msg = _recv_plain(sock)
    bad = hmac.new(b"wrong", msg["nonce"].encode(), hashlib.sha256).hexdigest()
    _send_plain(sock, {"t": "proof", "mac": bad})
    assert _recv_plain(sock)["t"] == "no"
    sock.close()


def test_handshake_retry_limit(lan_env):
    sock = _connect()
    challenge = _recv_plain(sock)
    assert challenge["t"] == "challenge"
    for _ in range(3):
        bad = hmac.new(b"x", challenge["nonce"].encode(), hashlib.sha256).hexdigest()
        _send_plain(sock, {"t": "proof", "mac": bad})
        assert _recv_plain(sock)["t"] == "no"
    sock.settimeout(2)
    closed = False
    try:
        while True:
            data = sock.recv(1)
            if not data:
                closed = True
                break
    except (ConnectionError, socket.timeout, OSError):
        closed = True
    assert closed
    sock.close()


def test_pull_manifest(lan_env):
    cfg, db, tmp = lan_env
    sock = _connect()
    key = _handshake(sock, "test-secret")
    _send_frame(sock, key, {"cmd": "pull_manifest"})
    resp = _recv_frame(sock, key)
    assert resp["ok"] is True
    assert "manifest" in resp
    assert isinstance(resp["manifest"].get("memes"), list)
    sock.close()


def test_push_pull_file(lan_env):
    cfg, db, tmp = lan_env
    import base64

    sock = _connect()
    key = _handshake(sock, "test-secret")
    png = _valid_png()
    png_b64 = base64.b64encode(png).decode()
    sha256 = hashlib.sha256(png).hexdigest()
    _send_frame(
        sock,
        key,
        {"cmd": "push_file", "filename": "test.png", "data": png_b64, "sha256": sha256},
    )
    resp = _recv_frame(sock, key)
    assert resp["ok"] is True

    sock2 = _connect()
    key2 = _handshake(sock2, "test-secret")
    _send_frame(sock2, key2, {"cmd": "pull_file", "filename": resp["filename"]})
    resp2 = _recv_frame(sock2, key2)
    assert resp2["ok"] is True

    assert base64.b64decode(resp2["data"]) == png
    sock.close()
    sock2.close()


def test_push_file_bad_hash(lan_env):
    cfg, db, tmp = lan_env
    import base64

    sock = _connect()
    key = _handshake(sock, "test-secret")
    png = _valid_png()
    _send_frame(
        sock,
        key,
        {
            "cmd": "push_file",
            "filename": "test.png",
            "data": base64.b64encode(png).decode(),
            "sha256": "0" * 64,
        },
    )
    resp = _recv_frame(sock, key)
    assert resp["ok"] is False
    assert "哈希" in resp["error"]
    assert not list((cfg.cache_dir).iterdir())
    sock.close()


def test_push_file_non_image(lan_env):
    """非图片字节不得落盘（杜绝孤儿文件）"""
    cfg, db, tmp = lan_env
    import base64

    sock = _connect()
    key = _handshake(sock, "test-secret")
    junk = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # 只有 PNG 魔数，无有效图像数据
    _send_frame(
        sock,
        key,
        {
            "cmd": "push_file",
            "filename": "fake.png",
            "data": base64.b64encode(junk).decode(),
        },
    )
    resp = _recv_frame(sock, key)
    assert resp["ok"] is False
    assert not list((cfg.cache_dir).iterdir())
    assert not db.search("", 0)
    sock.close()


def test_push_file_oversize(lan_env):
    """超过大小上限的文件被拒绝且不落盘（帧上限会先于该检查生效，故直接测处理器）"""
    cfg, db, tmp = lan_env
    import base64

    server = lan.LanServer()
    big = b"\x00" * (lan.MAX_FILE_SIZE + 1)
    resp = server._cmd_push_file(
        {"filename": "big.png", "data": base64.b64encode(big).decode()}
    )
    assert resp["ok"] is False
    assert not list((cfg.cache_dir).iterdir())


def test_push_file_bad_filename(lan_env):
    cfg, db, tmp = lan_env
    import base64

    sock = _connect()
    key = _handshake(sock, "test-secret")
    png = _valid_png()
    _send_frame(
        sock,
        key,
        {
            "cmd": "push_file",
            "filename": "../evil.png",
            "data": base64.b64encode(png).decode(),
        },
    )
    resp = _recv_frame(sock, key)
    assert resp["ok"] is False
    assert not list((cfg.cache_dir).iterdir())
    sock.close()


def test_get_config_no_secrets(lan_env):
    cfg, db, tmp = lan_env
    cfg.set("ftp_password", "hunter2")
    sock = _connect()
    key = _handshake(sock, "test-secret")
    _send_frame(sock, key, {"cmd": "get_config"})
    resp = _recv_frame(sock, key)
    assert resp["ok"] is True
    assert "ftp_password" not in resp["config"]
    assert resp["config"]["lan_port"] == TEST_PORT
    sock.close()


def test_send_config_filters_secrets(lan_env):
    """allow_secret_config 关闭时 send_config 忽略密钥字段"""
    cfg, db, tmp = lan_env
    sock = _connect()
    key = _handshake(sock, "test-secret")
    _send_frame(
        sock,
        key,
        {"cmd": "send_config", "config": {"ftp_password": "evil", "theme": "light"}},
    )
    resp = _recv_frame(sock, key)
    assert resp["ok"] is True
    assert cfg.get("theme") == "light"
    assert cfg.get("ftp_password") != "evil"
    sock.close()


def test_send_config_with_secrets(lan_env):
    """allow_secret_config 开启时 send_config 应用密钥字段"""
    cfg, db, tmp = lan_env
    lan.set_allow_secret_config(True)
    try:
        sock = _connect()
        key = _handshake(sock, "test-secret")
        _send_frame(
            sock,
            key,
            {
                "cmd": "send_config",
                "config": {"ftp_password": "evil", "theme": "light"},
            },
        )
        resp = _recv_frame(sock, key)
        assert resp["ok"] is True
        assert cfg.get("theme") == "light"
        assert cfg.get("ftp_password") == "evil"
        sock.close()
    finally:
        lan.set_allow_secret_config(False)


def test_get_config_with_secrets(lan_env):
    """allow_secret_config 开启时 get_config 包含密钥字段"""
    cfg, db, tmp = lan_env
    cfg.set("ftp_password", "hunter2")
    lan.set_allow_secret_config(True)
    try:
        sock = _connect()
        key = _handshake(sock, "test-secret")
        _send_frame(sock, key, {"cmd": "get_config"})
        resp = _recv_frame(sock, key)
        assert resp["config"]["ftp_password"] == "hunter2"
        sock.close()
    finally:
        lan.set_allow_secret_config(False)


def test_device_info_approved(lan_env):
    """设备描述经确认后放行，响应携带 allow_secret_config"""
    cfg, db, tmp = lan_env
    called = []

    def cb(device):
        called.append(device)
        lan.confirm_device(True)

    old = lan.set_confirm_callback(cb)
    try:
        sock = _connect()
        key = _handshake(sock, "test-secret")
        _send_frame(
            sock,
            key,
            {
                "cmd": "device_info",
                "name": "Pixel",
                "model": "Pixel 8",
                "os": "Android 15",
                "ver": "0.4.1",
            },
        )
        resp = _recv_frame(sock, key)
        assert resp["ok"] is True
        assert resp["approved"] is True
        assert resp["allow_secret_config"] is False
        assert called and called[0]["name"] == "Pixel"
        # 确认后其他命令正常放行
        _send_frame(sock, key, {"cmd": "ping"})
        assert _recv_frame(sock, key)["ok"] is True
        sock.close()
    finally:
        lan.set_confirm_callback(old)


def test_device_info_rejected(lan_env):
    """设备描述被拒绝则 approved=False"""
    cfg, db, tmp = lan_env

    def cb(device):
        lan.confirm_device(False)

    old = lan.set_confirm_callback(cb)
    try:
        sock = _connect()
        key = _handshake(sock, "test-secret")
        _send_frame(
            sock,
            key,
            {"cmd": "device_info", "name": "Evil", "os": "Android 14"},
        )
        resp = _recv_frame(sock, key)
        assert resp["ok"] is True
        assert resp["approved"] is False
        sock.close()
    finally:
        lan.set_confirm_callback(old)


def test_device_info_no_callback_auto_approve(lan_env):
    """无确认回调（测试/无 UI）时自动放行"""
    cfg, db, tmp = lan_env
    sock = _connect()
    key = _handshake(sock, "test-secret")
    _send_frame(
        sock,
        key,
        {"cmd": "device_info", "name": "Device", "os": "Android"},
    )
    resp = _recv_frame(sock, key)
    assert resp["ok"] is True
    assert resp["approved"] is True
    sock.close()


def test_unknown_cmd(lan_env):
    sock = _connect()
    key = _handshake(sock, "test-secret")
    _send_frame(sock, key, {"cmd": "nope"})
    resp = _recv_frame(sock, key)
    assert resp["ok"] is False
    sock.close()


def test_no_secret_server(tmp_path):
    """无密钥时直接放行"""
    cfg = Config(tmp_path / "config.json")
    cfg.set("cache_dir", str(tmp_path / "cache"))
    db = MemeDB(tmp_path / "test.db")
    old_cfg = config_module._config
    old_db = database._db
    config_module._config = cfg
    database._db = db
    lan.stop()
    assert lan.start(TEST_PORT, "")
    try:
        sock = _connect()
        msg = _recv_plain(sock)
        assert msg["t"] == "ok"
        key = _derive_client_key("")
        _send_frame(sock, key, {"cmd": "ping"})
        assert _recv_frame(sock, key)["ok"] is True
        sock.close()
    finally:
        lan.stop()
        config_module._config = old_cfg
        database._db = old_db


def test_stop_status(lan_env):
    assert lan.get_status()["status"] == "running"
    lan.stop()
    assert lan.get_status()["status"] == "stopped"
    lan.start(TEST_PORT, "test-secret")
