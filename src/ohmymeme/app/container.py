"""应用对象图和生命周期。"""

import threading
from pathlib import Path

from ohmymeme.core.assets import AssetPaths, ResourceLocator
from ohmymeme.core.config import Config
from ohmymeme.core.database import MemeDB
from ohmymeme.core.imports import ImageImportService
from ohmymeme.core.manifest import ManifestBuilder
from ohmymeme.integrations.platform.hotkey import GlobalHotkey
from ohmymeme.integrations.platform.system import is_auto_start_enabled, set_auto_start
from ohmymeme.integrations.platform.tray import TrayManager
from ohmymeme.services import updates
from ohmymeme.services.lan.server import LanServer
from ohmymeme.services.sync.service import SyncService

from .catalog import Catalog
from .job_manager import JobManager
from .local_library import LocalLibraryService
from .settings import Settings


class Container:
    """唯一完整应用对象图创建点。"""

    def __init__(self, root=None):
        root = Path(root) if root is not None else None
        config_path = root / "config.json" if root else None
        data_dir = root / "data" if root else None
        self.config = Config(config_path, data_dir)
        self.db = MemeDB(self.config.db_path)
        self.assets = AssetPaths(self.config.data_dir, self.config.cache_dir)
        self.manifest = ManifestBuilder(self.config, self.db, self.assets)
        self.resource_locator = ResourceLocator.for_source(self.config.data_dir)
        self._closed = False
        self._close_lock = threading.RLock()
        self._close_done = threading.Event()
        self._lan_server = None
        self.library = self.create_local_library_service()
        self.catalog = Catalog(
            self.config, self.db, self.manifest.build, library=self.library
        )
        self.settings = Settings(self.config, is_auto_start_enabled, set_auto_start)
        self.job_manager = JobManager()
        updates.set_job_manager(self.job_manager)

    def build_manifest(self):
        return self.manifest.build()

    def create_webui(self, update_debug=False, silent_start=False):
        with self._close_lock:
            self._ensure_open()
            from ohmymeme.presentation.desktop.window_manager import WebUI

            return WebUI(self, update_debug, silent_start)

    def create_import_service(self, decode_stego):
        with self._close_lock:
            self._ensure_open()
            return ImageImportService(
                self.db, self.assets, self.build_manifest, decode_stego
            )

    def create_local_library_service(self, decode_stego=None):
        """Create the Container-owned local-library write boundary."""
        with self._close_lock:
            self._ensure_open()
            importer = ImageImportService(
                self.db, self.assets, self.build_manifest, decode_stego
            )
            return LocalLibraryService(
                self.db, self.assets, importer, self.build_manifest, self.config
            )

    def create_sync_service(self):
        with self._close_lock:
            self._ensure_open()
            return SyncService(
                self.config,
                self.db,
                self.assets,
                self.manifest,
                self.library,
                self.job_manager,
            )

    def create_lan_server(self):
        with self._close_lock:
            self._ensure_open()
            server = LanServer(
                SyncService(
                    self.config,
                    self.db,
                    self.assets,
                    self.manifest,
                    self.library,
                    self.job_manager,
                ),
                self.config,
                self.db,
                self.assets,
                self.manifest,
                self.library,
            )
            self._lan_server = server
            return server

    def start_lan(self, port, secret):
        with self._close_lock:
            self._ensure_open()
            if self._lan_server is None:
                self._lan_server = self.create_lan_server()
            return self._lan_server.start(port, secret)

    def stop_lan(self):
        with self._close_lock:
            server = self._lan_server
            self._lan_server = None
        if server is not None:
            server.stop()

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("container is shut down")

    def create_hotkey(self):
        with self._close_lock:
            self._ensure_open()
            return GlobalHotkey()

    def create_tray(self, on_show, on_quit, source_mode):
        with self._close_lock:
            self._ensure_open()
            return TrayManager(
                on_show=on_show, on_quit=on_quit, source_mode=source_mode
            )

    def close(
        self,
        hotkey=None,
        tray=None,
        lan_stop=None,
        webui=None,
        timeout=2.0,
        external_stop=None,
    ):
        with self._close_lock:
            if self._closed:
                done = self._close_done
            else:
                self._closed = True
                lan_server = getattr(self, "_lan_server", None)
                self._lan_server = None
                done = None
        if done is not None:
            done.wait(timeout)
            return
        try:
            for action in (
                lambda: self.job_manager.shutdown(timeout),
                getattr(hotkey, "unregister", None),
                getattr(tray, "stop", None),
                getattr(webui, "stop", None),
                lambda: lan_server.stop() if lan_server is not None else None,
                lan_stop,
                external_stop,
                self.db.close,
                self.config.save,
            ):
                if not callable(action):
                    continue
                try:
                    action()
                except Exception:
                    continue
            updates.set_job_manager(None)
        finally:
            self._close_done.set()
