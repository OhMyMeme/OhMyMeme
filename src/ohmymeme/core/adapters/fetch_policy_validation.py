"""FetchPolicy 的 URL、地址、代理和内容校验。"""

import ipaddress
import os
import socket
import threading
from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from io import BytesIO
from urllib.parse import urljoin, urlsplit

from PIL import Image

from .fetch_policy import (
    FetchRejected,
    FetchTarget,
    ResolvedAddress,
    ResponsePort,
)

_PROXY_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_PROXY_LOCK = threading.RLock()
_FAKE_IP_RANGE = ipaddress.ip_network("198.18.0.0/15")


class _DefaultRedirect:
    def next_url(self, current_url: str, response: ResponsePort) -> str | None:
        if response.status not in (301, 302, 303, 307, 308):
            return None
        location = _header(response.headers, "location")
        if not location:
            raise FetchRejected("redirect without location")
        return urljoin(current_url, location)


def _header(headers: Mapping[str, str], name: str) -> str:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return ""


def _address(raw: ResolvedAddress | str) -> ResolvedAddress:
    if isinstance(raw, ResolvedAddress):
        return raw
    ip = ipaddress.ip_address(raw)
    family = socket.AF_INET if ip.version == 4 else socket.AF_INET6
    sockaddr: tuple[str, int] | tuple[str, int, int, int]
    if family == socket.AF_INET:
        sockaddr = (str(ip), 0)
    else:
        sockaddr = (str(ip), 0, 0, 0)
    return ResolvedAddress(family, sockaddr, str(ip))


def _safe_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError as error:
        raise FetchRejected("resolver returned invalid address") from error
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return False
    if ip.version == 4 and ip in _FAKE_IP_RANGE:
        # Clash/Surge 等代理的 fake-IP 会把公网域名解析到 RFC 2544 基准网段
        return True
    return bool(
        ip.is_global
        and not ip.is_loopback
        and not ip.is_private
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def _parse_target(url: str, trusted_hosts: Collection[str]) -> FetchTarget:
    if len(url) > 8192 or any(ord(char) < 32 for char in url):
        raise FetchRejected("url rejected")
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
        port = parts.port
    except ValueError as error:
        raise FetchRejected("malformed url") from error
    if parts.scheme not in ("http", "https") or not hostname:
        raise FetchRejected("url scheme or host rejected")
    if parts.username is not None or parts.password is not None or parts.fragment:
        raise FetchRejected("url credentials or fragment rejected")
    if port is None:
        port = 443 if parts.scheme == "https" else 80
    if port not in (80, 443) or (
        trusted_hosts and (parts.scheme, port) != ("https", 443)
    ):
        raise FetchRejected("url port rejected")
    hostname = hostname.lower()
    if trusted_hosts and hostname not in {host.lower() for host in trusted_hosts}:
        raise FetchRejected("host is not trusted")
    request_target = parts.path or "/"
    if parts.query:
        request_target += "?" + parts.query
    return FetchTarget(parts.scheme, hostname, port, parts.netloc, request_target)


@contextmanager
def proxy_bypass() -> Iterator[None]:
    """在直接连接期间暂时屏蔽所有环境代理，并在退出时恢复。"""
    with _PROXY_LOCK:
        saved = {name: os.environ.pop(name, None) for name in _PROXY_NAMES}
        try:
            yield
        finally:
            for name, value in saved.items():
                if value is not None:
                    os.environ[name] = value


def select_address(resolver, target: FetchTarget) -> ResolvedAddress:
    try:
        answers = resolver.resolve(target.hostname, target.port)
    except socket.gaierror as error:
        raise FetchRejected("host resolution failed") from error
    selected: ResolvedAddress | None = None
    for raw in answers:
        address = _address(raw)
        if not _safe_ip(address.ip):
            raise FetchRejected("resolver returned unsafe address")
        if len(address.sockaddr) == 2:
            address = ResolvedAddress(
                address.family, (address.ip, target.port), address.ip
            )
        else:
            address = ResolvedAddress(
                address.family,
                (address.ip, target.port, address.sockaddr[2], address.sockaddr[3]),
                address.ip,
            )
        if selected is None:
            selected = address
    if selected is None:
        raise FetchRejected("no globally routable address")
    return selected


def validate_image_bytes(data: bytes, max_pixels: int = 2560) -> str:
    """校验图片魔数、Pillow 解码和最长边限制，返回规范扩展名。"""
    signatures = (
        (b"\x89PNG\r\n\x1a\n", ".png"),
        (b"\xff\xd8\xff", ".jpg"),
        (b"GIF87a", ".gif"),
        (b"GIF89a", ".gif"),
        (b"BM", ".bmp"),
    )
    extension = ""
    for signature, candidate in signatures:
        if data.startswith(signature):
            extension = candidate
            break
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        extension = ".webp"
    if not extension:
        raise FetchRejected("image magic rejected")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
    except (OSError, SyntaxError, ValueError) as error:
        raise FetchRejected("image decode rejected") from error
    if width <= 0 or height <= 0 or max(width, height) > max_pixels:
        raise FetchRejected("image dimensions rejected")
    return extension
