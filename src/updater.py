"""版本更新检查与自动升级"""

import json
import logging
import os
import platform
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from . import __version__

logger = logging.getLogger(__name__)

_GITHUB_LATEST = "https://api.github.com/repos/OhMyMeme/OhMyMeme/releases/latest"
_GITHUB_LIST = "https://api.github.com/repos/OhMyMeme/OhMyMeme/releases?per_page=5"

# GitHub 镜像（按顺序逐个尝试）
_GH_MIRRORS = [
    "https://github.dpik.top/",
    "https://gh.dpik.top/",
    "https://gh-proxy.org/",
    "https://proxy.starsfire.top/-----",
]


def _parse_version(v: str):
    parts = v.strip("vV").split(".")
    return tuple(int(x) for x in parts) if parts else (0, 0, 0)


def _pick_asset_url(assets: list) -> str:
    """从 assets 列表中选取当前系统的安装包下载 URL"""
    if platform.system() == "Windows":
        for a in assets:
            name = a.get("name", "")
            if name.endswith("-setup.exe") or name.endswith(".exe"):
                return a.get("browser_download_url", "")
    elif platform.system() == "Linux":
        for a in assets:
            name = a.get("name", "")
            if name.endswith(".AppImage"):
                return a.get("browser_download_url", "")
    return ""


# 下载进度状态
_download_state = {"progress": 0, "status": "idle", "error": "", "path": None}
_download_lock = threading.Lock()


def _download_progress(block_count: int, block_size: int, total_size: int):
    with _download_lock:
        if total_size > 0:
            _download_state["progress"] = min(
                100, int(block_count * block_size * 100 / total_size)
            )
        else:
            _download_state["progress"] = 80  # 未知大小，假装到 80%


def get_download_progress() -> dict:
    with _download_lock:
        return dict(_download_state)


def start_download(url: str) -> bool:
    """在后台线程启动下载，立即返回"""
    if not url:
        return False
    with _download_lock:
        if _download_state["status"] == "downloading":
            return False
        _download_state["status"] = "downloading"
        _download_state["progress"] = 0
        _download_state["error"] = ""
        _download_state["path"] = None

    def _task():
        try:
            tmp = tempfile.gettempdir()
            fname = url.rstrip("/").split("/")[-1] or "OhMyMeme-setup.exe"
            dest = os.path.join(tmp, fname)
            _urlretrieve_mirror(url, dest, _download_progress)
            with _download_lock:
                _download_state["path"] = dest
                _download_state["progress"] = 100
                _download_state["status"] = "done"
        except Exception as e:
            logger.error("download failed: %s", e)
            with _download_lock:
                _download_state["error"] = str(e)
                _download_state["status"] = "error"

    threading.Thread(target=_task, daemon=True).start()
    return True


def run_downloaded_installer() -> bool:
    """运行已下载完成的安装程序"""
    with _download_lock:
        if _download_state["status"] != "done" or not _download_state["path"]:
            return False
        path = _download_state["path"]
        _download_state["status"] = "idle"
    return run_installer(path)


def _try_fetch(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OhMyMeme"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _urlopen_mirror(url: str, timeout: int = 10):
    """并发尝试所有镜像+直连，返回第一个成功响应"""
    targets = [(m + url, f"mirror {i + 1}") for i, m in enumerate(_GH_MIRRORS)] + [
        (url, "direct")
    ]
    pool = ThreadPoolExecutor(max_workers=len(targets))
    fut_map = {pool.submit(_try_fetch, u, timeout): label for u, label in targets}
    last_err = None
    for f in as_completed(fut_map):
        try:
            result = f.result()
            pool.shutdown(wait=False)
            return result
        except Exception as e:
            label = fut_map[f]
            logger.debug("check update %s failed: %s", label, e)
            last_err = e
    pool.shutdown(wait=False)
    raise last_err if last_err else Exception("all urls failed")


def _fetch_json(url: str):
    return json.loads(_urlopen_mirror(url).decode("utf-8"))


def _parse_release(rel: dict):
    """解析单个 release，返回 (tag, version_tuple, download_url) 或 None"""
    tag = (rel.get("tag_name") or "").lstrip("v")
    if not tag:
        return None
    url = _pick_asset_url(rel.get("assets", []))
    if not url:
        return None
    return tag, _parse_version(tag), url


def check_latest() -> dict:
    """查询 GitHub 最新版本（优先稳定版，无稳定版时回退到预发布）"""
    current = _parse_version(__version__)

    # 1. 尝试 releases/latest（仅非预发布稳定版）
    try:
        data = _fetch_json(_GITHUB_LATEST)
        parsed = _parse_release(data)
        if parsed:
            tag, ver, url = parsed
            return {
                "latest": tag,
                "download_url": url,
                "has_update": ver > current,
                "error": "",
            }
    except Exception as e:
        logger.warning("check update (latest) failed: %s", e)
        # 任何失败（含 403/404）均回落至列表

    # 2. 回退：遍历 release 列表（含预发布），取最高版本
    try:
        releases = _fetch_json(_GITHUB_LIST)
    except Exception as e:
        logger.warning("check update failed (list): %s", e)
        msg = "无法连接到 GitHub，请检查网络设置"
        return {"latest": "", "download_url": "", "has_update": False, "error": msg}

    if not isinstance(releases, list) or not releases:
        return {
            "latest": "",
            "download_url": "",
            "has_update": False,
            "error": "no releases",
        }

    best_tag = ""
    best_ver = (0, 0, 0)
    best_url = ""
    for rel in releases:
        parsed = _parse_release(rel)
        if not parsed:
            continue
        tag, ver, url = parsed
        if ver > best_ver:
            best_tag, best_ver, best_url = tag, ver, url

    return {
        "latest": best_tag,
        "download_url": best_url,
        "has_update": best_ver > current,
        "error": "",
    }


def _try_download(url: str, dest: str, reporthook) -> str:
    """下载单个 URL 到临时文件 dest，成功返回 dest"""
    req = urllib.request.Request(url, headers={"User-Agent": "OhMyMeme"})
    CHUNK = 8192
    with urllib.request.urlopen(req, timeout=30) as src:
        total = int(src.headers.get("Content-Length", 0))
        with open(dest, "wb") as f:
            written = 0
            while True:
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
                if reporthook:
                    reporthook(written // CHUNK, CHUNK, total)
    return dest


def _urlretrieve_mirror(url: str, dest: str, reporthook=None):
    """并发尝试所有镜像+直连，第一个成功者写入最终 dest"""
    targets = [(m + url, f"mirror {i + 1}") for i, m in enumerate(_GH_MIRRORS)] + [
        (url, "direct")
    ]
    base_dir = os.path.dirname(dest) or "."
    base_name = os.path.basename(dest)

    pool = ThreadPoolExecutor(max_workers=len(targets))
    fut_info = {}
    for i, (u, label) in enumerate(targets):
        tmp_dest = os.path.join(base_dir, f".{base_name}.part{i}")
        fut = pool.submit(_try_download, u, tmp_dest, reporthook)
        fut_info[fut] = (label, tmp_dest)

    last_err = None
    for f in as_completed(fut_info):
        label, tmp_dest = fut_info[f]
        try:
            f.result()
            os.replace(tmp_dest, dest)
            logger.info("download succeeded (%s)", label)
            pool.shutdown(wait=False)
            # 清理剩余临时文件
            for other_fut, (_, other_tmp) in fut_info.items():
                if other_fut != f and os.path.exists(other_tmp):
                    try:
                        os.remove(other_tmp)
                    except OSError:
                        pass
            return
        except Exception as e:
            logger.debug("download %s failed: %s", label, e)
            last_err = e
            if os.path.exists(tmp_dest):
                try:
                    os.remove(tmp_dest)
                except OSError:
                    pass
    pool.shutdown(wait=False)
    raise last_err if last_err else Exception("all urls failed")


def download_release(url: str) -> Optional[str]:
    """下载安装包到系统临时目录，返回本地路径"""
    if not url:
        return None
    try:
        tmp = tempfile.gettempdir()
        fname = url.rstrip("/").split("/")[-1] or "OhMyMeme-setup.exe"
        dest = os.path.join(tmp, fname)
        _urlretrieve_mirror(url, dest)
        return dest
    except Exception as e:
        logger.error("download failed: %s", e)
        return None


def run_installer(path: str) -> bool:
    """启动安装程序（有 UI，非静默）"""
    if not path or not os.path.isfile(path):
        return False
    try:
        if platform.system() == "Windows":
            os.startfile(path)
            return True
        elif platform.system() == "Linux":
            os.chmod(path, 0o755)
            subprocess.Popen(["bash", path], shell=False)
            return True
        return False
    except Exception as e:
        logger.error("run installer failed: %s", e)
        return False
