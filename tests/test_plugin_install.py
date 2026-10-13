# pyright: basic

"""第三方插件 ZIP 安装/卸载与包安全测试。"""

import io
import json
import zipfile

import pytest
from plugin_fixtures import install_official

from ohmymeme.core.plugins.runtime import seeding


def _write_zip(path, members):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def _meta(**overrides):
    meta = {
        "id": "community.demo",
        "name": "Demo",
        "version": "1.0.0",
        "entry": "demo_plugin:create_plugin",
    }
    meta.update(overrides)
    return json.dumps(meta)


def test_install_plugin_extracts_and_registers(tmp_path):
    data = tmp_path / "data"
    package = _write_zip(
        tmp_path / "demo.zip",
        {"plugin.json": _meta(), "demo_plugin.py": "def create_plugin():\n    pass\n"},
    )
    entry = seeding.install_plugin(data, package)
    assert entry["id"] == "community.demo"
    assert entry["version"] == "1.0.0"
    assert seeding.resolve_plugin(data, "community.demo")["entry"] == (
        "demo_plugin:create_plugin"
    )
    assert (
        seeding.plugins_dir(data) / "community.demo" / "1.0.0" / "demo_plugin.py"
    ).is_file()
    assert seeding.installed_plugins(data)[0]["name"] == "Demo"


def test_install_plugin_update_switches_active_version(tmp_path):
    data = tmp_path / "data"
    first = _write_zip(
        tmp_path / "a.zip", {"plugin.json": _meta(), "demo_plugin.py": "x = 1\n"}
    )
    second = _write_zip(
        tmp_path / "b.zip",
        {"plugin.json": _meta(version="2.0.0"), "demo_plugin.py": "x = 2\n"},
    )
    seeding.install_plugin(data, first)
    entry = seeding.install_plugin(data, second)
    assert entry["version"] == "2.0.0"
    assert (seeding.plugins_dir(data) / "community.demo" / "1.0.0").is_dir()


def test_activate_version_rolls_back_and_forward(tmp_path):
    data = tmp_path / "data"
    for version in ("1.0.0", "2.0.0"):
        seeding.install_plugin(
            data,
            _write_zip(
                tmp_path / (version + ".zip"),
                {"plugin.json": _meta(version=version), "demo_plugin.py": "x = 1\n"},
            ),
        )
    assert seeding.installed_plugins(data)[0]["versions"] == ["1.0.0", "2.0.0"]
    assert seeding.activate_version(data, "community.demo", "1.0.0")["version"] == (
        "1.0.0"
    )
    assert seeding.activate_version(data, "community.demo", "2.0.0")["version"] == (
        "2.0.0"
    )
    with pytest.raises(seeding.PluginSeedError) as error:
        seeding.activate_version(data, "community.demo", "9.9.9")
    assert error.value.reason == "plugin_missing"


@pytest.mark.parametrize(
    "meta,reason",
    [
        (_meta(id=""), "invalid_plugin_id"),
        (_meta(version="../escape"), "invalid_version"),
        (_meta(entry="demo_plugin"), "invalid_entry"),
    ],
)
def test_install_plugin_rejects_invalid_metadata(tmp_path, meta, reason):
    data = tmp_path / "data"
    package = _write_zip(tmp_path / "bad.zip", {"plugin.json": meta})
    with pytest.raises(seeding.PluginSeedError) as error:
        seeding.install_plugin(data, package)
    assert error.value.reason == reason


def _official_meta(**overrides):
    meta = {
        "id": "source.qqnt",
        "name": "ohmymeme-plugin-qqnt",
        "version": "1.2.3",
        "entry": "ohmymeme_plugin_qqnt:create_plugin",
        "api_version": 1,
        "package_root": "ohmymeme_plugin_qqnt",
        "capabilities": ["filesystem.read", "import.submit"],
    }
    meta.update(overrides)
    return meta


# 官方 ZIP 安装成功并记录 kind/package_root/capabilities
def test_install_official_zip_records_identity(tmp_path):
    data = tmp_path / "data"
    entry = install_official(data, "source.qqnt", version="0.0.0-test")
    assert entry["kind"] == "source"
    assert entry["package_root"] == "ohmymeme_plugin_qqnt"
    assert entry["capabilities"] == ("filesystem.read", "import.submit")
    version_dir = seeding.plugins_dir(data) / "source.qqnt" / "0.0.0-test"
    assert (version_dir / "ohmymeme_plugin_qqnt" / "__init__.py").is_file()
    record = seeding.read_state(data)["plugins"]["source.qqnt"]["versions"][
        "0.0.0-test"
    ]
    assert record["origin"] == "installed"
    assert record["kind"] == "source"
    assert record["package_root"] == "ohmymeme_plugin_qqnt"
    assert record["capabilities"] == ["filesystem.read", "import.submit"]


# 官方 ID 入口不符被拒且不留残留
def test_install_official_rejects_bad_entry(tmp_path):
    data = tmp_path / "data"
    package = _write_zip(
        tmp_path / "bad.zip",
        {"plugin.json": json.dumps(_official_meta(entry="wrong_pkg:create_plugin"))},
    )
    with pytest.raises(seeding.PluginSeedError) as error:
        seeding.install_plugin(data, package)
    assert error.value.reason == "official_identity_mismatch"
    assert not (seeding.plugins_dir(data) / "source.qqnt").exists()
    assert "source.qqnt" not in seeding.read_state(data)["plugins"]


# 官方 ID capabilities 或 api_version 不符被拒
@pytest.mark.parametrize(
    "overrides",
    [
        {"capabilities": ["filesystem.read"]},
        {"capabilities": ["import.submit", "filesystem.read"]},
        {"api_version": 2},
    ],
)
def test_install_official_rejects_identity_fields(tmp_path, overrides):
    data = tmp_path / "data"
    package = _write_zip(
        tmp_path / "bad.zip",
        {"plugin.json": json.dumps(_official_meta(**overrides))},
    )
    with pytest.raises(seeding.PluginSeedError) as error:
        seeding.install_plugin(data, package)
    assert error.value.reason == "official_identity_mismatch"
    assert not (seeding.plugins_dir(data) / "source.qqnt").exists()


# 第三方 api_version 不符单独拒绝
def test_install_third_party_rejects_api_version(tmp_path):
    data = tmp_path / "data"
    package = _write_zip(tmp_path / "bad.zip", {"plugin.json": _meta(api_version=2)})
    with pytest.raises(seeding.PluginSeedError) as error:
        seeding.install_plugin(data, package)
    assert error.value.reason == "invalid_api_version"


# 清理旧 bundled 记录与目录，保留 installed
def test_purge_legacy_bundled_clears_only_bundled(tmp_path):
    data = tmp_path / "data"
    install_official(data, "source.qqnt", version="0.0.0-test")
    state = seeding.read_state(data)
    state["plugins"]["source.telegram"] = {
        "origin": "bundled",
        "active": "0.6.3",
        "versions": {"0.6.3": {"version": "0.6.3"}},
    }
    seeding.write_state(data, state)
    bundled_dir = seeding.plugins_dir(data) / "source.telegram" / "0.6.3"
    bundled_dir.mkdir(parents=True)
    (bundled_dir / "legacy.py").write_text("x = 1\n", encoding="utf-8")
    purged = seeding.purge_legacy_bundled(data)
    assert purged == ["source.telegram"]
    assert not (seeding.plugins_dir(data) / "source.telegram").exists()
    assert "source.qqnt" in seeding.read_state(data)["plugins"]
    assert seeding.purge_legacy_bundled(data) == []


def test_install_plugin_extracts_hardened_zip_without_escaping(tmp_path):
    # 不做包安全校验；解压穿越由标准库扁平化，文件不会逃出插件目录
    data = tmp_path / "data"
    package = _write_zip(
        tmp_path / "flat.zip",
        {"plugin.json": _meta(), "../escape.py": "x = 1\n"},
    )
    entry = seeding.install_plugin(data, package)
    version_dir = seeding.plugins_dir(data) / entry["id"] / entry["version"]
    assert (version_dir / "escape.py").is_file()
    assert not (tmp_path / "escape.py").exists()


def test_uninstall_plugin_removes_third_party_and_official(tmp_path):
    data = tmp_path / "data"
    package = _write_zip(
        tmp_path / "demo.zip", {"plugin.json": _meta(), "demo_plugin.py": "x = 1\n"}
    )
    seeding.install_plugin(data, package)
    assert seeding.uninstall_plugin(data, "community.demo") is True
    assert not (seeding.plugins_dir(data) / "community.demo").exists()
    with pytest.raises(seeding.PluginSeedError) as error:
        seeding.resolve_plugin(data, "community.demo")
    assert error.value.reason == "plugin_missing"
    with pytest.raises(seeding.PluginSeedError) as error:
        seeding.uninstall_plugin(data, "source.qqnt")
    assert error.value.reason == "plugin_missing"
    install_official(data, "source.qqnt", version="0.0.0-test")
    assert seeding.uninstall_plugin(data, "source.qqnt") is True
    assert not (seeding.plugins_dir(data) / "source.qqnt").exists()


# 以 WSGI 直调方式 POST 原始字节或 JSON
def _post_request(app, port, path, body, content_type="application/json"):
    environ = {
        "REQUEST_METHOD": "POST",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "127.0.0.1",
        "SERVER_PORT": str(port),
        "SERVER_PROTOCOL": "HTTP/1.1",
        "HTTP_HOST": "127.0.0.1:%s" % port,
    }
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status

    chunks = app(environ, start_response)
    data = b"".join(chunks)
    return int(captured["status"].split(" ", 1)[0]), json.loads(data.decode("utf-8"))


# 真实 WebUI 的 ZIP 安装/卸载路由成功路径：回归 self._drop_worker_cache 缺失导致的 500
def test_zip_install_route_succeeds_with_real_webui(tmp_path):
    from pathlib import Path

    from scripts.plugin_packaging import build_plugin_zip

    from ohmymeme.app.container import Container
    from ohmymeme.presentation.desktop import window_manager as desktop

    container = Container(tmp_path / "host")
    try:
        webui = desktop.WebUI(container)
        app = webui.build_bottle_app()
        archive = build_plugin_zip("source.qqnt", "0.0.0-route", tmp_path / "qqnt.zip")
        status, data = _post_request(
            app,
            webui._port,
            "/api/plugins/install",
            Path(archive["path"]).read_bytes(),
            "application/octet-stream",
        )
        assert status == 200 and data["ok"] is True
        assert (
            seeding.resolve_plugin(container.config.data_dir, "source.qqnt")["version"]
            == "0.0.0-route"
        )
        status, data = _post_request(
            app,
            webui._port,
            "/api/plugins/uninstall",
            json.dumps({"id": "source.qqnt"}).encode("utf-8"),
        )
        assert status == 200 and data["ok"] is True
        with pytest.raises(seeding.PluginSeedError):
            seeding.resolve_plugin(container.config.data_dir, "source.qqnt")
    finally:
        container.close()
        container.db.close()
