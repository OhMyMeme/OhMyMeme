"""同步远端后端适配器。"""

import logging
import os
import shutil
import urllib.error
import urllib.request
from ftplib import FTP, error_perm
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

logger = logging.getLogger(__name__)


class SyncError(Exception):
    pass


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

    def test_connection(self):
        """连接后做一次真实可达性/权限探测（可选）。失败抛 SyncError。"""

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
        """连接 S3 后端，创建 boto3 客户端"""
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
            addressing = self.cfg.get("s3_addressing_style", "virtual")
            if addressing not in ("virtual", "path"):
                addressing = "virtual"
            sig_ver = self.cfg.get("s3_signature_version", "s3")
            if sig_ver not in ("s3", "s3v4"):
                sig_ver = "s3"
            config = BotoConfig(
                signature_version=sig_ver,
                s3={"payload_signing_enabled": False, "addressing_style": addressing},
            )
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
        # V2 签名下 boto3 put_object 不走 chunked 编码，直接用 SDK 上传
        # （presigned URL + urllib 会因多出的 Content-Type 与签名不匹配，OSS 拒绝）
        try:
            with open(local_path, "rb") as f:
                data = f.read()
            self.client.put_object(
                Bucket=self.bucket,
                Key=self._key(remote_path),
                Body=data,
                ContentType="application/octet-stream",
            )
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


def _quote_path(path: str) -> str:
    """按路径段做百分号编码，/ 保留为路径分隔符"""
    return "/".join(quote(part, safe="") for part in path.split("/"))


class _WebDAVBackend(_SyncBackend):
    def __init__(self, cfg):
        self.cfg = cfg
        self.base_url = ""
        self.auth_header = ""
        self.timeout = 30

    def connect(self):
        url = self.cfg.get("webdav_url", "")
        user = self.cfg.get("webdav_user", "")
        password = self.cfg.get("webdav_password", "")
        if not url:
            raise SyncError("WebDAV url not configured")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            raise SyncError("WebDAV URL 必须以 http:// 或 https:// 开头")
        if not parsed.netloc:
            raise SyncError("WebDAV URL 缺少主机名")
        # 规范化 base_url 的 path：按段编码；保留 "/" 与已存在的 "%XX"，避免双重编码
        enc_path = quote(parsed.path, safe="/%")
        self.base_url = "%s://%s%s" % (
            parsed.scheme,
            parsed.netloc,
            enc_path.rstrip("/"),
        )
        try:
            self.timeout = int(self.cfg.get("webdav_timeout", 30))
        except (TypeError, ValueError):
            self.timeout = 30
        if user:
            import base64

            token = base64.b64encode(
                ("%s:%s" % (user, password)).encode("utf-8")
            ).decode("ascii")
            self.auth_header = "Basic %s" % token

    def _url(self, remote_path):
        encoded = _quote_path(remote_path.lstrip("/"))
        if encoded:
            return self.base_url.rstrip("/") + "/" + encoded
        return self.base_url.rstrip("/")

    def _request(self, method, url, data=None, headers=None):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", "OhMyMeme")
        if self.auth_header:
            req.add_header("Authorization", self.auth_header)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        return urllib.request.urlopen(req, timeout=self.timeout)

    def ensure_remote_dir(self, path):
        rel = ""
        for p in [p for p in path.strip("/").split("/") if p]:
            rel += "/" + p
            url = self._url(rel)
            try:
                with self._request("MKCOL", url):
                    pass
            except urllib.error.HTTPError as e:
                if e.code == 405:
                    continue  # 标准"已存在"
                if 300 <= e.code < 400:
                    # 重定向：复核集合确实存在 → 幂等继续，否则判失败
                    if self.file_exists(rel):
                        continue
                raise SyncError("MKCOL %s 失败: HTTP %d" % (url, e.code)) from e
            except Exception as e:
                raise SyncError("MKCOL %s 失败: %s" % (url, e)) from e
        return True

    def upload_file(self, local_path, remote_path):
        try:
            size = local_path.stat().st_size
            with open(local_path, "rb") as f:
                with self._request(
                    "PUT",
                    self._url(remote_path),
                    data=f,
                    headers={
                        "Content-Length": str(size),
                        "Content-Type": "application/octet-stream",
                    },
                ) as resp:
                    return 200 <= resp.status < 300
        except Exception as e:
            logger.warning("upload failed %s: %s", remote_path, e)
            return False

    def download_file(self, remote_path, local_path):
        tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")
        try:
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with (
                self._request("GET", self._url(remote_path)) as resp,
                tmp_path.open("wb") as f,
            ):
                shutil.copyfileobj(resp, f, length=1024 * 1024)
            os.replace(tmp_path, local_path)
            return True
        except Exception as e:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
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
            if e.code in (405, 501):
                # 服务器不支持 PROPFIND → HEAD fallback
                try:
                    with self._request("HEAD", self._url(path)) as resp:
                        return resp.status in (200, 204)
                except urllib.error.HTTPError as e2:
                    if e2.code == 404:
                        return False
                    raise SyncError(
                        "WebDAV HEAD fallback failed: HTTP %d" % e2.code
                    ) from e2
                except Exception as e2:
                    raise SyncError("WebDAV HEAD fallback failed: %s" % e2) from e2
            raise SyncError("WebDAV PROPFIND failed: HTTP %d" % e.code) from e
        except Exception as e:
            raise SyncError("WebDAV file_exists failed: %s" % e) from e

    def test_connection(self):
        """真实网络探测：对 webdav_path 目录发 PROPFIND Depth:0。失败抛 SyncError。"""
        url = self._url(self.cfg.get("webdav_path", ""))
        try:
            with self._request("PROPFIND", url, headers={"Depth": "0"}) as resp:
                if resp.status not in (200, 207):
                    raise SyncError("WebDAV PROPFIND returned HTTP %d" % resp.status)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise SyncError(
                    "WebDAV 目录不存在（HTTP 404），首次上传将自动创建"
                ) from e
            if e.code in (401, 403):
                raise SyncError("WebDAV 鉴权失败（HTTP %d）" % e.code) from e
            if e.code in (405, 501):
                raise SyncError(
                    "WebDAV 服务器不支持 PROPFIND（HTTP %d）" % e.code
                ) from e
            raise SyncError("WebDAV 连接测试失败: HTTP %d" % e.code) from e
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise SyncError("WebDAV 网络不可达: %s" % e) from e

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
        try:
            with self._request("PROPFIND", url, headers={"Depth": "1"}) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (405, 501):
                raise SyncError(
                    "WebDAV 服务器不支持 PROPFIND（HTTP %d）" % e.code
                ) from e
            raise SyncError("WebDAV list_files failed: HTTP %d" % e.code) from e
        except Exception as e:
            raise SyncError("WebDAV list_files failed: %s" % e) from e
        base = url.rstrip("/") + "/"
        files = []
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise SyncError("WebDAV PROPFIND 响应不是合法 XML: %s" % e) from e
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
            name = unquote(name)
            if name:
                files.append(name)
        return files

    def close(self):
        pass


def get_backend(cfg):
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


def connect_ftp(cfg):
    backend = _FtpBackend(cfg)
    backend.connect()
    return backend.ftp
