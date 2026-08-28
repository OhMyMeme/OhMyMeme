from pathlib import Path

INDEX_FILENAME = "meme-index.json"
RECOVERY_MARKER_FILENAME = ".import-recovery.json"


def is_safe_filename(name):
    return (
        isinstance(name, str)
        and bool(name)
        and name not in (".", "..")
        and not name.startswith((".", "/", "\\", "~", ".."))
        and "/" not in name
        and "\\" not in name
    )


class AssetPaths:
    """Own user-data media and manifest locations without changing their layout."""

    def __init__(self, data_dir, cache_dir=None):
        self.data_dir = Path(data_dir)
        self.cache_dir = (
            Path(cache_dir) if cache_dir is not None else self.data_dir / "cache"
        )

    @property
    def thumbnail_dir(self):
        return self.data_dir / "thumbnails"

    @property
    def manifest_path(self):
        return self.data_dir / INDEX_FILENAME

    @property
    def recovery_marker_path(self):
        return self.data_dir / RECOVERY_MARKER_FILENAME


class ResourceLocator:
    def __init__(self, package_root, user_data_dir, frozen_layout):
        self.package_root = Path(package_root)
        self.user_data_dir = Path(user_data_dir)
        self.frozen_layout = frozen_layout

    @property
    def webui_dir(self):
        return self._static_root / "webui"

    @property
    def resources_dir(self):
        return self._static_root / "resources"

    @property
    def adb_help_path(self):
        return self._static_root / "adb-help.txt"

    @property
    def offsets_path(self):
        return self._config_root / "offsets.json"

    @property
    def _static_root(self):
        if self.frozen_layout:
            return self.package_root
        return self.package_root.parent

    @property
    def _config_root(self):
        if self.frozen_layout:
            return self.package_root / "config"
        return self.package_root.parent.parent / "config"

    @classmethod
    def for_source(cls, user_data_dir):
        # 源码布局：Python 包与固定静态资源均位于 src 根下。
        package_root = Path(__file__).parent.parent
        return cls(package_root, user_data_dir, False)

    @classmethod
    def for_frozen(cls, bundle_root, user_data_dir):
        # 冻结布局：打包器把固定资源放入包目录。
        package_root = Path(bundle_root) / "ohmymeme"
        return cls(package_root, user_data_dir, True)
