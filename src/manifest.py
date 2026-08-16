"""远端同步索引清单维护"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List

from .config import get_config
from .database import get_db

logger = logging.getLogger(__name__)

INDEX_FILENAME = "meme-index.json"


def _index_path() -> Path:
    return get_config().data_dir / INDEX_FILENAME


def _build_folder_list(db) -> list:
    """将兼容用 collections 表写成单层文件夹清单"""
    items = []
    for cid, cname, _, _ in db.get_collections():
        member_rows = db.search(collection_id=cid, limit=999999)
        items.append(
            {"name": cname, "filenames": [row["filename"] for row in member_rows]}
        )
    return items


def build() -> List[Dict]:
    """从数据库重建完整索引并写入磁盘"""
    db = get_db()
    rows = db.search(keyword="", tags=None, limit=999999)

    memes = []
    cache_dir = get_config().cache_dir

    for r in rows:
        fname = r["filename"]
        fpath = cache_dir / fname
        mtime = ""
        if fpath.exists():
            try:
                mtime = str(int(fpath.stat().st_mtime))
            except Exception:
                pass
        memes.append(
            {
                "filename": fname,
                "name": r.get("original_name", os.path.splitext(fname)[0]),
                "sha256": r.get("file_hash", ""),
                "file_size": r.get("file_size", 0),
                "mtime": mtime,
                "ai_description": r.get("ai_description", ""),
                "ai_ocr_text": r.get("ai_ocr_text", ""),
            }
        )

    collections = _build_folder_list(db)

    data = {"version": 4, "memes": memes, "collections": collections}
    path = _index_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # 原子替换，避免中断留下半写清单
        logger.debug(
            f"manifest written: {len(memes)} memes, {len(collections)} collections"
        )
    except Exception as e:
        logger.warning(f"manifest write failed: {e}")

    return memes


def load() -> Dict:
    """加载索引文件，不存在时返回空结构"""
    path = _index_path()
    if not path.exists():
        return {"version": 4, "memes": [], "collections": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("collections"), list):
            data["collections"] = []
        data["version"] = 4
        return data
    except Exception as e:
        logger.warning(f"manifest load failed: {e}")
        return {"version": 4, "memes": [], "collections": []}
