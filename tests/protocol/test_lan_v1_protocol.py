import json
import struct

import pytest
from cryptography.exceptions import InvalidTag

from ohmymeme.services.lan import protocol as lan_protocol


class FakeSocket:
    def __init__(self, data):
        self.data = bytearray(data)
        self.read_sizes = []

    def recv(self, size):
        self.read_sizes.append(size)
        chunk = self.data[:size]
        del self.data[:size]
        return bytes(chunk)


def recv_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise OSError("连接关闭")
        data.extend(chunk)
    return bytes(data)


def test_plain_frame_matches_v1_oracle():
    payload = lan_protocol.encode_plain({"t": "ok"})

    def decode(size):
        return payload[:size] if size == 4 else payload[4:]

    assert payload == b'\x00\x00\x00\x0b{"t": "ok"}'
    assert lan_protocol.decode_plain(decode) == {"t": "ok"}


def test_plain_frame_rejects_oversize_before_reading_body():
    sock = FakeSocket(struct.pack(">I", lan_protocol.MAX_FRAME + 1))

    with pytest.raises(ValueError, match="帧过大"):
        lan_protocol.decode_plain(lambda size: recv_exact(sock, size))

    assert sock.read_sizes == [4]


def test_plain_frame_rejects_truncated_body():
    sock = FakeSocket(struct.pack(">I", 4) + b"{}")

    with pytest.raises(OSError, match="连接关闭"):
        lan_protocol.decode_plain(lambda size: recv_exact(sock, size))


def test_encrypted_frame_rejects_too_short_body():
    sock = FakeSocket(struct.pack(">I", lan_protocol.IV_LEN + lan_protocol.TAG_LEN - 1))

    with pytest.raises(ValueError, match="帧长度非法"):
        lan_protocol.decode_frame(lambda size: recv_exact(sock, size), b"k" * 32)

    assert sock.read_sizes == [4]


def test_encrypted_frame_rejects_tampered_ciphertext(monkeypatch):
    monkeypatch.setattr(
        lan_protocol.os, "urandom", lambda _: b"i" * lan_protocol.IV_LEN
    )
    payload = bytearray(lan_protocol.encode_frame(b"k" * 32, {"cmd": "ping"}))
    payload[-1] ^= 1
    sock = FakeSocket(payload)

    with pytest.raises(InvalidTag):
        lan_protocol.decode_frame(lambda size: recv_exact(sock, size), b"k" * 32)


def test_oracle_fixture_has_only_v1_wire_fields():
    with open("tests/fixtures/lan-v1-oracle.json", encoding="utf-8") as source:
        oracle = json.load(source)

    assert oracle["discovery_response_fields"] == [
        "t",
        "name",
        "os",
        "ver",
        "need_secret",
    ]
    assert oracle["secret_handshake"] == ["challenge", "proof", "ok"]
