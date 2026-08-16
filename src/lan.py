"""局域网互联 - UDP 发现 + TCP 加密会话服务（手机 App 与电脑配对）"""

import base64
import hashlib
import hmac
import io
import json
import logging
import os
import platform
import socket
import struct
import sys
import threading
import time
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    HAS_AESGCM = True
except ImportError:
    HAS_AESGCM = False

from . import __version__
from .config import (
    _IMPORT_MAX_BYTES,
    _IMPORT_MAX_PX,
    _SECRET_KEYS,
    get_config,
)
from .database import get_db
from .manifest import build as build_manifest

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
MAX_FRAME = 64 * 1024 * 1024  # 帧上限 64MB
MAX_FILE_SIZE = 64 * 1024 * 1024  # 单文件大小上限 64MB
_HANDSHAKE_TIMEOUT = 10  # 握手超时（秒）
_IDLE_TIMEOUT = 60  # 会话空闲超时（秒）
_DEVICE_CONFIRM_TIMEOUT = 60  # 设备确认超时（秒）
_IV_LEN = 12
_TAG_LEN = 16

# 服务器运行状态（供设置页轮询）
_lan_state = {
    "status": "stopped",  # stopped | running | error
    "port": 0,
    "start_time": 0,
    "clients": [],  # 已连接设备列表
    "last_error": "",
    "allow_secret_config": False,  # 允许密钥传输（仅内存生效）
}
_lan_lock = threading.Lock()
_server = None
_confirm_cb = None  # 设备连接确认回调，由 WebUI 注入（阻塞等待用户决定）


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
        self._udp_pktinfo = False

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
            self._udp_pktinfo = False
            try:
                self._udp_sock.setsockopt(socket.IPPROTO_IP, socket.IP_PKTINFO, 1)
                self._udp_pktinfo = True
            except (AttributeError, OSError):
                pass
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
                if self._udp_pktinfo:
                    data, ancdata, _, addr = self._udp_sock.recvmsg(2048, 256)
                else:
                    data, addr = self._udp_sock.recvfrom(2048)
                    ancdata = []
            except socket.timeout:
                continue
            except (AttributeError, NotImplementedError):
                # recvmsg 不可用的平台：禁 pktinfo 退化 recvfrom，继续发现
                self._udp_pktinfo = False
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
            payload = json.dumps(reply, ensure_ascii=False).encode("utf-8")
            src_addr = self._extract_pktinfo_src(ancdata)
            try:
                self._send_udp_reply(payload, addr, src_addr)
            except OSError:
                pass

    def _extract_pktinfo_src(self, ancdata):
        """提取广播到达的本地接口（Linux 返回 ("ip", ip)；Windows ("ifindex", n)）"""
        for level, ctype, cdata in ancdata:
            if level != socket.IPPROTO_IP or ctype != socket.IP_PKTINFO:
                continue
            try:
                if sys.platform == "win32":
                    # Windows in_pktinfo 仅 8 字节 (ipi_addr, ipi_ifindex)，无
                    # spec_dst；ipi_addr 是目的地址（广播），只有接口索引可用
                    _, ifindex = struct.unpack("4sI", cdata)
                    if not ifindex:
                        return None
                    return ("ifindex", ifindex)
                else:
                    _, spec_dst, _ = struct.unpack("i4s4s", cdata)
                    return ("ip", socket.inet_ntoa(spec_dst))
            except (struct.error, OSError):
                return None
        return None

    def _send_udp_reply(self, data, addr, src):
        """UDP 回包：可固定源接口则 sendmsg（多网卡/虚拟网卡环境保证回包走真实网卡）"""
        if self._udp_pktinfo and src:
            try:
                kind, val = src
                pinfo = None
                if sys.platform == "win32" and kind == "ifindex":
                    src_ip = self._win_ifindex_source_ip(val, addr)
                    if src_ip:
                        # Windows 发送时 ipi_addr 为源地址，ipi_ifindex 指定出口
                        pinfo = struct.pack("4sI", socket.inet_aton(src_ip), val)
                elif kind == "ip":
                    pinfo = struct.pack("i4s4s", 0, socket.inet_aton(val), b"\x00" * 4)
                if pinfo:
                    self._udp_sock.sendmsg(
                        [data],
                        [(socket.IPPROTO_IP, socket.IP_PKTINFO, pinfo)],
                        0,
                        addr,
                    )
                    return
            except (AttributeError, NotImplementedError, struct.error, OSError):
                logger.debug("LAN UDP 回包 sendmsg 失败，退化为 sendto")
        self._udp_sock.sendto(data, addr)

    def _win_ifindex_source_ip(self, ifindex, peer):
        """Windows：用 IP_UNICAST_IF 钉住接收接口，connect 后 getsockname 取该接口 IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                opt = getattr(socket, "IP_UNICAST_IF", 31)
                # IP_UNICAST_IF 接口索引须为网络字节序（MSDN），勿用本机字节序
                s.setsockopt(socket.IPPROTO_IP, opt, struct.pack("!I", ifindex))
                s.connect((peer[0], peer[1]))
                return s.getsockname()[0]
            finally:
                s.close()
        except OSError:
            return None

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
            confirmed = threading.Event()
            if _confirm_cb is None:
                # 无确认回调（测试/无 UI 环境）直接放行
                confirmed.set()
            try:
                self._session_loop(conn, key, confirmed)
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

    def _session_loop(self, conn, key, confirmed: threading.Event):
        while self._running:
            msg = self._recv_frame(conn, key)
            if msg is None:
                break
            if not isinstance(msg, dict) or "cmd" not in msg:
                continue
            cmd = msg.get("cmd")
            if cmd == "device_info":
                result = self._cmd_device_info(msg, confirmed)
            elif not confirmed.is_set():
                # 未确认设备前挂起其他命令
                if not confirmed.wait(timeout=_DEVICE_CONFIRM_TIMEOUT):
                    result = {"ok": False, "error": "设备未确认"}
                else:
                    result = self._dispatch(msg)
            else:
                result = self._dispatch(msg)
            if isinstance(result, dict):
                self._send_frame(conn, key, result)

    def _cmd_device_info(self, msg: dict, confirmed: threading.Event) -> dict:
        """处理手机端设备描述，弹窗确认后返回批准结果"""
        device = {
            "name": msg.get("name", "未知设备"),
            "model": msg.get("model", ""),
            "os": msg.get("os", ""),
            "ver": msg.get("ver", ""),
        }
        entry = {"device": device, "approved": False, "done": threading.Event()}
        with _lan_lock:
            _lan_state["pending_confirm"] = entry
        try:
            cb = _confirm_cb
            if cb:
                try:
                    cb(device)
                except Exception:
                    logger.warning("device confirm callback error")
                entry["done"].wait(timeout=_DEVICE_CONFIRM_TIMEOUT)
            else:
                # 无确认回调（如测试/无 UI）默认放行
                entry["approved"] = True
            approved = bool(entry["approved"])
        finally:
            with _lan_lock:
                _lan_state.pop("pending_confirm", None)
        confirmed.set()
        with _lan_lock:
            allow_secret = bool(_lan_state["allow_secret_config"])
        return {
            "ok": True,
            "approved": approved,
            "allow_secret_config": allow_secret,
        }

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
        from .sync import (
            _apply_remote_ai_text,
            _apply_remote_collections,
            _apply_remote_order,
        )

        db = get_db()
        try:
            _apply_remote_ai_text(manifest)
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
        if len(data) > MAX_FILE_SIZE:
            return {"ok": False, "error": "文件超过大小限制"}
        expected = msg.get("sha256")
        if expected and hmac.compare_digest(hashlib.sha256(data).hexdigest(), expected):
            pass  # sha256 校验通过
        elif expected:
            return {"ok": False, "error": "文件哈希不一致"}
        return _import_bytes(data, filename)

    def _cmd_get_config(self) -> dict:
        # 配置拉取：allow_secret_config 关闭时剔除密钥字段
        cfg = get_config()
        d = cfg.to_dict()
        with _lan_lock:
            allow_secret = bool(_lan_state["allow_secret_config"])
        if not allow_secret:
            for k in _SECRET_KEYS:
                d.pop(k, None)
        return {"ok": True, "config": d}

    def _cmd_send_config(self, config) -> dict:
        # 配置推送：allow_secret_config 关闭时忽略密钥字段
        if not isinstance(config, dict):
            return {"ok": False, "error": "配置格式错误"}
        cfg = get_config()
        with _lan_lock:
            allow_secret = bool(_lan_state["allow_secret_config"])
        if not allow_secret:
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
    """把收到的文件字节校验合法性后按哈希去重入库（不合法不落盘，杜绝孤儿文件）"""
    db = get_db()
    cache_dir = get_config().cache_dir
    ext = _detect_ext(data[:16]) or os.path.splitext(filename)[1] or ".png"
    if not ext:
        return {"ok": False, "error": "无法识别的图片格式"}
    # 先解码校验图片，确认宽高有效后才写缓存，避免孤儿文件
    try:
        from PIL import Image as PILImage

        img = PILImage.open(io.BytesIO(data))
        w, h = img.size
    except Exception:
        return {"ok": False, "error": "图片解析失败"}
    if w <= 0 or h <= 0:
        return {"ok": False, "error": "图片尺寸无效"}
    if len(data) > _IMPORT_MAX_BYTES:
        return {
            "ok": False,
            "error": "文件超过 %dMB 限制" % (_IMPORT_MAX_BYTES // (1024 * 1024)),
        }
    if max(w, h) > _IMPORT_MAX_PX:
        return {"ok": False, "error": "分辨率超过 %dK 限制" % (_IMPORT_MAX_PX // 1000)}
    fhash = hashlib.sha256(data).hexdigest()
    if db.get_by_hash(fhash):
        return {"ok": True, "dedup": True}
    dst = cache_dir / f"{fhash[:16]}{ext}"
    try:
        dst.write_bytes(data)
    except OSError:
        return {"ok": False, "error": "写入缓存失败"}
    db.add_meme(
        filename=dst.name,
        file_hash=fhash,
        width=w,
        height=h,
        file_size=len(data),
        mime_type=f"image/{ext[1:]}",
        original_name=os.path.splitext(filename)[0],
    )
    build_manifest()
    return {"ok": True, "filename": dst.name}


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
            "allow_secret_config": bool(_lan_state["allow_secret_config"]),
        }


def set_allow_secret_config(enabled: bool):
    """设置是否允许密钥传输（仅内存生效，不落盘）"""
    with _lan_lock:
        _lan_state["allow_secret_config"] = bool(enabled)


def set_confirm_callback(cb):
    """注入设备连接确认回调（由 WebUI 调用，接收设备信息 dict，返回是否批准）"""
    global _confirm_cb
    old = _confirm_cb
    _confirm_cb = cb
    return old


def confirm_device(approved: bool):
    """由 JS 弹窗回传设备批准结果（见 _LanConfirm 记录）"""
    entry = _lan_state.get("pending_confirm")
    if entry:
        with _lan_lock:
            entry["approved"] = bool(approved)
            entry["done"].set()


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
