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
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS memes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filename    TEXT    NOT NULL,
                file_hash   TEXT    NOT NULL DEFAULT '',
                original_name TEXT  NOT NULL DEFAULT '',
                width       INTEGER DEFAULT 0,
                height      INTEGER DEFAULT 0,
                file_size   INTEGER DEFAULT 0,
                mime_type   TEXT    DEFAULT 'image/png',
                sort_order  INTEGER DEFAULT 0,
                stego_of_hash TEXT DEFAULT NULL,
                from_stego  INTEGER DEFAULT 0,
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
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL COLLATE NOCASE,
                parent_id   INTEGER DEFAULT NULL
                              REFERENCES collections(id) ON DELETE CASCADE,
                sort_order  INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS meme_collections (
                meme_id       INTEGER NOT NULL REFERENCES memes(id) ON DELETE CASCADE,
                collection_id INTEGER NOT NULL
                              REFERENCES collections(id) ON DELETE CASCADE,
                sort_order    INTEGER DEFAULT 0,
                PRIMARY KEY (meme_id, collection_id)
            );

            CREATE TABLE IF NOT EXISTS favorites (
                meme_id   INTEGER PRIMARY KEY REFERENCES memes(id) ON DELETE CASCADE,
                added_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS recent_uses (
                meme_id   INTEGER NOT NULL REFERENCES memes(id) ON DELETE CASCADE,
                used_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (meme_id)
            );

            CREATE INDEX IF NOT EXISTS idx_memes_hash ON memes(file_hash);
            CREATE INDEX IF NOT EXISTS idx_memes_name ON memes(filename);
            CREATE INDEX IF NOT EXISTS idx_recent_uses_at ON recent_uses(used_at);
        """)
        # 迁移旧表：添加可能缺失的列
        migrates = [
            ("memes", "sort_order", "INTEGER DEFAULT 0"),
            ("memes", "stego_of_hash", "TEXT DEFAULT NULL"),
            ("memes", "from_stego", "INTEGER DEFAULT 0"),
            (
                "collections",
                "parent_id",
                "INTEGER DEFAULT NULL REFERENCES collections(id) ON DELETE CASCADE",
            ),
            ("collections", "sort_order", "INTEGER DEFAULT 0"),
            ("meme_collections", "sort_order", "INTEGER DEFAULT 0"),
        ]
        for tbl, col, col_def in migrates:
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}")
            except sqlite3.OperationalError:
                pass  # 列已存在
        # 该索引依赖迁移新增的 stego_of_hash 列，必须放在迁移之后建，
        # 否则旧库缺列时 CREATE INDEX 会抛 OperationalError 中断启动
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memes_stego ON memes(stego_of_hash)"
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
        original_name: str = "",
        tags: List[str] = None,
        stego_of_hash: str = None,
        from_stego: int = 0,
    ) -> int:
        with self._lock:
            conn = self._get_conn()
            cur = conn.execute(
                """INSERT INTO memes
                   (filename, file_hash, width, height,
                    file_size, mime_type, original_name, stego_of_hash, from_stego)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    filename,
                    file_hash,
                    width,
                    height,
                    file_size,
                    mime_type,
                    original_name,
                    stego_of_hash,
                    from_stego,
                ),
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
            self._prune_orphan_tags(conn)
            conn.commit()

    def update_meme(self, meme_id: int, **kwargs):
        allowed = {
            "filename",
            "file_hash",
            "width",
            "height",
            "file_size",
            "mime_type",
            "original_name",
            "stego_of_hash",
            "from_stego",
        }
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
            conn.execute(
                f"UPDATE memes SET {', '.join(sets)} WHERE id=?", (*vals, meme_id)
            )
            conn.commit()

    # --- 标签 ---

    def _prune_orphan_tags(self, conn):
        """清理无任何表情使用的孤儿标签"""
        conn.execute(
            "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM meme_tags)"
        )

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
        self._prune_orphan_tags(conn)

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
        return [
            r[0] for r in conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
        ]

    # --- 收藏 ---

    def toggle_favorite(self, meme_id: int) -> bool:
        with self._lock:
            conn = self._get_conn()
            row = conn.execute(
                "SELECT 1 FROM favorites WHERE meme_id=?", (meme_id,)
            ).fetchone()
            if row:
                conn.execute("DELETE FROM favorites WHERE meme_id=?", (meme_id,))
                fav = False
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO favorites (meme_id) VALUES (?)", (meme_id,)
                )
                fav = True
            conn.commit()
            return fav

    def is_favorite(self, meme_id: int) -> bool:
        conn = self._get_conn()
        return (
            conn.execute(
                "SELECT 1 FROM favorites WHERE meme_id=?", (meme_id,)
            ).fetchone()
            is not None
        )

    # --- 收藏集 ---

    def create_collection(self, name: str, parent_id: int = None) -> int:
        with self._lock:
            conn = self._get_conn()
            if parent_id is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO collections (name, parent_id) VALUES (?, ?)",
                    (name, parent_id),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO collections (name) VALUES (?)", (name,)
                )
            conn.commit()
            row = conn.execute(
                "SELECT id FROM collections WHERE name=?", (name,)
            ).fetchone()
            return row[0] if row else -1

    def add_to_collection(self, meme_id: int, collection_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO meme_collections "
                "(meme_id, collection_id) VALUES (?, ?)",
                (meme_id, collection_id),
            )
            conn.commit()

    def collection_exists(self, name: str, parent_id: int = None) -> bool:
        """检查同名分组是否已存在"""
        conn = self._get_conn()
        if parent_id is not None:
            row = conn.execute(
                "SELECT 1 FROM collections WHERE name=? AND parent_id=?",
                (name, parent_id),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM collections WHERE name=? AND parent_id IS NULL",
                (name,),
            ).fetchone()
        return row is not None

    def remove_from_collection(self, meme_id: int, collection_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM meme_collections WHERE meme_id=? AND collection_id=?",
                (meme_id, collection_id),
            )
            conn.commit()

    def set_collection_members(self, collection_id: int, meme_ids: List[int]):
        """批量设置分组内成员（清空后按序写入，保留 sort_order）"""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM meme_collections WHERE collection_id=?", (collection_id,)
            )
            for i, mid in enumerate(meme_ids or []):
                conn.execute(
                    "INSERT OR IGNORE INTO meme_collections "
                    "(meme_id, collection_id, sort_order) VALUES (?, ?, ?)",
                    (mid, collection_id, i),
                )
            conn.commit()

    def get_collections(self) -> List[Tuple[int, str, int, int]]:
        conn = self._get_conn()
        return [
            (r[0], r[1], r[2], r[3])
            for r in conn.execute(
                "SELECT id, name, parent_id, sort_order FROM collections "
                "ORDER BY sort_order ASC, name"
            ).fetchall()
        ]

    def get_child_collections(self, parent_id: int) -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, name FROM collections WHERE parent_id=? "
            "ORDER BY sort_order ASC, name",
            (parent_id,),
        ).fetchall()
        return [{"id": r[0], "name": r[1]} for r in rows]

    def get_collection_depth(self, cid: int) -> int:
        depth = 0
        cur = cid
        conn = self._get_conn()
        while cur is not None:
            row = conn.execute(
                "SELECT parent_id FROM collections WHERE id=?", (cur,)
            ).fetchone()
            if row is None or row[0] is None:
                break
            cur = row[0]
            depth += 1
        return depth

    def delete_all(self):
        """删除所有表情包及相关数据"""
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM favorites")
            conn.execute("DELETE FROM meme_collections")
            conn.execute("DELETE FROM meme_tags")
            conn.execute("DELETE FROM memes")
            conn.execute("DELETE FROM collections")
            conn.execute("DELETE FROM tags")
            conn.commit()

    def delete_collection(self, collection_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "DELETE FROM meme_collections WHERE collection_id=?", (collection_id,)
            )
            conn.execute("DELETE FROM collections WHERE id=?", (collection_id,))
            conn.commit()

    def rename_collection(self, collection_id: int, new_name: str):
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE collections SET name=? WHERE id=?", (new_name, collection_id)
            )
            conn.commit()

    # --- 搜索 ---

    def search(
        self,
        keyword: str = "",
        tags: List[str] = None,
        collection_id: int = None,
        favorite_only: bool = False,
        uncategorized_only: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> List[dict]:
        conn = self._get_conn()
        where = ["(m.stego_of_hash IS NULL OR m.stego_of_hash = '')"]
        params = []

        if keyword:
            where.append("(m.filename LIKE ? OR m.original_name LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw])

        if tags:
            placeholders = ",".join("?" for _ in tags)
            where.append(f"""m.id IN (
                SELECT mt.meme_id FROM meme_tags mt
                JOIN tags t ON t.id = mt.tag_id
                WHERE t.name IN ({placeholders})
                GROUP BY mt.meme_id HAVING COUNT(DISTINCT t.id) = ?
            )""")
            params.extend(tags)
            params.append(len(tags))

        if collection_id is not None:
            where.append("""m.id IN (
                SELECT mc.meme_id FROM meme_collections mc WHERE mc.collection_id = ?
            )""")
            params.append(collection_id)

        if favorite_only:
            where.append("m.id IN (SELECT meme_id FROM favorites)")

        if uncategorized_only:
            where.append("""NOT EXISTS (
                SELECT 1 FROM meme_collections mc WHERE mc.meme_id = m.id
            )""")

        sql = "SELECT m.* FROM memes m"
        if where:
            sql += " WHERE " + " AND ".join(where)
        if collection_id is not None:
            # 分组/子分组内按 meme_collections.sort_order 排序（拖拽排序结果）
            sql += """ ORDER BY (
                SELECT mc.sort_order FROM meme_collections mc
                WHERE mc.meme_id = m.id AND mc.collection_id = ?
            ) ASC, m.updated_at DESC LIMIT ? OFFSET ?"""
            params.extend([collection_id, limit, offset])
        else:
            sql += " ORDER BY m.sort_order ASC, m.updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count(
        self,
        keyword: str = "",
        collection_id: int = None,
        favorite_only: bool = False,
        uncategorized_only: bool = False,
    ) -> int:
        conn = self._get_conn()
        where = ["(stego_of_hash IS NULL OR stego_of_hash = '')"]
        params = []
        if keyword:
            where.append("(filename LIKE ? OR original_name LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw])
        if collection_id is not None:
            where.append("""id IN (
                SELECT meme_id FROM meme_collections WHERE collection_id = ?
            )""")
            params.append(collection_id)
        if favorite_only:
            where.append("id IN (SELECT meme_id FROM favorites)")
        if uncategorized_only:
            where.append("""NOT EXISTS (
                SELECT 1 FROM meme_collections WHERE meme_id = memes.id
            )""")
        sql = "SELECT COUNT(*) FROM memes"
        if where:
            sql += " WHERE " + " AND ".join(where)
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    def get_by_hash(self, file_hash: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM memes WHERE file_hash=? LIMIT 1", (file_hash,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_stego_of(self, file_hash: str) -> Optional[dict]:
        """查找携带指定原图哈希的隐写 GIF 表情"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM memes WHERE stego_of_hash=? LIMIT 1", (file_hash,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_id(self, meme_id: int) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM memes WHERE id=?", (meme_id,)).fetchone()
        return dict(row) if row else None

    def get_by_filename(self, filename: str) -> Optional[dict]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM memes WHERE filename=? LIMIT 1", (filename,)
        ).fetchone()
        return dict(row) if row else None

    def get_all(self, offset: int = 0, limit: int = 100) -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM memes ORDER BY sort_order ASC, updated_at DESC "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]

    def reorder_memes(self, meme_ids: List[int]):
        with self._lock:
            conn = self._get_conn()
            for i, mid in enumerate(meme_ids):
                conn.execute("UPDATE memes SET sort_order=? WHERE id=?", (i, mid))
            conn.commit()

    def reorder_collections(self, collection_ids: List[int]):
        with self._lock:
            conn = self._get_conn()
            for i, cid in enumerate(collection_ids):
                conn.execute("UPDATE collections SET sort_order=? WHERE id=?", (i, cid))
            conn.commit()

    def reorder_collection_members(self, collection_id: int, meme_ids: List[int]):
        with self._lock:
            conn = self._get_conn()
            for i, mid in enumerate(meme_ids):
                conn.execute(
                    "UPDATE meme_collections SET sort_order=? "
                    "WHERE meme_id=? AND collection_id=?",
                    (i, mid, collection_id),
                )
            conn.commit()

    def record_use(self, meme_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO recent_uses (meme_id, used_at) "
                "VALUES (?, datetime('now','localtime'))",
                (meme_id,),
            )
            conn.commit()

    def remove_from_recent(self, meme_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM recent_uses WHERE meme_id=?", (meme_id,))
            conn.commit()

    def clear_recent(self):
        with self._lock:
            conn = self._get_conn()
            conn.execute("DELETE FROM recent_uses")
            conn.commit()

    def get_recent(self, limit: int = 50, offset: int = 0) -> List[dict]:
        """按最近使用时间分页查询表情（used_at 相同时以 meme_id 稳定排序）"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT m.* FROM memes m "
            "JOIN recent_uses r ON r.meme_id = m.id "
            "WHERE (m.stego_of_hash IS NULL OR m.stego_of_hash = '') "
            "ORDER BY r.used_at DESC, r.meme_id DESC LIMIT ? OFFSET ?",
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
