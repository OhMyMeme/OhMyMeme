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
        # 插件详情沙箱 iframe 需要允许同源嵌入，其余响应保持 DENY
        frame_asset = (
            bottle.request.path.startswith("/api/plugins/")
            and "/ui/" in bottle.request.path
        )
        bottle.response.headers["X-Frame-Options"] = (
            "SAMEORIGIN" if frame_asset else "DENY"
        )
        if bottle.request.path.startswith("/api/"):
            bottle.response.headers["Cache-Control"] = "no-store"


def create_bottle_app(owner, bottle, native=None):
    """从 WebUI 实例构建完整 WSGI 应用（不启动服务器；bottle/native 为调用方形参）。"""
    return owner.build_bottle_app()
