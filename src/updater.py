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
    """解析版本号，跳过非数字段（如 nightly 版本）"""
    parts = v.strip("vV").split("-")[0].split(".")
    nums = []
    for x in parts:
        if not x.isdigit():
            break
        nums.append(int(x))
    return tuple(nums) if nums else (0, 0, 0)


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
    elif platform.system() == "Darwin":
        for a in assets:
            name = a.get("name", "")
            if name.endswith(".dmg") and ("-" + _macos_arch() + ".dmg") in name:
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
            fname = url.rstrip("/").split("/")[-1] or _default_asset_name()
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
    """解析单个稳定 release，返回 (tag, version_tuple, download_url, notes) 或 None"""
    tag = (rel.get("tag_name") or "").lstrip("v")
    if not tag or rel.get("prerelease") or "nightly" in tag.lower():
        return None
    # 跳过预发布与非正式版（nightly 等），避免更新到非正式版本
    if rel.get("prerelease") or "nightly" in tag.lower():
        return None
    url = _pick_asset_url(rel.get("assets", []))
    if not url:
        return None
    notes = (rel.get("body") or "").strip()
    return tag, _parse_version(tag), url, notes


def check_latest() -> dict:
    """查询 GitHub 最新稳定版本，忽略预发布和 nightly。"""
    current = _parse_version(__version__)

    # 1. 尝试 releases/latest（仅非预发布稳定版）
    try:
        data = _fetch_json(_GITHUB_LATEST)
        parsed = _parse_release(data)
        if parsed:
            tag, ver, url, notes = parsed
            return {
                "latest": tag,
                "download_url": url,
                "has_update": ver > current,
                "notes": notes,
                "error": "",
            }
    except Exception as e:
        logger.warning("check update (latest) failed: %s", e)
        # 任何失败（含 403/404）均回落至列表

    # 2. 回退：遍历 release 列表，仅取最高稳定版本
    try:
        releases = _fetch_json(_GITHUB_LIST)
    except Exception as e:
        logger.warning("check update failed (list): %s", e)
        msg = "无法连接到 GitHub，请检查网络设置"
        return {
            "latest": "",
            "download_url": "",
            "has_update": False,
            "notes": "",
            "error": msg,
        }

    if not isinstance(releases, list) or not releases:
        return {
            "latest": "",
            "download_url": "",
            "has_update": False,
            "notes": "",
            "error": "no releases",
        }

    best_tag = ""
    best_ver = (0, 0, 0)
    best_url = ""
    best_notes = ""
    for rel in releases:
        parsed = _parse_release(rel)
        if not parsed:
            continue
        tag, ver, url, notes = parsed
        if ver > best_ver:
            best_tag, best_ver, best_url, best_notes = tag, ver, url, notes

    return {
        "latest": best_tag,
        "download_url": best_url,
        "has_update": best_ver > current,
        "notes": best_notes,
        "error": "",
    }


def _macos_arch() -> str:
    """当前 macOS 机器架构（arm64 / x86_64）"""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "x86_64"


def _default_asset_name() -> str:
    """URL 无文件名时的平台默认资产名"""
    if platform.system() == "Linux":
        return f"OhMyMeme-v{__version__}-x86_64.AppImage"
    if platform.system() == "Darwin":
        return f"OhMyMeme-v{__version__}-{_macos_arch()}.dmg"
    return "OhMyMeme-setup.exe"


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
        fname = url.rstrip("/").split("/")[-1] or _default_asset_name()
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
            # AppImage 是 ELF 可执行文件：chmod +x 后直接运行；
            # 无 FUSE 环境（容器/某些发行版）回退 --appimage-extract-and-run
            os.chmod(path, 0o755)
            cmd = [path]
            if _needs_appimage_fallback(path):
                cmd.append("--appimage-extract-and-run")
            subprocess.Popen(cmd, shell=False, start_new_session=True)
            return True
        elif platform.system() == "Darwin":
            # dmg：挂载后把 .app 复制到 /Applications，然后弹出安装窗口引导用户
            return _install_dmg_macos(path)
        return False
    except Exception as e:
        logger.error("run installer failed: %s", e)
        return False


def _install_dmg_macos(path: str) -> bool:
    """macOS：挂载 dmg，复制 .app 到 /Applications"""
    try:
        result = subprocess.run(
            ["hdiutil", "attach", path, "-nobrowse"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            logger.error("hdiutil attach failed: %s", result.stderr)
            return False
        # 输出形如: /dev/disk4 ... /Volumes/OhMyMeme
        mount_point = ""
        for line in result.stdout.splitlines():
            line = line.strip()
            if "/Volumes/" in line:
                mount_point = line.split("/Volumes/", 1)[1]
                mount_point = "/Volumes/" + mount_point.strip()
                break
        if not mount_point or not os.path.isdir(mount_point):
            logger.error("dmg mount point not found: %s", result.stdout)
            return False

        app_names = [n for n in os.listdir(mount_point) if n.endswith(".app")]
        if not app_names:
            logger.error("no .app found in dmg")
            return False

        src_app = os.path.join(mount_point, app_names[0])
        dst_app = os.path.join("/Applications", app_names[0])
        try:
            subprocess.run(
                ["ditto", src_app, dst_app],
                check=True,
                timeout=300,
            )
        except subprocess.CalledProcessError as e:
            logger.error("copy .app to /Applications failed: %s", e)
            return False
        finally:
            subprocess.run(
                ["hdiutil", "detach", mount_point],
                capture_output=True,
                text=True,
            )
        # 打开应用程序目录便于用户启动
        subprocess.Popen(["open", "/Applications"], start_new_session=True)
        return True
    except Exception as e:
        logger.error("macos install failed: %s", e)
        return False


def _needs_appimage_fallback(path: str) -> bool:
    """AppImage 直接运行依赖 FUSE；无 /dev/fuse 时回退 extract-and-run"""
    if not path.lower().endswith(".appimage"):
        return False
    try:
        return not os.path.exists("/dev/fuse")
    except Exception:
        return False
