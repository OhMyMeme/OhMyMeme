"""云端同步 - FTP / S3 (兼容 R2/MinIO) 实现"""

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from ohmymeme.app.local_library import LocalLibraryService
from ohmymeme.core.assets import AssetPaths
from ohmymeme.core.config import get_config, provider_supports
from ohmymeme.core.database import get_db
from ohmymeme.core.imports import ImageImportService, ImportPath
from ohmymeme.core.manifest import INDEX_FILENAME, ManifestBuilder
from ohmymeme.core.manifest import build as build_manifest  # noqa: F401
from ohmymeme.core.manifest import load as load_manifest

from . import planning
from .backends import SyncError, connect_ftp, get_backend

logger = logging.getLogger(__name__)

REMOTE_INDEX = planning.REMOTE_INDEX
REMOTE_MEME_DIR = planning.REMOTE_MEME_DIR


class SyncService:
    """同步用例的显式依赖适配器。"""

    def __init__(self, config, db, assets, manifest, library=None, job_manager=None):
        self.config = config
        self.db = db
        self.assets = assets
        self.manifest = manifest
        self.library = library
        self.job_manager = job_manager
        self._job_results = {}

    def apply_remote_order(self, remote_data):
        if self.library is None:
            return False
        return self.library.apply_remote_manifest_operation(
            remote_data, lambda data: planning._apply_remote_order(data, self.db)
        )

    def apply_remote_collections(self, remote_data):
        if self.library is None:
            return False
        return self.library.apply_remote_manifest_operation(
            remote_data, lambda data: planning._apply_remote_collections(data, self.db)
        )

    def apply_remote_metadata(self, remote_data):
        if self.library is not None:
            return self.library.apply_remote_metadata(remote_data)
        return planning._apply_remote_metadata(remote_data, self.db)

    def register_existing_path(self, request):
        if self.library is not None:
            return self.library.register_existing_path(request, project=False)
        from ohmymeme.core.imports import ImageImportService

        importer = ImageImportService(self.db, self.assets, lambda: None)
        return importer.register_existing_path(request)

    def project_manifest(self):
        if self.library is None:
            return False
        return self.library.project_manifest()

    def push(self, delete_remote=None):
        if self.job_manager is None:
            return push(delete_remote, self.library)
        return self._run_job(
            "sync",
            lambda context: push(
                delete_remote, self.library, cancellation=context.cancellation_event
            ),
        )

    def pull(self, remove_local=None):
        if self.job_manager is None:
            return pull(remove_local, self.library)
        return self._run_job(
            "sync",
            lambda context: pull(
                remove_local, self.library, cancellation=context.cancellation_event
            ),
        )

    def test_connection(self):
        """测试当前配置的同步后端连接。"""
        return sync_test()

    def delete_all_remote(self):
        """删除远端全部表情与索引。"""
        return delete_all_remote()

    def cleanup_remote_orphans(self, delete=False):
        """扫描或删除远端孤儿文件。"""
        return cleanup_remote_orphans(delete)

    def auto_sync(self):
        """按当前 Container 配置执行自动索引获取和同步。"""
        result = {"fetched": False, "synced": False, "error": ""}
        if not self.config.get("sync_type", ""):
            return result
        try:
            if self.config.get("sync_auto_fetch_index", False):
                result["fetched"] = download_index() is not None
            if self.config.get("sync_auto_sync", False):
                result["synced"] = self.pull().get("downloaded", 0) > 0
        except Exception as error:
            result["error"] = str(error)
        return result

    def get_status(self):
        """比较远端索引与当前 Container 本地目录。"""
        manifest = download_index()
        if not manifest:
            return {"ok": False, "error": "无法获取远端索引"}
        local_rows = self.db.search(keyword="", tags=None, limit=999999)
        local_filenames = {row["filename"] for row in local_rows}
        remote_filenames = {meme["filename"] for meme in manifest.get("memes", [])}
        local_count = len(local_rows)
        remote_count = len(remote_filenames)
        local_extra = local_filenames - remote_filenames
        local_missing = remote_filenames - local_filenames
        result = {
            "ok": True,
            "synced": not local_extra and not local_missing,
            "local_count": local_count,
            "remote_count": remote_count,
        }
        if local_extra or local_missing:
            result.update(
                local_extra=len(local_extra), local_missing=len(local_missing)
            )
        return result

    def _run_job(self, task_type, target):
        if self.job_manager.active(task_type) is not None:
            raise SyncError("同步正在进行中")
        result = {}
        error = {}

        def run(context):
            try:
                result.update(target(context))
            except Exception as exc:
                error["value"] = exc
                raise

        record = self.job_manager.start(task_type, run)
        self.job_manager.wait(record.id)
        if "value" in error:
            raise error["value"]
        return result


_sync_lock = threading.Lock()
_sync_run_lock = threading.Lock()  # 防止 push/pull 并发执行
_pull_library = None

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


def _default_library():
    config = get_config()
    db = get_db()
    assets = AssetPaths(config.data_dir, config.cache_dir)
    manifest = ManifestBuilder(config, db, assets)
    importer = ImageImportService(db, assets, manifest.build)
    library = LocalLibraryService(db, assets, importer, manifest.build)
    library._legacy_metadata = _apply_remote_metadata
    return library


def _apply_remote_collections(remote_data: dict):
    return planning._apply_remote_collections(remote_data, get_db())


def _apply_remote_order(remote_data: dict):
    return planning._apply_remote_order(remote_data, get_db())


def _apply_remote_metadata(remote_data: dict):
    return planning._apply_remote_metadata(remote_data, get_db())


def list_remote_orphans(bk, remote_root) -> list:
    return planning.list_remote_orphans(bk, remote_root, get_config())


# ─── 多线程工作函数 ───


def _push_worker(entries, remote_root, cache_dir, remote_memes, cancellation=None):
    """单线程批量上传一批文件"""
    bk = _get_backend()
    bk.connect()
    local_results = {"uploaded": 0, "skipped": 0, "errors": 0, "bytes": 0, "failed": []}
    try:
        for entry in entries:
            if cancellation is not None and cancellation.is_set():
                break
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
    return _pull_worker_core(entries, remote_root, cache_dir, db)


def _pull_worker_core(entries, remote_root, cache_dir, db, cancellation=None):
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
            if cancellation is not None and cancellation.is_set():
                break
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
                        if _pull_library is not None:
                            imported = _pull_library.register_existing_path(
                                ImportPath(local_path, oname), project=False
                            )
                        else:
                            from ohmymeme.core.imports import ImageImportService

                            importer = ImageImportService(
                                db,
                                AssetPaths(get_config().data_dir, cache_dir),
                                lambda: None,
                            )
                            imported = importer.register_existing_path(
                                ImportPath(local_path, oname)
                            )
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
    library = _pull_library
    success = True
    for meme_id in aggregated["created_meme_ids"]:
        if not library.rollback_delete(meme_id):
            success = False
    for path, backup_path in aggregated["overwritten_files"]:
        if path.exists():
            path.unlink()
        os.replace(backup_path, path)
    for snapshot in aggregated.get("removed_local", []):
        row = snapshot["row"]
        if row is None:
            continue
        if db.get_by_filename(row["filename"]):
            continue
        db.add_meme(
            row["filename"],
            file_hash=row.get("file_hash", ""),
            width=row.get("width", 0),
            height=row.get("height", 0),
            file_size=row.get("file_size", 0),
            mime_type=row.get("mime_type", "image/png"),
            original_name=row.get("original_name", ""),
        )
        snapshot["path"].parent.mkdir(parents=True, exist_ok=True)
        snapshot["path"].write_bytes(snapshot["data"])
    return success


def _discard_pull_backups(aggregated):
    for _path, backup_path in aggregated["overwritten_files"]:
        if backup_path.exists():
            backup_path.unlink()


# ─── 公开 API ───


def upload_index(bk=None) -> bool:
    """上传本地 manifest 到远端"""
    cfg = get_config()
    if not provider_supports(cfg.get("sync_type", ""), "delete"):
        return {"ok": False, "error": "当前同步后端不支持删除远端文件"}
    remote_root = _remote_root(cfg)
    library = _default_library()
    if not library.project_manifest():
        return False
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


def push(delete_remote: bool = None, library=None, cancellation=None) -> dict:
    """本地 -> 远端：上传缺失/变更的表情包和清单（多线程）"""
    cfg = get_config()
    if delete_remote is None:
        delete_remote = cfg.get("sync_delete_remote", False)
    remote_root = _remote_root(cfg)
    cache_dir = cfg.cache_dir
    max_workers = max(1, min(8, int(cfg.get("sync_threads", 3))))
    local = load_manifest()
    if not local.get("memes"):
        projected = (
            library.project_manifest()
            if library
            else _default_library().project_manifest()
        )
        if not projected:
            raise SyncError("本地 manifest 生成失败")
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
        if cancellation is not None and cancellation.is_set():
            return {
                "uploaded": 0,
                "skipped": 0,
                "errors": 0,
                "deleted": 0,
                "failed_files": [],
            }
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
                executor.submit(
                    _push_worker,
                    ch,
                    remote_root,
                    cache_dir,
                    remote_memes,
                    cancellation,
                )
                for ch in chunks
            ]
            for future in as_completed(futures):
                if cancellation is not None and cancellation.is_set():
                    for pending in futures:
                        pending.cancel()
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
        if cancellation is not None and cancellation.is_set():
            raise SyncError("同步已取消")

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
                if cancellation is not None and cancellation.is_set():
                    raise SyncError("同步已取消")
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
        projected = (
            library.project_manifest()
            if library
            else _default_library().project_manifest()
        )
        if not projected:
            raise SyncError("本地 manifest 生成失败")
        if cancellation is not None and cancellation.is_set():
            raise SyncError("同步已取消")
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


def pull(remove_local: bool = None, library=None, cancellation=None) -> dict:
    """远端 -> 本地：下载缺失/变更的表情包和清单（多线程）"""
    global _pull_library
    _pull_library = library or _default_library()
    cfg = get_config()
    if remove_local is None:
        remove_local = cfg.get("sync_remove_local", False)
    remote_root = _remote_root(cfg)
    cache_dir = cfg.cache_dir
    max_workers = max(1, min(8, int(cfg.get("sync_threads", 3))))
    db = get_db()

    if not _sync_run_lock.acquire(blocking=False):
        raise SyncError("同步正在进行中")

    try:
        if cancellation is not None and cancellation.is_set():
            raise SyncError("同步已取消")
        remote_data = download_index()
        if not remote_data:
            raise SyncError("no remote manifest available")

        remote_idx = {m["filename"]: m for m in remote_data.get("memes", [])}
        local_data = load_manifest()
        manifest_snapshot = (
            _pull_library._assets.manifest_path.read_bytes()
            if _pull_library._assets.manifest_path.exists()
            else None
        )
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
            "removed_local": [],
        }
        metadata_applied = False
        with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
            futures = [
                executor.submit(
                    _pull_worker_core, ch, remote_root, cache_dir, db, cancellation
                )
                for ch in chunks
            ]
            for future in as_completed(futures):
                if cancellation is not None and cancellation.is_set():
                    for pending in futures:
                        pending.cancel()
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
            rolled_back = _rollback_pull_changes(db, aggregated)
            _pull_library.restore_manifest(manifest_snapshot)
            if not rolled_back:
                raise SyncError("本地回滚失败")
            _update_sync_state(failed_items=aggregated["failed"])
            msg = "%d 个文件下载失败，本地清单仅包含成功项" % aggregated["errors"]
            logger.warning("sync pull aborted: %s", msg)
            raise SyncError(msg)
        if cancellation is not None and cancellation.is_set():
            rolled_back = _rollback_pull_changes(db, aggregated)
            _pull_library.restore_manifest(manifest_snapshot)
            _discard_pull_backups(aggregated)
            raise SyncError("同步已取消")

        try:
            if remove_local:
                for fname in list(local_idx.keys()):
                    if fname not in remote_idx:
                        row = db.get_by_filename(fname)
                        if row:
                            local_path = cache_dir / fname
                            snapshot = {
                                "row": dict(row),
                                "path": local_path,
                                "data": (
                                    local_path.read_bytes()
                                    if local_path.exists()
                                    else b""
                                ),
                            }
                            if _pull_library.delete_meme(row.get("id", 1)):
                                aggregated["removed_local"].append(snapshot)
                                results["removed_local"] += 1
                        else:
                            local_path = cache_dir / fname
                            if local_path.exists():
                                aggregated["removed_local"].append(
                                    {
                                        "row": None,
                                        "path": local_path,
                                        "data": local_path.read_bytes(),
                                    }
                                )
                                local_path.unlink()
                                results["removed_local"] += 1
                    if cancellation is not None and cancellation.is_set():
                        raise SyncError("同步已取消")

            if hasattr(_pull_library, "_legacy_metadata"):
                applied = _pull_library.apply_remote_metadata_with(
                    remote_data, _pull_library._legacy_metadata
                )
            else:
                applied = _pull_library.apply_remote_metadata(remote_data)
            if not applied:
                raise SyncError("本地远端元数据应用失败")
            metadata_applied = True
            if cancellation is not None and cancellation.is_set():
                raise SyncError("同步已取消")
            if not _pull_library.replace_manifest(remote_data):
                raise SyncError("本地 manifest 写入失败")
            if cancellation is not None and cancellation.is_set():
                raise SyncError("同步已取消")
        except Exception:
            if metadata_applied:
                _pull_library.apply_remote_metadata(local_data)
            rolled_back = _rollback_pull_changes(db, aggregated)
            _pull_library.restore_manifest(manifest_snapshot)
            if not rolled_back:
                raise SyncError("本地回滚失败")
            raise

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
        _pull_library = None
        _sync_run_lock.release()


def delete_all_remote() -> dict:
    """删除远端所有表情包和清单"""
    from ohmymeme.core.config import get_config

    cfg = get_config()
    if not provider_supports(cfg.get("sync_type", ""), "delete"):
        return {"ok": False, "error": "当前同步后端不支持删除远端文件"}
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
    if delete and not provider_supports(cfg.get("sync_type", ""), "delete"):
        return {"ok": False, "error": "当前同步后端不支持删除远端文件"}
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
