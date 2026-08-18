from io import BytesIO
from wsgiref.util import setup_testing_defaults

import bottle

from ohmymeme.presentation.desktop.bottle_app import install_security_hooks


def _request(
    app,
    method,
    port,
    host,
    origin="",
    fetch_site="",
):
    environment = {}
    setup_testing_defaults(environment)
    environment["REQUEST_METHOD"] = method
    environment["PATH_INFO"] = "/api/probe"
    environment["SERVER_NAME"] = "127.0.0.1"
    environment["SERVER_PORT"] = str(port)
    environment["HTTP_HOST"] = host
    environment["HTTP_ORIGIN"] = origin
    environment["HTTP_SEC_FETCH_SITE"] = fetch_site
    environment["wsgi.input"] = BytesIO()
    captured = {}

    def start_response(status, headers, _exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app(environment, start_response))
    return captured, body


def _app(port):
    app = bottle.Bottle()
    install_security_hooks(app, bottle, port)

    @app.get("/api/probe")
    def probe():
        return {"ok": True}

    @app.post("/api/probe")
    def post_probe():
        return {"ok": True}

    return app


def test_security_hooks_allow_loopback_and_apply_api_headers():
    # Given: a local Bottle application with desktop security hooks
    app = _app(17852)

    # When: a loopback request reaches an API route
    result, body = _request(app, "GET", 17852, "localhost:17852")

    # Then: the route succeeds with all security headers
    assert result["status"].startswith("200")
    assert body == b'{"ok": true}'
    assert result["headers"]["X-Content-Type-Options"] == "nosniff"
    assert result["headers"]["Referrer-Policy"] == "no-referrer"
    assert result["headers"]["X-Frame-Options"] == "DENY"
    assert result["headers"]["Cache-Control"] == "no-store"


def test_security_hooks_reject_host_origin_and_cross_site_requests():
    # Given: a local Bottle application with desktop security hooks
    app = _app(17852)

    # When: untrusted request metadata is presented
    bad_host, _ = _request(app, "GET", 17852, "evil.example")
    bad_origin, _ = _request(app, "POST", 17852, "localhost:17852", "https://evil")
    cross_site, _ = _request(app, "POST", 17852, "localhost:17852", "", "cross-site")

    # Then: every untrusted form is forbidden
    assert bad_host["status"].startswith("403")
    assert bad_origin["status"].startswith("403")
    assert cross_site["status"].startswith("403")
