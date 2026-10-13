# pyright: basic

import socket
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_fixtures import install_official  # noqa: E402

from ohmymeme.app.operation_coordinator import OperationCoordinator
from ohmymeme.core.domain import TaskKind, TaskState
from ohmymeme.services.lan import protocol
from ohmymeme.services.lan.server import HAS_AESGCM, LanServer


def _recv_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("closed")
        data.extend(chunk)
    return bytes(data)


def _connect(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    sock.connect(("127.0.0.1", port))
    assert protocol.decode_plain(lambda size: _recv_exact(sock, size)) == {"t": "ok"}
    return sock


def _assert_closed(sock):
    while sock.recv(4096):
        pass


@pytest.mark.skipif(not HAS_AESGCM, reason="cryptography is unavailable")
def test_lan_service_shutdown_owns_multiple_sessions_and_confirmation_waits(
    tmp_path,
):
    # Given: a coordinator-owned server with two unapproved device sessions
    from ohmymeme.core.plugins.runtime import PluginRuntimeManager

    coordinator = OperationCoordinator()
    runtime = PluginRuntimeManager(tmp_path / "runtime")
    install_official(tmp_path / "runtime", "transport.lan")
    server = LanServer(coordinator=coordinator, plugin_runtime=runtime)
    pending = threading.Event()
    confirm_ids = []

    def defer_confirmation(device):
        confirm_ids.append(device["_confirm_id"])
        if len(confirm_ids) == 2:
            pending.set()

    server.set_confirm_callback(defer_confirmation)
    first = second = None
    try:
        assert server.start(0, "")
        first = _connect(server.port)
        second = _connect(server.port)
        key = protocol.derive_key("")
        first.sendall(
            protocol.encode_frame(key, {"cmd": "device_info", "name": "first"})
        )
        second.sendall(
            protocol.encode_frame(key, {"cmd": "device_info", "name": "second"})
        )
        assert pending.wait(1)

        # When: host shutdown cancels the LAN operation under one deadline
        report = coordinator.shutdown(timeout=1, child_grace=0.01)

        # Then: sockets, sessions, and confirmation waits are drained by the coordinator
        snapshot = coordinator.query(TaskKind.LAN_SERVICE)
        assert snapshot is not None
        assert snapshot.state is TaskState.CANCELLED
        assert not report.timed_out
        assert report.inventory.sockets == ()
        assert server._threads == []
        assert server._pending_confirms == {}
        _assert_closed(first)
        _assert_closed(second)
    finally:
        if first is not None:
            first.close()
        if second is not None:
            second.close()
        server.stop()
        runtime.shutdown()
