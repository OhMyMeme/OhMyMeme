"""本地备份：ZIP 导出与恢复（仅 PC 间迁移，整库替换语义，仅允许恢复到空库）

包结构（ZIP_STORED 不压缩，图片本身已是压缩格式）：
- db/memes.db        sqlite backup API 导出的一致性快照
- meme-index.json    打包时的远端同步清单（供人工核对，恢复以 memes.db 为准）
- files/<文件名>     cache_dir 全部原图（文件名即 hash 前缀，跨机稳定）
- backup.json        包内清单（app 版本/导出时间/文件数，恢复时校验完整性）
"""

import json
import os
import shutil
import sqlite3
import time
import zipfile
from pathlib import Path

BACKUP_PREFIX = "OhMyMeme-backup-"
BACKUP_SUFFIX = ".zip"
INFO_NAME = "backup.json"


def _app_version() -> str:
    from . import __version__

    return __version__


def get_backup_dir(cfg):
    """备份目录：config backup_dir 非空用之，否则默认 data_dir/backups"""
    custom = cfg.get("backup_dir", "") or ""
    if custom:
        return Path(custom)
    return Path(cfg.data_dir) / "backups"


def _iter_image_files(cache_dir: Path):
    """遍历 cache_dir 全部图片文件，跳过缩略图子目录"""
    for root, dirs, files in os.walk(cache_dir):
        dirs[:] = [d for d in dirs if d != "thumbnails"]
        for name in files:
            yield Path(root) / name


def create_backup(backup_dir, data_dir, cache_dir, db, progress_cb=None) -> dict:
    """创建全量备份 ZIP，返回 {ok, path, file_count, size}"""
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    final = backup_dir / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"
    tmp = backup_dir / (final.name + ".tmp")
    cache_dir = Path(cache_dir)
    files = sorted(_iter_image_files(cache_dir)) if cache_dir.exists() else []
    manifest_path = Path(data_dir) / "meme-index.json"
    total = len(files) + 3  # db + manifest + backup.json
    done = 0

    def tick():
        nonlocal done
        done += 1
        if progress_cb:
            progress_cb(done, total)

    db_tmp = backup_dir / f".backup-db-{stamp}.tmp"
    try:
        db.backup_to(str(db_tmp))
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
            zf.write(db_tmp, "db/memes.db")
            tick()
            if manifest_path.exists():
                zf.write(manifest_path, "meme-index.json")
            tick()
            info = {
                "app_version": _app_version(),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "file_count": len(files),
            }
            zf.writestr(INFO_NAME, json.dumps(info, ensure_ascii=False, indent=2))
            tick()
            for f in files:
                zf.write(f, f"files/{f.name}")
                tick()
        os.replace(tmp, final)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    finally:
        try:
            db_tmp.unlink()
        except OSError:
            pass
    return {
        "ok": True,
        "path": final.name,
        "file_count": len(files),
        "size": final.stat().st_size,
    }


def list_backups(backup_dir) -> list:
    """列出备份 ZIP（按时间倒序），返回 [{name, size, mtime}]"""
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    out = []
    for p in backup_dir.iterdir():
        if (
            p.is_file()
            and p.name.startswith(BACKUP_PREFIX)
            and p.name.endswith(BACKUP_SUFFIX)
        ):
            st = p.stat()
            out.append({"name": p.name, "size": st.st_size, "mtime": int(st.st_mtime)})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def delete_backup(backup_dir, name: str) -> bool:
    """删除指定备份 ZIP；文件名白名单校验防路径穿越"""
    if (
        not name
        or "/" in name
        or "\\" in name
        or ".." in name
        or not name.startswith(BACKUP_PREFIX)
        or not name.endswith(BACKUP_SUFFIX)
    ):
        return False
    p = Path(backup_dir) / name
    if p.is_file():
        p.unlink()
        return True
    return False


def _validate_member(name: str) -> bool:
    """包内图片成员名必须是 files/ 下的安全文件名"""
    if not name.startswith("files/") or name.endswith("/"):
        return False
    base = name[len("files/") :]
    if not base or "/" in base or "\\" in base or base in (".", ".."):
        return False
    return True


def restore_backup(zip_path, data_dir, cache_dir, db, progress_cb=None) -> dict:
    """从备份 ZIP 恢复到空库（空库校验由调用方负责，落库前会复查）。

    解包到 data_dir/backup_restore_tmp staging，校验通过后图片移动进
    cache_dir（同名覆盖——文件名即 hash 前缀，同名必同内容）、数据库经
    backup API 原子替换并自动补齐旧版本缺失列。
    """
    data_dir = Path(data_dir)
    cache_dir = Path(cache_dir)
    staging = data_dir / "backup_restore_tmp"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            if INFO_NAME not in names or "db/memes.db" not in names:
                return {"ok": False, "error": "不是有效的 OhMyMeme 备份包"}
            info = json.loads(zf.read(INFO_NAME).decode("utf-8"))
            file_count = info.get("file_count", -1)
            members = [n for n in names if _validate_member(n)]
            if not isinstance(file_count, int) or len(members) != file_count:
                return {
                    "ok": False,
                    "error": (
                        f"备份包不完整：期望 {file_count} 个图片文件，"
                        f"实际 {len(members)} 个"
                    ),
                }
            total = len(members) * 2 + 2  # 解包 N + 库解包 1 + 移动 N + 落库 1
            done = 0

            def tick():
                nonlocal done
                done += 1
                if progress_cb:
                    progress_cb(done, total)

            files_dir = staging / "files"
            files_dir.mkdir()
            for n in members:
                target = files_dir / n[len("files/") :]
                with zf.open(n) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                tick()
            db_target = staging / "restored.db"
            with zf.open("db/memes.db") as src, open(db_target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            tick()
            # 落库前复查空库：恢复期间用户导入会使库非空，此时中止
            if db.count() != 0:
                return {"ok": False, "error": "恢复期间检测到新数据写入，已中止"}
            cache_dir.mkdir(parents=True, exist_ok=True)
            for f in sorted(files_dir.iterdir()):
                shutil.move(str(f), str(cache_dir / f.name))
                tick()
            try:
                db.restore_from(str(db_target))
            except sqlite3.DatabaseError:
                return {"ok": False, "error": "备份包中的数据库文件无效"}
            tick()
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"ok": True, "file_count": len(members)}
