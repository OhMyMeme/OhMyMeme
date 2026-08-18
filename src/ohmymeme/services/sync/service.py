"""云端同步 - FTP / S3 (兼容 R2/MinIO) 实现"""

import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from ohmymeme.core.assets import AssetPaths
from ohmymeme.core.config import get_config
from ohmymeme.core.database import get_db
from ohmymeme.core.imports import ImageImportService, ImportPath
from ohmymeme.core.manifest import INDEX_FILENAME
from ohmymeme.core.manifest import _write as write_manifest
from ohmymeme.core.manifest import build as build_manifest
from ohmymeme.core.manifest import load as load_manifest

from . import planning
from .backends import SyncError, connect_ftp, get_backend

logger = logging.getLogger(__name__)

REMOTE_INDEX = planning.REMOTE_INDEX
REMOTE_MEME_DIR = planning.REMOTE_MEME_DIR

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
    "failed_items": [],  # [{filename, status: error|unknown, error}]
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
        failed_items=[],
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


def get_sync_progress() -> dict:
    """返回当前同步进度（供 JS 轮询）"""
    s = _sync_state
    if s["start_time"] > 0 and s["status"] in ("uploading", "downloading"):
        elapsed = max(time.time() - s["start_time"], 0.001)
        s["speed"] = s["bytes_done"] / elapsed
        if s["bytes_total"] > 0:
            s["progress"] = min(int(s["bytes_done"] * 100 / s["bytes_total"]), 99)
    return dict(s)


def _get_backend():
    return get_backend(get_config())


def _connect():
    """快捷方式：直接建立 FTP 连接（供 sync_test_ftp 等外部调用）"""
    return connect_ftp(get_config())


def _chunk_list(lst, n):
    return planning._chunk_list(lst, n)


def _remote_root(cfg):
    return planning._remote_root(cfg)


def _safe_remote_fname(name: str) -> bool:
    return planning._safe_remote_fname(name)


def _fetch_remote_memes(bk, remote_root):
    return planning._fetch_remote_memes(bk, remote_root, get_config())


def _apply_remote_collections(remote_data: dict):
    return planning._apply_remote_collections(remote_data, get_db())


def _apply_remote_order(remote_data: dict):
    return planning._apply_remote_order(remote_data, get_db())


def _apply_remote_metadata(remote_data: dict):
    return planning._apply_remote_metadata(remote_data, get_db())


def list_remote_orphans(bk, remote_root) -> list:
    return planning.list_remote_orphans(bk, remote_root, get_config())


# ─── 多线程工作函数 ───


def _push_worker(entries, remote_root, cache_dir, remote_memes):
    """单线程批量上传一批文件"""
    bk = _get_backend()
    bk.connect()
    local_results = {"uploaded": 0, "skipped": 0, "errors": 0, "bytes": 0, "failed": []}
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
                local_results["failed"].append(
                    {"filename": fname, "status": "error", "error": "本地文件缺失"}
                )
                _increment_sync_progress(files_add=1)
                continue
            bk.ensure_remote_dir(os.path.dirname(rem_path))
            if bk.upload_file(local_file, rem_path):
                local_results["uploaded"] += 1
                local_results["bytes"] += fsize
                _increment_sync_progress(files_add=1, bytes_add=fsize)
            else:
                local_results["errors"] += 1
                local_results["failed"].append(
                    {"filename": fname, "status": "error", "error": "上传失败"}
                )
                _increment_sync_progress(files_add=1)
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
            local_results["failed"].append(
                {
                    "filename": "",
                    "status": "error",
                    "error": "%d 个文件因 worker 中断未处理" % remaining,
                }
            )
        return local_results
    finally:
        bk.close()


def _pull_worker(entries, remote_root, cache_dir, db):
    """单线程批量下载一批文件"""
    bk = _get_backend()
    bk.connect()
    local_results = {
        "downloaded": 0,
        "skipped": 0,
        "errors": 0,
        "bytes": 0,
        "failed": [],
        "created_files": [],
        "created_meme_ids": [],
        "overwritten_files": [],
    }
    local_idx = {}
    try:
        from ohmymeme.core.manifest import load as _load_manifest

        ld = _load_manifest()
        local_idx = {m["filename"]: m for m in ld.get("memes", [])}
    except Exception:
        pass
    try:
        for fname, rentry in entries:
            if not _safe_remote_fname(fname):
                local_results["skipped"] += 1
                _increment_sync_progress(files_add=1)
                continue
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
            backup_path = None
            if local_path.exists():
                fd, backup_name = tempfile.mkstemp(
                    prefix=".%s.pull-" % fname,
                    suffix=".bak",
                    dir=str(local_path.parent),
                )
                os.close(fd)
                backup_path = Path(backup_name)
                backup_path.unlink()
                os.replace(local_path, backup_path)
            if bk.download_file(rem_path, local_path):
                if local_path.stat().st_size == 0:
                    # 下载到空文件视为失败：清理并计错误，避免污染本地清单
                    local_results["errors"] += 1
                    local_results["failed"].append(
                        {"filename": fname, "status": "error", "error": "下载内容为空"}
                    )
                    _increment_sync_progress(files_add=1)
                    if local_path.exists():
                        local_path.unlink()
                    if backup_path is not None:
                        os.replace(backup_path, local_path)
                    continue
                expected_hash = rentry.get("sha256", "")
                with open(local_path, "rb") as downloaded:
                    actual_hash = hashlib.file_digest(downloaded, "sha256").hexdigest()
                if len(expected_hash) == 64 and actual_hash != expected_hash:
                    local_results["errors"] += 1
                    local_results["failed"].append(
                        {
                            "filename": fname,
                            "status": "error",
                            "error": "下载哈希不一致",
                        }
                    )
                    _increment_sync_progress(files_add=1)
                    local_path.unlink(missing_ok=True)
                    if backup_path is not None:
                        os.replace(backup_path, local_path)
                    continue
                row = db.get_by_filename(fname)
                if not row:
                    try:
                        oname = rentry.get("name", "") or os.path.splitext(fname)[0]
                        imported = ImageImportService(
                            db,
                            AssetPaths(get_config().data_dir, cache_dir),
                            lambda: None,
                        ).register_existing_path(ImportPath(local_path, oname))
                        if imported.rejected:
                            logger.info(f"pull skip (invalid image): {fname}")
                            local_results["skipped"] += 1
                            _increment_sync_progress(files_add=1)
                            if local_path.exists():
                                local_path.unlink()
                            if backup_path is not None:
                                os.replace(backup_path, local_path)
                            continue
                        local_results["created_meme_ids"].extend(imported.imported_ids)
                        local_results["created_files"].append(local_path)
                    except Exception as e:
                        # DB 写入失败：清理残留 cache，避免“文件在但无记录”的游离态
                        logger.warning("pull db add failed %s: %s", fname, e)
                        local_results["errors"] += 1
                        local_results["failed"].append(
                            {
                                "filename": fname,
                                "status": "error",
                                "error": "数据库写入失败",
                            }
                        )
                        _increment_sync_progress(files_add=1)
                        if local_path.exists():
                            local_path.unlink()
                        if backup_path is not None:
                            os.replace(backup_path, local_path)
                        continue
                if backup_path is not None:
                    local_results["overwritten_files"].append((local_path, backup_path))
                local_results["downloaded"] += 1
                local_results["bytes"] += fsize
                _increment_sync_progress(files_add=1, bytes_add=fsize)
            else:
                if backup_path is not None:
                    os.replace(backup_path, local_path)
                local_results["errors"] += 1
                local_results["failed"].append(
                    {"filename": fname, "status": "error", "error": "下载失败"}
                )
                _increment_sync_progress(files_add=1)
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
            local_results["failed"].append(
                {
                    "filename": "",
                    "status": "error",
                    "error": "%d 个文件因 worker 中断未处理" % remaining,
                }
            )
        return local_results
    finally:
        bk.close()


def _rollback_pull_changes(db, aggregated):
    for meme_id in aggregated["created_meme_ids"]:
        db.delete_meme(meme_id)
    for path in aggregated["created_files"]:
        if path.exists():
            path.unlink()
    for path, backup_path in aggregated["overwritten_files"]:
        if path.exists():
            path.unlink()
        os.replace(backup_path, path)


def _discard_pull_backups(aggregated):
    for _path, backup_path in aggregated["overwritten_files"]:
        if backup_path.exists():
            backup_path.unlink()


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

        aggregated = {
            "uploaded": 0,
            "skipped": 0,
            "errors": 0,
            "bytes": 0,
            "failed": [],
        }
        with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
            futures = [
                executor.submit(_push_worker, ch, remote_root, cache_dir, remote_memes)
                for ch in chunks
            ]
            for future in as_completed(futures):
                r = future.result()
                aggregated["uploaded"] += r["uploaded"]
                aggregated["skipped"] += r["skipped"]
                aggregated["errors"] += r["errors"]
                aggregated["bytes"] += r["bytes"]
                aggregated["failed"].extend(r.get("failed", []))

        if aggregated["errors"] > 0:
            _update_sync_state(failed_items=aggregated["failed"])
            msg = "%d 个文件上传失败，未更新远端 manifest" % aggregated["errors"]
            logger.warning("sync push aborted: %s", msg)
            raise SyncError(msg)

        failed_files = list(aggregated["failed"])
        results = {
            "uploaded": aggregated["uploaded"],
            "skipped": aggregated["skipped"],
            "errors": aggregated["errors"],
            "deleted": 0,
            "failed_files": failed_files,
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
                        unknown = False
                        try:
                            still = bk.file_exists(rem_path)
                        except Exception:
                            still = True
                            unknown = True  # 复核异常 → unknown，保留待下次重查
                        if not still:
                            # 复核确认已删 → 视为删除成功
                            deleted_fnames.add(fname)
                            results["deleted"] += 1
                        else:
                            # 仍在/未知 → 保留在远端 manifest，记录失败供 UI 展示
                            failed_files.append(
                                {
                                    "filename": fname,
                                    "status": "unknown" if unknown else "error",
                                    "error": (
                                        "删除结果不确定，将在下次同步复核"
                                        if unknown
                                        else "远端删除失败（文件仍存在）"
                                    ),
                                }
                            )
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
            failed_items=results["failed_files"],
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
        bk.test_connection()
        bk.close()
        return "ok"
    except Exception as e:
        return str(e)


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

        aggregated = {
            "downloaded": 0,
            "skipped": 0,
            "errors": 0,
            "bytes": 0,
            "failed": [],
            "created_files": [],
            "created_meme_ids": [],
            "overwritten_files": [],
        }
        with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
            futures = [
                executor.submit(_pull_worker, ch, remote_root, cache_dir, db)
                for ch in chunks
            ]
            for future in as_completed(futures):
                r = future.result()
                aggregated["downloaded"] += r["downloaded"]
                aggregated["skipped"] += r["skipped"]
                aggregated["errors"] += r["errors"]
                aggregated["bytes"] += r["bytes"]
                aggregated["failed"].extend(r.get("failed", []))
                aggregated["created_files"].extend(r.get("created_files", []))
                aggregated["created_meme_ids"].extend(r.get("created_meme_ids", []))
                aggregated["overwritten_files"].extend(r.get("overwritten_files", []))

        results = {
            "downloaded": aggregated["downloaded"],
            "skipped": aggregated["skipped"],
            "errors": aggregated["errors"],
            "removed_local": 0,
            "failed_files": aggregated["failed"],
        }

        if aggregated["errors"] > 0:
            _rollback_pull_changes(db, aggregated)
            _update_sync_state(failed_items=aggregated["failed"])
            msg = "%d 个文件下载失败，本地清单仅包含成功项" % aggregated["errors"]
            logger.warning("sync pull aborted: %s", msg)
            raise SyncError(msg)

        manifest_path = cfg.data_dir / INDEX_FILENAME
        manifest_backup = None
        if manifest_path.exists():
            fd, backup_name = tempfile.mkstemp(
                prefix=".manifest.pull-", suffix=".bak", dir=str(cfg.data_dir)
            )
            os.close(fd)
            manifest_backup = Path(backup_name)
            shutil.copyfile(manifest_path, manifest_backup)
        try:
            write_manifest(remote_data)
        except OSError:
            if manifest_backup is not None:
                shutil.copyfile(manifest_backup, manifest_path)
                manifest_backup.unlink()
            _rollback_pull_changes(db, aggregated)
            raise

        try:
            _apply_remote_metadata(remote_data)
        except Exception:
            if manifest_backup is not None:
                shutil.copyfile(manifest_backup, manifest_path)
                manifest_backup.unlink()
            _rollback_pull_changes(db, aggregated)
            raise
        if manifest_backup is not None:
            manifest_backup.unlink()

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

        _discard_pull_backups(aggregated)

        _update_sync_state(
            status="done",
            progress=100,
            files_done=files_total,
            bytes_done=bytes_total,
            results=results,
            failed_items=results["failed_files"],
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
    from ohmymeme.core.config import get_config

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
    """清理中断遗留的临时文件（.remote-* / *.tmp，含 cache 目录），返回清理数量。"""
    cfg = get_config()
    count = 0
    for base in (cfg.data_dir, cfg.cache_dir):
        if not base.exists():
            continue
        for p in base.iterdir():
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
