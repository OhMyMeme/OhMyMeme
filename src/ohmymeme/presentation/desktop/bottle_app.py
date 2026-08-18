"""Bottle 应用创建入口。"""

from .security import host_allowed


def install_security_hooks(app, bottle, port: int):
    """安装 localhost Origin/Host 防护和响应安全头。"""

    @app.hook("before_request")
    def guard_cross_origin():
        if not host_allowed(bottle.request.headers.get("Host", ""), port):
            bottle.abort(403, "Forbidden")
        if bottle.request.method == "POST":
            origin = bottle.request.headers.get("Origin", "")
            if origin and origin not in (
                f"http://127.0.0.1:{port}",
                f"http://localhost:{port}",
            ):
                bottle.abort(403, "Forbidden")
            if bottle.request.headers.get("Sec-Fetch-Site", "") == "cross-site":
                bottle.abort(403, "Forbidden")

    @app.hook("after_request")
    def set_security_headers():
        bottle.response.headers["X-Content-Type-Options"] = "nosniff"
        bottle.response.headers["Referrer-Policy"] = "no-referrer"
        bottle.response.headers["X-Frame-Options"] = "DENY"
        if bottle.request.path.startswith("/api/"):
            bottle.response.headers["Cache-Control"] = "no-store"
