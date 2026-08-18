"""微信表情包导入 - 协调 helper 二进制完成内存取证 + Python 侧 DB 解密/下载/入库

架构：
  Python (本模块) -> subprocess -> wechat_keyfinder (C++ 二进制，内存取证)
  Python -> AES-256-CBC 解密数据库 -> SQLite 查询 -> CDN 下载 -> _do_import 入库

安全：
  - 二进制执行前校验 SHA-256（防篡改），未配置真实哈希默认拒绝执行
  - 90s 超时
  - 仅 Windows 可用
"""

import hashlib
import ipaddress
import json
import logging
import os
import platform
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from ohmymeme.core.assets import ResourceLocator

logger = logging.getLogger(__name__)

# 二进制完整性校验（发布时更新）
_WECHAT_KEYFINDER_SHA256 = {
    "Windows": "72f281c6b7638735b13c2c80f8de92034f49ce0e20d75feb6640c8c6e0dd4e31",
}

# 下载源（GitHub Releases）
_WECHAT_KEYFINDER_URLS = {
    "Windows": (
        "https://github.com/ZE514/OhMyMeme/releases/download/v0.6.3/"
        "wechat_keyfinder-windows-x64.exe"
    ),
}

_WECHAT_STATE = {
    "status": "idle",
    "progress": 0,
    "message": "",
    "error": "",
    "error_code": "",
    "total": 0,
    "done": 0,
    "imported": 0,
    "failed": 0,
    "rejected": 0,
}

_WECHAT_LOCK = threading.Lock()
_WECHAT_CANCEL = False

_MAX_DOWNLOAD = 20 * 1024 * 1024


def _update_wechat(**kw):
    """更新微信导入进度状态"""
    with _WECHAT_LOCK:
        _WECHAT_STATE.update(**kw)


def get_wechat_progress():
    """返回微信导入进度状态副本"""
    with _WECHAT_LOCK:
        return dict(_WECHAT_STATE)


def cancel_wechat_import():
    """请求取消微信导入"""
    global _WECHAT_CANCEL
    _WECHAT_CANCEL = True


def _check_cancel():
    """是否请求了取消"""
    return _WECHAT_CANCEL


def _reset_state():
    """重置导入状态（调用方需已持有锁或不在锁内）"""
    global _WECHAT_CANCEL
    _WECHAT_CANCEL = False
    _update_wechat(
        status="idle",
        progress=0,
        message="",
        error="",
        error_code="",
        total=0,
        done=0,
        imported=0,
        failed=0,
        rejected=0,
    )


def _get_wechat_dir():
    """微信导入辅助文件目录"""
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    else:
        base = Path.home() / ".local" / "share"
    return Path(base) / "OhMyMeme" / ".wechat"


def _binary_name():
    """helper 二进制文件名"""
    if platform.system() == "Windows":
        return "wechat_keyfinder.exe"
    return "wechat_keyfinder"


def _download_url():
    """helper 二进制下载地址"""
    return _WECHAT_KEYFINDER_URLS.get(platform.system(), "")


def _offsets_path():
    """offsets.json 配置路径"""
    return ResourceLocator.for_source(Path.home()).offsets_path


def detect_wechat_keyfinder():
    """检测本地 helper 二进制路径，不存在返回空串"""
    binary = _binary_name()
    wechat_dir = _get_wechat_dir()
    candidate = wechat_dir / binary
    if candidate.exists():
        return str(candidate)
    return ""


def verify_binary_integrity(path):
    """校验二进制 SHA-256；未配置真实哈希默认拒绝（开发用环境变量跳过）"""
    expected = _WECHAT_KEYFINDER_SHA256.get(platform.system(), "")
    if not expected or expected == "PLACEHOLDER_UPDATE_ON_RELEASE":
        if os.environ.get("OHMYMEME_INSECURE_SKIP_HELPER_HASH") == "1":
            logger.warning("跳过 wechat_keyfinder 完整性校验（开发开关）")
            return True
        logger.error("wechat_keyfinder SHA256 未配置，拒绝执行")
        return False
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    actual = sha256.hexdigest()
    if actual != expected:
        logger.error("integrity check failed: expected=%s actual=%s", expected, actual)
        return False
    return True


_DL_LOCK = threading.Lock()
_DL_ACTIVE = False


def ensure_wechat_keyfinder():
    """确保 helper 二进制可用，返回路径或空串（单实例下载）"""
    global _DL_ACTIVE
    cached = detect_wechat_keyfinder()
    if cached and verify_binary_integrity(cached):
        return cached
    if not _download_url():
        return ""
    with _DL_LOCK:
        if not _DL_ACTIVE:
            _DL_ACTIVE = True
            threading.Thread(target=_download_task, daemon=True).start()
    waited = 0
    while waited < 60:
        time.sleep(0.5)
        waited += 0.5
        cached = detect_wechat_keyfinder()
        if cached and verify_binary_integrity(cached):
            return cached
    return ""


def _download_task():
    """后台下载 helper 二进制（唯一临时路径，校验通过后替换目标）"""
    global _DL_ACTIVE
    try:
        url = _download_url()
        if not url:
            return
        wechat_dir = _get_wechat_dir()
        wechat_dir.mkdir(parents=True, exist_ok=True)
        dest = wechat_dir / _binary_name()
        tmp = wechat_dir / (dest.name + f".tmp{os.getpid()}")
        req = urllib.request.Request(url, headers={"User-Agent": "OhMyMeme"})
        with urllib.request.urlopen(req, timeout=60) as src:
            with open(tmp, "wb") as f:
                shutil.copyfileobj(src, f)
        if verify_binary_integrity(str(tmp)):
            tmp.replace(dest)
            logger.info("wechat_keyfinder downloaded to %s", dest)
        else:
            tmp.unlink(missing_ok=True)
            logger.error("wechat_keyfinder download integrity check failed")
    except Exception as e:
        logger.error("wechat_keyfinder download failed: %s", e)
    finally:
        with _DL_LOCK:
            _DL_ACTIVE = False


def _find_wechat_root():
    """自动检测微信文件根目录"""
    if platform.system() != "Windows":
        return ""
    profile = os.environ.get("USERPROFILE", "")
    if not profile:
        return ""
    candidates = [
        Path(profile) / "Documents" / "xwechat_files",
        Path(profile) / "Documents" / "WeChat Files",
    ]
    for p in candidates:
        if p.is_dir():
            return str(p)
    return ""


def _find_account_dirs(root):
    """查找微信账号目录（wxid_ 开头）"""
    accounts = []
    try:
        for entry in os.listdir(root):
            if entry.startswith("wxid_"):
                p = os.path.join(root, entry)
                if os.path.isdir(p):
                    accounts.append(p)
    except OSError:
        pass
    return accounts


def _find_emoticon_db(account_root):
    """查找表情数据库路径"""
    candidates = [
        os.path.join(account_root, "db_storage", "emoticon", "emoticon.db"),
        os.path.join(account_root, "Msg", "emoticon.db"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return ""


def _is_sqlite_header(path):
    """文件头是否为 SQLite 格式"""
    try:
        with open(path, "rb") as f:
            return f.read(16) == b"SQLite format 3\x00"
    except OSError:
        return False


def _inspect_account(account_root):
    """检查单个账号目录，返回 {id, path, status, reason, db_path}"""
    account_id = os.path.basename(account_root)
    db_path = _find_emoticon_db(account_root)
    if not db_path:
        # 无表情库文件（favorite.db 等非表情索引存在与否都不影响）
        return {
            "id": account_id,
            "path": account_root,
            "status": "resource_unmapped",
            "reason": "sticker_index_missing",
            "db_path": "",
        }
    if not _is_sqlite_header(db_path):
        return {
            "id": account_id,
            "path": account_root,
            "status": "encrypted_index",
            "reason": "wechat_index_encrypted",
            "db_path": db_path,
        }
    return {
        "id": account_id,
        "path": account_root,
        "status": "supported",
        "reason": "sticker_index_found",
        "db_path": db_path,
    }


def _run_keyfinder(binary_path, db_path, pid=None):
    """执行 helper 二进制，返回 JSON 结果"""
    config_path = str(_offsets_path())
    cmd = [binary_path, "--config", config_path, "--db-path", db_path, "--no-snapshot"]
    if pid:
        cmd += ["--pid", str(pid)]
    kw = {"capture_output": True, "timeout": 90}
    if os.name == "nt" and getattr(sys, "frozen", False):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(cmd, **kw)
    except FileNotFoundError:
        return {
            "ok": False,
            "reason": "binary_not_found",
            "detail": f"找不到辅助二进制: {binary_path}",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "reason": "binary_timeout",
            "detail": "辅助二进制执行超时（90s）",
        }
    except OSError as e:
        return {
            "ok": False,
            "reason": "binary_launch_failed",
            "detail": f"启动辅助二进制失败: {e}",
        }
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        try:
            err = json.loads(stdout)
            if isinstance(err, dict) and err.get("ok") is False:
                return err
        except Exception:
            pass
        tail = (stdout or stderr).strip()[-400:]
        return {
            "ok": False,
            "reason": "binary_error",
            "returncode": result.returncode,
            "detail": tail or f"辅助二进制异常退出（code {result.returncode}）",
        }
    try:
        err = json.loads(stdout)
        if isinstance(err, dict):
            return err
        return {
            "ok": False,
            "reason": "parse_error",
            "detail": "二进制输出不是 JSON 对象",
        }
    except Exception as e:
        return {
            "ok": False,
            "reason": "parse_error",
            "detail": str(e) or "二进制输出解析失败",
        }


def _decrypt_page(key, page_data, page_number, page_size=4096):
    """解密单个 4096 字节页，首页替换为 SQLite header"""
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    iv = page_data[page_size - 80 : page_size - 64]
    enc_offset = 16 if page_number == 1 else 0
    enc_size = page_size - 80 - enc_offset
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    plain = (
        decryptor.update(page_data[enc_offset : enc_offset + enc_size])
        + decryptor.finalize()
    )
    out = bytearray(page_size)
    if page_number == 1:
        out[:16] = b"SQLite format 3\x00"
        out[16 : 16 + len(plain)] = plain
    else:
        out[: len(plain)] = plain
    return out


_WAL_MAGIC_BE = b"\x37\x7f\x06\x82"
_WAL_MAGIC_LE = b"\x37\x7f\x06\x83"


def _apply_wal(output, key, wal_path, expected_page_size=4096):
    """将 WAL 帧合并进已解密数据库字节流（校验 magic/页大小 + salt 代际 + 截断）"""
    try:
        with open(wal_path, "rb") as f:
            wal = f.read()
    except OSError:
        return 0
    if len(wal) < 32:
        return 0
    if wal[0:4] not in (_WAL_MAGIC_BE, _WAL_MAGIC_LE):
        return 0
    header_page_size = struct.unpack(">I", wal[8:12])[0]
    if header_page_size < 512 or header_page_size > 65536:
        return 0
    if header_page_size != expected_page_size:
        return 0
    page_size = header_page_size
    hdr_salt1 = wal[16:20]
    hdr_salt2 = wal[20:24]

    # 先解析所有完整帧，定位最后一个同代提交帧（db_size>0）作为提交边界
    frames = []
    pos = 32  # 跳过 WAL header
    while pos + 24 + page_size <= len(wal):
        frame = wal[pos : pos + 24]
        page_number = struct.unpack(">I", frame[0:4])[0]
        db_size = struct.unpack(">I", frame[4:8])[0]
        same_gen = frame[8:12] == hdr_salt1 and frame[12:16] == hdr_salt2
        frames.append(
            (page_number, db_size, wal[pos + 24 : pos + 24 + page_size], same_gen)
        )
        pos += 24 + page_size

    boundary = None
    for i, (pn, ds, _, same) in enumerate(frames):
        if same and ds > 0:
            boundary = i
    if boundary is None:
        return 0
    final_pages = frames[boundary][1]

    # 仅应用提交边界及之前的同代帧；边界后的未提交帧不应用
    applied = 0
    for i in range(boundary + 1):
        page_number, _db_size, page_data, same_gen = frames[i]
        if not same_gen or page_number == 0:
            continue
        offset = (page_number - 1) * page_size
        need = offset + page_size
        # WAL 帧可能引用超出主文件大小的页（库增长、主文件是 checkpoint 旧快照）
        if need > len(output):
            output.extend(b"\x00" * (need - len(output)))
        output[offset : offset + page_size] = _decrypt_page(
            key, page_data, page_number, page_size
        )
        applied += 1
    # 按提交帧的 db_size 截断（SQLite WAL 恢复会截断到该大小）
    if final_pages and final_pages * page_size < len(output):
        del output[final_pages * page_size :]
    return applied


def _decrypt_database(db_path, key_hex, merge_wal=True):
    """AES-256-CBC 逐页解密微信数据库（可选合并 WAL），返回 bytearray"""
    key = bytes.fromhex(key_hex)
    if len(key) != 32:
        return None
    page_size = 4096
    try:
        with open(db_path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if len(data) % page_size != 0:
        return None
    pages = len(data) // page_size
    output = bytearray()
    for page in range(1, pages + 1):
        if _check_cancel():
            return None
        page_data = data[(page - 1) * page_size : page * page_size]
        output.extend(_decrypt_page(key, page_data, page, page_size))
    if merge_wal:
        _apply_wal(output, key, db_path + "-wal", page_size)
    return output


def _query_sticker_metadata(db_bytes):
    """从解密后的数据库查询表情元数据"""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = None
    try:
        with open(tmp, "wb") as f:
            f.write(db_bytes)
        conn = sqlite3.connect(tmp)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT type, md5, aes_key, cdn_url, encrypt_url, extern_url, extern_md5 "
            "FROM kNonStoreEmoticonTable ORDER BY rowid ASC"
        )
        rows = []
        for r in cur.fetchall():
            md5 = (r["md5"] or "").lower()
            if len(md5) != 32:
                continue
            url = r["cdn_url"] or r["encrypt_url"] or r["extern_url"] or ""
            if not url:
                continue
            rows.append(
                {
                    "md5": md5,
                    "url": url,
                    "aes_key": r["aes_key"] or "",
                }
            )
        return rows
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _detect_image_ext(data):
    """通过魔数识别图片扩展名"""
    if data[:4] == b"\x89PNG":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    return ""


_WECHAT_CDN_HOSTS = {"vweixinf.tc.qq.com", "wxapp.tc.qq.com"}


def _url_allowed(url):
    """校验 URL：仅允许显式批准的微信 CDN 主机（http/https）"""
    try:
        parts = urlparse(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    host = (parts.hostname or "").lower()
    if host not in _WECHAT_CDN_HOSTS:
        return False
    return True


def _resolve_safe(host):
    """解析主机，拒绝回环/私网/链路本地/保留/未指定地址（防 DNS 投毒 SSRF）"""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
    return True


class _WechatRedirect(urllib.request.HTTPRedirectHandler):
    """重定向时逐目标重新校验主机"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _url_allowed(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_sticker(url, aes_key=None):
    """下载单个表情，返回图片字节或 None（校验 CDN 主机防 SSRF）"""
    if not _url_allowed(url):
        logger.debug("download rejected: url not allowed")
        return None
    host = urlparse(url).hostname or ""
    if not _resolve_safe(host):
        logger.debug("download rejected: unsafe host %s", host)
        return None
    try:
        opener = urllib.request.build_opener(_WechatRedirect)
        req = urllib.request.Request(url, headers={"User-Agent": "OhMyMeme"})
        with opener.open(req, timeout=15) as resp:
            data = resp.read(_MAX_DOWNLOAD + 1)
        if len(data) > _MAX_DOWNLOAD:
            return None
        if aes_key:
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

            key = bytes.fromhex(aes_key)
            if len(key) == 16 and len(data) % 16 == 0:
                cipher = Cipher(
                    algorithms.AES(key), modes.CBC(key), backend=default_backend()
                )
                data = cipher.decryptor().update(data)
        if _detect_image_ext(data):
            return data
        return None
    except Exception as e:
        logger.debug("download failed: %s", e)
        return None


def inspect_wechat_environment(user_root=None):
    """检测微信环境，返回状态字典（含账号列表）"""
    if platform.system() != "Windows":
        return {"status": "unsupported_platform", "reason": "仅支持 Windows"}
    explicit = bool(user_root)
    root = user_root or _find_wechat_root()
    if not root or not os.path.isdir(root):
        if explicit:
            reason = "account_root_missing"
            root_source = "explicit"
        else:
            reason = "default_root_missing"
            root_source = "default"
        return {
            "status": "not_found",
            "reason": reason,
            "root": root or "",
            "root_source": root_source,
            "root_exists": False,
            "account_directory_count": 0,
            "accounts": [],
        }
    root_name = os.path.basename(root)
    if root_name.startswith("wxid_"):
        accounts = [_inspect_account(root)]
    else:
        accounts = []
        for acc in _find_account_dirs(root):
            accounts.append(_inspect_account(acc))
    supported = [a for a in accounts if a["status"] == "supported"]
    encrypted = any(a["status"] == "encrypted_index" for a in accounts)
    if supported:
        status = "supported"
        reason = "sticker_index_found"
    elif encrypted:
        status = "encrypted_index"
        reason = "wechat_index_encrypted"
    elif accounts:
        status = "no_database"
        reason = "sticker_index_missing"
    else:
        status = "no_accounts"
        reason = "account_root_missing"
    root_source = "explicit" if explicit else "default"
    return {
        "status": status,
        "reason": reason,
        "root": root,
        "root_source": root_source,
        "root_exists": True,
        "account_directory_count": len(accounts),
        "accounts": accounts,
    }


_PROCEEDABLE = ("supported", "encrypted_index")


def _pick_account(env, account_path=None):
    """从环境账号列表中选择目标账号，返回账号 dict 或 None（多账号未指定）"""
    accounts = [a for a in env.get("accounts", []) if a["status"] in _PROCEEDABLE]
    if account_path:
        for a in accounts:
            if a["path"] == account_path or a["id"] == account_path:
                return a
        return None
    if len(accounts) == 1:
        return accounts[0]
    return None


def _load_sticker_metadata(db_path, key):
    """解密 DB 并查询表情元数据，优先主文件（通常已完整），失败/为空时回退 WAL 合并"""
    output = _decrypt_database(db_path, key, merge_wal=False)
    if output is None:
        return []
    try:
        meta = _query_sticker_metadata(output)
    except Exception:
        meta = None
    if meta:
        return meta
    # 主文件查询为空 → 复用同一缓冲合并 WAL，避免二次解密
    _apply_wal(output, key, db_path + "-wal")
    try:
        return _query_sticker_metadata(output)
    except Exception:
        return []


def _read_plaintext_metadata(db_path):
    """直接读取明文 SQLite 库并查询表情元数据"""
    try:
        with open(db_path, "rb") as f:
            return _query_sticker_metadata(f.read())
    except Exception as e:
        logger.debug("read plaintext metadata failed: %s", e)
        return []


def _load_metadata_for_account(account):
    """按账号状态加载表情元数据：supported 直读明文，encrypted_index 走密钥+解密"""
    db_path = account.get("db_path", "")
    if not db_path:
        return []
    if account.get("status") == "supported":
        return _read_plaintext_metadata(db_path)
    binary_path = ensure_wechat_keyfinder()
    if not binary_path:
        return []
    result = _run_keyfinder(binary_path, db_path)
    if not result.get("ok"):
        return []
    key = result.get("key", "")
    if not key:
        return []
    return _load_sticker_metadata(db_path, key)


def _list_stickers_for_account(account):
    """对单个账号列出可导入的表情"""
    metadata = _load_metadata_for_account(account)
    return {
        "status": "supported",
        "total": len(metadata),
        "files": metadata[:50],
        "account": account.get("id", ""),
    }


def list_wechat_stickers(user_root, account_path=None):
    """列出可导入的表情（不实际下载）"""
    env = inspect_wechat_environment(user_root)
    if env.get("status") not in _PROCEEDABLE:
        return env
    account = _pick_account(env, account_path)
    if not account:
        if env.get("account_directory_count", 0) > 1:
            return {
                "status": "multiple_accounts",
                "reason": "检测到多个微信账号，请选择账号",
                "accounts": [a["id"] for a in env.get("accounts", [])],
            }
        return {"status": "no_account", "reason": "未找到可用账号"}
    return _list_stickers_for_account(account)


_WECHAT_ACTIVE = (
    "scanning",
    "extracting_key",
    "decrypting_db",
    "querying",
    "downloading",
    "importing",
)


def start_wechat_import(
    import_callback, user_root=None, download=True, account_path=None
):
    """后台启动微信表情包导入，已有任务时返回 False"""
    global _WECHAT_CANCEL
    with _WECHAT_LOCK:
        if _WECHAT_STATE["status"] in _WECHAT_ACTIVE:
            return False
        # 持锁内直接重置状态（_reset_state 内部会再取锁，非可重入会死锁）
        _WECHAT_CANCEL = False
        _WECHAT_STATE.update(
            status="scanning",
            progress=0,
            message="",
            error="",
            error_code="",
            total=0,
            done=0,
            imported=0,
            failed=0,
            rejected=0,
        )
    threading.Thread(
        target=_wechat_worker,
        args=(import_callback, user_root, download, account_path),
        daemon=True,
    ).start()
    return True


def _wechat_worker(import_callback, user_root, download, account_path):
    """后台：环境检测 -> 密钥提取 -> DB 解密 -> 下载 -> 入库"""
    temp_dir = None
    try:
        _update_wechat(status="scanning", message="正在检测微信环境...")
        if _check_cancel():
            _update_wechat(status="cancelled", message="已取消")
            return
        env = inspect_wechat_environment(user_root)
        if env.get("status") not in _PROCEEDABLE:
            logger.error(
                "wechat import: 环境检测失败 status=%s reason=%s",
                env.get("status"),
                env.get("reason"),
            )
            _update_wechat(
                status="error",
                error_code=env.get("status", "unknown"),
                error=env.get("reason", "微信环境检测失败"),
            )
            return
        account = _pick_account(env, account_path)
        if not account:
            multi = env.get("account_directory_count", 0) > 1
            error_msg = "检测到多个微信账号，请选择账号" if multi else "未找到可用账号"
            logger.error("wechat import: %s", error_msg)
            _update_wechat(
                status="error",
                error_code="multiple_accounts",
                error=error_msg,
            )
            return
        db_path = account["db_path"]
        if not db_path:
            logger.error("wechat import: 未找到表情数据库: %s", account.get("path"))
            _update_wechat(
                status="error",
                error_code="no_database",
                error="未找到表情数据库",
            )
            return
        if account.get("status") == "supported":
            _update_wechat(status="querying", message="正在查询表情元数据...")
            if _check_cancel():
                _update_wechat(status="cancelled", message="已取消")
                return
            metadata = _read_plaintext_metadata(db_path)
        else:
            _update_wechat(status="extracting_key", message="正在提取加密密钥...")
            if _check_cancel():
                _update_wechat(status="cancelled", message="已取消")
                return
            binary_path = ensure_wechat_keyfinder()
            if not binary_path:
                logger.error("wechat import: helper 二进制不可用")
                _update_wechat(
                    status="error",
                    error_code="no_binary",
                    error="helper 二进制不可用（下载失败或平台不支持）",
                )
                return
            result = _run_keyfinder(binary_path, db_path)
            if not result.get("ok"):
                detail = result.get("detail", "")
                rc = result.get("returncode")
                if rc is not None:
                    detail = (
                        f"{detail} (exit code {rc})"
                        if detail
                        else f"辅助二进制退出码 {rc}"
                    )
                _update_wechat(
                    status="error",
                    error_code=result.get("reason", "keyfinder_failed"),
                    error=detail or "密钥提取失败",
                )
                logger.error("wechat import: 密钥提取失败: %s", detail)
                return
            key = result.get("key", "")
            if not key:
                logger.error("wechat import: 无法提取加密密钥")
                _update_wechat(
                    status="error",
                    error_code="no_key",
                    error="无法提取加密密钥（微信版本不兼容或未登录）",
                )
                return
            _update_wechat(status="decrypting_db", message="正在解密数据库...")
            if _check_cancel():
                _update_wechat(status="cancelled", message="已取消")
                return
            _update_wechat(status="querying", message="正在查询表情元数据...")
            if _check_cancel():
                _update_wechat(status="cancelled", message="已取消")
                return
            metadata = _load_sticker_metadata(db_path, key)
        if _check_cancel():
            _update_wechat(status="cancelled", message="已取消")
            return
        if not metadata:
            _update_wechat(
                status="done",
                message="未找到可导入的表情",
                total=0,
                done=0,
            )
            return
        if not download:
            _update_wechat(
                status="done",
                message=f"发现 {len(metadata)} 个表情（仅扫描模式）",
                total=len(metadata),
                done=len(metadata),
            )
            return
        _update_wechat(
            status="downloading",
            message="正在下载表情...",
            total=len(metadata),
            done=0,
        )
        if _check_cancel():
            _update_wechat(status="cancelled", message="已取消")
            return
        temp_dir = tempfile.mkdtemp(prefix="wechat_import_")
        imported_paths = []
        failed = 0
        for i, item in enumerate(metadata):
            if _check_cancel():
                _update_wechat(status="cancelled", message="已取消")
                return
            data = _download_sticker(item["url"], item.get("aes_key") or None)
            if data:
                ext = _detect_image_ext(data) or ".png"
                path = os.path.join(temp_dir, f"{item['md5']}{ext}")
                with open(path, "wb") as f:
                    f.write(data)
                imported_paths.append(path)
            else:
                failed += 1
            pct = int((i + 1) / len(metadata) * 100)
            _update_wechat(
                progress=pct,
                done=i + 1,
                message=f"正在下载: {i + 1}/{len(metadata)}",
            )
        _update_wechat(status="importing", message="正在导入...")
        if _check_cancel():
            _update_wechat(status="cancelled", message="已取消")
            return
        if imported_paths:
            result = import_callback(imported_paths)
            imported = len(result.get("ids", []))
            rejected = result.get("rejected", 0)
        else:
            imported = 0
            rejected = 0
        msg = f"导入完成，共 {imported} 个表情"
        if failed:
            msg += f"（{failed} 个下载失败）"
        if rejected:
            msg += f"（{rejected} 个被拒绝）"
        _update_wechat(
            status="done",
            message=msg,
            progress=100,
            done=len(metadata),
            imported=imported,
            failed=failed,
            rejected=rejected,
        )
    except Exception as e:
        logger.error("wechat import error: %s", e)
        _update_wechat(status="error", error_code="", error=str(e))
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
