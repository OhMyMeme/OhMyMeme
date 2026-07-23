"""配置管理 - 本地JSON配置文件，密钥字段加密存储"""

import json
import os
import platform
from pathlib import Path

from .crypto_util import encrypt_data, decrypt_data

APP_NAME = "OhMyMeme"

# ~~~ 加密字段列表 ~~~（写入前自动加密，读取时自动解密）
_SECRET_KEYS = {
    "s3_access_key", "s3_secret_key",
    "r2_access_key", "r2_secret_key",
    "ftp_password",
}


def _get_config_dir() -> Path:
    """跨平台配置目录"""
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    return Path(base) / APP_NAME


def _get_data_dir() -> Path:
    """跨平台数据/缓存目录"""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    elif platform.system() == "Darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


class Config:
    """应用配置"""

    DEFAULTS = {
        # 全局设置
        "hotkey": "Ctrl+Alt+M",
        "auto_start": False,
        "language": "zh-CN",
        # 缓存设置
        "cache_max_size_mb": 500,
        "thumbnail_size": 150,
        # 同步模式: "manual" | "on_startup" | "scheduled"
        "sync_mode": "manual",
        "sync_interval_minutes": 60,
        # 云端存储（加密存储）
        "storage_type": "",  # "s3" | "r2" | "ftp" | ""
        "s3_endpoint": "",
        "s3_region": "",
        "s3_bucket": "",
        "s3_access_key": "",
        "s3_secret_key": "",
        "r2_endpoint": "",
        "r2_bucket": "",
        "r2_access_key": "",
        "r2_secret_key": "",
        "ftp_host": "",
        "ftp_port": 21,
        "ftp_user": "",
        "ftp_password": "",
        "ftp_path": "/",
        # UI
        "theme": "dark",
        "window_width": 700,
        "window_height": 500,
        "auto_play_gif": True,
    }

    def __init__(self, path: Path = None):
        self._path = path or (_get_config_dir() / "config.json")
        self._data = dict(self.DEFAULTS)
        self._dirty = False
        self._load()

    # --- 公开属性访问 ---

    def get(self, key: str, default=None):
        val = self._data.get(key, default)
        if val is not None and key in _SECRET_KEYS:
            dec = decrypt_data(val)
            return dec if dec else val
        return val

    def set(self, key: str, value):
        if key in _SECRET_KEYS and value:
            value = encrypt_data(str(value))
        self._data[key] = value
        self._dirty = True

    def __getattr__(self, key):
        if key.startswith("_"):
            raise AttributeError(key)
        val = self._data.get(key)
        if val is not None and key in _SECRET_KEYS:
            val = decrypt_data(val)
        return val

    def __setattr__(self, key, value):
        if key.startswith("_"):
            super().__setattr__(key, value)
        else:
            self.set(key, value)

    def to_dict(self) -> dict:
        """导出纯文本字典（密钥已解密），用于界面展示"""
        result = {}
        for k, v in self._data.items():
            if v is not None and k in _SECRET_KEYS:
                result[k] = decrypt_data(v) or ""
            else:
                result[k] = v
        return result

    def update_from_dict(self, d: dict):
        """从字典批量更新"""
        for k, v in d.items():
            self.set(k, v)

    def reset(self):
        """恢复出厂默认值"""
        self._data = dict(self.DEFAULTS)
        self._dirty = True

    # --- 持久化 ---

    def _load(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                for k in self.DEFAULTS:
                    if k in raw:
                        self._data[k] = raw[k]
            except (json.JSONDecodeError, OSError):
                pass

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        self._dirty = False

    @property
    def config_dir(self) -> Path:
        return self._path.parent

    @property
    def data_dir(self) -> Path:
        d = _get_data_dir()
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def cache_dir(self) -> Path:
        d = self.data_dir / "cache"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def thumbnail_dir(self) -> Path:
        d = self.data_dir / "thumbnails"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def db_path(self) -> Path:
        return self.data_dir / "memes.db"


# 全局单例
_config = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
