"""应用对象图和生命周期。"""

import threading
from pathlib import Path

from ohmymeme.core.assets import AssetPaths, ResourceLocator
from ohmymeme.core.config import Config
from ohmymeme.core.database import MemeDB
from ohmymeme.core.imports import ImageImportService
from ohmymeme.core.manifest import build as build_manifest
from ohmymeme.integrations.platform.hotkey import GlobalHotkey
from ohmymeme.integrations.platform.system import is_auto_start_enabled, set_auto_start
from ohmymeme.integrations.platform.tray import TrayManager

from .catalog import Catalog
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
        self.resource_locator = ResourceLocator.for_source(self.config.data_dir)
        self.catalog = Catalog(self.config, self.db, self.build_manifest)
        self.settings = Settings(self.config, is_auto_start_enabled, set_auto_start)
        self._closed = False
        self._close_lock = threading.Lock()

    def build_manifest(self):
        from ohmymeme.core import manifest

        old_config, old_db = manifest.get_config, manifest.get_db
        manifest.get_config, manifest.get_db = lambda: self.config, lambda: self.db
        try:
            return build_manifest()
        finally:
            manifest.get_config, manifest.get_db = old_config, old_db

    def create_webui(self, update_debug=False, silent_start=False):
        from ohmymeme.presentation.desktop.window_manager import WebUI

        return WebUI(self, update_debug, silent_start)

    def create_import_service(self, decode_stego):
        return ImageImportService(
            self.db, self.assets, self.build_manifest, decode_stego
        )

    def create_hotkey(self):
        return GlobalHotkey()

    def create_tray(self, on_show, on_quit, source_mode):
        return TrayManager(on_show=on_show, on_quit=on_quit, source_mode=source_mode)

    def close(self, hotkey=None, tray=None, lan_stop=None, webui=None):
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        for action in (
            getattr(hotkey, "unregister", None),
            getattr(tray, "stop", None),
            lan_stop,
            getattr(webui, "stop", None),
            self.db.close,
            self.config.save,
        ):
            if not callable(action):
                continue
            try:
                action()
            except Exception:
                continue
