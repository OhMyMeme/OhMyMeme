import hashlib
import http.server
import io
import os
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path

import ohmymeme_plugin_douyin as douyin
import ohmymeme_plugin_wechat as wechat
import pytest
from PIL import Image

from ohmymeme.core.adapters import fetch_policy as fetch_module
from ohmymeme.core.adapters.fetch_policy import (
    FetchLimitError,
    FetchPolicy,
    FetchRejected,
    validate_image_bytes,
)
from ohmymeme.integrations.imports import adb_qq
from ohmymeme.presentation.desktop import window_manager
from ohmymeme.services import updates


@dataclass
class FakeResponse:
    status: int
    body: bytes
    headers: dict[str, str]

    def read(self, size=-1):
        if size < 0:
            size = len(self.body)
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk

    def close(self):
        return None


class FakeResolver:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def resolve(self, hostname, port):
        self.calls.append((hostname, port))
        return self.answers.pop(0)


class FakeConnector:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.proxy_values = []

    def open(self, target, address, timeout, headers):
        self.calls.append((target, address, timeout, dict(headers)))
        self.proxy_values.append(
            tuple(
                os.environ.get(name)
                for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
            )
        )
        return self.responses.pop(0)


class FakeRedirect:
    def __init__(self, locations):
        self.locations = list(locations)

    def next_url(self, current_url, response):
        return self.locations.pop(0) if self.locations else None


class FakeCurlResponse:
    def __init__(self, status_code, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.cookies = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("status")


class FakeCurlSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def _png_bytes():
    output = __import__("io").BytesIO()
    Image.new("RGBA", (2, 2), (255, 0, 0, 255)).save(output, "PNG")
    return output.getvalue()


def test_policy_rejects_private_and_mapped_addresses():
    resolver = FakeResolver([["127.0.0.1"], ["::ffff:8.8.8.8"]])
    policy = FetchPolicy(resolver=resolver)

    with pytest.raises(FetchRejected):
        policy.fetch_bytes("https://public.example/image.png")
    with pytest.raises(FetchRejected):
        policy.fetch_bytes("https://public.example/image.png")


def test_policy_rejects_a_mixed_public_and_private_answer_set():
    resolver = FakeResolver([["93.184.216.34", "10.0.0.8"]])
    policy = FetchPolicy(resolver=resolver)

    with pytest.raises(FetchRejected):
        policy.fetch_bytes("https://public.example/image.png")


@pytest.mark.parametrize(
    "address",
    ["169.254.1.1", "224.0.0.1", "0.0.0.0", "192.0.2.1", "::1", "fe80::1"],
)
def test_policy_rejects_non_global_address_classes(address):
    policy = FetchPolicy(resolver=FakeResolver([[address]]))

    with pytest.raises(FetchRejected):
        policy.fetch_bytes("https://public.example/image.png")


def test_policy_rejects_loopback_before_real_local_http_server_receives_request():
    class Handler(http.server.BaseHTTPRequestHandler):
        request_count = 0

        def do_GET(self):
            type(self).request_count += 1
            self.send_response(200)
            self.end_headers()

        def log_message(self, format, *args):
            return None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        policy = FetchPolicy(resolver=FakeResolver([["127.0.0.1"]]))

        with pytest.raises(FetchRejected):
            policy.fetch_bytes("https://public.example/image.png")

        assert Handler.request_count == 0
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_policy_requires_exact_trusted_cdn_host_and_https_443():
    resolver = FakeResolver([["93.184.216.34"]])
    connector = FakeConnector([FakeResponse(200, _png_bytes(), {})])
    policy = FetchPolicy(resolver=resolver, connector=connector)

    assert (
        policy.fetch_bytes(
            "https://vweixinf.tc.qq.com/image",
            trusted_hosts={"vweixinf.tc.qq.com"},
            image=True,
        )
        == _png_bytes()
    )
    with pytest.raises(FetchRejected):
        policy.fetch_bytes(
            "http://vweixinf.tc.qq.com/image", trusted_hosts={"vweixinf.tc.qq.com"}
        )
    with pytest.raises(FetchRejected):
        policy.fetch_bytes(
            "https://evil.vweixinf.tc.qq.com/image",
            trusted_hosts={"vweixinf.tc.qq.com"},
        )


def test_policy_rejects_credentials_and_nonstandard_ports():
    policy = FetchPolicy(resolver=FakeResolver([["93.184.216.34"]]))

    with pytest.raises(FetchRejected):
        policy.fetch_bytes("https://user:pass@public.example/image.png")
    with pytest.raises(FetchRejected):
        policy.fetch_bytes("https://public.example:8443/image.png")


def test_policy_overrides_caller_host_header_with_approved_authority():
    resolver = FakeResolver([["93.184.216.34"]])
    connector = FakeConnector([FakeResponse(200, _png_bytes(), {})])
    policy = FetchPolicy(resolver=resolver, connector=connector)

    policy.fetch_bytes(
        "https://public.example/image.png",
        headers={"Host": "evil.example"},
    )

    assert connector.calls[0][3]["Host"] == "public.example"


def test_policy_uses_one_total_deadline_for_connect_and_read(monkeypatch):
    resolver = FakeResolver([["93.184.216.34"]])
    connector = FakeConnector([FakeResponse(200, b"ok", {})])
    policy = FetchPolicy(resolver=resolver, connector=connector)
    ticks = iter((100.0, 100.0, 129.0, 131.0))
    monkeypatch.setattr(fetch_module.time, "monotonic", lambda: next(ticks))

    with pytest.raises(fetch_module.FetchTimeout):
        policy.fetch_bytes("https://public.example/data")


def test_douyin_policy_request_pins_each_manual_redirect(monkeypatch):
    resolver = FakeResolver([["93.184.216.34"], ["93.184.216.35"]])
    policy = FetchPolicy(resolver=resolver)
    session = FakeCurlSession(
        [
            FakeCurlResponse(302, headers={"Location": "https://cdn.example/a.webp"}),
            FakeCurlResponse(200, content=_png_bytes()),
        ]
    )
    monkeypatch.setattr(douyin, "_FETCH_POLICY", policy)

    response = douyin._policy_request(session, "GET", "https://public.example/a.webp")

    assert response.status_code == 200
    assert [call[2]["resolve"] for call in session.calls] == [
        ["public.example:443:93.184.216.34"],
        ["cdn.example:443:93.184.216.35"],
    ]
    assert [call[2]["headers"]["Host"] for call in session.calls] == [
        "public.example",
        "cdn.example",
    ]
    assert all(call[2]["proxies"] == {} for call in session.calls)


def test_douyin_policy_request_rejects_https_downgrade_redirect(monkeypatch):
    resolver = FakeResolver([["93.184.216.34"]])
    policy = FetchPolicy(resolver=resolver)
    session = FakeCurlSession(
        [FakeCurlResponse(302, headers={"Location": "http://cdn.example/a.webp"})]
    )
    monkeypatch.setattr(douyin, "_FETCH_POLICY", policy)

    with pytest.raises(FetchRejected):
        douyin._policy_request(session, "GET", "https://public.example/a.webp")


def test_wechat_adapter_keeps_exact_cdn_policy_and_image_validation(monkeypatch):
    class BytePolicy:
        def __init__(self, body):
            self.body = body
            self.calls = []

        def prepare(self, url, trusted_hosts):
            self.calls.append((url, trusted_hosts))
            if "vweixinf.tc.qq.com" not in url:
                raise FetchRejected("untrusted")
            return None

        def fetch_bytes(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return self.body

    policy = BytePolicy(_png_bytes())
    monkeypatch.setattr(wechat, "_FETCH_POLICY", policy)

    assert wechat._url_allowed("https://vweixinf.tc.qq.com/image")
    assert not wechat._url_allowed("https://evil.example/image")
    assert wechat._download_sticker("https://vweixinf.tc.qq.com/image") == _png_bytes()
    assert policy.calls[-1][1]["trusted_hosts"] == wechat._WECHAT_CDN_HOSTS


def test_wechat_adapter_rejects_bad_image_bytes_without_returning_data(monkeypatch):
    class BytePolicy:
        def fetch_bytes(self, url, **kwargs):
            return b"not an image"

    monkeypatch.setattr(wechat, "_FETCH_POLICY", BytePolicy())

    assert wechat._download_sticker("https://vweixinf.tc.qq.com/image") is None


def test_wechat_adapter_rejects_metadata_md5_mismatch(monkeypatch):
    class BytePolicy:
        def fetch_bytes(self, url, **kwargs):
            return _png_bytes()

    monkeypatch.setattr(wechat, "_FETCH_POLICY", BytePolicy())

    assert (
        wechat._download_sticker(
            "https://vweixinf.tc.qq.com/image",
            expected_md5="0" * 32,
        )
        is None
    )


def test_wechat_adapter_accepts_matching_metadata_md5(monkeypatch):
    body = _png_bytes()

    class BytePolicy:
        def fetch_bytes(self, url, **kwargs):
            return body

    monkeypatch.setattr(wechat, "_FETCH_POLICY", BytePolicy())

    assert (
        wechat._download_sticker(
            "https://vweixinf.tc.qq.com/image",
            expected_md5=hashlib.md5(body).hexdigest(),
        )
        == body
    )


def test_storage_settings_image_download_uses_policy_and_cleans_staging(monkeypatch):
    class Config:
        def get(self, key, default=None):
            return True if key == "try_original_image" else default

    class Webui:
        def __init__(self):
            self.imported = []

        def _do_import(self, paths):
            self.imported.extend(paths)
            return {"ids": [7], "rejected": 0}

    class ImagePolicy:
        def fetch_bytes(self, url, **kwargs):
            assert url == "https://public.example/image.png"
            assert kwargs["image"] is True
            return _png_bytes()

    webui = Webui()
    api = object.__new__(window_manager.JsApi)
    api._cfg = Config()
    api._webui = webui
    monkeypatch.setattr(window_manager, "_FETCH_POLICY", ImagePolicy())
    monkeypatch.setattr(window_manager, "_check_connectivity", lambda: {"ok": True})

    result = api.download_original_image("https://public.example/image.png")

    assert result == {"ok": True, "id": 7}
    assert len(webui.imported) == 1
    assert not Path(webui.imported[0]).exists()


def test_updater_download_seam_uses_atomic_policy_destination(tmp_path, monkeypatch):
    class Policy:
        def download_to(self, url, destination, **kwargs):
            destination.write_bytes(b"release")
            if kwargs["progress"]:
                kwargs["progress"](7, 7)

    progress = []
    monkeypatch.setattr(updates, "_FETCH_POLICY", Policy())

    assert updates._try_download(
        "https://public.example/release.bin",
        str(tmp_path / "release.bin"),
        lambda done, size, total: progress.append((done, size, total)),
    ) == str(tmp_path / "release.bin")
    assert (tmp_path / "release.bin").read_bytes() == b"release"
    assert progress == [(0, 8192, 7)]
    assert not (tmp_path / "release.bin.fetching").exists()


def test_adb_download_seam_validates_zip_and_extracts_expected_binary(
    tmp_path, monkeypatch
):
    archive_data = io.BytesIO()
    with zipfile.ZipFile(archive_data, "w") as archive:
        archive.writestr("platform-tools/adb", b"adb")

    class Policy:
        def download_to(self, url, destination, **kwargs):
            destination.write_bytes(archive_data.getvalue())

    adb_dir = tmp_path / ".adb"
    monkeypatch.setitem(
        adb_qq._ADB_SHA256,
        "Windows",
        hashlib.sha256(archive_data.getvalue()).hexdigest(),
    )
    monkeypatch.setitem(
        adb_qq._ADB_BINARY_SHA256, "Windows", hashlib.sha256(b"adb").hexdigest()
    )
    monkeypatch.setattr(adb_qq, "_FETCH_POLICY", Policy())
    monkeypatch.setattr(adb_qq, "_get_adb_dir", lambda: adb_dir)
    monkeypatch.setattr(
        adb_qq, "_adb_download_url", lambda: "https://public.example/adb.zip"
    )
    monkeypatch.setattr(adb_qq, "_adb_binary_name", lambda: "adb")

    assert adb_qq._download_with_progress() == str(adb_dir / "platform-tools" / "adb")
    assert (adb_dir / "platform-tools" / "adb").read_bytes() == b"adb"


def test_adb_download_seam_rejects_zip_path_traversal(tmp_path, monkeypatch):
    archive_data = io.BytesIO()
    with zipfile.ZipFile(archive_data, "w") as archive:
        archive.writestr("../escape", b"bad")

    class Policy:
        def download_to(self, url, destination, **kwargs):
            destination.write_bytes(archive_data.getvalue())

    adb_dir = tmp_path / ".adb"
    monkeypatch.setattr(adb_qq, "_FETCH_POLICY", Policy())
    monkeypatch.setattr(adb_qq, "_get_adb_dir", lambda: adb_dir)
    monkeypatch.setattr(
        adb_qq, "_adb_download_url", lambda: "https://public.example/adb.zip"
    )

    assert adb_qq._download_with_progress() is False
    assert not (tmp_path / "escape").exists()
    assert not (adb_dir / "platform-tools.zip").exists()


def test_policy_pins_socket_peer_and_re_resolves_each_redirect():
    resolver = FakeResolver([["93.184.216.34"], ["93.184.216.35"]])
    connector = FakeConnector(
        [
            FakeResponse(302, b"", {"Location": "https://cdn.example/image.png"}),
            FakeResponse(200, _png_bytes(), {"Content-Length": "74"}),
        ]
    )
    policy = FetchPolicy(
        resolver=resolver,
        connector=connector,
        redirect=FakeRedirect(["https://cdn.example/image.png"]),
    )

    result = policy.fetch_bytes("https://public.example/image.png", image=True)

    assert result == _png_bytes()
    assert [call[1].ip for call in connector.calls] == [
        "93.184.216.34",
        "93.184.216.35",
    ]
    assert resolver.calls == [("public.example", 443), ("cdn.example", 443)]
    assert all(
        call[0].hostname in ("public.example", "cdn.example")
        for call in connector.calls
    )


def test_default_connectors_use_numeric_peer_and_original_tls_hostname(monkeypatch):
    class FakeSocket:
        def __init__(self):
            self.peer = None
            self.timeout = None

        def settimeout(self, value):
            self.timeout = value

        def connect(self, peer):
            self.peer = peer

        def close(self):
            return None

    class FakeContext:
        def __init__(self):
            self.hostname = None

        def wrap_socket(self, sock, server_hostname):
            self.hostname = server_hostname
            return sock

    http_socket = FakeSocket()
    monkeypatch.setattr(fetch_module.socket, "socket", lambda *args: http_socket)
    http_target = fetch_module.FetchTarget(
        "http", "public.example", 80, "public.example", "/"
    )
    http_address = fetch_module.ResolvedAddress(
        2, ("93.184.216.34", 80), "93.184.216.34"
    )
    http_connection = fetch_module._PinnedHTTPConnection(http_target, http_address, 10)
    http_connection.connect()
    assert http_socket.peer == ("93.184.216.34", 80)

    https_socket = FakeSocket()
    monkeypatch.setattr(fetch_module.socket, "socket", lambda *args: https_socket)
    https_target = fetch_module.FetchTarget(
        "https", "public.example", 443, "public.example", "/"
    )
    https_address = fetch_module.ResolvedAddress(
        2, ("93.184.216.35", 443), "93.184.216.35"
    )
    https_connection = fetch_module._PinnedHTTPSConnection(
        https_target, https_address, 10
    )
    context = FakeContext()
    https_connection._context = context
    https_connection.connect()
    assert https_socket.peer == ("93.184.216.35", 443)
    assert context.hostname == "public.example"


def test_direct_connector_reaches_real_local_http_server_with_authority_header():
    class Handler(http.server.BaseHTTPRequestHandler):
        request_count = 0
        received_host = ""

        def do_GET(self):
            type(self).request_count += 1
            type(self).received_host = self.headers.get("Host", "")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"local-ok")

        def log_message(self, format, *args):
            return None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        port = server.server_address[1]
        target = fetch_module.FetchTarget(
            "http", "127.0.0.1", port, f"127.0.0.1:{port}", "/"
        )
        address = fetch_module.ResolvedAddress(
            fetch_module.socket.AF_INET, ("127.0.0.1", port), "127.0.0.1"
        )
        response = fetch_module._DirectConnector().open(
            target, address, 10, {"Host": "evil.example"}
        )
        try:
            assert response.read() == b"local-ok"
        finally:
            response.close()
        assert Handler.request_count == 1
        assert Handler.received_host == f"127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_policy_ignores_proxy_environment_during_connector(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    resolver = FakeResolver([["93.184.216.34"]])
    connector = FakeConnector([FakeResponse(200, _png_bytes(), {})])
    policy = FetchPolicy(resolver=resolver, connector=connector)

    policy.fetch_bytes("https://public.example/image.png", image=True)

    assert connector.proxy_values == [(None, None, None)]
    assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:9"


def test_policy_rejects_oversize_and_bad_image_without_partial_result():
    resolver = FakeResolver([["93.184.216.34"], ["93.184.216.34"]])
    connector = FakeConnector(
        [
            FakeResponse(200, b"x" * (20 * 1024 * 1024 + 1), {}),
            FakeResponse(200, b"not an image", {}),
        ]
    )
    policy = FetchPolicy(resolver=resolver, connector=connector)

    with pytest.raises(FetchLimitError):
        policy.fetch_bytes("https://public.example/a.bin")
    with pytest.raises(FetchRejected):
        policy.fetch_bytes("https://public.example/a.png", image=True)


def test_validate_image_bytes_rejects_zero_dimension_and_accepts_magic():
    assert validate_image_bytes(_png_bytes()) == ".png"
    with pytest.raises(FetchRejected):
        validate_image_bytes(b"RIFF0000WEBP", max_pixels=2560)


def test_fake_ip_proxy_range_is_allowed_but_other_private_ranges_are_not():
    # Clash/Surge fake-IP 解析到 RFC 2544 基准网段时放行更新检查
    from ohmymeme.core.adapters import fetch_policy_validation as validation

    assert validation._safe_ip("198.18.0.7") is True
    assert validation._safe_ip("198.19.255.254") is True
    assert validation._safe_ip("8.8.8.8") is True
    assert validation._safe_ip("192.168.1.1") is False
    assert validation._safe_ip("10.0.0.1") is False
    assert validation._safe_ip("127.0.0.1") is False
    assert validation._safe_ip("169.254.1.1") is False
    assert validation._safe_ip("::ffff:198.18.0.7") is False
