"""宿主本地备份与恢复；不依赖桌面、插件或远端同步。"""

import json
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

from ohmymeme import __version__
from ohmymeme.app.operations import (
    OperationBusyError,
    OperationClosedError,
    ResourceKind,
)
from ohmymeme.core.domain import TaskKind
from ohmymeme.core.imports import _IMPORT_LOCK

BACKUP_PREFIX = "OhMyMeme-backup-"


def validate_backup_dir(path, cache_dir):
    # 避免备份与图片目录互相包含。
    target, cache = Path(path).resolve(), Path(cache_dir).resolve()
    if target == cache or target in cache.parents or cache in target.parents:
        raise ValueError("备份目录不能与图片目录相同或互为嵌套")
    return target


def create_backup(directory, data_dir, cache_dir, database, tick):
    # 使用 SQLite backup 一致快照和未压缩 ZIP，完成后原子发布。
    directory = validate_backup_dir(directory, cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    name = (
        BACKUP_PREFIX
        + time.strftime("%Y%m%d-%H%M%S")
        + "-"
        + uuid.uuid4().hex[:8]
        + ".zip"
    )
    final = directory / name
    files = [
        path
        for path in Path(cache_dir).rglob("*")
        if path.is_file()
        and "thumbnails" not in path.relative_to(cache_dir).parts
        and not path.name.startswith(".")
    ]
    if len({path.name for path in files}) != len(files):
        raise ValueError("缓存存在同名文件，无法生成完整备份")
    with tempfile.TemporaryDirectory(prefix=".backup-", dir=directory) as workspace:
        database_path = Path(workspace) / "memes.db"
        archive_path = Path(workspace) / "backup.zip"
        database.backup_to(str(database_path))
        total = len(files) + 3
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED) as archive:
            archive.write(database_path, "db/memes.db")
            tick(1, total)
            manifest = Path(data_dir) / "meme-index.json"
            if manifest.is_file():
                archive.write(manifest, "meme-index.json")
            tick(2, total)
            archive.writestr(
                "backup.json",
                json.dumps(
                    {
                        "app_version": __version__,
                        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "file_count": len(files),
                    }
                ),
            )
            tick(3, total)
            for index, path in enumerate(sorted(files), 4):
                archive.write(path, "files/" + path.name)
                tick(index, total)
        os.replace(archive_path, final)
    return {
        "ok": True,
        "path": name,
        "file_count": len(files),
        "size": final.stat().st_size,
    }


def restore_backup(path, data_dir, cache_dir, database, tick):
    # 候选库先校验，文件冲突不覆盖，失败只清理本次新副本。
    if database.has_any_data():
        raise ValueError("只能恢复到空库")
    added = []
    with tempfile.TemporaryDirectory(
        prefix="backup-restore-", dir=data_dir
    ) as workspace:
        staging = Path(workspace)
        files_dir = staging / "files"
        files_dir.mkdir()
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = archive.namelist()
            if len(names) > 100000 or len(set(names)) != len(names):
                raise ValueError("备份成员重复或数量超限")
            if (
                any(
                    entry.file_size > 64 * 1024 * 1024
                    or entry.compress_type
                    not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    for entry in entries
                )
                or sum(entry.file_size for entry in entries) > 20 * 1024**3
            ):
                raise ValueError("备份包大小或压缩格式不受支持")
            info = json.loads(archive.read("backup.json"))
            files = [
                name for name in names if name.startswith("files/") and name != "files/"
            ]
            if (
                type(info.get("file_count")) is not int
                or len(files) != info["file_count"]
            ):
                raise ValueError("备份文件数量不符")
            if any(
                Path(name[6:]).name != name[6:]
                or "\\" in name[6:]
                or name[6:] in (".", "..")
                for name in files
            ):
                raise ValueError("备份文件名无效")
            candidate = staging / "memes.db"
            with archive.open("db/memes.db") as source, candidate.open("wb") as target:
                shutil.copyfileobj(source, target)
            database.prepare_restore_source(str(candidate))
            total = max(1, len(files) * 2 + 2)
            tick(1, total)
            for index, name in enumerate(files, 2):
                with archive.open(name) as source, (files_dir / Path(name).name).open(
                    "wb"
                ) as target:
                    shutil.copyfileobj(source, target)
                tick(index, total)
        try:
            for index, name in enumerate(files, len(files) + 2):
                source, destination = (
                    files_dir / Path(name).name,
                    Path(cache_dir) / Path(name).name,
                )
                if destination.exists():
                    if destination.read_bytes() != source.read_bytes():
                        raise ValueError("恢复目标存在不同内容的同名文件")
                else:
                    shutil.copyfile(source, destination)
                    added.append(destination)
                tick(index, total)
            database.restore_from(str(candidate))
        except Exception:
            for destination in added:
                destination.unlink(missing_ok=True)
            raise
    return {"ok": True, "file_count": len(files)}


class BackupService:
    def __init__(self, config, database, build_manifest, mutations, operations):
        # 宿主持有持久路径和任务资源，UI 只读取结果与进度。
        self._config = config
        self._database = database
        self._build_manifest = build_manifest
        self._mutations = mutations
        self._operations = operations
        self._lock = threading.Lock()
        self._state = {"status": "idle", "progress": 0}

    @property
    def directory(self):
        # 备份位置与图片位置分离。
        return Path(self._config.get("backup_dir") or self._config.data_dir / "backups")

    def get_info(self):
        # 文件列表不触发备份或启动后台任务。
        files = []
        if self.directory.exists():
            for path in self.directory.glob(BACKUP_PREFIX + "*.zip"):
                stat = path.stat()
                files.append(
                    {"name": path.name, "size": stat.st_size, "mtime": stat.st_mtime}
                )
        return {
            "ok": True,
            "directory": str(self.directory),
            "custom": bool(self._config.get("backup_dir")),
            "backups": sorted(files, key=lambda row: row["mtime"], reverse=True),
        }

    def set_directory(self, path):
        # 选择目录立即生效，但写入失败不能改变内存配置。
        directory = validate_backup_dir(path, self._config.cache_dir)
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass
        previous = self._config.get("backup_dir", "")
        self._config.set("backup_dir", str(directory))
        try:
            self._config.save()
        except OSError:
            self._config.set("backup_dir", previous)
            raise
        return self.get_info()

    def delete(self, name):
        # 仅删除当前备份目录中列出的 ZIP。
        if (
            Path(name).name != name
            or "\\" in name
            or not name.startswith(BACKUP_PREFIX)
            or not name.endswith(".zip")
        ):
            return {"ok": False, "error": "备份文件名无效"}
        (self.directory / name).unlink()
        return {"ok": True}

    def get_progress(self):
        # 进度快照不能修改后台状态。
        with self._lock:
            return dict(self._state)

    def start(self, path=None):
        # 创建与恢复都参与操作协调器和持久状态互斥。
        if path and self._database.has_any_data():
            return {"ok": False, "error": "只能恢复到空库"}
        kind = TaskKind.BACKUP_RESTORE if path else TaskKind.BACKUP_CREATE
        with self._lock:
            if self._state["status"] == "running":
                return {"ok": False, "error": "备份或恢复正在进行中"}
            self._state = {"status": "running", "progress": 0}

        def run(context):
            def tick(done, total):
                # 每次文件边界传播退出取消，不留下半个发布包。
                if context.cancel_requested:
                    raise InterruptedError("操作已取消")
                with self._lock:
                    self._state.update(
                        progress=round(done * 100 / total), done=done, total=total
                    )
                context.update_progress(min(1, done / total))

            try:
                with context.lease(ResourceKind.DATABASE), context.lease(
                    ResourceKind.CONFIG
                ), self._mutations.mutation(kind.value) as lease, _IMPORT_LOCK:
                    if path:
                        result = restore_backup(
                            path,
                            self._config.data_dir,
                            self._config.cache_dir,
                            self._database,
                            tick,
                        )
                        self._build_manifest()
                        lease.commit()
                    else:
                        self._build_manifest()
                        result = create_backup(
                            self.directory,
                            self._config.data_dir,
                            self._config.cache_dir,
                            self._database,
                            tick,
                        )
                    with self._lock:
                        self._state.update(status="done", progress=100, result=result)
            except Exception as error:
                with self._lock:
                    self._state.update(
                        status=(
                            "cancelled"
                            if isinstance(error, InterruptedError)
                            else "error"
                        ),
                        error=str(error),
                    )
            finally:
                self._database.close()

        try:
            previous = self._operations.query(kind)
            snapshot = self._operations.start(kind, run)
            if previous and snapshot.task_id == previous.task_id:
                raise OperationBusyError("library")
        except (OperationBusyError, OperationClosedError) as error:
            with self._lock:
                self._state.update(status="idle", error=str(error))
            return {"ok": False, "error": "其他导入或备份正在进行中"}
        return {"ok": True, "started": True}
