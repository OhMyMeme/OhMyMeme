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


def test_pktinfo_extract_linux_layout(monkeypatch):
    """Linux in_pktinfo 布局 (ifindex, spec_dst, addr) 解析"""
    monkeypatch.setattr(lan.socket, "IP_PKTINFO", 8, raising=False)
    monkeypatch.setattr(lan.sys, "platform", "linux")
    srv = lan.LanServer()
    cdata = struct.pack(
        "i4s4s",
        1,
        socket.inet_aton("192.168.1.5"),
        socket.inet_aton("255.255.255.255"),
    )
    anc = [(socket.IPPROTO_IP, getattr(socket, "IP_PKTINFO", 8), cdata)]
    assert srv._extract_pktinfo_src(anc) == ("ip", "192.168.1.5")


def test_pktinfo_extract_windows_layout(monkeypatch):
    """Windows in_pktinfo 仅 8 字节 (ipi_addr, ipi_ifindex)，返回接口索引"""
    monkeypatch.setattr(lan.socket, "IP_PKTINFO", 8, raising=False)
    monkeypatch.setattr(lan.sys, "platform", "win32")
    srv = lan.LanServer()
    cdata = struct.pack("4sI", socket.inet_aton("255.255.255.255"), 7)
    anc = [(socket.IPPROTO_IP, getattr(socket, "IP_PKTINFO", 8), cdata)]
    assert srv._extract_pktinfo_src(anc) == ("ifindex", 7)


def test_pktinfo_extract_windows_zero_ifindex(monkeypatch):
    """Windows 接口索引为 0（不可用）时返回 None"""
    monkeypatch.setattr(lan.socket, "IP_PKTINFO", 8, raising=False)
    monkeypatch.setattr(lan.sys, "platform", "win32")
    srv = lan.LanServer()
    cdata = struct.pack("4sI", socket.inet_aton("255.255.255.255"), 0)
    anc = [(socket.IPPROTO_IP, getattr(socket, "IP_PKTINFO", 8), cdata)]
    assert srv._extract_pktinfo_src(anc) is None


@pytest.mark.skipif(not hasattr(socket, "IP_PKTINFO"), reason="平台不支持 IP_PKTINFO")
def test_udp_reply_pins_source_interface(lan_env):
    """回包源 IP 钉在广播到达的接口上（虚拟网卡环境发现可达）"""
    cfg, db, tmp = lan_env
    srv = lan._server
    assert srv is not None and srv._udp_pktinfo
    cli = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    cli.settimeout(5)
    cli.sendto(b'{"t":"discover"}', ("127.0.0.1", TEST_PORT))
    data, src = cli.recvfrom(2048)
    cli.close()
    assert json.loads(data.decode("utf-8"))["t"] == "hello"
    assert src[0] == "127.0.0.1"


def test_pktinfo_extract_ignores_other_cmsg(monkeypatch):
    """非 IP_PKTINFO 控制消息被忽略并返回 None"""
    monkeypatch.setattr(lan.socket, "IP_PKTINFO", 8, raising=False)
    srv = lan.LanServer()
    anc = [
        (socket.SOL_SOCKET, socket.SO_REUSEADDR, b"\x00\x00\x00\x00"),
        (socket.IPPROTO_TCP, socket.IP_TTL, b"\x00" * 4),
    ]
    assert srv._extract_pktinfo_src(anc) is None


def test_pktinfo_extract_short_cdata(monkeypatch):
    """cdata 过短时解析失败返回 None 而非抛异常"""
    monkeypatch.setattr(lan.socket, "IP_PKTINFO", 8, raising=False)
    srv = lan.LanServer()
    anc = [(socket.IPPROTO_IP, 8, b"\x00")]
    assert srv._extract_pktinfo_src(anc) is None


class _FakeUdpSock:
    """记录 sendmsg/sendto 调用的假 UDP socket"""

    def __init__(self):
        self.sendmsg_calls = []
        self.sendto_calls = []

    def sendmsg(self, buffers, ancdata, flags=0, address=None):
        self.sendmsg_calls.append(
            {"buffers": buffers, "ancdata": ancdata, "address": address}
        )

    def sendto(self, data, address=None):
        self.sendto_calls.append({"data": data, "address": address})


def test_send_udp_reply_uses_sendmsg_with_pktinfo(monkeypatch):
    """Linux 路径 sendmsg 的 ancdata 携带 IP_PKTINFO（源地址 = 接收接口）"""
    monkeypatch.setattr(lan.socket, "IP_PKTINFO", 8, raising=False)
    srv = lan.LanServer()
    sock = _FakeUdpSock()
    srv._udp_sock = sock
    srv._udp_pktinfo = True
    srv._send_udp_reply(b'{"t":"hello"}', ("192.168.0.1", 12345), ("ip", "192.168.1.5"))
    assert not sock.sendto_calls
    assert len(sock.sendmsg_calls) == 1
    call = sock.sendmsg_calls[0]
    assert call["address"] == ("192.168.0.1", 12345)
    level, ctype, cdata = call["ancdata"][0]
    assert level == socket.IPPROTO_IP and ctype == 8
    _, spec_dst, _ = struct.unpack("i4s4s", cdata)
    assert socket.inet_ntoa(spec_dst) == "192.168.1.5"


def test_send_udp_reply_windows_sendmsg_pins_ifindex(monkeypatch):
    """Windows 路径 sendmsg 的 ancdata 源地址填 ipi_addr、接口填 ipi_ifindex"""
    monkeypatch.setattr(lan.socket, "IP_PKTINFO", 8, raising=False)
    monkeypatch.setattr(lan.sys, "platform", "win32")
    srv = lan.LanServer()
    sock = _FakeUdpSock()
    srv._udp_sock = sock
    srv._udp_pktinfo = True
    monkeypatch.setattr(srv, "_win_ifindex_source_ip", lambda ifindex, peer: "10.0.0.5")
    srv._send_udp_reply(b'{"t":"hello"}', ("192.168.0.1", 12345), ("ifindex", 7))
    assert not sock.sendto_calls
    assert len(sock.sendmsg_calls) == 1
    level, ctype, cdata = sock.sendmsg_calls[0]["ancdata"][0]
    assert level == socket.IPPROTO_IP and ctype == 8
    ipi_addr, ipi_ifindex = struct.unpack("4sI", cdata)
    assert socket.inet_ntoa(ipi_addr) == "10.0.0.5"
    assert ipi_ifindex == 7


def test_win_ifindex_source_ip_sets_unicast_if(monkeypatch):
    """Windows 反查接口 IP：用 IP_UNICAST_IF（网络字节序）钉接口并 connect"""
    monkeypatch.setattr(lan.sys, "platform", "win32")
    captured = {}

    class _FakeProbeSock:
        def setsockopt(self, level, optname, value):
            captured["opt"] = (level, optname, value)

        def connect(self, addr):
            captured["addr"] = addr

        def getsockname(self):
            return ("10.0.0.5", 0)

        def close(self):
            pass

    monkeypatch.setattr(lan.socket, "socket", lambda *a, **k: _FakeProbeSock())
    srv = lan.LanServer()
    assert srv._win_ifindex_source_ip(7, ("192.168.0.1", 12345)) == "10.0.0.5"
    level, optname, value = captured["opt"]
    assert level == socket.IPPROTO_IP
    assert optname == getattr(socket, "IP_UNICAST_IF", 31)
    assert value == struct.pack("!I", 7)
    assert captured["addr"] == ("192.168.0.1", 12345)


def test_win_ifindex_source_ip_oserror(monkeypatch):
    """Windows 反查失败（OSError）时返回 None"""
    monkeypatch.setattr(lan.sys, "platform", "win32")

    class _FakeProbeSock:
        def setsockopt(self, level, optname, value):
            raise OSError("no such interface")

        def connect(self, addr):
            pass

        def getsockname(self):
            return ("10.0.0.5", 0)

        def close(self):
            pass

    monkeypatch.setattr(lan.socket, "socket", lambda *a, **k: _FakeProbeSock())
    srv = lan.LanServer()
    assert srv._win_ifindex_source_ip(7, ("192.168.0.1", 12345)) is None


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
