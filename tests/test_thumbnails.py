"""缩略图统一命名（{sha256}.webp）测试

核心保障：产物为 WebP 且按 sha 命名、旧命名迁移幂等清除、
/api/thumb/<sha256> 路由做 sha 格式校验并按缓存/现生成分流。
"""

import io

import pytest
from PIL import Image

from src import webui


class _Cfg:
    def __init__(self, tmp_path):
        self.data_dir = tmp_path / "data"
        self.cache_dir = tmp_path / "cache"
        self.thumbnail_dir = tmp_path / "thumbnails"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.thumbnail_dir.mkdir(parents=True, exist_ok=True)
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeDb:
    def __init__(self):
        self.rows = {}

    def get_by_hash(self, file_hash):
        return self.rows.get(file_hash)


@pytest.fixture
def env(tmp_path):
    """跳过 WebUI.__init__（避免真实 config/端口），仅注入 _cfg/_port"""
    cfg = _Cfg(tmp_path)
    ui = webui.WebUI.__new__(webui.WebUI)
    ui._cfg = cfg
    ui._port = 17999
    return ui, cfg


def test_migrate_removes_legacy_and_keeps_new(env):
    ui, cfg = env
    (cfg.thumbnail_dir / "12_150.png").write_bytes(b"x")
    (cfg.thumbnail_dir / "12_128.png").write_bytes(b"x")
    (cfg.thumbnail_dir / "abc.tmp").write_bytes(b"x")
    sha = "a" * 64
    (cfg.thumbnail_dir / f"{sha}.webp").write_bytes(b"RIFF0000WEBPdata")

    removed = webui._migrate_thumbnails(cfg.thumbnail_dir)

    assert removed == 3
    assert [f.name for f in cfg.thumbnail_dir.iterdir()] == [f"{sha}.webp"]
    assert webui._migrate_thumbnails(cfg.thumbnail_dir) == 0


def test_migrate_missing_dir_returns_zero(tmp_path):
    assert webui._migrate_thumbnails(tmp_path / "not_exists") == 0


def test_thumbnail_path_is_hash_webp(env):
    ui, cfg = env
    src = cfg.cache_dir / "meme.png"
    Image.new("RGB", (300, 200), (10, 20, 30)).save(src)
    sha = "b" * 64

    path = ui._get_thumbnail_path(sha, "meme.png")

    assert path == str(cfg.thumbnail_dir / f"{sha}.webp")
    data = open(path, "rb").read()
    assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    img = Image.open(io.BytesIO(data))
    assert max(img.size) <= 150
    src.unlink()
    assert ui._get_thumbnail_path(sha, "meme.png") == path  # 命中缓存不再读源文件


def test_thumbnail_keeps_alpha(env):
    ui, cfg = env
    src = cfg.cache_dir / "alpha.png"
    Image.new("RGBA", (64, 64), (255, 0, 0, 128)).save(src)
    sha = "c" * 64

    path = ui._get_thumbnail_path(sha, "alpha.png")

    img = Image.open(path)
    assert "A" in img.getbands()


def test_thumbnail_missing_source_returns_empty(env):
    ui, cfg = env
    assert ui._get_thumbnail_path("d" * 64, "nope.png") == ""


class _FakePagedDb:
    def __init__(self, rows):
        self.rows = rows

    def get_all(self, offset=0, limit=100):
        return self.rows[offset : offset + limit]


def test_ensure_local_thumbs_respects_switch(env, monkeypatch):
    ui, cfg = env
    monkeypatch.setattr(
        webui, "get_db", lambda: (_ for _ in ()).throw(AssertionError("不应触库"))
    )
    assert ui.ensure_local_thumbs() == 0


def test_ensure_local_thumbs_generates_missing(env, monkeypatch):
    ui, cfg = env
    cfg.values["cloud_direct"] = True
    Image.new("RGB", (64, 64), (1, 2, 3)).save(cfg.cache_dir / "b.png")
    sha_done = "a" * 64
    sha_new = "b" * 64
    (cfg.thumbnail_dir / f"{sha_done}.webp").write_bytes(b"RIFF0000WEBPdone")
    rows = [
        {"filename": "b.png", "file_hash": sha_done},
        {"filename": "b.png", "file_hash": sha_new},
        {"filename": "ghost.png", "file_hash": "c" * 64},  # 无源文件 → 跳过
    ]
    monkeypatch.setattr(webui, "get_db", lambda: _FakePagedDb(rows))

    assert ui.ensure_local_thumbs() == 1
    assert (cfg.thumbnail_dir / f"{sha_new}.webp").exists()
    assert not (cfg.thumbnail_dir / f"{'c' * 64}.webp").exists()
    assert ui.ensure_local_thumbs() == 0  # 第二次无缺失


def _build_app(monkeypatch, ui):
    captured = {}
    monkeypatch.setattr(
        webui.bottle, "run", lambda app, **kw: captured.setdefault("app", app)
    )
    ui._setup_bottle()
    return captured["app"]


def _request(app, path, port=17999):
    from wsgiref.util import setup_testing_defaults

    environ = {}
    setup_testing_defaults(environ)
    environ["REQUEST_METHOD"] = "GET"
    environ["PATH_INFO"] = path
    environ["HTTP_HOST"] = f"127.0.0.1:{port}"
    environ["SERVER_PORT"] = str(port)
    status = []

    def start_response(s, headers, exc_info=None):
        status.append(s)
        return lambda data: None

    body = b"".join(app(environ, start_response))
    return status[0], body


def test_thumb_route_rejects_bad_sha(monkeypatch, env):
    ui, cfg = env
    app = _build_app(monkeypatch, ui)
    for bad in ("not-a-sha", "Z" * 64, "e" * 63, "e" * 65):
        status, _ = _request(app, f"/api/thumb/{bad}")
        assert status.startswith("404"), bad
    status, _ = _request(app, "/api/thumb/../../etc/passwd")
    assert status.startswith("404")


def test_thumb_route_serves_cached(monkeypatch, env):
    ui, cfg = env
    sha = "e" * 64
    payload = b"RIFF0000WEBPdata"
    (cfg.thumbnail_dir / f"{sha}.webp").write_bytes(payload)
    monkeypatch.setattr(webui, "get_db", lambda: _FakeDb())
    app = _build_app(monkeypatch, ui)

    status, body = _request(app, f"/api/thumb/{sha}")

    assert status.startswith("200")
    assert body == payload


def test_thumb_route_generates_from_source(monkeypatch, env):
    ui, cfg = env
    src = cfg.cache_dir / "gen.png"
    Image.new("RGB", (300, 200), (5, 6, 7)).save(src)
    sha = "f" * 64
    fake_db = _FakeDb()
    fake_db.rows[sha] = {"filename": "gen.png"}
    monkeypatch.setattr(webui, "get_db", lambda: fake_db)
    app = _build_app(monkeypatch, ui)

    status, body = _request(app, f"/api/thumb/{sha}")

    assert status.startswith("200")
    assert body[:4] == b"RIFF" and body[8:12] == b"WEBP"
    assert (cfg.thumbnail_dir / f"{sha}.webp").exists()


def test_thumb_route_404_when_unknown(monkeypatch, env):
    ui, cfg = env
    monkeypatch.setattr(webui, "get_db", lambda: _FakeDb())
    app = _build_app(monkeypatch, ui)

    status, _ = _request(app, f"/api/thumb/{'1' * 64}")

    assert status.startswith("404")


def _make_gif(path, frames=4, size=(80, 60), duration=40):
    imgs = [Image.new("RGB", size, (i * 40 % 255, 10, 10)) for i in range(frames)]
    imgs[0].save(
        path, save_all=True, append_images=imgs[1:], duration=duration, loop=0
    )


def _webp_frame_durations(path):
    """解析 WebP 容器 ANMF 块的逐帧延时（Pillow 读回不暴露 webp duration）"""
    data = open(path, "rb").read()
    durs = []
    i = 12  # RIFF(4)+size(4)+WEBP(4)
    while i + 8 <= len(data):
        fourcc = data[i : i + 4]
        size = int.from_bytes(data[i + 4 : i + 8], "little")
        payload = i + 8
        if fourcc == b"ANMF":
            durs.append(int.from_bytes(data[payload + 12 : payload + 15], "little"))
        i = payload + size + (size & 1)
    return durs


def test_animated_gif_thumb_is_animated_webp(env):
    ui, cfg = env
    _make_gif(cfg.cache_dir / "anim.gif", frames=4, duration=40)
    sha = "a1" * 32

    path = ui._get_thumbnail_path(sha, "anim.gif")

    assert path == str(cfg.thumbnail_dir / f"{sha}.webp")
    img = Image.open(path)
    assert img.format == "WEBP"
    assert img.n_frames == 4
    assert max(img.size) <= 150
    assert img.info.get("loop") == 0
    assert _webp_frame_durations(path) == [40, 40, 40, 40]


def test_animated_webp_thumb_is_animated(env):
    ui, cfg = env
    src = cfg.cache_dir / "anim.webp"
    imgs = [Image.new("RGB", (60, 60), (i * 30 % 255, 5, 5)) for i in range(3)]
    imgs[0].save(src, save_all=True, append_images=imgs[1:], duration=30, loop=0)
    sha = "a2" * 32

    img = Image.open(ui._get_thumbnail_path(sha, "anim.webp"))
    assert img.n_frames == 3


def test_single_frame_gif_thumb_stays_static(env):
    ui, cfg = env
    _make_gif(cfg.cache_dir / "one.gif", frames=1)
    sha = "a3" * 32

    img = Image.open(ui._get_thumbnail_path(sha, "one.gif"))
    assert img.n_frames == 1


def test_ensure_local_thumbs_rebuilds_stale_static(env, monkeypatch):
    """源为动图但缩略图是静态旧产物 → ensure 重建为动画 WebP，幂等"""
    ui, cfg = env
    cfg.values["cloud_direct"] = True
    _make_gif(cfg.cache_dir / "g.gif", frames=3, duration=50)
    sha = "b1" * 32
    Image.new("RGB", (64, 64), (1, 2, 3)).save(
        cfg.thumbnail_dir / f"{sha}.webp", "WEBP"
    )
    rows = [{"filename": "g.gif", "file_hash": sha}]
    monkeypatch.setattr(webui, "get_db", lambda: _FakePagedDb(rows))

    assert ui.ensure_local_thumbs() == 1
    img = Image.open(cfg.thumbnail_dir / f"{sha}.webp")
    assert img.n_frames == 3
    assert ui.ensure_local_thumbs() == 0
