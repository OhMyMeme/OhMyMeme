"""同步差异、安全文件名和远端路径规划。"""

import json
import logging
import os
import tempfile
from pathlib import Path

from ohmymeme.core.assets import is_safe_filename
from ohmymeme.core.config import get_config
from ohmymeme.core.database import get_db
from ohmymeme.core.manifest import INDEX_FILENAME

from .backends import SyncError

REMOTE_INDEX = INDEX_FILENAME
REMOTE_MEME_DIR = "memes"

logger = logging.getLogger(__name__)


def _chunk_list(lst, n):
    """将列表均匀分成 n 个块"""
    if n < 1 or not lst:
        return [lst] if lst else []
    k, m = divmod(len(lst), n)
    return [lst[i * k + min(i, m) : (i + 1) * k + min(i + 1, m)] for i in range(n)]


def _remote_root(cfg) -> str:
    """返回远端根路径：FTP→ftp_path，WebDAV→webdav_path，对象存储→空"""
    st = cfg.get("sync_type", "")
    if st == "ftp":
        return cfg.get("ftp_path", "/")
    if st == "webdav":
        return cfg.get("webdav_path", "")
    return ""


def _safe_remote_fname(name: str) -> bool:
    """校验远端 manifest 中的文件名，拒绝路径穿越与绝对路径"""
    return is_safe_filename(name)


def _fetch_remote_memes(bk, remote_root, config=None):
    """下载远端 manifest 并返回 {filename: entry} 字典（无 manifest 返回 {}）"""
    cfg = config if config is not None else get_config()
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
        return {
            m["filename"]: m
            for m in rdata.get("memes", [])
            if _safe_remote_fname(m.get("filename", ""))
        }
    except SyncError:
        raise
    except Exception as e:
        raise SyncError("远端 manifest 解析失败: %s" % e)
    finally:
        if tmp.exists():
            tmp.unlink()


def _apply_remote_collections(remote_data: dict, db=None):
    db = db if db is not None else get_db()
    for rc in remote_data.get("collections", []):
        cname = rc["name"]
        cid = db.create_collection(cname)
        if cid < 0:
            continue
        for fname in rc.get("filenames", []):
            row = db.get_by_filename(fname)
            if row:
                db.add_to_collection(row["id"], cid)


def _apply_remote_order(remote_data: dict, db=None):
    """按远端 manifest 的 memes 顺序更新本地 sort_order，保留云端排序"""
    db = db if db is not None else get_db()
    ordered_ids = []
    for m in remote_data.get("memes", []):
        if not isinstance(m, dict):
            continue
        fname = m.get("filename", "")
        if not _safe_remote_fname(fname):
            continue
        row = db.get_by_filename(fname)
        if row:
            ordered_ids.append(row["id"])
    if ordered_ids:
        db.reorder_memes(ordered_ids)


def _apply_remote_metadata(remote_data: dict, db=None):
    (db if db is not None else get_db()).apply_remote_metadata(remote_data)


def list_remote_orphans(bk, remote_root, config=None) -> list:
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
        remote_memes = _fetch_remote_memes(bk, remote_root, config)
    except Exception as e:
        logger.warning("list_remote_orphans fetch manifest failed: %s", e)
        return []
    return [fname for fname in remote_files if fname not in remote_memes]
