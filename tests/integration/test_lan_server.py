import hashlib
import hmac
import json
import socket
import struct
import threading

import pytest

import ohmymeme.core.config as config_module
import ohmymeme.core.database as database
import ohmymeme.services.lan.server as lan
from ohmymeme.core.config import Config
from ohmymeme.core.database import MemeDB

TEST_PORT = 0


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def start_test_server(secret):
    global TEST_PORT
    for _ in range(10):
        TEST_PORT = free_port()
        if lan.start(TEST_PORT, secret):
            return
        lan.stop()
    pytest.fail("无法为 LAN 集成测试绑定临时端口")


@pytest.fixture()
def lan_env(tmp_path):
    cfg = Config(tmp_path / "config.json")
    cfg.set("cache_dir", str(tmp_path / "cache"))
    db = MemeDB(tmp_path / "test.db")
    old_cfg = config_module._config
    old_db = database._db
    old_callback = lan.set_confirm_callback(None)
    config_module._config = cfg
    database._db = db
    try:
        lan.stop()
        lan.set_allow_secret_config(False)
        start_test_server("test-secret")
        cfg.set("lan_port", TEST_PORT)
        yield cfg
    finally:
        lan.stop()
        assert lan.get_status()["status"] == "stopped"
        lan.set_confirm_callback(old_callback)
        lan.set_allow_secret_config(False)
        config_module._config = old_cfg
        database._db = old_db
        db.close()


def recv_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data.extend(chunk)
    return bytes(data)


def recv_plain(sock):
    (length,) = struct.unpack(">I", recv_exact(sock, 4))
    return json.loads(recv_exact(sock, length).decode("utf-8"))


def send_plain(sock, obj):
    sock.sendall(lan.lan_protocol.encode_plain(obj))


def recv_frame(sock, key):
    return lan.lan_protocol.decode_frame(lambda size: recv_exact(sock, size), key)[0]


def frame(key, obj):
    return lan.lan_protocol.encode_frame(key, obj)


def handshake(sock, secret="test-secret"):
    challenge = recv_plain(sock)
    assert challenge["t"] == "challenge"
    mac = hmac.new(
        secret.encode(), challenge["nonce"].encode(), hashlib.sha256
    ).hexdigest()
    send_plain(sock, {"t": "proof", "mac": mac})
    assert recv_plain(sock) == {"t": "ok"}
    return lan.lan_protocol.derive_key(secret)


def connect(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    sock.connect(("127.0.0.1", port))
    return sock


def test_rejected_connection_cannot_dispatch(lan_env):
    def reject(device):
        lan.confirm_device(False, device["_confirm_id"])

    old = lan.set_confirm_callback(reject)
    sock = None
    try:
        sock = connect(TEST_PORT)
        key = handshake(sock)
        sock.sendall(frame(key, {"cmd": "device_info", "name": "blocked"}))
        assert recv_frame(sock, key)["approved"] is False
        sock.sendall(frame(key, {"cmd": "ping"}))
        assert recv_frame(sock, key) == {"ok": False, "error": "设备未授权"}
    finally:
        lan.set_confirm_callback(old)
        if sock is not None:
            sock.close()


def test_lan_fixture_uses_a_private_ephemeral_port(lan_env):
    assert TEST_PORT > 0
    assert TEST_PORT != 17990


def test_replayed_mutation_is_rejected_but_ping_remains_compatible(lan_env):
    sock = connect(TEST_PORT)
    try:
        key = handshake(sock)
        payload = frame(key, {"cmd": "send_config", "config": {"theme": "light"}})
        sock.sendall(payload)
        assert recv_frame(sock, key) == {"ok": True}
        sock.sendall(payload)
        assert recv_frame(sock, key) == {"ok": False, "error": "重复请求"}
        sock.sendall(frame(key, {"cmd": "ping"}))
        assert recv_frame(sock, key)["ok"] is True
    finally:
        sock.close()


def test_replay_cache_is_bounded(lan_env):
    server = lan.LanServer()
    for index in range(lan._REPLAY_CACHE_LIMIT + 1):
        assert server._is_replayed_mutation("send_config", index.to_bytes(4)) is False

    assert len(server._replay_cache) == lan._REPLAY_CACHE_LIMIT
    assert server._is_replayed_mutation("send_config", (0).to_bytes(4)) is False


def test_late_confirmation_does_not_authorize_next_connection(lan_env, monkeypatch):
    monkeypatch.setattr(lan, "_DEVICE_CONFIRM_TIMEOUT", 0.05)
    pending = []
    ready = threading.Event()

    def defer(device):
        pending.append(device["_confirm_id"])
        ready.set()

    old = lan.set_confirm_callback(defer)
    first = second = None
    try:
        first = connect(TEST_PORT)
        first_key = handshake(first)
        first.sendall(frame(first_key, {"cmd": "device_info", "name": "first"}))
        assert recv_frame(first, first_key)["approved"] is False
        assert ready.wait(1)
        first.close()

        second = connect(TEST_PORT)
        second_key = handshake(second)
        second.sendall(frame(second_key, {"cmd": "device_info", "name": "second"}))
        assert recv_frame(second, second_key)["approved"] is False
        lan.confirm_device(True, pending[0])
        second.sendall(frame(second_key, {"cmd": "ping"}))
        assert recv_frame(second, second_key) == {"ok": False, "error": "设备未授权"}
    finally:
        lan.set_confirm_callback(old)
        if first:
            first.close()
        if second:
            second.close()
