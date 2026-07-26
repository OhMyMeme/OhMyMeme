"""远端同步索引清单维护"""

import json
import logging
from pathlib import Path
from typing import Dict, List

from .config import get_config
from .database import get_db

logger = logging.getLogger(__name__)

INDEX_FILENAME = "meme-index.json"


def _index_path() -> Path:
    return get_config().data_dir / INDEX_FILENAME


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
                "sha256": r.get("file_hash", ""),
                "file_size": r.get("file_size", 0),
                "mtime": mtime,
            }
        )

    # 收集分组信息（跳过并清理空分组）
    raw_colls = db.get_collections()
    collections = []
    for cid, cname in raw_colls:
        member_rows = db.search(collection_id=cid, limit=999999)
        filenames = [mr["filename"] for mr in member_rows]
        if not filenames:
            db.delete_collection(cid)
            continue
        collections.append({"name": cname, "filenames": filenames})

    data = {"version": 2, "memes": memes, "collections": collections}
    path = _index_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug(f"manifest written: {len(memes)} memes, {len(collections)} collections")
    except Exception as e:
        logger.warning(f"manifest write failed: {e}")

    return memes


def load() -> Dict:
    """加载索引文件，不存在时返回空结构"""
    path = _index_path()
    if not path.exists():
        return {"version": 2, "memes": [], "collections": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"manifest load failed: {e}")
        return {"version": 2, "memes": [], "collections": []}
