"""Telegram Desktop 缓存表情包提取"""

import hashlib
import logging
import os
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

_TG_STATE = {
    "status": "idle",
    "progress": 0,
    "message": "",
    "error": "",
    "error_code": "",
    "total": 0,
    "done": 0,
    "imported": 0,
    "rejected": 0,
    "convert_failed": 0,
    "skipped_static": 0,
    "elapsed_s": 0,
}

_TG_LOCK = threading.RLock()
_TG_CANCEL = False
_TG_ACTIVE_PROC = set()
_TG_T0 = None
_TG_JOB_CANCEL = None
_TG_JOB_SNAPSHOT = None


def _bind_tg_job(_manager, record, context):
    global _TG_JOB_CANCEL, _TG_JOB_SNAPSHOT
    _TG_JOB_CANCEL = record.cancellation_event
    _TG_JOB_SNAPSHOT = context.snapshot


def _update_tg(**kw):
    global _TG_JOB_SNAPSHOT
    with _TG_LOCK:
        _refresh_tg_elapsed()
        _TG_STATE.update(**kw)
        snapshot = _TG_JOB_SNAPSHOT
        state = dict(_TG_STATE)
    if snapshot is not None:
        snapshot(
            phase=state["status"],
            progress=state["progress"] / 100,
            message=state["message"],
            error_code=state["error_code"],
            error=state["error"],
        )


# 按任务起点刷新已用秒数（仅运行中状态推进）
def _refresh_tg_elapsed():
    if _TG_T0 is not None and _TG_STATE.get("status") in (
        "scanning",
        "loading_key",
        "decrypting",
        "converting",
        "deduping",
        "importing",
    ):
        _TG_STATE["elapsed_s"] = int(time.monotonic() - _TG_T0)


def get_tg_progress():
    with _TG_LOCK:
        _refresh_tg_elapsed()
        return dict(_TG_STATE)


def cancel_tg_import():
    global _TG_CANCEL
    _TG_CANCEL = True
    if _TG_JOB_CANCEL is not None:
        _TG_JOB_CANCEL.set()
    with _TG_LOCK:
        procs = list(_TG_ACTIVE_PROC)
    for p in procs:
        if p.poll() is None:
            try:
                p.terminate()
            except Exception as e:
                logger.warning(f"terminate tg process failed: {e}")


def _check_cancel():
    return _TG_CANCEL or (_TG_JOB_CANCEL is not None and _TG_JOB_CANCEL.is_set())


def _import_tgcrypto():
    """惰性导入 tgcrypto，缺失返回 None"""
    try:
        import tgcrypto

        return tgcrypto
    except ImportError:
        return None


def _import_crypto():
    """惰性导入 cryptography，缺失返回 None"""
    try:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        return default_backend, Cipher, algorithms, modes
    except ImportError:
        return None


def _reset_state():
    global _TG_CANCEL, _TG_T0
    _TG_CANCEL = False
    _TG_T0 = None
    with _TG_LOCK:
        for p in list(_TG_ACTIVE_PROC):
            if p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        _TG_ACTIVE_PROC.clear()
    _update_tg(
        status="idle",
        progress=0,
        message="",
        error="",
        error_code="",
        total=0,
        done=0,
        imported=0,
        rejected=0,
        convert_failed=0,
        skipped_static=0,
        elapsed_s=0,
    )


def is_valid_tdata(path):
    """校验目录是否为 Telegram Desktop tdata（含 key_datas/key_data）"""
    if not path or not os.path.isdir(path):
        return False
    return os.path.exists(os.path.join(path, "key_datas")) or os.path.exists(
        os.path.join(path, "key_data")
    )


def find_tdata_path():
    """跨平台自动检测 Telegram Desktop tdata 路径"""
    sys_name = platform.system()
    if sys_name == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            p = os.path.join(appdata, "Telegram Desktop", "tdata")
            if os.path.isdir(p):
                return p
        return ""
    if sys_name == "Darwin":
        p = os.path.expanduser("~/Library/Application Support/Telegram Desktop/tdata")
        if os.path.isdir(p):
            return p
        return ""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".local", "share", "TelegramDesktop", "tdata"),
        os.path.join(home, ".TelegramDesktop", "tdata"),
    ]
    snap_base = os.path.join(home, "snap", "telegram-desktop")
    if os.path.isdir(snap_base):
        for entry in os.listdir(snap_base):
            p = os.path.join(
                snap_base,
                entry,
                ".local/share/TelegramDesktop/tdata",
            )
            if os.path.isdir(p):
                candidates.append(p)
    flatpak_p = os.path.join(
        home,
        ".var/app/org.telegram.desktop/data/TelegramDesktop/tdata",
    )
    candidates.append(flatpak_p)
    for p in candidates:
        if os.path.isdir(p):
            return p
    return ""


def _sha1(data):
    return hashlib.sha1(data).digest()


def _sha256(data):
    return hashlib.sha256(data).digest()


def _prepare_aes_oldmtp(key, msg_key):
    sha1_a = _sha1(msg_key[:16] + key[8:40])
    sha1_b = _sha1(key[40:56] + msg_key[:16] + key[56:72])
    sha1_c = _sha1(key[72:104] + msg_key[:16])
    sha1_d = _sha1(msg_key[:16] + key[104:136])
    aes_key = sha1_a[:8] + sha1_b[8:20] + sha1_c[4:16]
    aes_iv = sha1_a[8:20] + sha1_b[:8] + sha1_c[16:20] + sha1_d[:8]
    return aes_key, aes_iv


def _aes_decrypt_local(src, key, key128):
    tgcrypto = _import_tgcrypto()
    if tgcrypto is None:
        raise RuntimeError("缺少依赖 tgcrypto，请安装后重试")
    aes_key, aes_iv = _prepare_aes_oldmtp(key, key128)
    return bytearray(tgcrypto.ige256_decrypt(src, aes_key, aes_iv))


def _decrypt_local(encrypted, key):
    encrypted_key = encrypted[:16]
    decrypted = _aes_decrypt_local(encrypted[16:], key, encrypted_key)
    if _sha1(decrypted)[:16] != encrypted_key:
        raise ValueError("bad checksum for decrypted data")
    data_len = struct.unpack_from("<I", decrypted)[0]
    return decrypted[4:data_len]


def _create_local_key(passcode, salt):
    h = hashlib.sha512(salt + passcode + salt).digest()
    iter_count = 100000 if passcode else 1
    return bytearray(hashlib.pbkdf2_hmac("sha512", h, salt, iter_count, 256))


def _read_tdf_file(path):
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"TDF$":
            raise ValueError(f"not a TDF$ file: {magic!r}")
        version = f.read(4)
        data = f.read()
    payload = data[:-16]
    stored_md5 = data[-16:]
    m = hashlib.md5()
    m.update(payload)
    m.update(len(payload).to_bytes(4, "little"))
    m.update(version)
    m.update(b"TDF$")
    if m.digest() != stored_md5:
        raise ValueError(f"MD5 checksum mismatch in {path}")
    return payload


def read_local_key(key_path, passcode=""):
    """从 key_datas 读取本地加密密钥"""
    raw = _read_tdf_file(key_path)
    stream = memoryview(raw)
    pos = 0

    def read_qbytearray():
        nonlocal pos
        size = struct.unpack_from(">I", stream, pos)[0]
        pos += 4
        chunk = bytes(stream[pos : pos + size])
        pos += size
        return chunk

    salt = read_qbytearray()
    key_encrypted = read_qbytearray()
    _info_encrypted = read_qbytearray()
    pass_key = _create_local_key(passcode.encode(), salt)
    key_data = _decrypt_local(key_encrypted, pass_key)
    return bytearray(key_data)


class _CTRDecryptor:
    def __init__(self, key, iv):
        self.key = key
        self.iv = bytearray(iv)
        self.block_index = 0

    def decrypt(self, src):
        crypto = _import_crypto()
        if crypto is None:
            raise RuntimeError("缺少依赖 cryptography，请安装后重试")
        default_backend, Cipher, algorithms, modes = crypto
        counter = int.from_bytes(self.iv, "big") + self.block_index
        iv = counter.to_bytes(16, "big")
        cipher = Cipher(
            algorithms.AES(self.key),
            modes.CTR(iv),
            backend=default_backend(),
        )
        result = cipher.decryptor().update(src)
        self.block_index += len(src) // 16
        return result


def decrypt_tdf_file(path, key):
    """解密 TDF$ 格式文件"""
    payload = _read_tdf_file(path)
    size = struct.unpack_from(">I", payload, 0)[0]
    encrypted = payload[4 : 4 + size]
    return bytes(_decrypt_local(encrypted, key))


def decrypt_tdef_file(path, key):
    """解密 TDEF 格式文件"""
    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"TDEF":
            raise ValueError(f"not a TDEF file: {magic!r}")
        salt = f.read(64)
        header_encrypted = f.read(48)
        rest = f.read()
    real_key = _sha256(bytes(key[: len(key) // 2]) + salt[:32])
    iv = _sha256(bytes(key[len(key) // 2 :]) + salt[32:])[:16]
    d = _CTRDecryptor(real_key, iv)
    header = d.decrypt(header_encrypted)
    if _sha256(bytes(key) + salt + header[:16]) != header[16:]:
        raise ValueError(f"wrong key for {path}")
    return d.decrypt(rest)


def detect_extension(data):
    """通过魔数识别文件扩展名"""
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"\x89PNG":
        return ".png"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:4] == b"RIFF":
        return ".webp" if data[8:12] == b"WEBP" else ""
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    if data[4:8] == b"ftyp":
        return ".mp4"
    return ""


def _check_ffmpeg():
    """检查系统是否存在 ffmpeg"""
    return shutil.which("ffmpeg") is not None


def _reap_proc(proc, timeout=5):
    """集中回收子进程：kill 后无条件 wait 回收，实际退出后才从活动集合移除"""
    if proc is None:
        return
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
        # kill 后无条件 wait：真实子进程需 wait 才能回收（避免 zombie）
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()  # 二次 SIGKILL 兜底，确保尽快退出
            except Exception:
                pass
            try:
                proc.wait(timeout=timeout)
            except Exception:
                pass
    # 仅进程实际退出才从集合移除；未退出则保留（可被后续 cancel terminate）
    if proc.poll() is not None:
        with _TG_LOCK:
            _TG_ACTIVE_PROC.discard(proc)


def convert_webm_to_webp(webm_path, out_path, timeout=120):
    """webm 转 animated webp: 有损(q80), 保持宽高比, 最长边 512"""
    proc = None
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-c:v",
            "libvpx-vp9",
            "-i",
            webm_path,
            "-loop",
            "1",
            "-lossless",
            "0",
            "-quality",
            "80",
            "-vf",
            "scale=512:512:force_original_aspect_ratio=decrease",
            "-an",
            out_path,
        ]
        kw = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
        if os.name == "nt" and getattr(sys, "frozen", False):
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen(cmd, **kw)
        with _TG_LOCK:
            _TG_ACTIVE_PROC.add(proc)
        try:
            if _check_cancel():
                proc.terminate()
            try:
                _, _ = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                _reap_proc(proc)
                raise
        finally:
            # 仅在进程实际退出后移除；未退出交由回收路径处理
            if proc.poll() is not None:
                with _TG_LOCK:
                    _TG_ACTIVE_PROC.discard(proc)
        return proc.returncode == 0
    except Exception as e:
        _reap_proc(proc)
        logger.warning(f"convert_webm_to_webp failed: {e}")
        return False


def _gray_thumb(path, size=32):
    """白底合成 RGBA -> 32x32 灰度缩略图, 供内容比对"""
    from PIL import Image as PILImage

    with PILImage.open(path) as im:
        im = im.convert("RGBA").resize((size, size))
        bg = PILImage.new("RGBA", im.size, (255, 255, 255, 255))
        return PILImage.alpha_composite(bg, im).convert("L")


def _thumb_diff(a, b, size=32):
    """归一化灰度差分, 0=完全一致, 1=完全相反"""
    from PIL import ImageChops

    d = ImageChops.difference(a, b)
    hist = d.histogram()
    return sum(h * i for h, i in enumerate(hist)) / (size * size * 255.0)


def _is_animated_webp(path):
    """webp 是否多帧动画"""
    from PIL import Image as PILImage

    try:
        with PILImage.open(path) as im:
            return getattr(im, "n_frames", 1) > 1
    except Exception:
        return False


def dedup_static_against_animated(webp_paths, threshold=0.02):
    """去掉与动画 webp 首帧内容一致的静态 webp（动态表情的静态版）"""
    try:
        from PIL import Image as PILImage  # noqa: F401
    except ImportError:
        return list(webp_paths), 0
    animated = []
    static = []
    for p in webp_paths:
        if p.lower().endswith(".webp") and _is_animated_webp(p):
            animated.append(p)
        else:
            static.append(p)
    if not animated or not static:
        return list(webp_paths), 0
    anim_thumbs = []
    for p in animated:
        try:
            anim_thumbs.append(_gray_thumb(p))
        except Exception:
            continue
    if not anim_thumbs:
        return list(webp_paths), 0
    keep = list(animated)
    skipped = 0
    for p in static:
        try:
            t = _gray_thumb(p)
        except Exception:
            keep.append(p)
            continue
        if any(_thumb_diff(t, at) < threshold for at in anim_thumbs):
            logger.info(f"skip static version of animated sticker: {p}")
            skipped += 1
        else:
            keep.append(p)
    return keep, skipped


def start_tg_import(
    import_callback,
    tdata_path=None,
    passcode="",
    convert_webm=True,
    job_manager=None,
):
    """后台启动 Telegram 表情包导入流程，已有任务时返回 False"""
    global _TG_CANCEL
    if job_manager is not None and job_manager.active("import.telegram") is not None:
        return False
    with _TG_LOCK:
        if _TG_STATE["status"] in (
            "scanning",
            "loading_key",
            "decrypting",
            "converting",
            "deduping",
            "importing",
        ):
            return False
        _reset_state()
        # 锁内立即占位运行态，使并发调用在锁内看到 scanning 而拒绝，防止双 worker
        _update_tg(status="scanning", message="正在检测 Telegram Desktop 数据目录...")

    def target(context):
        global _TG_JOB_CANCEL, _TG_JOB_SNAPSHOT
        try:
            _tg_worker(import_callback, tdata_path, passcode, convert_webm)
            if _TG_STATE["status"] == "error":
                raise RuntimeError(f"{_TG_STATE['error_code']}: {_TG_STATE['error']}")
        finally:
            _TG_JOB_CANCEL = None
            _TG_JOB_SNAPSHOT = None

    if job_manager is None:
        threading.Thread(
            target=_tg_worker,
            args=(import_callback, tdata_path, passcode, convert_webm),
            daemon=True,
        ).start()
    else:
        _, created = job_manager.try_start(
            "import.telegram",
            target,
            resources=("telegram",),
            on_admit=lambda record, context: _bind_tg_job(job_manager, record, context),
        )
        if not created:
            return False
    return True


def _tg_worker(import_callback, tdata_path, passcode, convert_webm):
    """后台: 检测 tdata -> 解密缓存 -> (可选) webm转webp -> 导入回调"""
    temp_dir = None
    try:
        _update_tg(status="scanning", message="正在检测 Telegram Desktop 数据目录...")
        if _check_cancel():
            _update_tg(status="cancelled", message="已取消")
            return
        if tdata_path:
            tdata = tdata_path
            if _check_cancel():
                _update_tg(status="cancelled", message="已取消")
                return
            if not is_valid_tdata(tdata):
                if _check_cancel():
                    _update_tg(status="cancelled", message="已取消")
                    return
                logger.error("tg import: 无效 tdata 目录: %s", tdata)
                _update_tg(
                    status="error",
                    error_code="invalid_tdata",
                    error=(
                        f"目录不是有效的 Telegram tdata"
                        f"（未找到 key_datas/key_data）: {tdata}"
                    ),
                )
                return
        else:
            tdata = find_tdata_path()
            if not tdata:
                logger.error("tg import: 未检测到 tdata 目录")
                _update_tg(
                    status="error",
                    error_code="no_tdata",
                    error=(
                        "未自动检测到 Telegram Desktop 数据目录，请手动指定 tdata 目录"
                        "（点击下方按钮或设置页「手动指定 tdata 目录」）"
                    ),
                )
                return
        _update_tg(status="loading_key", message="正在加载解密密钥...")
        if _check_cancel():
            _update_tg(status="cancelled", message="已取消")
            return
        key_path = os.path.join(tdata, "key_datas")
        if not os.path.exists(key_path):
            key_path = os.path.join(tdata, "key_data")
        if not os.path.exists(key_path):
            logger.error("tg import: 未找到 key_datas 文件: %s", key_path)
            _update_tg(
                status="error",
                error_code="invalid_tdata",
                error="未找到 key_datas 文件",
            )
            return
        try:
            local_key = read_local_key(key_path, passcode)
        except Exception as e:
            logger.error("tg import: 密钥加载失败: %s", e)
            _update_tg(
                status="error",
                error_code="bad_key",
                error=(
                    f"密钥加载失败: {e}"
                    "（若 Telegram Desktop 设置了本地密码，需要提供正确密码）"
                ),
            )
            return
        cache_dirs = []
        for sub in ("user_data/cache", "user_data/media_cache"):
            p = os.path.join(tdata, sub.replace("/", os.sep))
            if os.path.isdir(p):
                cache_dirs.append(p)
        if not cache_dirs:
            logger.error("tg import: 未找到缓存目录: %s", tdata)
            _update_tg(status="error", error_code="no_cache", error="未找到缓存目录")
            return
        all_files = []
        for cache_dir in cache_dirs:
            for root, _, files in os.walk(cache_dir):
                for name in files:
                    if name in ("version", "binlog", "maps", "maps0", "maps1"):
                        continue
                    all_files.append(os.path.join(root, name))
        total_files = len(all_files)
        global _TG_T0
        _TG_T0 = time.monotonic()
        _update_tg(
            status="decrypting",
            message="正在解密缓存文件...",
            total=total_files,
            done=0,
        )
        if _check_cancel():
            _update_tg(status="cancelled", message="已取消")
            return
        temp_dir = tempfile.mkdtemp(prefix="tg_import_")
        decrypted_paths = []
        for i, fpath in enumerate(all_files):
            if _check_cancel():
                _update_tg(status="cancelled", message="已取消")
                return
            try:
                with open(fpath, "rb") as f:
                    magic = f.read(4)
                if magic == b"TDEF":
                    data = decrypt_tdef_file(fpath, local_key)
                elif magic == b"TDF$":
                    data = decrypt_tdf_file(fpath, local_key)
                else:
                    continue
                ext = detect_extension(data)
                if ext not in (".webp", ".webm"):
                    continue
                out_path = os.path.join(temp_dir, f"tg_{i}{ext}")
                with open(out_path, "wb") as f:
                    f.write(data)
                decrypted_paths.append(out_path)
            except RuntimeError as e:
                if "缺少依赖" in str(e):
                    raise
                logger.debug(f"skip {fpath}: {e}")
            except Exception as e:
                logger.debug(f"skip {fpath}: {e}")
            finally:
                pct = int((i + 1) / total_files * 100) if total_files > 0 else 100
                _update_tg(
                    progress=pct,
                    done=i + 1,
                    message=f"正在解密: {i + 1}/{total_files}",
                )
        if not decrypted_paths:
            _update_tg(status="done", message="未找到表情包文件", total=0, done=0)
            return
        convert_failed = 0
        if convert_webm:
            webm_count = sum(1 for p in decrypted_paths if p.endswith(".webm"))
            if webm_count and not _check_ffmpeg():
                logger.error("tg import: 检测到 WebM 但未安装 ffmpeg")
                _update_tg(
                    status="error",
                    error_code="no_ffmpeg",
                    error=(
                        "检测到 WebM 表情，但系统未安装 ffmpeg，无法转换为 WebP。"
                        "请安装 ffmpeg 后重试"
                    ),
                )
                return
            _update_tg(
                status="converting",
                message="正在转换 WebM 到 WebP...",
                progress=0,
                done=0,
                total=len(decrypted_paths),
            )
            if _check_cancel():
                _update_tg(status="cancelled", message="已取消")
                return
            converted = []
            total = len(decrypted_paths)
            # 并行转换: 受控并发, 避免内存峰值与资源争用
            workers = min(os.cpu_count() or 1, 4)
            executor = ThreadPoolExecutor(max_workers=workers)
            futures = {}
            done_count = 0
            fail_count = 0
            try:
                for fpath in decrypted_paths:
                    if _check_cancel():
                        break
                    if fpath.endswith(".webm"):
                        webp_path = fpath.replace(".webm", ".webp")
                        fut = executor.submit(convert_webm_to_webp, fpath, webp_path)
                        futures[fut] = (fpath, webp_path)
                    else:
                        converted.append(fpath)
                        with _TG_LOCK:
                            done_count += 1
                        pct = int(done_count / total * 100) if total else 100
                        _update_tg(
                            progress=pct,
                            done=done_count,
                            convert_failed=fail_count,
                            message=f"正在转换: {done_count}/{total}",
                        )
                for fut in as_completed(futures):
                    if _check_cancel():
                        break
                    fpath, webp_path = futures[fut]
                    try:
                        ok = fut.result()
                    except Exception as e:
                        logger.warning(f"convert failed {fpath}: {e}")
                        ok = False
                    with _TG_LOCK:
                        done_count += 1
                        if ok:
                            try:
                                os.unlink(fpath)
                            except OSError:
                                pass
                            converted.append(webp_path)
                        else:
                            fail_count += 1
                        pct = int(done_count / total * 100) if total else 100
                        _update_tg(
                            progress=pct,
                            done=done_count,
                            convert_failed=fail_count,
                            message=f"正在转换: {done_count}/{total}",
                        )
            finally:
                # 等已启动的转换 future 退出，避免与 temp_dir 清理/下次导入交错
                executor.shutdown(wait=True, cancel_futures=True)
            if _check_cancel():
                _update_tg(status="cancelled", message="已取消")
                return
            convert_failed = fail_count
            decrypted_paths = converted
            _update_tg(status="converting", message="转换完成")
        skipped_static = 0
        if decrypted_paths:
            _update_tg(
                status="deduping",
                message="正在去重动态表情的静态版本...",
                progress=0,
                done=0,
                total=len(decrypted_paths),
            )
            decrypted_paths, skipped_static = dedup_static_against_animated(
                decrypted_paths
            )
        if not decrypted_paths:
            _update_tg(
                status="done",
                message="未找到表情包文件"
                + (
                    f"（{convert_failed} 个 WebM 转换失败已跳过）"
                    if convert_failed
                    else ""
                ),
                total=0,
                done=0,
                convert_failed=convert_failed,
                skipped_static=skipped_static,
            )
            return
        _update_tg(
            status="importing",
            message="正在导入表情包...",
            progress=0,
            done=0,
            total=len(decrypted_paths),
        )
        if _check_cancel():
            _update_tg(status="cancelled", message="已取消")
            return
        total = len(decrypted_paths)
        imported_ids = []
        rejected = 0
        batch = 20
        for i in range(0, total, batch):
            if _check_cancel():
                _update_tg(status="cancelled", message="已取消")
                return
            chunk = decrypted_paths[i : i + batch]
            r = import_callback(chunk)
            imported_ids.extend(r.get("ids", []))
            rejected += r.get("rejected", 0)
            _update_tg(
                status="importing",
                message=f"正在导入: {min(i + batch, total)}/{total}",
                progress=int(min(i + batch, total) / total * 100),
                done=min(i + batch, total),
            )
        imported = len(imported_ids)
        msg = f"导入完成，共 {imported} 个表情"
        if convert_failed:
            msg += f"（{convert_failed} 个 WebM 转换失败已跳过）"
        if skipped_static:
            msg += f"（跳过 {skipped_static} 个动态表情的静态版本）"
        _update_tg(
            status="done",
            message=msg,
            progress=100,
            done=total,
            imported=imported,
            rejected=rejected,
            convert_failed=convert_failed,
            skipped_static=skipped_static,
        )
    except Exception as e:
        logger.error(f"tg import error: {e}")
        _update_tg(status="error", error_code="", error=str(e))
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
