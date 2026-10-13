# pyright: basic

"""GitHub 仓库插件导入模块的离线测试（全部注入下载器，不发起真实网络）。"""

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ohmymeme.core.plugins.runtime import github_source, seeding

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _isolate_archive_cache():
    # 每个用例前后清空归档缓存，避免跨用例复用旧归档字节
    github_source.clear_cache()
    yield
    github_source.clear_cache()

CANONICAL_META = {
    "id": "source.qqnt",
    "name": "ohmymeme-plugin-qqnt",
    "entry": "ohmymeme_plugin_qqnt:create_plugin",
    "api_version": 1,
    "package_root": "ohmymeme_plugin_qqnt",
    "capabilities": ["filesystem.read", "import.submit"],
}

PACKAGE_SOURCE = (
    "class Provider:\n"
    '    provider_id = "source.qqnt"\n'
    "    api_version = 1\n"
    "\n"
    "    def start(self, context):\n"
    "        return True\n"
    "\n"
    "    def stop(self):\n"
    "        pass\n"
    "\n"
    "    def finish(self):\n"
    "        pass\n"
    "\n"
    "    def get_progress(self):\n"
    '        return {"status": "idle"}\n'
    "\n"
    "\n"
    "def create_plugin():\n"
    "    return Provider()\n"
)


# 构造一次 GitHub 归档：{repo}-{suffix}/plugins/{id}/ + 包目录 + LICENSE
def _build_archive(
    repo,
    plugin_id,
    layout="flat",
    meta_overrides=None,
    extra_entries=None,
    top_suffix="main",
):
    top = "%s-%s" % (repo.split("/")[-1], top_suffix)
    base = "%s/plugins/%s" % (top, plugin_id)
    meta = dict(CANONICAL_META)
    if meta_overrides:
        meta.update(meta_overrides)
    pkg = meta.get("package_root") or meta["entry"].split(":", 1)[0]
    members = {
        "%s/plugin.json"
        % base: json.dumps(meta, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        "%s/LICENSE" % base: b"MIT\n",
    }
    if layout == "flat":
        members["%s/%s/__init__.py" % (base, pkg)] = PACKAGE_SOURCE.encode("utf-8")
    elif layout == "src":
        members["%s/src/%s/__init__.py" % (base, pkg)] = PACKAGE_SOURCE.encode("utf-8")
    if extra_entries:
        members.update(extra_entries)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


# 返回恒定字节的注入下载器
def _constant_opener(data):
    def opener(url):
        return data

    return opener


# parse_repo 接受常见形态并拒绝非法值
@pytest.mark.parametrize(
    "value,expected",
    [
        ("owner/repo", "owner/repo"),
        ("OhMyMeme/OhMyMeme", "OhMyMeme/OhMyMeme"),
        ("https://github.com/owner/repo", "owner/repo"),
        ("https://github.com/owner/repo.git", "owner/repo"),
        ("https://github.com/owner/repo/tree/main", "owner/repo"),
    ],
)
def test_parse_repo_accepts(value, expected):
    assert github_source.parse_repo(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "owner", "owner/repo/extra", "owner /repo", "../repo", "own!er/repo"],
)
def test_parse_repo_rejects(value):
    with pytest.raises(seeding.PluginSeedError) as error:
        github_source.parse_repo(value)
    assert error.value.reason == "invalid_repo"


# 分支导入：元数据、带 sha 的 version_key 与嵌套落盘
def test_branch_import_and_install(tmp_path):
    archive = _build_archive("local/repo", "source.qqnt")
    fetched = github_source.fetch_plugin(
        "local/repo", None, "source.qqnt", opener=_constant_opener(archive)
    )
    assert fetched["meta"]["id"] == "source.qqnt"
    assert fetched["ref"] == "HEAD"
    assert fetched["ref_label"] == "main"
    assert fetched["tag"] is None
    assert fetched["version"] == "main"
    assert fetched["version_key"] == "main-%s" % fetched["tree_sha256"][:7]
    assert len(fetched["tree_sha256"]) == 16
    assert any(path.endswith("LICENSE") for path in fetched["license_paths"])

    data = tmp_path / "data"
    entry = github_source.install_plugin(data, fetched)
    assert entry["id"] == "source.qqnt"
    resolved = seeding.resolve_plugin(data, "source.qqnt")
    assert resolved["version"] == "main"
    package_dir = Path(resolved["package_dir"])
    assert (package_dir / "ohmymeme_plugin_qqnt" / "__init__.py").is_file()
    record = seeding.read_state(data)["plugins"]["source.qqnt"]["versions"][
        fetched["version_key"]
    ]
    assert record["kind"] == "source"
    assert record["package_root"] == "ohmymeme_plugin_qqnt"
    assert record["source"] == {
        "type": "github",
        "repo": "local/repo",
        "ref": "HEAD",
        "tree": fetched["tree_sha256"],
    }
    github_source.dispose(fetched)
    assert not Path(fetched["tmp_dir"]).exists()


# 兼容布局 src/{pkg}/ 也能定位并落盘
def test_src_layout_import_and_install(tmp_path):
    archive = _build_archive("local/repo", "source.qqnt", layout="src")
    fetched = github_source.fetch_plugin(
        "local/repo", None, "source.qqnt", opener=_constant_opener(archive)
    )
    assert (
        fetched["package_dir_src"]
        .replace("\\", "/")
        .endswith("/src/ohmymeme_plugin_qqnt")
    )
    data = tmp_path / "data"
    github_source.install_plugin(data, fetched)
    resolved = seeding.resolve_plugin(data, "source.qqnt")
    assert (Path(resolved["package_dir"]) / "ohmymeme_plugin_qqnt").is_dir()
    github_source.dispose(fetched)


# tag 导入：version 去前导 v 且无 sha 后缀
def test_tag_ref_import():
    archive = _build_archive("OhMyMeme/OhMyMeme", "source.qqnt")
    fetched = github_source.fetch_plugin(
        "OhMyMeme/OhMyMeme",
        "refs/tags/v1.2.3",
        "source.qqnt",
        opener=_constant_opener(archive),
    )
    assert fetched["tag"] == "v1.2.3"
    assert fetched["version"] == "1.2.3"
    assert fetched["version_key"] == "1.2.3"
    github_source.dispose(fetched)


# 官方仓库默认 ref 先试版本 tag，404 后回落 HEAD
def test_default_official_ref_falls_back_to_head():
    archive = _build_archive("OhMyMeme/OhMyMeme", "source.qqnt")
    seen = []

    def opener(url):
        seen.append(url)
        if "refs/tags/v9.9.9" in url:
            raise github_source.DownloadError("missing", status=404)
        return archive

    fetched = github_source.fetch_plugin(
        "OhMyMeme/OhMyMeme", None, "source.qqnt", app_version="9.9.9", opener=opener
    )
    assert fetched["ref"] == "HEAD"
    assert seen[0].endswith("/archive/refs/tags/v9.9.9.zip")
    assert seen[1].endswith("/archive/HEAD.zip")
    github_source.dispose(fetched)


# 缺少 plugins/{id} 子树
def test_missing_plugin_subtree():
    archive = _build_archive("local/repo", "source.qqnt")
    with pytest.raises(seeding.PluginSeedError) as error:
        github_source.fetch_plugin(
            "local/repo", None, "source.telegram", opener=_constant_opener(archive)
        )
    assert error.value.reason == "layout_mismatch"


# plugin.json id 与请求不符
def test_identity_mismatch():
    archive = _build_archive(
        "local/repo", "source.qqnt", meta_overrides={"id": "source.telegram"}
    )
    with pytest.raises(seeding.PluginSeedError) as error:
        github_source.fetch_plugin(
            "local/repo", None, "source.qqnt", opener=_constant_opener(archive)
        )
    assert error.value.reason == "identity_mismatch"


# 符号链接条目被拒绝且不留临时目录
def test_symlink_entry_rejected():
    top = "repo-main"
    base = "%s/plugins/source.qqnt" % top
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "%s/plugin.json" % base,
            json.dumps(CANONICAL_META, sort_keys=True),
        )
        info = zipfile.ZipInfo("%s/evil" % base)
        info.external_attr = 0o120000 << 16
        archive.writestr(info, "target")
    with pytest.raises(seeding.PluginSeedError) as error:
        github_source.fetch_plugin(
            "local/repo",
            None,
            "source.qqnt",
            opener=_constant_opener(buffer.getvalue()),
        )
    assert error.value.reason == "invalid_package"


# 归档超过上限被拒绝
def test_archive_too_large(monkeypatch):
    archive = _build_archive("local/repo", "source.qqnt")
    monkeypatch.setattr(github_source, "ARCHIVE_MAX_BYTES", 16)
    with pytest.raises(seeding.PluginSeedError) as error:
        github_source.fetch_plugin(
            "local/repo", None, "source.qqnt", opener=_constant_opener(archive)
        )
    assert error.value.reason == "too_large"


# 直连网络错误后按镜像前缀重试成功
def test_mirror_fallback_on_network_error():
    archive = _build_archive("local/repo", "source.qqnt")
    seen = []

    def opener(url):
        seen.append(url)
        if url.startswith("https://github.dpik.top/"):
            return archive
        raise github_source.DownloadError("offline", status=None)

    fetched = github_source.fetch_plugin(
        "local/repo", "HEAD", "source.qqnt", opener=opener
    )
    assert fetched["ref"] == "HEAD"
    assert seen[0] == "https://github.com/local/repo/archive/HEAD.zip"
    assert any(url.startswith("https://github.dpik.top/") for url in seen)
    github_source.dispose(fetched)


# 404 直接判 not_found 且不做镜像重试
def test_not_found_without_mirror_retry():
    seen = []

    def opener(url):
        seen.append(url)
        raise github_source.DownloadError("missing", status=404)

    with pytest.raises(seeding.PluginSeedError) as error:
        github_source.fetch_plugin("local/repo", "HEAD", "source.qqnt", opener=opener)
    assert error.value.reason == "not_found"
    assert seen == ["https://github.com/local/repo/archive/HEAD.zip"]


# 403 判 rate_limited
def test_rate_limited():
    def opener(url):
        raise github_source.DownloadError("slow down", status=403)

    with pytest.raises(seeding.PluginSeedError) as error:
        github_source.fetch_plugin("local/repo", "HEAD", "source.qqnt", opener=opener)
    assert error.value.reason == "rate_limited"


# 全部镜像均网络失败最终判 network
def test_network_error_after_all_mirrors():
    def opener(url):
        raise github_source.DownloadError("offline", status=None)

    with pytest.raises(seeding.PluginSeedError) as error:
        github_source.fetch_plugin("local/repo", "HEAD", "source.qqnt", opener=opener)
    assert error.value.reason == "network"


# dispose 幂等
def test_dispose_is_idempotent():
    archive = _build_archive("local/repo", "source.qqnt")
    fetched = github_source.fetch_plugin(
        "local/repo", None, "source.qqnt", opener=_constant_opener(archive)
    )
    github_source.dispose(fetched)
    github_source.dispose(fetched)
    assert not Path(fetched["tmp_dir"]).exists()


# 同一归档 URL 第二次获取命中缓存，不重复下载
def test_archive_cache_avoids_second_download():
    archive = _build_archive("cache/repo", "source.qqnt")
    calls = []

    def opener(url):
        calls.append(url)
        return archive

    first = github_source.fetch_plugin("cache/repo", None, "source.qqnt", opener=opener)
    second = github_source.fetch_plugin("cache/repo", None, "source.qqnt", opener=opener)
    assert len(calls) == 1
    assert first["tree_sha256"] == second["tree_sha256"]
    github_source.dispose(first)
    github_source.dispose(second)


def _call_app(app, path, payload):
    body = json.dumps(payload).encode("utf-8")
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "127.0.0.1",
        "SERVER_PORT": "17899",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_HOST": "127.0.0.1:17899",
    }
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status

    chunks = app(environ, start_response)
    data = b"".join(chunks)
    return int(captured["status"].split(" ", 1)[0]), json.loads(data.decode("utf-8"))


def _webui(tmp_path, container=None, drop_cache=None):
    from ohmymeme.presentation.desktop import window_manager as desktop

    namespace = SimpleNamespace(
        _port=17899,
        _html_dir=ROOT / "src/webui",
        _cfg=SimpleNamespace(data_dir=tmp_path),
    )
    if container is not None:
        namespace._container = container
    if drop_cache is not None:
        namespace._drop_worker_cache = drop_cache
    return desktop.WebUI.build_bottle_app(namespace)


# inspect 路由成功：返回预览字段并回收临时目录
def test_route_inspect_success(monkeypatch, tmp_path):
    fake = {
        "repo": "OhMyMeme/OhMyMeme",
        "ref": "refs/heads/main",
        "meta": {
            "id": "source.qqnt",
            "name": "QQNT",
            "entry": "ohmymeme_plugin_qqnt:create_plugin",
        },
        "version": "main",
        "tree_sha256": "0123456789abcdef",
    }
    monkeypatch.setattr(github_source, "fetch_plugin", lambda *a, **k: fake)
    disposed = []
    monkeypatch.setattr(
        github_source, "dispose", lambda fetched: disposed.append(fetched)
    )
    app = _webui(tmp_path)
    status, data = _call_app(
        app, "/api/plugins/github/inspect", {"plugin": "source.qqnt", "repo": "a/b"}
    )
    assert status == 200
    assert data == {
        "ok": True,
        "repo": "OhMyMeme/OhMyMeme",
        "ref": "refs/heads/main",
        "id": "source.qqnt",
        "name": "QQNT",
        "version": "main",
        "entry": "ohmymeme_plugin_qqnt:create_plugin",
        "official": True,
        "tree_sha256": "0123456789abcdef",
    }
    assert disposed == [fake]


# inspect 路由缺少插件 id 返回 400
def test_route_inspect_requires_plugin(tmp_path):
    app = _webui(tmp_path)
    status, data = _call_app(app, "/api/plugins/github/inspect", {"repo": "a/b"})
    assert status == 400
    assert data == {"ok": False, "error": "plugin id required"}


# inspect 路由把解析失败翻译为 400
def test_route_inspect_failure(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise seeding.PluginSeedError("layout_mismatch", "missing")

    monkeypatch.setattr(github_source, "fetch_plugin", boom)
    app = _webui(tmp_path)
    status, data = _call_app(
        app, "/api/plugins/github/inspect", {"plugin": "source.qqnt"}
    )
    assert status == 400
    assert data["ok"] is False
    assert "layout_mismatch" in data["error"]


# install 路由成功：安装后停止旧 worker 并回收临时目录
def test_route_install_success(monkeypatch, tmp_path):
    fake = {
        "repo": "OhMyMeme/OhMyMeme",
        "ref": "refs/tags/v1.2.3",
        "meta": {"id": "source.qqnt", "name": "QQNT", "entry": "x:create_plugin"},
        "version": "1.2.3",
        "tree_sha256": "0123456789abcdef",
    }
    monkeypatch.setattr(github_source, "fetch_plugin", lambda *a, **k: fake)
    monkeypatch.setattr(
        github_source,
        "install_plugin",
        lambda data_dir, fetched: {"id": "source.qqnt", "version": "1.2.3"},
    )
    disposed = []
    monkeypatch.setattr(
        github_source, "dispose", lambda fetched: disposed.append(fetched)
    )
    runtime = Mock()
    drop_cache = Mock()
    app = _webui(
        tmp_path,
        container=SimpleNamespace(plugin_runtime=runtime),
        drop_cache=drop_cache,
    )
    status, data = _call_app(
        app, "/api/plugins/github/install", {"plugin": "source.qqnt"}
    )
    assert status == 200
    assert data == {"ok": True, "plugin": "source.qqnt", "version": "1.2.3"}
    runtime.stop_plugin.assert_called_once_with("source.qqnt", "install")
    drop_cache.assert_called_once_with("source.qqnt")
    assert disposed == [fake]
