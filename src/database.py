"""SQLite元数据管理 - 零依赖"""

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from .config import get_config


class MemeDB:
    """SQLite元数据存储，线程安全"""

    def __init__(self, db_path: Path = None):
        if db_path is None:
            db_path = get_config().db_path
        self._db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self._db_path), timeout=5.0, check_same_thread=False
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_db(self):
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filename    TEXT    NOT NULL,
                file_hash   TEXT    NOT NULL DEFAULT '',
                original_name TEXT  NOT NULL DEFAULT '',
                width       INTEGER DEFAULT 0,
                height      INTEGER DEFAULT 0,
                file_size   INTEGER DEFAULT 0,
                mime_type   TEXT    DEFAULT 'image/png',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS tags (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT    NOT NULL UNIQUE COLLATE NOCASE
            );

            CREATE TABLE IF NOT EXISTS meme_tags (
                meme_id INTEGER NOT NULL REFERENCES memes(id) ON DELETE CASCADE,
                tag_id  INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                PRIMARY KEY (meme_id, tag_id)
            );

            CREATE TABLE IF NOT EXISTS collections (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT    NOT NULL UNIQUE COLLATE NOCASE
            );

            CREATE TABLE IF NOT EXISTS meme_collections (
                meme_id       INTEGER NOT NULL REFERENCES memes(id) ON DELETE CASCADE,
                collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                PRIMARY KEY (meme_id, collection_id)
            );

            CREATE TABLE IF NOT EXISTS favorites (
                meme_id   INTEGER PRIMARY KEY REFERENCES memes(id) ON DELETE CASCADE,
                added_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_memes_hash ON memes(file_hash);
            CREATE INDEX IF NOT EXISTS idx_memes_name ON memes(filename);
        """
        )
        conn.commit()

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    # --- 增删改 ---

    def add_meme(
        self,
        filename: str,
        file_hash: str = "",
        width: int = 0,
        height: int = 0,
        file_size: int = 0,
        mime_type: str = "image/png",
        tags: List[str] = None,
    ) -> int:
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute(
                """INSERT INTO memes (filename, file_hash, width, height, file_size, mime_type)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (filename, file_hash, width, height, file_size, mime_type),
            )
            meme_id = cur.lastrowid
            conn.commit()  # 先提交meme插入，确保FOREIGN KEY约束通过
            if tags:
                self._set_tags(conn, meme_id, tags)
                conn.commit()
            return meme_id

    def delete_meme(self, meme_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM memes WHERE id=?", (meme_id,))
            conn.commit()

    def update_meme(self, meme_id: int, **kwargs):
        allowed = {"filename", "file_hash", "width", "height", "file_size", "mime_type"}
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k in allowed:
                sets.append(f"{k}=?")
                vals.append(v)
        if not sets:
            return
        sets.append("updated_at=datetime('now','localtime')")
        with self._lock:
            conn = self._get_conn()
            conn.execute(f"UPDATE memes SET {', '.join(sets)} WHERE id=?", (*vals, meme_id))
            conn.commit()

    # --- 标签 ---

    def _set_tags(self, conn, meme_id: int, tags: List[str]):
        conn.execute("DELETE FROM meme_tags WHERE meme_id=?", (meme_id,))
        for tag in tags:
            tag = tag.strip()
            if not tag:
                continue
            # INSERT OR IGNORE 后 lastrowid 不可靠（已有tag时返回上次真实插入的rowid）
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
            row = conn.execute("SELECT id FROM tags WHERE name=?", (tag,)).fetchone()
            if row is None:
                continue
            tag_id = row[0]
            conn.execute(
                "INSERT OR IGNORE INTO meme_tags (meme_id, tag_id) VALUES (?, ?)",
                (meme_id, tag_id),
            )

    def set_meme_tags(self, meme_id: int, tags: List[str]):
        with self._lock:
            conn = self._get_conn()
            self._set_tags(conn, meme_id, tags)
            conn.commit()

    def get_meme_tags(self, meme_id: int) -> List[str]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT t.name FROM tags t
               JOIN meme_tags mt ON mt.tag_id = t.id
               WHERE mt.meme_id = ?""",
            (meme_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def get_all_tags(self) -> List[str]:
        conn = self._get_conn()
        return [r[0] for r in conn.execute("SELECT name FROM tags ORDER BY name").fetchall()]

    # --- 收藏 ---

    def toggle_favorite(self, meme_id: int) -> bool:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute("SELECT 1 FROM favorites WHERE meme_id=?", (meme_id,)).fetchone()
            if row:
                conn.execute("DELETE FROM favorites WHERE meme_id=?", (meme_id,))
                fav = False
            else:
                conn.execute("INSERT OR IGNORE INTO favorites (meme_id) VALUES (?)", (meme_id,))
                fav = True
            conn.commit()
            return fav

    def is_favorite(self, meme_id: int) -> bool:
        conn = self._get_conn()
        return (
            conn.execute("SELECT 1 FROM favorites WHERE meme_id=?", (meme_id,)).fetchone()
            is not None
        )

    # --- 收藏集 ---

    def create_collection(self, name: str) -> int:
        with self._lock:
            conn = self._get_conn()
            conn.execute("INSERT OR IGNORE INTO collections (name) VALUES (?)", (name,))
            conn.commit()
            row = conn.execute("SELECT id FROM collections WHERE name=?", (name,)).fetchone()
            return row[0] if row else -1

    def add_to_collection(self, meme_id: int, collection_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO meme_collections (meme_id, collection_id) VALUES (?, ?)",
                (meme_id, collection_id),
            )
            conn.commit()

    def remove_from_collection(self, meme_id: int, collection_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM meme_collections WHERE meme_id=? AND collection_id=?",
                (meme_id, collection_id),
            )
            conn.commit()

    def get_collections(self) -> List[Tuple[int, str]]:
        conn = self._get_conn()
        return [
            (r[0], r[1])
            for r in conn.execute("SELECT id, name FROM collections ORDER BY name").fetchall()
        ]

    def delete_collection(self, collection_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM meme_collections WHERE collection_id=?", (collection_id,))
            conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))
            conn.commit()

    # --- 搜索 ---

    def search(
        self,
        keyword: str = "",
        tags: List[str] = None,
        collection_id: int = None,
        favorite_only: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> List[dict]:
        conn = self._get_conn()
        where = []
        params = []

        if keyword:
            where.append("(m.filename LIKE ? OR m.original_name LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw])

        if tags:
            placeholders = ",".join("?" for _ in tags)
            where.append(
                f"""m.id IN (
                SELECT mt.meme_id FROM meme_tags mt
                JOIN tags t ON t.id = mt.tag_id
                WHERE t.name IN ({placeholders})
                GROUP BY mt.meme_id HAVING COUNT(DISTINCT t.id) = ?
            )"""
            )
            params.extend(tags)
            params.append(len(tags))

        if collection_id is not None:
            where.append(
                """m.id IN (
                SELECT mc.meme_id FROM meme_collections mc WHERE mc.collection_id = ?
            )"""
            )
            params.append(collection_id)

        if favorite_only:
            where.append("m.id IN (SELECT meme_id FROM favorites)")

        sql = "SELECT m.* FROM memes m"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count(
        self, keyword: str = "", collection_id: int = None, favorite_only: bool = False
    ) -> int:
        conn = self._get_conn()
        where = []
        params = []
        if keyword:
            where.append("(filename LIKE ? OR original_name LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw])
        if collection_id is not None:
            where.append(
                """id IN (
                SELECT meme_id FROM meme_collections WHERE collection_id = ?
            )"""
            )
            params.append(collection_id)
        if favorite_only:
            where.append("id IN (SELECT meme_id FROM favorites)")
        sql = "SELECT COUNT(*) FROM memes"
        if where:
            sql += " WHERE " + " AND ".join(where)
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def get_by_hash(self, file_hash: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM memes WHERE file_hash=? LIMIT 1", (file_hash,)).fetchone()
        return dict(row) if row else None

    def get_by_id(self, meme_id: int) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM memes WHERE id=?", (meme_id,)).fetchone()
        return dict(row) if row else None

    def get_by_filename(self, filename: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM memes WHERE filename=? LIMIT 1", (filename,)).fetchone()
        return dict(row) if row else None

    def get_all(self, offset: int = 0, limit: int = 100) -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM memes ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


# 全局单例
_db = None


def get_db() -> MemeDB:
    global _db
    if _db is None:
        _db = MemeDB()
    return _db
