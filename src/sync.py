"""云端同步 - FTP / S3 (兼容 R2/MinIO) 实现"""

import json
import logging
import os
import time
from ftplib import FTP, error_perm
from pathlib import Path
from typing import Optional

from .config import get_config
from .database import get_db
from .manifest import INDEX_FILENAME
from .manifest import build as build_manifest
from .manifest import load as load_manifest

logger = logging.getLogger(__name__)

# 同步进度状态（全局，供 JS 轮询）
_sync_state = {
    "status": "idle",  # idle | uploading | downloading | done | error
    "direction": "",  # upload | download
    "progress": 0,  # 0-100
    "files_done": 0,
    "files_total": 0,
    "bytes_done": 0,
    "bytes_total": 0,
    "current_file": "",
    "speed": 0,  # bytes/sec
    "start_time": 0,
    "results": None,
    "error": "",
}


def _reset_sync_state(direction, files_total, bytes_total):
    global _sync_state
    _sync_state.update(
        status="idle",
        direction=direction,
        progress=0,
        files_done=0,
        files_total=files_total,
        bytes_done=0,
        bytes_total=bytes_total,
        current_file="",
        speed=0,
        start_time=0,
        results=None,
        error="",
    )


def _update_sync_state(**kw):
    _sync_state.update(**kw)


def get_sync_progress() -> dict:
    """返回当前同步进度（供 JS 轮询）"""
    s = _sync_state
    if s["start_time"] > 0 and s["status"] in ("uploading", "downloading"):
        elapsed = max(time.time() - s["start_time"], 0.001)
        s["speed"] = s["bytes_done"] / elapsed
        if s["bytes_total"] > 0:
            s["progress"] = min(int(s["bytes_done"] * 100 / s["bytes_total"]), 99)
    return dict(s)

REMOTE_INDEX = INDEX_FILENAME
REMOTE_MEME_DIR = "memes"
REMOTE_THUMB_DIR = "thumbnails"


class SyncError(Exception):
    pass


# ─── 抽象后端 ───


class _SyncBackend:
    """后端基类，定义同步所需的底层操作"""

    def connect(self):
        raise NotImplementedError

    def ensure_remote_dir(self, path: str):
        raise NotImplementedError

    def upload_file(self, local_path: Path, remote_path: str) -> bool:
        raise NotImplementedError

    def download_file(self, remote_path: str, local_path: Path) -> bool:
        raise NotImplementedError

    def file_exists(self, path: str) -> bool:
        raise NotImplementedError

    def delete_file(self, path: str) -> bool:
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


# ─── FTP 后端 ───


class _FtpBackend(_SyncBackend):
    def __init__(self, cfg):
        self.cfg = cfg
        self.ftp = None

    def connect(self):
        host = self.cfg.get("ftp_host", "")
        port = self.cfg.get("ftp_port", 21)
        user = self.cfg.get("ftp_user", "")
        password = self.cfg.get("ftp_password", "")

        if not host:
            raise SyncError("FTP host not configured")

        try:
            ftp = FTP()
            ftp.connect(host, int(port), timeout=15)
            if user:
                ftp.login(user, password)
            else:
                ftp.login()
            ftp.encoding = "utf-8"
            self.ftp = ftp
        except Exception as e:
            raise SyncError("FTP connect failed: %s" % e)

    def ensure_remote_dir(self, path):
        parts = path.strip("/").split("/")
        sofar = ""
        for p in parts:
            if not p:
                continue
            sofar += "/" + p
            try:
                self.ftp.cwd(sofar)
            except error_perm:
                self.ftp.mkd(sofar)
                self.ftp.cwd(sofar)

    def upload_file(self, local_path, remote_path):
        try:
            with open(local_path, "rb") as f:
                self.ftp.storbinary("STOR %s" % remote_path, f)
            return True
        except Exception as e:
            logger.warning("upload failed %s: %s", remote_path, e)
            return False

    def download_file(self, remote_path, local_path):
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "wb") as f:
                self.ftp.retrbinary("RETR %s" % remote_path, f.write)
            return True
        except Exception as e:
            logger.warning("download failed %s: %s", remote_path, e)
            return False

    def file_exists(self, path):
        try:
            self.ftp.size(path)
            return True
        except error_perm:
            return False
        except Exception:
            return False

    def delete_file(self, path):
        try:
            self.ftp.delete(path)
            return True
        except error_perm:
            return False
        except Exception as e:
            logger.warning("delete failed %s: %s", path, e)
            return False

    def close(self):
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except Exception:
                pass
            self.ftp = None


# ─── S3 后端（兼容 R2 / MinIO） ───


class _S3Backend(_SyncBackend):
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = None
        self.bucket = ""
        self.prefix = ""

    def connect(self):
        endpoint = self.cfg.get("s3_endpoint", "")
        region = self.cfg.get("s3_region", "")
        access_key = self.cfg.get("s3_access_key", "")
        secret_key = self.cfg.get("s3_secret_key", "")
        bucket = self.cfg.get("s3_bucket", "")

        if not endpoint or not bucket:
            raise SyncError("S3 endpoint or bucket not configured")

        import boto3

        kwargs = {"endpoint_url": endpoint}
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        if region:
            kwargs["region_name"] = region

        try:
            self.client = boto3.client("s3", **kwargs)
            self.bucket = bucket
            prefix = self.cfg.get("s3_path", "").strip("/")
            self.prefix = (prefix + "/") if prefix else ""
        except Exception as e:
            raise SyncError("S3 connect failed: %s" % e)

    def _key(self, remote_path):
        return self.prefix + remote_path.lstrip("/")

    def ensure_remote_dir(self, path):
        pass

    def upload_file(self, local_path, remote_path):
        try:
            self.client.upload_file(
                str(local_path), self.bucket, self._key(remote_path)
            )
            return True
        except Exception as e:
            logger.warning("upload failed %s: %s", remote_path, e)
            return False

    def download_file(self, remote_path, local_path):
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(
                self.bucket, self._key(remote_path), str(local_path)
            )
            return True
        except Exception as e:
            logger.warning("download failed %s: %s", remote_path, e)
            return False

    def file_exists(self, path):
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(path))
            return True
        except Exception:
            return False

    def delete_file(self, path):
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(path))
            return True
        except Exception as e:
            logger.warning("delete failed %s: %s", path, e)
            return False

    def close(self):
        self.client = None


# ─── R2 后端 ───


class _R2Backend(_SyncBackend):
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = None
        self.bucket = ""
        self.prefix = ""

    def connect(self):
        account_id = self.cfg.get("r2_account_id", "")
        access_key = self.cfg.get("r2_access_key_id", "")
        secret_key = self.cfg.get("r2_secret_access_key", "")
        bucket = self.cfg.get("r2_bucket", "")

        if not account_id or not bucket:
            raise SyncError("R2 account ID and bucket not configured")
        if not access_key or not secret_key:
            raise SyncError("R2 credentials not configured")

        import boto3

        endpoint = "https://%s.r2.cloudflarestorage.com" % account_id

        try:
            self.client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )
            self.bucket = bucket
            prefix = self.cfg.get("r2_path", "").strip("/")
            self.prefix = (prefix + "/") if prefix else ""
        except Exception as e:
            raise SyncError("R2 connect failed: %s" % e)

    def _key(self, remote_path):
        return self.prefix + remote_path.lstrip("/")

    def ensure_remote_dir(self, path):
        pass

    def upload_file(self, local_path, remote_path):
        try:
            self.client.upload_file(
                str(local_path), self.bucket, self._key(remote_path)
            )
            return True
        except Exception as e:
            logger.warning("upload failed %s: %s", remote_path, e)
            return False

    def download_file(self, remote_path, local_path):
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self.client.download_file(
                self.bucket, self._key(remote_path), str(local_path)
            )
            return True
        except Exception as e:
            logger.warning("download failed %s: %s", remote_path, e)
            return False

    def file_exists(self, path):
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(path))
            return True
        except Exception:
            return False

    def delete_file(self, path):
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(path))
            return True
        except Exception as e:
            logger.warning("delete failed %s: %s", path, e)
            return False

    def close(self):
        self.client = None


# ─── 后端工厂 ───


def _get_backend():
    cfg = get_config()
    sync_type = cfg.get("sync_type", "")
    if sync_type == "ftp":
        return _FtpBackend(cfg)
    elif sync_type == "s3":
        return _S3Backend(cfg)
    elif sync_type == "r2":
        return _R2Backend(cfg)
    else:
        raise SyncError("No sync type configured")


def _connect():
    """快捷方式：直接建立 FTP 连接（供 sync_test_ftp 等外部调用）"""
    bk = _FtpBackend(get_config())
    bk.connect()
    return bk.ftp


def _fetch_remote_memes(bk, remote_root):
    """下载远端 manifest 并返回 {filename: entry} 字典"""
    cfg = get_config()
    remote_path = remote_root.rstrip("/") + "/" + REMOTE_INDEX
    if not bk.file_exists(remote_path):
        return {}
    tmp = cfg.data_dir / ".remote-index.json"
    if not bk.download_file(remote_path, tmp):
        return {}
    try:
        rdata = json.loads(tmp.read_text(encoding="utf-8"))
        return {m["filename"]: m for m in rdata.get("memes", [])}
    except Exception:
        return {}
    finally:
        if tmp.exists():
            tmp.unlink()


# ─── 公开 API ───


def upload_index(bk=None) -> bool:
    """上传本地 manifest 到远端"""
    cfg = get_config()
    remote_root = cfg.get("ftp_path", "/") if cfg.get("sync_type", "") == "ftp" else ""
    local_index = cfg.data_dir / INDEX_FILENAME
    if not local_index.exists():
        build_manifest()
    own_backend = bk is None
    if own_backend:
        bk = _get_backend()
        bk.connect()
    try:
        bk.ensure_remote_dir(remote_root)
        remote_path = remote_root.rstrip("/") + "/" + REMOTE_INDEX
        ok = bk.upload_file(local_index, remote_path)
        if ok:
            logger.info("manifest uploaded")
        return ok
    finally:
        if own_backend:
            bk.close()


def download_index() -> Optional[dict]:
    """从远端下载 manifest，返回解析后的 dict 或 None"""
    cfg = get_config()
    remote_root = cfg.get("ftp_path", "/") if cfg.get("sync_type", "") == "ftp" else ""
    tmp = cfg.data_dir / ".remote-index.json"
    bk = _get_backend()
    bk.connect()
    try:
        remote_path = remote_root.rstrip("/") + "/" + REMOTE_INDEX
        if not bk.file_exists(remote_path):
            logger.info("no remote manifest found")
            return None
        if not bk.download_file(remote_path, tmp):
            return None
        data = json.loads(tmp.read_text(encoding="utf-8"))
        return data
    except Exception as e:
        logger.warning("download_index failed: %s", e)
        return None
    finally:
        bk.close()
        if tmp.exists():
            tmp.unlink()


def push(delete_remote: bool = None) -> dict:
    """本地 -> 远端：上传缺失/变更的表情包和清单"""
    cfg = get_config()
    if delete_remote is None:
        delete_remote = cfg.get("sync_delete_remote", False)
    remote_root = cfg.get("ftp_path", "/") if cfg.get("sync_type", "") == "ftp" else ""
    cache_dir = cfg.cache_dir
    thumb_dir = cfg.thumbnail_dir
    local = load_manifest()
    if not local.get("memes"):
        build_manifest()
        local = load_manifest()
        if not local.get("memes"):
            raise SyncError("local manifest is empty, nothing to push")

    # 计算总文件数和字节数
    files_total = len(local["memes"])
    bytes_total = 0
    for entry in local["memes"]:
        fp = cache_dir / entry["filename"]
        if fp.exists():
            bytes_total += fp.stat().st_size

    _reset_sync_state("upload", files_total, bytes_total)
    start = time.time()

    bk = _get_backend()
    bk.connect()
    _update_sync_state(status="uploading", start_time=start)
    results = {"uploaded": 0, "skipped": 0, "errors": 0, "deleted": 0}
    files_done = 0
    bytes_done = 0
    try:
        bk.ensure_remote_dir(remote_root)
        remote_memes = _fetch_remote_memes(bk, remote_root)
        local_idx = {m["filename"]: m for m in local["memes"]}

        for entry in local["memes"]:
            fname = entry["filename"]
            _update_sync_state(current_file=fname)
            local_file = cache_dir / fname
            fsize = local_file.stat().st_size if local_file.exists() else 0
            local_hash = entry["sha256"]
            remote_entry = remote_memes.get(fname)
            if remote_entry and remote_entry.get("sha256") == local_hash:
                results["skipped"] += 1
            elif not local_file.exists():
                results["errors"] += 1
            else:
                rem_path = remote_root.rstrip("/") + "/" + REMOTE_MEME_DIR + "/" + fname
                bk.ensure_remote_dir(os.path.dirname(rem_path))
                if bk.upload_file(local_file, rem_path):
                    results["uploaded"] += 1
                    bytes_done += fsize
                else:
                    results["errors"] += 1
                thumb_file = thumb_dir / ("%s_thumb.png" % fname)
                if thumb_file.exists():
                    rem_thumb = (
                        remote_root.rstrip("/") + "/" + REMOTE_THUMB_DIR + "/" + fname
                    )
                    bk.ensure_remote_dir(os.path.dirname(rem_thumb))
                    bk.upload_file(thumb_file, rem_thumb)
            files_done += 1
            _update_sync_state(files_done=files_done, bytes_done=bytes_done)

        if delete_remote:
            for fname in list(remote_memes.keys()):
                if fname not in local_idx:
                    rem_path = (
                        remote_root.rstrip("/") + "/" + REMOTE_MEME_DIR + "/" + fname
                    )
                    if bk.delete_file(rem_path):
                        results["deleted"] += 1
                    rem_thumb = (
                        remote_root.rstrip("/") + "/" + REMOTE_THUMB_DIR + "/" + fname
                    )
                    bk.delete_file(rem_thumb)

        remote_manifest_path = remote_root.rstrip("/") + "/" + REMOTE_INDEX
        local_index = cfg.data_dir / INDEX_FILENAME
        bk.upload_file(local_index, remote_manifest_path)

        _update_sync_state(
            status="done",
            progress=100,
            files_done=files_total,
            bytes_done=bytes_total,
            results=results,
        )
        logger.info("sync push done: %s", results)
        return results
    except Exception as e:
        _update_sync_state(status="error", error=str(e))
        raise
    finally:
        bk.close()


def sync_test() -> str:
    """测试当前配置的存储后端连接是否可用，返回 'ok' 或错误信息"""
    try:
        bk = _get_backend()
        bk.connect()
        bk.close()
        return "ok"
    except Exception as e:
        return str(e)


def _apply_remote_collections(remote_data: dict):
    db = get_db()
    for rc in remote_data.get("collections", []):
        cname = rc["name"]
        cid = db.create_collection(cname)
        if cid < 0:
            continue
        for fname in rc.get("filenames", []):
            row = db.get_by_filename(fname)
            if row:
                db.add_to_collection(row["id"], cid)


def pull(remove_local: bool = None) -> dict:
    """远端 -> 本地：下载缺失/变更的表情包和清单"""
    cfg = get_config()
    if remove_local is None:
        remove_local = cfg.get("sync_remove_local", False)
    remote_root = cfg.get("ftp_path", "/") if cfg.get("sync_type", "") == "ftp" else ""
    cache_dir = cfg.cache_dir
    thumb_dir = cfg.thumbnail_dir
    db = get_db()

    remote_data = download_index()
    if not remote_data:
        raise SyncError("no remote manifest available")

    remote_idx = {m["filename"]: m for m in remote_data.get("memes", [])}
    local_data = load_manifest()
    local_idx = {m["filename"]: m for m in local_data.get("memes", [])}

    files_total = len(remote_idx)
    bytes_total = 0
    for m in remote_data.get("memes", []):
        bytes_total += m.get("file_size", 0)

    _reset_sync_state("download", files_total, bytes_total)
    start = time.time()

    bk = _get_backend()
    bk.connect()
    _update_sync_state(status="downloading", start_time=start)
    results = {"downloaded": 0, "skipped": 0, "errors": 0, "removed_local": 0}
    files_done = 0
    bytes_done = 0
    try:
        for fname, rentry in remote_idx.items():
            _update_sync_state(current_file=fname)
            local_entry = local_idx.get(fname)
            if local_entry and local_entry.get("sha256") == rentry.get("sha256"):
                results["skipped"] += 1
                files_done += 1
                _update_sync_state(files_done=files_done, bytes_done=bytes_done)
                continue
            rem_path = remote_root.rstrip("/") + "/" + REMOTE_MEME_DIR + "/" + fname
            local_path = cache_dir / fname
            fsize = rentry.get("file_size", 0)
            if bk.download_file(rem_path, local_path):
                if not db.get_by_filename(fname):
                    ext = os.path.splitext(fname)[1].lower()
                    w = h = 0
                    try:
                        from PIL import Image as PILImage

                        img = PILImage.open(local_path)
                        w, h = img.size
                    except Exception:
                        pass
                    oname = rentry.get("name", "") or os.path.splitext(fname)[0]
                    db.add_meme(
                        filename=fname,
                        file_hash=rentry.get("sha256", ""),
                        width=w,
                        height=h,
                        file_size=local_path.stat().st_size,
                        mime_type="image/%s" % ext[1:] if ext else "image/png",
                        original_name=oname,
                    )
                results["downloaded"] += 1
                bytes_done += fsize
            else:
                results["errors"] += 1
            files_done += 1
            _update_sync_state(files_done=files_done, bytes_done=bytes_done)
            rem_thumb = remote_root.rstrip("/") + "/" + REMOTE_THUMB_DIR + "/" + fname
            local_thumb = thumb_dir / fname
            if bk.file_exists(rem_thumb):
                bk.download_file(rem_thumb, local_thumb)

        if remove_local:
            for fname in list(local_idx.keys()):
                if fname not in remote_idx:
                    row = db.get_by_filename(fname)
                    if row:
                        db.delete_meme(row["id"])
                    local_path = cache_dir / fname
                    if local_path.exists():
                        try:
                            local_path.unlink()
                            results["removed_local"] += 1
                        except Exception:
                            pass
                    thumb_path = thumb_dir / fname
                    if thumb_path.exists():
                        try:
                            thumb_path.unlink()
                        except Exception:
                            pass

        _apply_remote_collections(remote_data)
        build_manifest()
        _update_sync_state(
            status="done",
            progress=100,
            files_done=files_total,
            bytes_done=bytes_total,
            results=results,
        )
        logger.info("sync pull done: %s", results)
        return results
    except Exception as e:
        _update_sync_state(status="error", error=str(e))
        raise
    finally:
        bk.close()


def delete_all_remote() -> dict:
    """删除远端所有表情包和清单"""
    from .config import get_config

    cfg = get_config()
    remote_root = cfg.get("ftp_path", "/") if cfg.get("sync_type", "") == "ftp" else ""
    bk = _get_backend()
    bk.connect()
    try:
        remote_memes = _fetch_remote_memes(bk, remote_root)
        count = 0
        for fname in remote_memes:
            rem_path = remote_root.rstrip("/") + "/" + REMOTE_MEME_DIR + "/" + fname
            try:
                bk.delete_file(rem_path)
                count += 1
            except Exception:
                pass
        rem_manifest = remote_root.rstrip("/") + "/" + REMOTE_INDEX
        try:
            bk.delete_file(rem_manifest)
        except Exception:
            pass
        return {"ok": True, "deleted": count}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        bk.close()
