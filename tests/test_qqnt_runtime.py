# pyright: basic

"""source.qqnt 子进程 runtime 端到端测试。"""

import io

import pytest
from PIL import Image
from plugin_fixtures import install_official

from ohmymeme.app.operation_coordinator import OperationCoordinator
from ohmymeme.app.runtime_imports import RuntimeImportWorker
from ohmymeme.core.assets import AssetPaths
from ohmymeme.core.database import MemeDB
from ohmymeme.core.domain import TaskKind
from ohmymeme.core.imports import HostImportSink, ImageImportService
from ohmymeme.core.plugins.manifest import canonical_descriptor
from ohmymeme.core.plugins.policy import PluginPolicy
from ohmymeme.core.plugins.runtime import PluginRuntimeManager


def _png(width=1):
    output = io.BytesIO()
    Image.new("RGBA", (width, 1), (255, 0, 0, 255)).save(output, "PNG")
    return output.getvalue()


def _emoji_source(root, count=0):
    source = (
        root
        / "userdata"
        / "10001"
        / "nt_qq"
        / "nt_data"
        / "Emoji"
        / "personal_emoji"
        / "Ori"
    )
    source.mkdir(parents=True)
    (source / "valid.png").write_bytes(_png())
    (source / "corrupt.png").write_bytes(b"not an image")
    (source / "oversize.png").write_bytes(_png(2561))
    for index in range(count):
        (source / ("extra-%03d.png" % index)).write_bytes(_png())
    return source.parents[5]


class _Config:
    def __init__(self, data_dir, cache_dir):
        self.data_dir = data_dir
        self.cache_dir = cache_dir

    def get(self, key, default=None):
        return default

    def get_plugin_value(self, provider, key, legacy, secret=False):
        return None


class _Host:
    def __init__(self, tmp_path):
        self.data_dir = tmp_path / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.data_dir / "cache"
        self.config = _Config(self.data_dir, self.cache_dir)
        install_official(self.data_dir, "source.qqnt")
        self.manager = PluginRuntimeManager(self.data_dir)
        self.coordinator = OperationCoordinator()
        self.assets = AssetPaths(self.data_dir, self.cache_dir)
        self.database = MemeDB(self.data_dir / "memes.db")
        self.service = ImageImportService(
            self.database,
            self.assets,
            lambda: self.assets.manifest_path.write_text("manifest"),
        )
        self.worker = RuntimeImportWorker(
            self.manager,
            "source.qqnt",
            canonical_descriptor("source.qqnt"),
            PluginPolicy(self.config),
            self.coordinator,
            HostImportSink(self.service),
            close_thread=self.database.close,
        )

    def start(self, output_dir, overwrite=False):
        return self.worker.start_qqnt(
            "10001", str(output_dir), False, overwrite, self.config
        )

    def wait(self, timeout=120):
        self.coordinator.wait(TaskKind.IMPORT_QQNT, timeout)

    def close(self):
        self.coordinator.shutdown()
        self.manager.shutdown()
        self.database.close()


def test_qqnt_cache_target_routes_every_image_through_atomic_import(tmp_path):
    # 库内目标：只经 staging+sink 提交合法图片
    host = _Host(tmp_path)
    try:
        userdata = _emoji_source(tmp_path)
        host.config.get = lambda key, default=None: (
            str(userdata) if key == "qqnt_userdata_path" else default
        )
        assert host.start(host.assets.cache_dir) is True
        host.wait()
        result = host.worker.get_progress()["result"]
        assert result["copied"] == 1
        assert result["skipped"] == 2
        assert result["output_dir"] == str(host.assets.cache_dir)
        assert len(host.database.search()) == 1
        assert len(list(host.assets.cache_dir.iterdir())) == 1
        assert host.assets.manifest_path.exists()
    finally:
        host.close()


def test_qqnt_external_output_preserves_copy_export_semantics(tmp_path):
    # 外部导出：保留非图片与坏图复制语义，不进 sink
    host = _Host(tmp_path)
    try:
        userdata = _emoji_source(tmp_path)
        host.config.get = lambda key, default=None: (
            str(userdata) if key == "qqnt_userdata_path" else default
        )
        output = tmp_path / "external-export"
        assert host.start(output) is True
        host.wait()
        result = host.worker.get_progress()["result"]
        assert result["copied"] == 3
        assert result["output_dir"] == str(output)
        assert (output / "valid.png").exists()
        assert (output / "corrupt.png").exists()
        assert not host.database.search()
    finally:
        host.close()


def test_qqnt_external_output_rejects_non_empty_dir_without_overwrite(tmp_path):
    # 外部导出：非空目录且未允许覆盖时拒绝
    host = _Host(tmp_path)
    try:
        _emoji_source(tmp_path)
        output = tmp_path / "external-export"
        output.mkdir()
        (output / "keep.txt").write_text("keep", encoding="utf-8")
        with pytest.raises(FileExistsError):
            host.start(output)
        assert (output / "keep.txt").read_text(encoding="utf-8") == "keep"
    finally:
        host.close()


def test_qqnt_cache_target_cancellation_creates_no_library_state(tmp_path):
    # 取消后不产生缓存文件、数据库行或 manifest
    host = _Host(tmp_path)
    try:
        userdata = _emoji_source(tmp_path, count=300)
        host.config.get = lambda key, default=None: (
            str(userdata) if key == "qqnt_userdata_path" else default
        )
        assert host.start(host.assets.cache_dir) is True
        host.worker.cancel()
        host.wait()
        assert host.worker.get_progress()["status"] == "cancelled"
        assert not host.database.search()
        assert not host.assets.cache_dir.exists()
        assert not host.assets.manifest_path.exists()
    finally:
        host.close()


def test_qqnt_cache_target_deduplicates_through_image_import_service(tmp_path):
    # 同一图片重复导入只保留一份
    host = _Host(tmp_path)
    try:
        userdata = _emoji_source(tmp_path)
        host.config.get = lambda key, default=None: (
            str(userdata) if key == "qqnt_userdata_path" else default
        )
        for _ in range(2):
            assert host.start(host.assets.cache_dir) is True
            host.wait()
        assert len(host.database.search()) == 1
        assert len(list(host.assets.cache_dir.iterdir())) == 1
    finally:
        host.close()


def test_qqnt_inspect_returns_accounts_through_worker(tmp_path):
    # inspect 通过固定查询进入 worker，并注入宿主昵称回调
    host = _Host(tmp_path)
    try:
        userdata = _emoji_source(tmp_path)
        result = host.worker.query(
            "inspect",
            {
                "ini_path": str(tmp_path / "missing.ini"),
                "userdata_save_path": str(userdata),
            },
            nickname_lookup=lambda qq: "nick-" + qq,
        )
        assert result["ok"] is True
        assert result["accounts"] == [
            {"qq": "10001", "nickname": "nick-10001", "count": 3}
        ]
    finally:
        host.close()


def test_qqnt_worker_package_stays_importable_without_host(tmp_path):
    # 插件模块只依赖 ohmymeme.core，不持有宿主对象
    import ohmymeme_plugin_qqnt

    plugin = ohmymeme_plugin_qqnt.create_plugin()
    assert plugin.provider_id == "source.qqnt"
    assert plugin.get_progress()["status"] == "idle"
    assert not hasattr(plugin, "_webui")
