"""局域网互联测试 - pytest风格（回环 socket）"""

import hashlib
import hmac
import json
import os
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["OHMYMEME_TEST"] = "1"

import pytest

import ohmymeme.core.config as config_module
import ohmymeme.core.database as database
import ohmymeme.services.lan as lan_package
import ohmymeme.services.lan.server as lan
import ohmymeme.services.sync.service as sync_module
from ohmymeme.app.local_library import LocalLibraryService
from ohmymeme.core.assets import AssetPaths
from ohmymeme.core.config import Config
from ohmymeme.core.database import MemeDB
from ohmymeme.core.imports import ImageImportService
from ohmymeme.core.manifest import ManifestBuilder

TEST_PORT = 0
_IV_LEN = 12


def test_lan_package_exports_public_server_api():
    """包级 LAN 门面应暴露启动流程使用的公共函数。"""
    exports = (
        "start",
        "stop",
        "get_status",
        "get_lan_ip",
        "set_allow_secret_config",
        "set_confirm_callback",
        "confirm_device",
    )

    assert all(callable(getattr(lan_package, name, None)) for name in exports)


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


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _start_test_server(server, secret):
    global TEST_PORT
    for _ in range(10):
        TEST_PORT = _free_port()
        if server.start(TEST_PORT, secret):
            return
        server.stop()
    pytest.fail("无法为 LAN 测试绑定临时端口")


def _connect(port=None):
    port = TEST_PORT if port is None else port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    sock.connect(("127.0.0.1", port))
    return sock


@pytest.fixture()
def lan_env(tmp_path):
    """隔离 config/db/cache 并启动 lan 服务"""
    cfg = Config(tmp_path / "config.json")
    cfg.set("cache_dir", str(tmp_path / "cache"))
    db = MemeDB(tmp_path / "test.db")
    assets = AssetPaths(cfg.data_dir, cfg.cache_dir)
    manifest = ManifestBuilder(cfg, db, assets)
    library = LocalLibraryService(
        db,
        assets,
        ImageImportService(db, assets, manifest.build),
        manifest.build,
        cfg,
    )
    server = lan.LanServer(
        config=cfg,
        db=db,
        assets=assets,
        manifest=manifest,
        library=library,
    )

    old_cfg = config_module._config
    old_db = database._db
    old_cb = lan.set_confirm_callback(None)
    config_module._config = cfg
    database._db = db

    try:
        lan.stop()
        lan.set_allow_secret_config(False)
        lan._server = server
        _start_test_server(server, "test-secret")
        cfg.set("lan_port", TEST_PORT)
        yield cfg, db, tmp_path
    finally:
        lan.stop()
        assert lan.get_status()["status"] == "stopped"
        lan.set_confirm_callback(old_cb)
        lan.set_allow_secret_config(False)
        config_module._config = old_cfg
        database._db = old_db
        db.close()


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


def test_lan_fixture_uses_a_private_ephemeral_port(lan_env):
    cfg, _, _ = lan_env

    assert TEST_PORT > 0
    assert TEST_PORT != 17990
    assert cfg.get("lan_port") == TEST_PORT


def test_lan_fixture_injects_config_into_owned_library(lan_env):
    cfg, _, _ = lan_env

    assert lan._server._commands.library._config is cfg


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


@pytest.mark.skipif(
    not hasattr(socket, "IP_PKTINFO") or not hasattr(socket.socket, "recvmsg"),
    reason="平台不支持 IP_PKTINFO 或 recvmsg（pktinfo 源地址钉定依赖 recvmsg）",
)
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


def test_pull_manifest_uses_public_library_projection_boundary(lan_env):
    class Library:
        def project_manifest(self):
            return False

        def __getattr__(self, name):
            if name == "_project_after_mutation":
                raise AssertionError("private projection boundary bypass")
            raise AttributeError(name)

    server = lan.LanServer(library=Library())

    # When: LAN asks for a local manifest through the command handler
    response = server._cmd_pull_manifest()

    # Then: projection failure keeps the established LAN error envelope
    assert response == {"ok": False, "error": "本地清单生成失败"}


def test_legacy_manifest_apply_uses_public_library_boundary(lan_env, monkeypatch):
    calls = []

    class Library:
        def apply_remote_metadata(self, manifest):
            calls.append(manifest)
            return True

        def __getattr__(self, name):
            if name == "_project_after_mutation":
                raise AssertionError("private projection boundary bypass")
            raise AttributeError(name)

    def fail_private_helper(_manifest):
        raise AssertionError("private sync helper bypass")

    monkeypatch.setattr(sync_module, "_apply_remote_order", fail_private_helper)
    monkeypatch.setattr(sync_module, "_apply_remote_collections", fail_private_helper)
    server = lan.LanServer(library=Library())

    # When: a legacy LAN manifest apply helper receives remote metadata
    response = server._commands._apply_manifest({"version": 3, "memes": []})

    # Then: the public library operation applies the manifest and reports success
    assert response is True
    assert calls == [{"version": 3, "memes": []}]


def test_push_manifest_returns_compatible_success_and_failure_shapes(lan_env):
    cfg, db, _ = lan_env
    handlers = lan._server._commands

    # When: a valid remote manifest is applied through the real LAN command handler
    success = handlers._cmd_push_manifest(
        {"version": 3, "memes": [], "collections": []}
    )

    # Then: success keeps the established count envelope
    assert success == {"ok": True, "local_count": db.count()}

    # When: malformed remote metadata is submitted to the same handler
    malformed = handlers._cmd_push_manifest([])

    # Then: malformed input keeps the established error envelope
    assert malformed == {"ok": False, "error": "manifest 格式错误"}


def test_push_manifest_projection_failure_returns_error_shape(lan_env):
    class Library:
        def apply_remote_metadata(self, _manifest):
            return False

    server = lan.LanServer(library=Library())

    # When: the local public apply operation reports projection failure
    response = server._commands._cmd_push_manifest(
        {"version": 3, "memes": [], "collections": []}
    )

    # Then: LAN does not report a false success
    assert response == {"ok": False, "error": "本地清单应用失败"}


def test_lan_command_handlers_reuse_explicit_application_graph(lan_env):
    cfg, db, tmp = lan_env
    assets = AssetPaths(cfg.data_dir, cfg.cache_dir)
    manifest = ManifestBuilder(cfg, db, assets)
    library = LocalLibraryService(
        db,
        assets,
        type("Importer", (), {"import_bytes": lambda self, request: None})(),
        manifest.build,
        cfg,
    )
    server = lan.LanServer(
        config=cfg,
        db=db,
        assets=assets,
        manifest=manifest,
        library=library,
    )

    assert server._commands.config is cfg
    assert server._commands.db is db
    assert server._commands.assets is assets
    assert server._commands.manifest is manifest
    assert server._commands.library is library
    assert server._commands._cmd_push_manifest(
        {"version": 3, "memes": [], "collections": []}
    ) == {"ok": True, "local_count": 0}


def test_push_pull_file(lan_env, monkeypatch):
    cfg, db, tmp = lan_env
    import base64

    monkeypatch.setattr(
        "ohmymeme.services.lan.commands.get_config",
        lambda: (_ for _ in ()).throw(AssertionError("default config accessed")),
    )
    monkeypatch.setattr(
        "ohmymeme.services.lan.commands.get_db",
        lambda: (_ for _ in ()).throw(AssertionError("default db accessed")),
    )
    assert lan._server._commands.config is cfg
    assert lan._server._commands.db is db
    assert lan._server._commands.assets.cache_dir == cfg.cache_dir
    assert lan._server._commands.manifest.config is cfg
    assert lan._server._commands.library._config is cfg
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

    server = lan._server
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


def test_get_config_filters_every_provider_secret(lan_env):
    cfg, _, _ = lan_env
    for key in (
        "ftp_password",
        "s3_access_key",
        "s3_secret_key",
        "r2_access_key_id",
        "r2_secret_access_key",
        "webdav_password",
        "lan_secret",
    ):
        cfg.set(key, "secret")
    sock = _connect()
    key = _handshake(sock, "test-secret")
    _send_frame(sock, key, {"cmd": "get_config"})
    resp = _recv_frame(sock, key)
    assert resp["ok"] is True
    assert all(
        secret not in resp["config"]
        for secret in (
            "ftp_password",
            "s3_access_key",
            "s3_secret_key",
            "r2_access_key_id",
            "r2_secret_access_key",
            "webdav_password",
            "lan_secret",
        )
    )
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


def test_send_config_ignores_removed_settings(lan_env):
    cfg, db, tmp = lan_env
    sock = _connect()
    key = _handshake(sock, "test-secret")
    _send_frame(
        sock,
        key,
        {"cmd": "send_config", "config": {"auto_paste_meme": True}},
    )
    resp = _recv_frame(sock, key)

    assert resp["ok"] is True
    assert "auto_paste_meme" not in cfg.to_dict()
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
        lan.confirm_device(True, device["_confirm_id"])

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
        lan.confirm_device(False, device["_confirm_id"])

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


def test_stop_unblocks_pending_device_confirmation(lan_env):
    called = []

    def cb(device):
        called.append(device)

    old = lan.set_confirm_callback(cb)
    sock = None
    try:
        sock = _connect()
        key = _handshake(sock, "test-secret")
        _send_frame(sock, key, {"cmd": "device_info", "name": "Pending"})
        deadline = time.monotonic() + 1
        while not called and time.monotonic() < deadline:
            time.sleep(0.01)
        started = time.monotonic()
        lan.stop()
        assert time.monotonic() - started < 1.5
        assert lan.get_status()["status"] == "stopped"
    finally:
        if sock:
            sock.close()
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
    old_cb = lan.set_confirm_callback(None)
    config_module._config = cfg
    database._db = db
    assets = AssetPaths(cfg.data_dir, cfg.cache_dir)
    manifest = ManifestBuilder(cfg, db, assets)
    library = LocalLibraryService(
        db,
        assets,
        ImageImportService(db, assets, manifest.build),
        manifest.build,
        cfg,
    )
    server = lan.LanServer(
        config=cfg,
        db=db,
        assets=assets,
        manifest=manifest,
        library=library,
    )
    port = _free_port()
    lan.stop()
    for _ in range(10):
        lan._server = server
        if server.start(port, ""):
            break
        lan.stop()
        port = _free_port()
    else:
        pytest.fail("无法为无密钥 LAN 测试绑定临时端口")
    sock = None
    try:
        sock = _connect(port)
        msg = _recv_plain(sock)
        assert msg["t"] == "ok"
        key = _derive_client_key("")
        _send_frame(sock, key, {"cmd": "ping"})
        assert _recv_frame(sock, key)["ok"] is True
        sock.close()
    finally:
        if sock is not None:
            sock.close()
        lan.stop()
        lan.set_confirm_callback(old_cb)
        config_module._config = old_cfg
        database._db = old_db
        db.close()


def test_stop_status(lan_env):
    assert lan.get_status()["status"] == "running"
    lan.stop()
    assert lan.get_status()["status"] == "stopped"
