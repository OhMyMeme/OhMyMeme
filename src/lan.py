"""局域网互联 - UDP 发现 + TCP 加密会话服务（手机 App 与电脑配对）"""

import base64
import hashlib
import hmac
import json
import logging
import os
import platform
import socket
import struct
import threading
import time
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    HAS_AESGCM = True
except ImportError:
    HAS_AESGCM = False

from . import __version__
from .config import _SECRET_KEYS, get_config
from .database import get_db
from .manifest import build as build_manifest

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
MAX_FRAME = 64 * 1024 * 1024  # 帧上限 64MB
_HANDSHAKE_TIMEOUT = 10  # 握手超时（秒）
_IDLE_TIMEOUT = 60  # 会话空闲超时（秒）
_IV_LEN = 12
_TAG_LEN = 16

# 服务器运行状态（供设置页轮询）
_lan_state = {
    "status": "stopped",  # stopped | running | error
    "port": 0,
    "start_time": 0,
    "clients": [],  # 已连接设备列表
    "last_error": "",
    "allow_secret_config": False,  # 配置同步是否含密钥字段（仅内存生效）
}
_lan_lock = threading.Lock()
_server = None


class LanServer:
    """UDP 发现 + TCP 加密会话服务（单实例）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._udp_sock = None
        self._tcp_sock = None
        self._threads = []
        self._port = 0
        self._secret = ""
        self._clients = {}

    # --- 生命周期 ---

    def start(self, port: int, secret: str) -> bool:
        if not HAS_AESGCM:
            with _lan_lock:
                _lan_state["status"] = "error"
                _lan_state["last_error"] = "缺少 cryptography 依赖"
            return False
        with self._lock:
            if self._running:
                return False
            self._running = True
        self._port = int(port)
        self._secret = secret or ""
        ok = True
        try:
            self._udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._udp_sock.bind(("0.0.0.0", self._port))
            self._udp_sock.settimeout(0.5)
            self._tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._tcp_sock.bind(("0.0.0.0", self._port))
            self._tcp_sock.listen(8)
            self._tcp_sock.settimeout(0.5)
        except OSError as e:
            self._cleanup_sockets()
            with _lan_lock:
                _lan_state["status"] = "error"
                _lan_state["last_error"] = f"端口 {self._port} 无法监听: {e}"
            with self._lock:
                self._running = False
            return False
        self._spawn_thread(self._udp_loop)
        self._spawn_thread(self._tcp_loop)
        with _lan_lock:
            _lan_state["status"] = "running"
            _lan_state["port"] = self._port
            _lan_state["start_time"] = int(time.time())
            _lan_state["last_error"] = ""
        logger.info(f"LAN 服务已启动，端口 {self._port}")
        return ok

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
        self._cleanup_sockets()
        for t in self._threads:
            t.join(timeout=1)
        self._threads.clear()
        with _lan_lock:
            _lan_state["status"] = "stopped"
            _lan_state["port"] = 0
            _lan_state["start_time"] = 0
            _lan_state["clients"] = []
        logger.info("LAN 服务已停止")

    def _cleanup_sockets(self):
        for s in (self._udp_sock, self._tcp_sock):
            if s:
                try:
                    s.close()
                except OSError:
                    pass
        self._udp_sock = None
        self._tcp_sock = None

    def _spawn_thread(self, target):
        t = threading.Thread(target=target, daemon=True)
        t.start()
        self._threads.append(t)

    # --- UDP 发现 ---

    def _udp_loop(self):
        while self._running:
            try:
                data, addr = self._udp_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8", errors="replace"))
            except Exception:
                continue
            if not isinstance(msg, dict) or msg.get("t") != "discover":
                continue
            reply = {
                "t": "hello",
                "name": platform.node(),
                "os": platform.system(),
                "ver": __version__,
                "need_secret": bool(self._secret),
            }
            try:
                self._udp_sock.sendto(
                    json.dumps(reply, ensure_ascii=False).encode("utf-8"), addr
                )
            except OSError:
                pass

    # --- TCP 会话 ---

    def _tcp_loop(self):
        while self._running:
            try:
                conn, addr = self._tcp_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._spawn_thread(lambda c=conn, a=addr: self._handle_conn(c, a))

    def _handle_conn(self, conn, addr):
        try:
            conn.settimeout(_HANDSHAKE_TIMEOUT)
            key = self._handshake(conn)
            if not key:
                return
            conn.settimeout(_IDLE_TIMEOUT)
            self._clients[addr] = time.time()
            self._sync_clients()
            try:
                self._session_loop(conn, key)
            finally:
                self._clients.pop(addr, None)
                self._sync_clients()
        except (OSError, ValueError, json.JSONDecodeError) as e:
            logger.debug(f"LAN conn {addr}: {e}")
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _sync_clients(self):
        now = time.time()
        with _lan_lock:
            _lan_state["clients"] = [
                {"addr": f"{addr[0]}:{addr[1]}", "connected_at": int(t)}
                for addr, t in list(self._clients.items())
                if now - t < _IDLE_TIMEOUT
            ]

    # --- 握手 ---

    def _handshake(self, conn):
        if not self._secret:
            # 无密钥直接放行（本地信任网络）
            self._send_plain(conn, {"t": "ok"})
            return _derive_key("")
        nonce = os.urandom(16).hex()
        self._send_plain(conn, {"t": "challenge", "nonce": nonce})
        for attempt in range(3):
            msg = self._recv_plain(conn)
            if not isinstance(msg, dict) or msg.get("t") != "proof":
                self._send_plain(conn, {"t": "no"})
                continue
            expected = hmac.new(
                self._secret.encode(), nonce.encode(), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(msg.get("mac", ""), expected):
                self._send_plain(conn, {"t": "no"})
                continue
            self._send_plain(conn, {"t": "ok"})
            return _derive_key(self._secret)
        return None

    # --- 会话命令循环 ---

    def _session_loop(self, conn, key):
        while self._running:
            msg = self._recv_frame(conn, key)
            if msg is None:
                break
            if not isinstance(msg, dict) or "cmd" not in msg:
                continue
            result = self._dispatch(msg)
            if isinstance(result, dict):
                self._send_frame(conn, key, result)

    def _dispatch(self, msg: dict) -> dict:
        cmd = msg.get("cmd")
        if cmd == "pull_manifest":
            return self._cmd_pull_manifest()
        if cmd == "push_manifest":
            return self._cmd_push_manifest(msg.get("manifest"))
        if cmd == "pull_file":
            return self._cmd_pull_file(msg.get("filename", ""))
        if cmd == "push_file":
            return self._cmd_push_file(msg)
        if cmd == "get_config":
            return self._cmd_get_config()
        if cmd == "send_config":
            return self._cmd_send_config(msg.get("config"))
        if cmd == "ping":
            return {"ok": True, "ver": __version__}
        return {"ok": False, "error": f"未知命令: {cmd}"}

    # --- 命令实现 ---

    def _cmd_pull_manifest(self) -> dict:
        from .manifest import load as load_manifest

        build_manifest()
        return {"ok": True, "manifest": load_manifest()}

    def _cmd_push_manifest(self, manifest) -> dict:
        if not isinstance(manifest, dict):
            return {"ok": False, "error": "manifest 格式错误"}
        from .sync import _apply_remote_collections, _apply_remote_order

        db = get_db()
        try:
            _apply_remote_order(manifest)
            _apply_remote_collections(manifest)
        except Exception as e:
            logger.warning(f"push_manifest apply error: {e}")
        build_manifest()
        return {"ok": True, "local_count": db.count()}

    def _cmd_pull_file(self, filename: str) -> dict:
        if not _safe_fname(filename):
            return {"ok": False, "error": "非法文件名"}
        path = _find_meme_file(filename)
        if not path:
            return {"ok": False, "error": "文件不存在"}
        try:
            data = Path(path).read_bytes()
        except OSError as e:
            return {"ok": False, "error": str(e)}
        data_b64 = base64.b64encode(data).decode()
        return {"ok": True, "filename": filename, "data": data_b64}

    def _cmd_push_file(self, msg: dict) -> dict:
        filename = msg.get("filename", "")
        if not _safe_fname(filename):
            return {"ok": False, "error": "非法文件名"}
        data_b64 = msg.get("data", "")
        if not data_b64:
            return {"ok": False, "error": "缺少文件数据"}
        try:
            data = base64.b64decode(data_b64)
        except Exception:
            return {"ok": False, "error": "文件数据解码失败"}
        return _import_bytes(data, filename)

    def _cmd_get_config(self) -> dict:
        cfg = get_config()
        d = cfg.to_dict()
        if not _lan_state["allow_secret_config"]:
            for k in _SECRET_KEYS:
                d.pop(k, None)
        return {"ok": True, "config": d}

    def _cmd_send_config(self, config) -> dict:
        if not isinstance(config, dict):
            return {"ok": False, "error": "配置格式错误"}
        cfg = get_config()
        if not _lan_state["allow_secret_config"]:
            config = {k: v for k, v in config.items() if k not in _SECRET_KEYS}
        cfg.update_from_dict(config)
        cfg.save()
        return {"ok": True}

    # --- 帧协议 ---

    def _recv_exact(self, conn, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise OSError("连接关闭")
            buf += chunk
        return buf

    def _send_plain(self, conn, obj: dict):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        conn.sendall(struct.pack(">I", len(data)) + data)

    def _recv_plain(self, conn) -> dict:
        hdr = self._recv_exact(conn, 4)
        (ln,) = struct.unpack(">I", hdr)
        if ln > MAX_FRAME:
            raise ValueError("帧过大")
        payload = self._recv_exact(conn, ln)
        return json.loads(payload.decode("utf-8"))

    def _send_frame(self, conn, key: bytes, obj: dict):
        plain = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        iv = os.urandom(_IV_LEN)
        ct = AESGCM(key).encrypt(iv, plain, None)
        conn.sendall(struct.pack(">I", _IV_LEN + len(ct)) + iv + ct)

    def _recv_frame(self, conn, key: bytes) -> dict:
        hdr = self._recv_exact(conn, 4)
        (ln,) = struct.unpack(">I", hdr)
        if ln > MAX_FRAME or ln < _IV_LEN + _TAG_LEN:
            raise ValueError("帧长度非法")
        body = self._recv_exact(conn, ln)
        iv, ct = body[:_IV_LEN], body[_IV_LEN:]
        plain = AESGCM(key).decrypt(iv, ct, None)
        return json.loads(plain.decode("utf-8"))


def _derive_key(secret: str) -> bytes:
    """由共享密钥派生 AES-GCM 会话密钥"""
    if not secret:
        return b"\x00" * 32
    return hashlib.pbkdf2_hmac(
        "sha256", secret.encode(), b"ohmy-meme-lan", 100000, dklen=32
    )


def _safe_fname(name) -> bool:
    """校验文件名，拒绝路径穿越与绝对路径"""
    return (
        isinstance(name, str)
        and bool(name)
        and name not in (".", "..")
        and not name.startswith((".", "/", "\\", "~", ".."))
        and "/" not in name
        and "\\" not in name
    )


def _find_meme_file(filename: str):
    """在缓存目录递归查找表情文件"""
    cache_dir = get_config().cache_dir
    direct = cache_dir / filename
    if direct.exists() and direct.is_file():
        return direct
    for root, _, files in os.walk(cache_dir):
        if filename in files:
            full = os.path.join(root, filename)
            if os.path.isfile(full):
                return full
    return None


def _import_bytes(data: bytes, filename: str) -> dict:
    """把收到的文件字节按哈希去重后入库"""
    import shutil
    import tempfile

    db = get_db()
    cache_dir = get_config().cache_dir
    tmp = Path(tempfile.mkstemp(prefix=".lan-", suffix=".tmp")[1])
    try:
        tmp.write_bytes(data)
        ext = _detect_image_ext(str(tmp)) or os.path.splitext(filename)[1] or ".png"
        fhash = hashlib.sha256(data).hexdigest()
        if db.get_by_hash(fhash):
            return {"ok": True, "dedup": True}
        dst = cache_dir / f"{fhash[:16]}{ext}"
        shutil.copy2(tmp, dst)
        w = h = 0
        try:
            from PIL import Image as PILImage

            img = PILImage.open(dst)
            w, h = img.size
        except Exception:
            pass
        db.add_meme(
            filename=dst.name,
            file_hash=fhash,
            width=w,
            height=h,
            file_size=len(data),
            mime_type=f"image/{ext[1:]}" if ext else "image/png",
            original_name=os.path.splitext(filename)[0],
        )
        build_manifest()
        return {"ok": True, "filename": dst.name}
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _detect_image_ext(path):
    """读取文件头魔数识别真实扩展名"""
    try:
        with open(path, "rb") as f:
            return _detect_ext(f.read(16))
    except OSError:
        return ""


def _detect_ext(data: bytes):
    """按魔数识别图片扩展名，未知返回空串"""
    if data.startswith(b"\x89PNG"):
        return ".png"
    if data.startswith(b"\xff\xd8"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"BM"):
        return ".bmp"
    return ""


# 密钥字段（配置同步默认剔除）


# --- 对外接口 ---


def start(port: int = 17852, secret: str = "") -> bool:
    """启动局域网服务（设置页开关调用）"""
    global _server
    with _lan_lock:
        if _lan_state["status"] == "running" and _server:
            return True
    _server = LanServer()
    return _server.start(port, secret)


def stop():
    """停止局域网服务"""
    global _server
    with _lan_lock:
        if not _server:
            return
    _server.stop()


def get_status() -> dict:
    """返回服务状态（设置页轮询）"""
    with _lan_lock:
        return {
            "status": _lan_state["status"],
            "port": _lan_state["port"],
            "start_time": _lan_state["start_time"],
            "clients": list(_lan_state["clients"]),
            "last_error": _lan_state["last_error"],
            "allow_secret_config": _lan_state["allow_secret_config"],
        }


def get_lan_ip() -> str:
    """获取本机局域网 IP（用于设置页展示）"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def set_allow_secret_config(enabled: bool):
    """设置配置同步是否含密钥字段（仅内存生效，不落盘）"""
    with _lan_lock:
        _lan_state["allow_secret_config"] = bool(enabled)
