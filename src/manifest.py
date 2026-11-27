"""远端同步索引清单维护"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List

from .config import get_config
from .database import _name_sort_key, get_db

logger = logging.getLogger(__name__)

INDEX_FILENAME = "meme-index.json"


def _index_path() -> Path:
    return get_config().data_dir / INDEX_FILENAME


def _build_collection_tree(db, parent_id=None) -> list:
    raw = db.get_collections()
    items = []
    for cid, cname, pid, _ in raw:
        if pid != parent_id:
            continue
        member_rows = db.search(collection_id=cid, limit=999999)
        filenames = [mr["filename"] for mr in member_rows]
        children = _build_collection_tree(db, parent_id=cid)
        if not filenames and not children:
            db.delete_collection(cid)
            continue
        item = {"name": cname, "filenames": filenames}
        if children:
            item["children"] = children
        items.append(item)
    return items


def _write(data: Dict) -> None:
    """原子写入清单（先写临时文件再替换）"""
    path = _index_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # 原子替换，避免中断留下半写清单
    except Exception as e:
        logger.warning(f"manifest write failed: {e}")


def _cache_mtimes(cache_dir):
    """缓存目录内「文件名 → mtime」映射（单次 scandir，避免逐文件 stat）"""
    out = {}
    try:
        with os.scandir(str(cache_dir)) as it:
            for entry in it:
                try:
                    if not entry.is_file():
                        continue
                    out[entry.name] = str(int(entry.stat().st_mtime))
                except OSError:
                    continue
    except OSError:
        pass
    return out


def build() -> List[Dict]:
    """从数据库重建完整索引并写入磁盘"""
    db = get_db()
    rows = db.search(keyword="", tags=None, limit=999999)
    # 默认展示序：未拖拽排序过（sort_order 全 0）时，
    # 按自然名称序（数字按数值、中文按拼音），与 A-Z 排序同一套键；
    # 用户拖拽排序后尊重自定义顺序
    if rows and not any(r.get("sort_order") for r in rows):
        rows = sorted(
            rows,
            key=lambda r: _name_sort_key(
                r.get("original_name") or os.path.splitext(r["filename"])[0]
            ),
        )
    include_tags = bool(get_config().get("manifest_include_tags", True))
    tags_map = db.get_tags_map() if include_tags else {}

    memes = []
    mtimes = _cache_mtimes(get_config().cache_dir)

    for r in rows:
        fname = r["filename"]
        entry = {
            "filename": fname,
            "name": r.get("original_name", os.path.splitext(fname)[0]),
            "sha256": r.get("file_hash", ""),
            "file_size": r.get("file_size", 0),
            "mtime": mtimes.get(fname, ""),
        }
        if include_tags:
            entry["tags"] = tags_map.get(fname, [])
        memes.append(entry)

    collections = []
    include_collections = bool(get_config().get("manifest_include_collections", True))
    if include_collections:
        collections = _build_collection_tree(db)

    include_favorites = bool(get_config().get("manifest_include_favorites", True))
    favorite = []
    if include_favorites:
        favorite = [
            r["filename"]
            for r in db.search(keyword="", favorite_only=True, limit=999999)
        ]

    data = {"version": 3, "memes": memes}
    if include_collections:
        data["collections"] = collections
    if include_favorites:
        data["favorite"] = favorite
    _write(data)
    logger.debug(
        f"manifest written: {len(memes)} memes, {len(collections)} collections, "
        f"{len(favorite)} favorites"
    )

    return memes


def index_path() -> Path:
    return get_config().data_dir / INDEX_FILENAME


def index_order() -> List[str]:
    """本地清单 memes 的文件名顺序（不可用时空列表）"""
    order = []
    for m in load().get("memes") or []:
        if isinstance(m, dict) and isinstance(m.get("filename"), str):
            order.append(m["filename"])
    return order


def load() -> Dict:
    """加载索引文件，不存在时返回空结构"""
    path = _index_path()
    if not path.exists():
        return {"version": 3, "memes": [], "collections": [], "favorite": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version", 2) < 3:
            # 旧版 v2 扁平分组 → 新版 v3 嵌套：原地转换
            if isinstance(data.get("collections"), list):
                new_colls = []
                for c in data["collections"]:
                    if isinstance(c, dict) and "name" in c:
                        new_colls.append(
                            {
                                "name": c["name"],
                                "filenames": c.get("filenames", []),
                            }
                        )
                data["collections"] = new_colls
            data["version"] = 3
        return data
    except Exception as e:
        logger.warning(f"manifest load failed: {e}")
        return {"version": 3, "memes": [], "collections": [], "favorite": []}
