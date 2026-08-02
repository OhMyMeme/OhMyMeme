"""云端同步 - FTP / S3 (兼容 R2/MinIO) 实现"""

import json
import logging
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from ftplib import FTP, error_perm
from pathlib import Path
from typing import Optional

from .config import get_config
from .database import get_db
from .manifest import INDEX_FILENAME
from .manifest import build as build_manifest
from .manifest import load as load_manifest

logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()
_sync_run_lock = threading.Lock()  # 防止 push/pull 并发执行

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
    with _sync_lock:
        _sync_state.update(**kw)


def _increment_sync_progress(files_add=0, bytes_add=0, current_file=""):
    """原子递增进度计数器（多线程安全）"""
    with _sync_lock:
        _sync_state["files_done"] += files_add
        _sync_state["bytes_done"] += bytes_add
        if current_file:
            _sync_state["current_file"] = current_file


def _chunk_list(lst, n):
    """将列表均匀分成 n 个块"""
    if n < 1 or not lst:
        return [lst] if lst else []
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m) : (i + 1) * k + min(i + 1, m)] for i in range(n)]


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

    def list_files(self, path: str) -> list:
        """列出远端目录下的文件名（仅顶层）。不支持时抛 NotImplementedError。"""
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
        except error_perm as e:
            if "550" in str(e):  # 550说明文件不存在，视为删除成功
                return True
            return False
        except Exception as e:
            logger.warning("delete failed %s: %s", path, e)
            return False

    def list_files(self, path):
        try:
            names = []
            self.ftp.retrlines("NLST %s" % path, names.append)
            return [n.split("/")[-1] for n in names if n and not n.endswith("/")]
        except Exception as e:
            logger.warning("list_files %s failed: %s", path, e)
            raise

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
        from botocore.config import Config as BotoConfig

        kwargs = {"endpoint_url": endpoint}
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        if region:
            kwargs["region_name"] = region

        try:
            config = BotoConfig(s3={"payload_signing_enabled": False})
            self.client = boto3.client("s3", config=config, **kwargs)
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
            with open(local_path, "rb") as f:
                data = f.read()
            key = self._key(remote_path)
            url = self.client.generate_presigned_url(
                ClientMethod="put_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=3600,
            )
            req = urllib.request.Request(url, data=data, method="PUT")
            req.add_header("Content-Type", "application/octet-stream")
            with urllib.request.urlopen(req) as resp:
                if resp.status != 200:
                    logger.warning(
                        "upload failed %s: HTTP %d", remote_path, resp.status
                    )
                    return False
            return True
        except Exception as e:
            logger.warning("upload failed %s: %s", remote_path, e)
            return False

    def download_file(self, remote_path, local_path):
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            resp = self.client.get_object(
                Bucket=self.bucket, Key=self._key(remote_path)
            )
            raw = resp["Body"].read()
            with open(local_path, "wb") as f:
                f.write(raw)
            return True
        except Exception as e:
            logger.warning("download failed %s: %s", remote_path, e)
            return False

    def file_exists(self, path):
        key = self._key(path)
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            try:
                self.client.get_object(Bucket=self.bucket, Key=key)["Body"].close()
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

    def list_files(self, path):
        prefix = self._key(path)
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        keys = []
        kwargs = {"Bucket": self.bucket, "Prefix": prefix}
        while True:
            resp = self.client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                keys.append(key[len(prefix) :])
            if resp.get("IsTruncated"):
                kwargs["ContinuationToken"] = resp.get("NextContinuationToken")
            else:
                break
        return keys

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

    def list_files(self, path):
        prefix = self._key(path)
        if prefix and not prefix.endswith("/"):
            prefix += "/"
        keys = []
        kwargs = {"Bucket": self.bucket, "Prefix": prefix}
        while True:
            resp = self.client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue
                keys.append(key[len(prefix) :])
            if resp.get("IsTruncated"):
                kwargs["ContinuationToken"] = resp.get("NextContinuationToken")
            else:
                break
        return keys

    def close(self):
        self.client = None


# ─── WebDAV 后端 ───


class _WebDAVBackend(_SyncBackend):
    def __init__(self, cfg):
        self.cfg = cfg
        self.base_url = ""
        self.auth_header = ""

    def connect(self):
        url = self.cfg.get("webdav_url", "")
        user = self.cfg.get("webdav_user", "")
        password = self.cfg.get("webdav_password", "")
        if not url:
            raise SyncError("WebDAV url not configured")
        self.base_url = url.rstrip("/")
        if user:
            import base64

            token = base64.b64encode(
                ("%s:%s" % (user, password)).encode("utf-8")
            ).decode("ascii")
            self.auth_header = "Basic %s" % token

    def _url(self, remote_path):
        return self.base_url + "/" + remote_path.lstrip("/")

    def _request(self, method, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", "OhMyMeme")
        if self.auth_header:
            req.add_header("Authorization", self.auth_header)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        return urllib.request.urlopen(req, timeout=30)

    def ensure_remote_dir(self, path):
        parts = [p for p in path.strip("/").split("/") if p]
        cur = self.base_url
        for p in parts:
            cur += "/" + p
            try:
                with self._request("MKCOL", cur):
                    pass
            except urllib.error.HTTPError as e:
                if e.code not in (405, 301):  # 405=已存在, 301=重定向到自身
                    logger.warning("MKCOL %s -> HTTP %d", cur, e.code)
            except Exception as e:
                logger.warning("MKCOL %s failed: %s", cur, e)

    def upload_file(self, local_path, remote_path):
        try:
            size = local_path.stat().st_size
            with open(local_path, "rb") as f:
                with self._request(
                    "PUT",
                    self._url(remote_path),
                    data=f,
                    headers={"Content-Length": str(size)},
                ) as resp:
                    return 200 <= resp.status < 300
        except Exception as e:
            logger.warning("upload failed %s: %s", remote_path, e)
            return False

    def download_file(self, remote_path, local_path):
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with self._request("GET", self._url(remote_path)) as resp:
                raw = resp.read()
            with open(local_path, "wb") as f:
                f.write(raw)
            return True
        except Exception as e:
            logger.warning("download failed %s: %s", remote_path, e)
            return False

    def file_exists(self, path):
        try:
            with self._request(
                "PROPFIND", self._url(path), headers={"Depth": "0"}
            ) as resp:
                return resp.status in (200, 207)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            logger.warning("file_exists %s -> HTTP %d", path, e.code)
            return False
        except Exception as e:
            logger.warning("file_exists %s failed: %s", path, e)
            return False

    def delete_file(self, path):
        try:
            with self._request("DELETE", self._url(path)) as resp:
                return resp.status in (200, 204)
        except urllib.error.HTTPError as e:
            if e.code == 404:  # 404说明目标不存在，视为删除成功
                return True
            logger.warning("delete failed %s -> HTTP %d", path, e.code)
            return False
        except Exception as e:
            logger.warning("delete failed %s: %s", path, e)
            return False

    def list_files(self, path):
        import xml.etree.ElementTree as ET

        url = self._url(path)
        with self._request("PROPFIND", url, headers={"Depth": "1"}) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        base = url.rstrip("/") + "/"
        files = []
        root = ET.fromstring(raw)
        for response in root.findall("{DAV:}response"):
            href_el = response.find("{DAV:}href")
            if href_el is None or href_el.text is None:
                continue
            href = href_el.text.strip()
            if href.endswith("/"):
                continue  # 目录条目跳过（仅顶层）
            if href.rstrip("/") == url.rstrip("/"):
                continue
            if href.startswith(base):
                name = href[len(base) :]
            else:
                name = href.split("/")[-1]
            if name:
                files.append(name)
        return files

    def close(self):
        pass


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
    elif sync_type == "webdav":
        return _WebDAVBackend(cfg)
    else:
        raise SyncError("No sync type configured")


def _connect():
    """快捷方式：直接建立 FTP 连接（供 sync_test_ftp 等外部调用）"""
    bk = _FtpBackend(get_config())
    bk.connect()
    return bk.ftp


def _remote_root(cfg) -> str:
    """返回远端根路径：FTP→ftp_path，WebDAV→webdav_path，对象存储→空"""
    st = cfg.get("sync_type", "")
    if st == "ftp":
        return cfg.get("ftp_path", "/")
    if st == "webdav":
        return cfg.get("webdav_path", "")
    return ""


def _fetch_remote_memes(bk, remote_root):
    """下载远端 manifest 并返回 {filename: entry} 字典（无 manifest 返回 {}）"""
    cfg = get_config()
    remote_path = remote_root.rstrip("/") + "/" + REMOTE_INDEX
    if not bk.file_exists(remote_path):
        return {}
    fd, tmp_name = tempfile.mkstemp(
        prefix=".remote-index-", suffix=".json", dir=str(cfg.data_dir)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        if not bk.download_file(remote_path, tmp):
            raise SyncError("远端 manifest 下载失败")
        raw_bytes = tmp.read_bytes()
        rdata = json.loads(raw_bytes.decode("utf-8"))
        return {m["filename"]: m for m in rdata.get("memes", [])}
    except SyncError:
        raise
    except Exception as e:
        raise SyncError("远端 manifest 解析失败: %s" % e)
    finally:
        if tmp.exists():
            tmp.unlink()


# ─── 多线程工作函数 ───


def _push_worker(entries, remote_root, cache_dir, thumb_dir, remote_memes):
    """单线程批量上传一批文件"""
    bk = _get_backend()
    bk.connect()
    local_results = {"uploaded": 0, "skipped": 0, "errors": 0, "bytes": 0}
    try:
        for entry in entries:
            fname = entry["filename"]
            local_file = cache_dir / fname
            fsize = local_file.stat().st_size if local_file.exists() else 0
            local_hash = entry["sha256"]
            remote_entry = remote_memes.get(fname)
            rem_path = remote_root.rstrip("/") + "/" + REMOTE_MEME_DIR + "/" + fname
            if remote_entry and remote_entry.get("sha256") == local_hash:
                try:
                    remote_ok = bk.file_exists(rem_path)
                except Exception:
                    remote_ok = False
                if remote_ok:
                    local_results["skipped"] += 1
                    _increment_sync_progress(files_add=1)
                    continue
            if not local_file.exists():
                local_results["errors"] += 1
                _increment_sync_progress(files_add=1)
                continue
            bk.ensure_remote_dir(os.path.dirname(rem_path))
            if bk.upload_file(local_file, rem_path):
                local_results["uploaded"] += 1
                local_results["bytes"] += fsize
                _increment_sync_progress(files_add=1, bytes_add=fsize)
            else:
                local_results["errors"] += 1
                _increment_sync_progress(files_add=1)
            thumb_file = thumb_dir / ("%s_thumb.png" % fname)
            if thumb_file.exists():
                rem_thumb = (
                    remote_root.rstrip("/") + "/" + REMOTE_THUMB_DIR + "/" + fname
                )
                bk.ensure_remote_dir(os.path.dirname(rem_thumb))
                bk.upload_file(thumb_file, rem_thumb)
        return local_results
    except Exception as e:
        logger.warning("push worker error: %s", e)
        done = (
            local_results["uploaded"]
            + local_results["skipped"]
            + local_results["errors"]
        )
        remaining = len(entries) - done
        if remaining > 0:
            local_results["errors"] += remaining
            _increment_sync_progress(files_add=remaining)
        return local_results
    finally:
        bk.close()


def _pull_worker(entries, remote_root, cache_dir, thumb_dir, db):
    """单线程批量下载一批文件"""
    bk = _get_backend()
    bk.connect()
    local_results = {"downloaded": 0, "skipped": 0, "errors": 0, "bytes": 0}
    local_idx = {}
    try:
        from .manifest import load as _load_manifest

        ld = _load_manifest()
        local_idx = {m["filename"]: m for m in ld.get("memes", [])}
    except Exception:
        pass
    try:
        for fname, rentry in entries:
            local_entry = local_idx.get(fname)
            if (
                local_entry
                and local_entry.get("sha256") == rentry.get("sha256")
                and (cache_dir / fname).exists()
            ):
                local_results["skipped"] += 1
                _increment_sync_progress(files_add=1)
                continue
            rem_path = remote_root.rstrip("/") + "/" + REMOTE_MEME_DIR + "/" + fname
            local_path = cache_dir / fname
            fsize = rentry.get("file_size", 0)
            if bk.download_file(rem_path, local_path):
                if local_path.stat().st_size == 0:
                    # 下载到空文件视为失败：清理并计错误，避免污染本地清单
                    local_results["errors"] += 1
                    _increment_sync_progress(files_add=1)
                    try:
                        local_path.unlink()
                    except Exception:
                        pass
                    continue
                row = db.get_by_filename(fname)
                if not row:
                    try:
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
                    except Exception as e:
                        # DB 写入失败：清理残留 cache，避免“文件在但无记录”的游离态
                        logger.warning("pull db add failed %s: %s", fname, e)
                        local_results["errors"] += 1
                        _increment_sync_progress(files_add=1)
                        try:
                            local_path.unlink()
                        except Exception:
                            pass
                        continue
                local_results["downloaded"] += 1
                local_results["bytes"] += fsize
                _increment_sync_progress(files_add=1, bytes_add=fsize)
            else:
                local_results["errors"] += 1
                _increment_sync_progress(files_add=1)
            rem_thumb = remote_root.rstrip("/") + "/" + REMOTE_THUMB_DIR + "/" + fname
            local_thumb = thumb_dir / fname
            if bk.file_exists(rem_thumb):
                bk.download_file(rem_thumb, local_thumb)
        return local_results
    except Exception as e:
        logger.warning("pull worker error: %s", e)
        done = (
            local_results["downloaded"]
            + local_results["skipped"]
            + local_results["errors"]
        )
        remaining = len(entries) - done
        if remaining > 0:
            local_results["errors"] += remaining
            _increment_sync_progress(files_add=remaining)
        return local_results
    finally:
        bk.close()


# ─── 公开 API ───


def upload_index(bk=None) -> bool:
    """上传本地 manifest 到远端"""
    cfg = get_config()
    remote_root = _remote_root(cfg)
    build_manifest()
    local_index = cfg.data_dir / INDEX_FILENAME
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
    """从远端下载 manifest。

    无 manifest 返回 None；读取/解析失败抛 SyncError。
    """
    cfg = get_config()
    remote_root = _remote_root(cfg)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".remote-index-", suffix=".json", dir=str(cfg.data_dir)
    )
    os.close(fd)
    tmp = Path(tmp_name)
    bk = _get_backend()
    bk.connect()
    try:
        remote_path = remote_root.rstrip("/") + "/" + REMOTE_INDEX
        if not bk.file_exists(remote_path):
            return None
        if not bk.download_file(remote_path, tmp):
            raise SyncError("远端 manifest 下载失败")
        raw_bytes = tmp.read_bytes()
        data = json.loads(raw_bytes.decode("utf-8"))
        return data
    except SyncError:
        raise
    except Exception as e:
        logger.warning("download_index failed: %s", e)
        raise SyncError("远端 manifest 解析失败: %s" % e)
    finally:
        bk.close()
        if tmp.exists():
            tmp.unlink()


def push(delete_remote: bool = None) -> dict:
    """本地 -> 远端：上传缺失/变更的表情包和清单（多线程）"""
    cfg = get_config()
    if delete_remote is None:
        delete_remote = cfg.get("sync_delete_remote", False)
    remote_root = _remote_root(cfg)
    cache_dir = cfg.cache_dir
    thumb_dir = cfg.thumbnail_dir
    max_workers = max(1, min(8, int(cfg.get("sync_threads", 3))))
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

    if not _sync_run_lock.acquire(blocking=False):
        raise SyncError("同步正在进行中")

    _reset_sync_state("upload", files_total, bytes_total)
    start = time.time()
    _update_sync_state(status="uploading", start_time=start)

    bk = None
    try:
        bk = _get_backend()
        bk.connect()
        bk.ensure_remote_dir(remote_root)
        remote_memes = _fetch_remote_memes(bk, remote_root)
        local_idx = {m["filename"]: m for m in local["memes"]}

        entries = local["memes"]
        if max_workers <= 1 or len(entries) <= 1:
            chunks = [entries]
        else:
            chunks = _chunk_list(entries, min(max_workers, len(entries)))

        aggregated = {"uploaded": 0, "skipped": 0, "errors": 0, "bytes": 0}
        with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
            futures = [
                executor.submit(
                    _push_worker, ch, remote_root, cache_dir, thumb_dir, remote_memes
                )
                for ch in chunks
            ]
            for future in as_completed(futures):
                r = future.result()
                aggregated["uploaded"] += r["uploaded"]
                aggregated["skipped"] += r["skipped"]
                aggregated["errors"] += r["errors"]
                aggregated["bytes"] += r["bytes"]

        if aggregated["errors"] > 0:
            msg = "%d 个文件上传失败，未更新远端 manifest" % aggregated["errors"]
            logger.warning("sync push aborted: %s", msg)
            raise SyncError(msg)

        results = {
            "uploaded": aggregated["uploaded"],
            "skipped": aggregated["skipped"],
            "errors": aggregated["errors"],
            "deleted": 0,
        }

        deleted_fnames = set()
        if delete_remote:
            for fname in list(remote_memes.keys()):
                if fname not in local_idx:
                    rem_path = (
                        remote_root.rstrip("/") + "/" + REMOTE_MEME_DIR + "/" + fname
                    )
                    if bk.delete_file(rem_path):
                        deleted_fnames.add(fname)
                        results["deleted"] += 1
                    else:
                        # 删除结果不确定：复核远端是否真的已删
                        try:
                            still = bk.file_exists(rem_path)
                        except Exception:
                            still = True  # 复核异常 → unknown，保留待下次重查
                        if not still:
                            # 复核确认已删 → 视为删除成功
                            deleted_fnames.add(fname)
                            results["deleted"] += 1
                        # still=True（仍在或复核异常）→ 保留在远端 manifest
                    rem_thumb = (
                        remote_root.rstrip("/") + "/" + REMOTE_THUMB_DIR + "/" + fname
                    )
                    bk.delete_file(rem_thumb)

        build_manifest()
        remote_manifest_path = remote_root.rstrip("/") + "/" + REMOTE_INDEX
        merged_file = None
        try:
            # 远端仍保留、但本地清单没有的项合并进待上传清单，避免孤儿
            data = load_manifest()
            local_fnames = {m["filename"] for m in data["memes"]}
            kept = [
                m
                for fname, m in remote_memes.items()
                if fname not in local_fnames and fname not in deleted_fnames
            ]
            manifest_file = cfg.data_dir / INDEX_FILENAME
            if kept:
                data["memes"].extend(kept)
                fd, tmp_name = tempfile.mkstemp(
                    prefix=".remote-merged-", suffix=".json", dir=str(cfg.data_dir)
                )
                os.close(fd)
                merged_file = Path(tmp_name)
                merged_file.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                manifest_file = merged_file
            ok = bk.upload_file(manifest_file, remote_manifest_path)
            if not ok:
                raise SyncError("远端 manifest 上传失败")
        finally:
            if merged_file is not None and merged_file.exists():
                try:
                    merged_file.unlink()
                except Exception:
                    pass

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
        if bk is not None:
            bk.close()
        _sync_run_lock.release()


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
    """远端 -> 本地：下载缺失/变更的表情包和清单（多线程）"""
    cfg = get_config()
    if remove_local is None:
        remove_local = cfg.get("sync_remove_local", False)
    remote_root = _remote_root(cfg)
    cache_dir = cfg.cache_dir
    thumb_dir = cfg.thumbnail_dir
    max_workers = max(1, min(8, int(cfg.get("sync_threads", 3))))
    db = get_db()

    if not _sync_run_lock.acquire(blocking=False):
        raise SyncError("同步正在进行中")

    try:
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
        _update_sync_state(status="downloading", start_time=start)

        entries = list(remote_idx.items())
        if max_workers <= 1 or len(entries) <= 1:
            chunks = [entries]
        else:
            chunks = _chunk_list(entries, min(max_workers, len(entries)))

        aggregated = {"downloaded": 0, "skipped": 0, "errors": 0, "bytes": 0}
        with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
            futures = [
                executor.submit(_pull_worker, ch, remote_root, cache_dir, thumb_dir, db)
                for ch in chunks
            ]
            for future in as_completed(futures):
                r = future.result()
                aggregated["downloaded"] += r["downloaded"]
                aggregated["skipped"] += r["skipped"]
                aggregated["errors"] += r["errors"]
                aggregated["bytes"] += r["bytes"]

        results = {
            "downloaded": aggregated["downloaded"],
            "skipped": aggregated["skipped"],
            "errors": aggregated["errors"],
            "removed_local": 0,
        }

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
        if aggregated["errors"] > 0:
            msg = "%d 个文件下载失败，本地清单仅包含成功项" % aggregated["errors"]
            logger.warning("sync pull aborted: %s", msg)
            raise SyncError(msg)

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
        _sync_run_lock.release()


def delete_all_remote() -> dict:
    """删除远端所有表情包和清单"""
    from .config import get_config

    cfg = get_config()
    remote_root = _remote_root(cfg)
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


def list_remote_orphans(bk, remote_root) -> list:
    """返回远端 memes/ 中真实存在但 manifest 未记录的孤儿文件名。

    后端不支持 list_files 或目录不可枚举时返回 []（降级，不影响主同步）。
    """
    remote_path = remote_root.rstrip("/") + "/" + REMOTE_MEME_DIR
    try:
        remote_files = bk.list_files(remote_path)
    except NotImplementedError:
        return []
    except Exception as e:
        logger.warning("list_files %s failed: %s", remote_path, e)
        return []
    try:
        remote_memes = _fetch_remote_memes(bk, remote_root)
    except Exception as e:
        logger.warning("list_remote_orphans fetch manifest failed: %s", e)
        return []
    return [fname for fname in remote_files if fname not in remote_memes]


def cleanup_remote_orphans(delete: bool = False) -> dict:
    """识别远端孤儿文件；delete=True 时物理删除，返回 {ok, orphans, removed}。"""
    cfg = get_config()
    remote_root = _remote_root(cfg)
    bk = _get_backend()
    bk.connect()
    try:
        orphans = list_remote_orphans(bk, remote_root)
        removed = 0
        if delete:
            for fname in orphans:
                rem_path = remote_root.rstrip("/") + "/" + REMOTE_MEME_DIR + "/" + fname
                if bk.delete_file(rem_path):
                    removed += 1
        return {"ok": True, "orphans": orphans, "removed": removed}
    except Exception as e:
        logger.warning("cleanup_remote_orphans failed: %s", e)
        return {"ok": False, "error": str(e)}
    finally:
        bk.close()


def cleanup_stale_temp_files() -> int:
    """清理数据目录下中断遗留的临时文件（.remote-* / *.tmp），返回清理数量。"""
    cfg = get_config()
    data_dir = cfg.data_dir
    if not data_dir.exists():
        return 0
    count = 0
    for p in data_dir.iterdir():
        if not p.is_file():
            continue
        name = p.name
        if name.startswith(".remote-") or name.endswith(".tmp"):
            try:
                p.unlink()
                count += 1
            except Exception:
                pass
    return count
