# pyright: basic

"""应用对象图和生命周期。"""

import logging
import threading
from pathlib import Path

from ohmymeme.core.adapters.sqlite.library import MemeDbLibraryPort
from ohmymeme.core.assets import AssetPaths, ResourceLocator
from ohmymeme.core.config import Config
from ohmymeme.core.database import MemeDB
from ohmymeme.core.imports import HostImportSink, ImageImportService
from ohmymeme.core.manifest import build as build_manifest
from ohmymeme.core.plugins.manifest import CANONICAL_PROVIDERS, canonical_descriptor
from ohmymeme.core.plugins.registry import PluginRegistry
from ohmymeme.core.plugins.runtime import PluginRuntimeManager, seeding
from ohmymeme.core.recovery import StorageRecovery
from ohmymeme.integrations.platform.hotkey import GlobalHotkey
from ohmymeme.integrations.platform.system import is_auto_start_enabled, set_auto_start
from ohmymeme.integrations.platform.tray import TrayManager
from ohmymeme.services.lan.server import LanServer
from ohmymeme.services.lifecycle import LifecycleResources, LifecycleService
from ohmymeme.services.sync.service import SyncService

from .library import LibraryService
from .operation_coordinator import OperationCoordinator
from .pull_commit_service import PullCommitService
from .remote_mutation_coordinator import RemoteMutationCoordinator
from .settings import Settings

logger = logging.getLogger(__name__)


class Container:
    """唯一完整应用对象图创建点。"""

    def __init__(self, root=None):
        root = Path(root) if root is not None else None
        config_path = root / "config.json" if root else None
        data_dir = root / "data" if root else None
        self.config = Config(config_path, data_dir)
        self.remote_mutations = RemoteMutationCoordinator(self.config.data_dir)
        try:
            self._initialize_components()
        except BaseException:
            self.remote_mutations.close()
            raise

    def _initialize_components(self):
        configured_cache = self.config.get("cache_dir", "")
        cache_root = (
            Path(configured_cache).expanduser().resolve()
            if configured_cache
            else self.config.data_dir / "cache"
        )
        self.recovery = StorageRecovery(self.config.data_dir, cache_root)
        self.recovery.recover_before_database(cache_root)
        self.db = MemeDB(self.config.db_path)
        self.assets = AssetPaths(self.config.data_dir, self.config.cache_dir)
        ImageImportService(self.db, self.assets, self.build_manifest).recover()
        self.pull_commit = PullCommitService(
            self.assets,
            self._apply_pull_projection,
            self._write_manifest_projection,
            self.build_manifest,
            self._pull_metadata_committed,
        )
        self.pull_commit.recover()
        self.resource_locator = ResourceLocator.for_source(self.config.data_dir)
        self.catalog = LibraryService(
            self.config,
            MemeDbLibraryPort(self.db),
            self.build_manifest,
            mutation_coordinator=self.remote_mutations,
        )
        self.settings = Settings(self.config, is_auto_start_enabled, set_auto_start)
        self.plugins = PluginRegistry(
            tuple(
                canonical_descriptor(provider_id)
                for provider_id, _, _ in CANONICAL_PROVIDERS
            )
        )
        disabled = self.config.get("disabled_plugins", None)
        disabled = set(disabled) if isinstance(disabled, (list, tuple)) else set()
        self.enabled_plugins = (
            frozenset(provider_id for provider_id, _, _ in CANONICAL_PROVIDERS)
            - disabled
        )
        self.plugin_runtime = PluginRuntimeManager(self.config.data_dir)
        try:
            seeding.purge_legacy_bundled(self.config.data_dir)
        except Exception:
            logger.exception("plugin legacy migration failed")
        self.sync = SyncService(
            self.config,
            self.db,
            self.build_manifest,
            self._write_manifest_data,
            self.remote_mutations,
            registry=self.plugins,
            enabled=self.enabled_plugins,
            plugin_runtime=self.plugin_runtime,
        )
        self._closed = False
        self._closing = False
        self._close_resources = None
        self._last_shutdown = None
        self._close_lock = threading.Lock()
        self.operations = OperationCoordinator(self._retry_shutdown)
        self.lan = LanServer(
            sync_service=self.sync,
            coordinator=self.operations,
            config=self.config,
            database=self.db,
            build_manifest=self.build_manifest,
            import_service_factory=self.create_raw_import_service,
            registry=self.plugins,
            mutation_coordinator=self.remote_mutations,
            enabled=self.enabled_plugins,
            plugin_runtime=self.plugin_runtime,
        )
        self.recovery.finish_manifest(self.build_manifest)

    def build_manifest(self) -> None:
        from ohmymeme.core import manifest

        old_config, old_db = manifest.get_config, manifest.get_db
        manifest.get_config, manifest.get_db = lambda: self.config, lambda: self.db
        try:
            build_manifest()
        finally:
            manifest.get_config, manifest.get_db = old_config, old_db

    def _apply_pull_projection(self, projection):
        self.db.apply_remote_pull_metadata(projection.to_data())

    def _write_manifest_projection(self, projection):
        self._write_manifest_data(projection.to_data())

    def _write_manifest_data(self, data: dict) -> None:
        from ohmymeme.core import manifest

        old_config, old_db = manifest.get_config, manifest.get_db
        manifest.get_config, manifest.get_db = lambda: self.config, lambda: self.db
        try:
            manifest._write(data)
        finally:
            manifest.get_config, manifest.get_db = old_config, old_db

    def _pull_metadata_committed(self, record):
        return all(
            self.db.get_by_filename(entry["filename"]) for entry in record["entries"]
        )

    def create_webui(self, update_debug=False, silent_start=False):
        from ohmymeme.presentation.desktop.window_manager import WebUI

        webui = WebUI(self, update_debug, silent_start)
        webui._enabled_import_plugins = self.enabled_plugins
        return webui

    def create_import_service(self, decode_stego=None, coordinated=True):
        return ImageImportService(
            self.db,
            self.assets,
            self.build_manifest,
            decode_stego,
            self.remote_mutations if coordinated else None,
        )

    def create_raw_import_service(self):
        return self.create_import_service(coordinated=False)

    def create_import_sink(self, decode_stego=None, coordinated=True):
        return HostImportSink(self.create_import_service(decode_stego, coordinated))

    def create_hotkey(self):
        return GlobalHotkey()

    def create_tray(self, on_show, on_quit, source_mode):
        return TrayManager(on_show=on_show, on_quit=on_quit, source_mode=source_mode)

    def close(self, hotkey=None, tray=None, lan_stop=None, webui=None, lifecycle=None):
        with self._close_lock:
            if self._closed:
                return self._last_shutdown
            if not self._closing:
                self._closing = True
                self._close_resources = (hotkey, tray, lan_stop, webui, lifecycle)
        return self._drain_close()

    def _retry_shutdown(self):
        with self._close_lock:
            if not self._closing or self._closed:
                return
        self._drain_close()

    def _drain_close(self):
        report = self.operations.shutdown()
        with self._close_lock:
            self._last_shutdown = report
            if self._closed:
                return report
            resources = self._close_resources
            if report.shutdown_blocked:
                window = resources[3] if resources is not None else None
            else:
                self._closed = True
                self._closing = False
                window = None
        if report.shutdown_blocked:
            if window is not None:
                window.hide()
            return report
        self.plugin_runtime.shutdown()
        if resources is None:
            try:
                self.lan.stop()
            finally:
                self.remote_mutations.close()
            return report
        hotkey, tray, lan_stop, webui, lifecycle = resources
        if lifecycle is None:
            lifecycle = LifecycleService(
                LifecycleResources(hotkey, tray, lan_stop, webui, self.db, self.config)
            )
        try:
            lifecycle.close()
        finally:
            self.remote_mutations.close()
        return report
