"""ADB 自动检测与下载管理 + QQ 表情包导入"""

import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_ADB_URLS = {
    "Windows": "https://googledownloads.cn/android/repository/platform-tools-latest-windows.zip",
    "Darwin": "https://googledownloads.cn/android/repository/platform-tools-latest-darwin.zip",
    "Linux": "https://googledownloads.cn/android/repository/platform-tools-latest-linux.zip",
}

_ADB_STATE = {"ready": False, "path": None, "error": "", "done": False}

_QQ_STATE = {
    "status": "idle",  # idle|downloading|starting|waiting|pulling|processing|done|error
    "progress": 0,
    "message": "",
    "error": "",
    "zip_path": "",
    "dl_progress": 0,
}

_QQ_LOCK = threading.Lock()
_QQ_CANCEL = False

_ADB_DEBUG = False


def set_adb_debug(enabled: bool = True):
    global _ADB_DEBUG
    _ADB_DEBUG = enabled


def _update_qq(**kw):
    with _QQ_LOCK:
        _QQ_STATE.update(**kw)


_QQ_FILE_TYPES = {
    b"\x89PNG": ".png",
    b"\xff\xd8": ".jpg",
    b"GIF87a": ".gif",
    b"GIF89a": ".gif",
    b"RIFF": ".webp",
    b"BM": ".bmp",
}


def _detect_ext(data: bytes) -> str:
    for magic, ext in _QQ_FILE_TYPES.items():
        if data.startswith(magic):
            if ext == ".webp" and data[8:12] != b"WEBP":
                continue
            return ext
    return ""


def get_qq_progress() -> dict:
    with _QQ_LOCK:
        return dict(_QQ_STATE)


# ─── ADB 基础 ───


def _get_adb_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "OhMyMeme" / ".adb"
    return Path(__file__).parent.parent / ".adb"


def _get_old_adb_dir() -> Path:
    """旧版（<0.3.5）打包版 .adb 路径：exe 所在目录"""
    return Path(sys.executable).parent / ".adb"


def _migrate_adb():
    """将旧版 .adb 从 exe 目录迁移至 %LOCALAPPDATA%/OhMyMeme/.adb"""
    if not getattr(sys, "frozen", False):
        return
    old = _get_old_adb_dir()
    new = _get_adb_dir()
    if not old.exists():
        return
    if new.exists():
        try:
            shutil.rmtree(old)
            logger.info("旧版 .adb 已清理: %s", old)
        except Exception as e:
            logger.warning("清理旧版 .adb 失败: %s", e)
        return
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old), str(new))
        logger.info("旧版 .adb 已迁移至: %s", new)
    except Exception as e:
        logger.warning("迁移旧版 .adb 失败: %s", e)


def _adb_binary_name() -> str:
    return "adb.exe" if platform.system() == "Windows" else "adb"


def _adb_download_url() -> str:
    return _ADB_URLS.get(platform.system(), "")


def detect_adb() -> str:
    binary = _adb_binary_name()
    adb_dir = _get_adb_dir()
    candidate = adb_dir / "platform-tools" / binary
    if candidate.exists():
        return str(candidate)
    try:
        kw = {"capture_output": True, "timeout": 5, "shell": False}
        if os.name == "nt" and getattr(sys, "frozen", False):
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        r = subprocess.run(["adb", "--version"], **kw)
        if r.returncode == 0:
            return "adb"
    except Exception:
        pass
    return ""


def ensure_adb() -> str:
    cached = detect_adb()
    if cached:
        _ADB_STATE["ready"] = True
        _ADB_STATE["path"] = cached
        _ADB_STATE["done"] = True
        return cached
    if _ADB_STATE["error"]:
        return ""
    if not _ADB_STATE["done"] or not _ADB_STATE["ready"]:
        _background_download()
    waited = 0
    while waited < 60:
        if _ADB_STATE["ready"]:
            return _ADB_STATE["path"]
        if _ADB_STATE["error"]:
            return ""
        threading.Event().wait(0.5)
        waited += 0.5
    return ""


def _background_download():
    if _ADB_STATE["done"]:
        return
    threading.Thread(target=_download_task, daemon=True).start()


def _download_task():
    url = _adb_download_url()
    if not url:
        _ADB_STATE["error"] = "unsupported platform"
        _ADB_STATE["done"] = True
        return
    adb_dir = _get_adb_dir()
    zip_path = adb_dir / "platform-tools.zip"
    try:
        adb_dir.mkdir(parents=True, exist_ok=True)
        logger.info("downloading ADB from %s", url)
        req = urllib.request.Request(url, headers={"User-Agent": "OhMyMeme"})
        CHUNK = 8192
        with urllib.request.urlopen(req, timeout=30) as src:
            with open(zip_path, "wb") as f:
                while True:
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
        logger.info("ADB download complete, extracting...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(adb_dir)
        zip_path.unlink()
        binary = _adb_binary_name()
        exe_path = adb_dir / "platform-tools" / binary
        if exe_path.exists():
            if platform.system() != "Windows":
                exe_path.chmod(0o755)
            _ADB_STATE["ready"] = True
            _ADB_STATE["path"] = str(exe_path)
            logger.info("ADB ready at %s", exe_path)
        else:
            _ADB_STATE["error"] = "extract failed: adb not found"
        _ADB_STATE["done"] = True
    except Exception as e:
        logger.warning("ADB download failed: %s", e)
        _ADB_STATE["error"] = str(e)
        _ADB_STATE["done"] = True
        if zip_path.exists():
            try:
                zip_path.unlink()
            except OSError:
                pass


def init_background():
    if _ADB_STATE["done"]:
        return
    _migrate_adb()
    cached = detect_adb()
    if cached:
        _ADB_STATE["ready"] = True
        _ADB_STATE["path"] = cached
    _ADB_STATE["done"] = True


def cancel_qq_import():
    global _QQ_CANCEL
    _QQ_CANCEL = True
    _update_qq(status="cancelled")


def reset_qq_import():
    global _QQ_CANCEL
    _QQ_CANCEL = False
    with _QQ_LOCK:
        _QQ_STATE.clear()
        _QQ_STATE.update(
            {
                "status": "idle",
                "progress": 0,
                "message": "",
                "error": "",
                "zip_path": "",
                "dl_progress": 0,
            }
        )


# ─── ADB 带进度下载 ───


def _download_with_progress():
    """下载 ADB 并更新 _QQ_STATE 进度"""
    url = _adb_download_url()
    if not url:
        logger.error("adb download: 不支持的平台")
        _update_qq(status="error", error="unsupported platform")
        return False
    adb_dir = _get_adb_dir()
    zip_path = adb_dir / "platform-tools.zip"
    try:
        adb_dir.mkdir(parents=True, exist_ok=True)
        _update_qq(message="正在下载 ADB...")
        req = urllib.request.Request(url, headers={"User-Agent": "OhMyMeme"})
        CHUNK = 8192
        with urllib.request.urlopen(req, timeout=30) as src:
            total = int(src.headers.get("Content-Length", 0))
            with open(zip_path, "wb") as f:
                written = 0
                while True:
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    if total > 0:
                        pct = int(written * 100 / total)
                        _update_qq(dl_progress=pct)
        _update_qq(message="正在解压 ADB...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(adb_dir)
        zip_path.unlink()
        binary = _adb_binary_name()
        exe_path = adb_dir / "platform-tools" / binary
        if exe_path.exists():
            if platform.system() != "Windows":
                exe_path.chmod(0o755)
            _ADB_STATE["ready"] = True
            _ADB_STATE["path"] = str(exe_path)
            _ADB_STATE["done"] = True
            return str(exe_path)
        _update_qq(status="error", error="解压后未找到 adb")
        logger.error("adb download: 解压后未找到 adb")
        return False
    except Exception as e:
        _update_qq(status="error", error=str(e))
        logger.error("adb download: 下载/解压失败: %s", e)
        if zip_path.exists():
            try:
                zip_path.unlink()
            except OSError:
                pass
        return False


# ─── QQ 表情包导入 ───


def _run_adb(adb_path, args, timeout=30):
    full_cmd = [adb_path] + args if adb_path != "adb" else ["adb"] + args
    if _ADB_DEBUG:
        logger.info("adb: %s", " ".join(str(a) for a in full_cmd))
    kwargs = {"capture_output": True, "timeout": timeout, "text": True}
    if os.name == "nt" and getattr(sys, "frozen", False):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        r = subprocess.run(full_cmd, **kwargs)
    except subprocess.TimeoutExpired:
        if _ADB_DEBUG:
            logger.warning("adb timeout after %ss", timeout)
        raise
    if _ADB_DEBUG:
        if r.returncode != 0:
            logger.warning("adb rc=%s stderr=%s", r.returncode, r.stderr.strip()[:500])
        else:
            stdout = r.stdout.strip()
            if stdout:
                logger.info("adb stdout: %s", stdout[:500])
    return r


def _resolve_adb(adb_path):
    """返回可用的 adb 路径（PATH 上的 'adb' 或完整路径）"""
    return adb_path if adb_path != "adb" else "adb"


def start_qq_import():
    """后台启动 QQ 表情包导入流程"""
    global _QQ_CANCEL
    _QQ_CANCEL = False
    threading.Thread(target=_qq_worker, daemon=True).start()


def _check_cancel():
    """检查是否取消，是则清理并返回 True"""
    if _QQ_CANCEL:
        _update_qq(status="cancelled")
        return True
    return False


def open_adb_folder():
    """打开 .adb 文件夹"""
    p = _get_adb_dir()
    p.mkdir(parents=True, exist_ok=True)
    os.startfile(str(p))


def open_adb_help():
    """打开 adb-help.txt"""
    from pathlib import Path

    p = Path(__file__).resolve().parent / "adb-help.txt"
    if p.exists():
        os.startfile(str(p))


_QQ_FAVORITE_SUFFIX = "Android/data/com.tencent.mobileqq/Tencent/QQ_Favorite"
_NON_VOLUME_ENTRIES = {"emulated", "emulated/0", "self"}


def _find_qq_favorite_dir(adb_path):
    # 在常见存储根目录中查找 QQ_Favorite（主存储 + 外置 TF 卡）
    candidates = ["/storage/emulated/0", "/sdcard"]
    try:
        r = _run_adb(adb_path, ["shell", "ls", "/storage/"], timeout=10)
        if r.returncode == 0:
            for line in (r.stdout or "").splitlines():
                entry = line.strip()
                if (
                    entry
                    and entry not in _NON_VOLUME_ENTRIES
                    and not entry.startswith(".")
                ):
                    candidates.append(f"/storage/{entry}")
    except Exception as e:
        logger.debug("list /storage failed: %s", e)
    for base in candidates:
        if _check_cancel():
            return None
        remote = base + "/" + _QQ_FAVORITE_SUFFIX
        r = _run_adb(adb_path, ["shell", "test", "-d", remote], timeout=10)
        if r.returncode == 0:
            return remote
    return None


def _qq_worker():
    _update_qq(status="downloading_adb", progress=0, message="检查 ADB...", error="")
    adb_path = detect_adb()
    if _check_cancel():
        return
    if not adb_path:
        _update_qq(status="downloading_adb", message="正在下载 ADB...")
        adb_path = _download_with_progress()
        if not adb_path:
            if _QQ_STATE["status"] != "error":
                _update_qq(
                    status="error",
                    error="ADB 下载失败，请手动下载并放入 .adb 文件夹",
                )
                logger.error("qq import: ADB 下载失败")
            return
    if _check_cancel():
        return
    _update_qq(status="starting_adb", progress=10, message="正在启动 ADB 服务...")
    try:
        _run_adb(adb_path, ["start-server"], timeout=10)
    except Exception as e:
        _update_qq(status="error", error="ADB 启动失败: %s" % e)
        logger.error("qq import: ADB 启动失败: %s", e)
        return
    if _check_cancel():
        return
    _update_qq(
        status="waiting_device", progress=20, message="请连接手机并开启 USB 调试"
    )
    detected = False
    for i in range(150):
        if _check_cancel():
            return
        try:
            r = _run_adb(adb_path, ["devices"], timeout=5)
            lines = r.stdout.strip().splitlines()
            for line in lines[1:]:
                if line.strip() and "device" in line and "offline" not in line:
                    detected = True
                    break
        except Exception:
            pass
        if detected:
            break
        threading.Event().wait(2)
    if not detected:
        _update_qq(
            status="error", error="未检测到设备，请确认手机已连接并开启 USB 调试"
        )
        logger.error("qq import: 未检测到 ADB 设备")
        return
    if _check_cancel():
        return
    _update_qq(status="pulling", progress=30, message="正在拉取 QQ 缓存文件...")
    tmp_dir = Path(tempfile.mkdtemp(prefix="ohmymeme-qq-"))
    try:
        remote = _find_qq_favorite_dir(adb_path)
    except subprocess.TimeoutExpired:
        _update_qq(status="error", error="检测存储目录超时，请检查 ADB 连接")
        logger.error("qq import: 检测存储目录超时")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return
    except Exception as e:
        _update_qq(status="error", error="检测存储目录失败: %s" % e)
        logger.error("qq import: 检测存储目录失败: %s", e)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return
    if _check_cancel():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return
    if not remote:
        _update_qq(
            status="error",
            error="未找到 QQ_Favorite 目录，请确认手机已安装 QQ"
            "（含外置存储卡时检查 TF 卡）",
        )
        logger.error("qq import: 未找到 QQ_Favorite 目录")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return
    pull_ok = False
    try:
        r = _run_adb(adb_path, ["pull", remote, str(tmp_dir)], timeout=120)
        if r.returncode == 0:
            pull_ok = True
    except subprocess.TimeoutExpired:
        pull_ok = False
    except Exception as e:
        _update_qq(status="error", error="拉取文件失败: %s" % e)
        logger.error("qq import: 拉取文件失败: %s", e)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return
    if not pull_ok:
        _update_qq(status="error", error="拉取文件失败，请检查 USB 连接")
        logger.error("qq import: 拉取文件失败（USB 连接）")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return
    if _check_cancel():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return
    _update_qq(status="processing", progress=60, message="正在识别文件格式...")
    src_dir = tmp_dir / "QQ_Favorite"
    if not src_dir.exists():
        src_dir = tmp_dir
    count = 0
    for f in src_dir.iterdir():
        if f.is_file():
            try:
                data = f.read_bytes()
            except Exception:
                continue
            if not f.suffix:
                ext = _detect_ext(data)
                if ext:
                    f.rename(f.with_suffix(ext))
            count += 1
    if _check_cancel():
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return
    _update_qq(progress=80, message="正在打包 ZIP...")
    zip_name = "QQ_Favorite_%s.zip" % time.strftime("%Y%m%d_%H%M%S")
    zip_path = Path(tempfile.gettempdir()) / zip_name
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in src_dir.iterdir():
                if f.is_file():
                    zf.write(f, f.name)
    except Exception as e:
        _update_qq(status="error", error="打包失败: %s" % e)
        logger.error("qq import: 打包 ZIP 失败: %s", e)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return
    shutil.rmtree(tmp_dir, ignore_errors=True)
    _update_qq(
        status="done",
        progress=100,
        message="导入完成，请选择保存位置",
        zip_path=str(zip_path),
    )
