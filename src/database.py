"""SQLite元数据管理 - 零依赖"""

import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from .config import get_config

_lazy_pinyin = None


def _load_json_list(raw) -> List[str]:
    """解析库里以 JSON 文本存储的字符串数组（脏数据一律退回空列表）"""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(val, list):
        return []
    return [str(x) for x in val]


# 备份恢复候选库预校验所需的表与列（backup.prepare_restore_source 使用）
_RESTORE_REQUIRED_TABLES = (
    "memes",
    "tags",
    "meme_tags",
    "collections",
    "meme_collections",
    "favorites",
    "recent_uses",
)
# 恢复候选库必需的外键定义：(子表列, 父表, 父表列, ON DELETE 行为)，
# 缺失会导致恢复后级联删除失效、产生孤儿记录
_RESTORE_REQUIRED_FOREIGN_KEYS = {
    "meme_tags": {
        ("meme_id", "memes", "id", "CASCADE"),
        ("tag_id", "tags", "id", "CASCADE"),
    },
    "meme_collections": {
        ("meme_id", "memes", "id", "CASCADE"),
        ("collection_id", "collections", "id", "CASCADE"),
    },
    "favorites": {("meme_id", "memes", "id", "CASCADE")},
    "recent_uses": {("meme_id", "memes", "id", "CASCADE")},
    "collections": {("parent_id", "collections", "id", "CASCADE")},
}
_RESTORE_REQUIRED_COLUMNS = {
    "memes": {
        "id",
        "filename",
        "file_hash",
        "original_name",
        "width",
        "height",
        "file_size",
        "mime_type",
        "sort_order",
        "stego_of_hash",
        "from_stego",
        "perceptual_hash",
        "created_at",
        "updated_at",
    },
    "tags": {"id", "name"},
    "meme_tags": {"meme_id", "tag_id"},
    "collections": {"id", "name", "parent_id", "sort_order"},
    "meme_collections": {"meme_id", "collection_id", "sort_order"},
    "favorites": {"meme_id", "added_at"},
    "recent_uses": {"meme_id", "used_at"},
}


# 名称自然排序键：数字段按整数（1,2,10），其余段按拼音（pypinyin 缺失时退回原串小写）
def _name_sort_key(name):
    global _lazy_pinyin
    key = []
    for part in re.split(r"(\d+)", str(name)):
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
            continue
        if _lazy_pinyin is None:
            try:
                from pypinyin import lazy_pinyin as _lp

                _lazy_pinyin = _lp
            except Exception:
                _lazy_pinyin = False
        if _lazy_pinyin:
            text = "".join(_lazy_pinyin(part)).lower()
        else:
            text = part.lower()
        key.append((1, text))
    return key


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
                perceptual_hash TEXT DEFAULT NULL,
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
        self._migrate(conn)

    def _migrate(self, conn):
        """迁移旧表：添加可能缺失的列并补建依赖新列的索引（幂等，可重复执行）"""
        migrates = [
            ("memes", "sort_order", "INTEGER DEFAULT 0"),
            ("memes", "stego_of_hash", "TEXT DEFAULT NULL"),
            ("memes", "from_stego", "INTEGER DEFAULT 0"),
            ("memes", "perceptual_hash", "TEXT DEFAULT NULL"),
            (
                "collections",
                "parent_id",
                "INTEGER DEFAULT NULL REFERENCES collections(id) ON DELETE CASCADE",
            ),
            ("collections", "sort_order", "INTEGER DEFAULT 0"),
            ("meme_collections", "sort_order", "INTEGER DEFAULT 0"),
            # AI 打标产出（ai_status 为状态机：unprocessed/running/done/failed）
            ("memes", "ai_name", "TEXT DEFAULT NULL"),
            ("memes", "ai_description", "TEXT DEFAULT NULL"),
            ("memes", "ai_visible_text", "TEXT DEFAULT NULL"),
            ("memes", "ai_emotions", "TEXT DEFAULT NULL"),
            ("memes", "ai_intents", "TEXT DEFAULT NULL"),
            ("memes", "ai_status", "TEXT DEFAULT NULL"),
            ("memes", "ai_error", "TEXT DEFAULT NULL"),
            ("memes", "ai_provider", "TEXT DEFAULT NULL"),
            ("memes", "ai_analyzed_at", "TEXT DEFAULT NULL"),
            # 嵌入（embedding 为 L2 归一化后的 float32 定长二进制）
            ("memes", "embedding", "BLOB DEFAULT NULL"),
            ("memes", "embedding_model", "TEXT DEFAULT NULL"),
            ("memes", "embedding_dim", "INTEGER DEFAULT NULL"),
            ("memes", "embedding_text_hash", "TEXT DEFAULT NULL"),
            ("memes", "embedded_at", "TEXT DEFAULT NULL"),
        ]
        for tbl, col, col_def in migrates:
            try:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {col_def}")
            except sqlite3.OperationalError:
                pass  # 列已存在
        # 审核模式的建议暂存表：在此建（而非 _init_db 的建表脚本）是为了让
        # 「恢复旧备份」路径也补上该表——prepare_restore_source 在必需表检查后
        # 调用 _migrate，故旧备份库同样能得到本表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_suggestions (
                meme_id      INTEGER PRIMARY KEY REFERENCES memes(id) ON DELETE CASCADE,
                tags         TEXT,
                name         TEXT,
                description  TEXT,
                visible_text TEXT,
                emotions     TEXT,
                intents      TEXT,
                provider     TEXT,
                created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """)
        # 该索引依赖迁移新增的 stego_of_hash 列，必须放在迁移之后建，
        # 否则旧库缺列时 CREATE INDEX 会抛 OperationalError 中断启动
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memes_stego ON memes(stego_of_hash)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memes_ai_status ON memes(ai_status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_memes_embedded_at ON memes(embedded_at)"
        )
        conn.commit()

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def backup_to(self, path: str):
        """WAL 一致快照：经 sqlite backup API 把当前库导出到目标文件"""
        with self._lock:
            dest = sqlite3.connect(path)
            try:
                self._get_conn().backup(dest)
                dest.commit()
            finally:
                dest.close()

    def has_any_data(self) -> bool:
        """是否存在任何业务数据（memes/分组/标签/收藏，含 stego 载体行）

        供备份恢复的空库判定。
        """
        conn = self._get_conn()
        for tbl in ("memes", "collections", "tags", "favorites"):
            if conn.execute(f"SELECT 1 FROM {tbl} LIMIT 1").fetchone():
                return True
        return False

    def prepare_restore_source(self, path: str):
        """候选备份库预校验：integrity_check + 全部表/必需列存在性 + 隔离连接上
        预迁移 + 孤儿外键检查。

        在 staging 文件的独立连接上操作，不触碰活动库；失败抛 ValueError。
        """
        conn = sqlite3.connect(path)
        # Row 按列名取值：foreign_key_list 的 on_delete 列序存在版本歧义
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            if not row or row[0] != "ok":
                raise ValueError(f"integrity_check: {row[0] if row else 'unknown'}")
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            missing_tables = [t for t in _RESTORE_REQUIRED_TABLES if t not in tables]
            if missing_tables:
                raise ValueError("缺少必需的数据表: " + ", ".join(missing_tables))
            self._migrate(conn)
            for tbl, cols in _RESTORE_REQUIRED_COLUMNS.items():
                have = {
                    r[1] for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()
                }
                missing_cols = cols - have
                if missing_cols:
                    raise ValueError(
                        f"表 {tbl} 缺少必需列: " + ", ".join(sorted(missing_cols))
                    )
            # 外键定义必须存在且带 ON DELETE CASCADE（缺失则级联删除失效）
            for tbl, required in _RESTORE_REQUIRED_FOREIGN_KEYS.items():
                actual = set()
                for r in conn.execute(f"PRAGMA foreign_key_list({tbl})").fetchall():
                    parent = r["table"]
                    col_from = r["from"]
                    col_to = r["to"]
                    on_delete = r["on_delete"]
                    if col_to is None:  # 隐式引用父表主键
                        pk = [
                            c[1]
                            for c in conn.execute(
                                f"PRAGMA table_info({parent})"
                            ).fetchall()
                            if c[5] > 0
                        ]
                        col_to = pk[0] if pk else None
                    actual.add((col_from, parent, col_to, on_delete))
                missing_fks = required - actual
                if missing_fks:
                    raise ValueError(f"表 {tbl} 缺少必需的外键定义")
            fk_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_issues:
                raise ValueError(f"存在 {len(fk_issues)} 条孤儿外键记录")
            conn.commit()
        finally:
            conn.close()

    def restore_from(self, path: str):
        """用备份库原子替换当前库内容（backup API，绕过 SQL 层），并补齐旧版本缺失列

        获取 _lock 后、替换前复查空库：所有 MemeDB 写入（含未走 _IMPORT_LOCK 的
        rescan）都在同一把锁上串行，检查与替换因此原子，绕过前置检查的竞态窗口
        不可能得手；非空时抛 ValueError 交由 restore_backup 回滚缓存文件。
        """
        with self._lock:
            if self.has_any_data():
                raise ValueError("恢复期间检测到新数据写入，已中止")
            src = sqlite3.connect(path)
            try:
                src.backup(self._get_conn())
            finally:
                src.close()
            conn = self._get_conn()
            self._migrate(conn)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()

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
        perceptual_hash: int = None,
    ) -> int:
        with self._lock:
            conn = self._get_conn()
            if perceptual_hash:
                ph_hex = hex(perceptual_hash)
            elif perceptual_hash == 0:
                ph_hex = "0"  # 已计算但无感知内容：占位，避免反复回填
            else:
                ph_hex = None
            cur = conn.execute(
                """INSERT INTO memes
                   (filename, file_hash, width, height,
                    file_size, mime_type, original_name, stego_of_hash, from_stego,
                    perceptual_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    ph_hex,
                ),
            )
            meme_id = cur.lastrowid
            conn.commit()  # 先提交meme插入，确保FOREIGN KEY约束通过
            if tags:
                self._set_tags(conn, meme_id, tags)
                conn.commit()
            return meme_id

    def delete_memes(self, meme_ids: List[int]):
        """批量删除表情（单锁单事务），一次性清理孤儿标签"""
        if not meme_ids:
            return
        with self._lock:
            conn = self._get_conn()
            placeholders = ",".join("?" for _ in meme_ids)
            conn.execute(f"DELETE FROM memes WHERE id IN ({placeholders})", meme_ids)
            self._prune_orphan_tags(conn)
            conn.commit()

    def delete_meme(self, meme_id: int):
        self.delete_memes([meme_id])

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
            # perceptual_hash 不在此列：写统一走 set_perceptual_hash（hex 序列化）
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

    def _existing_meme_ids(self, conn, ids: List[int]) -> List[int]:
        """过滤出实际存在的表情 id（外键开启时对缺失 id 写子表会整批失败）"""
        placeholders = ",".join("?" for _ in ids)
        return [
            r[0]
            for r in conn.execute(
                f"SELECT id FROM memes WHERE id IN ({placeholders})", ids
            ).fetchall()
        ]

    def add_tags_to_memes(self, meme_ids: List[int], tags: List[str]) -> int:
        """批量合并追加标签（不清空各表情已有标签），返回实际存在的表情数"""
        names = [t.strip() for t in (tags or []) if t.strip()]
        ids = list(dict.fromkeys(int(x) for x in (meme_ids or [])))
        if not names or not ids:
            return 0
        with self._lock:
            conn = self._get_conn()
            try:
                valid_ids = self._existing_meme_ids(conn, ids)
                if not valid_ids:
                    return 0
                for tag in names:
                    # INSERT OR IGNORE 后 lastrowid 不可靠（同 _set_tags）
                    conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (tag,))
                    row = conn.execute(
                        "SELECT id FROM tags WHERE name=?", (tag,)
                    ).fetchone()
                    if row is None:
                        continue
                    for mid in valid_ids:
                        conn.execute(
                            "INSERT OR IGNORE INTO meme_tags "
                            "(meme_id, tag_id) VALUES (?, ?)",
                            (mid, row[0]),
                        )
                conn.commit()
                return len(valid_ids)
            except Exception:
                conn.rollback()
                raise

    # --- AI 打标 ---

    def list_ai_pending(self, limit: int = 0) -> List[dict]:
        """取待打标的表情（从未处理、上次失败、或上次中断留下的 running）

        running 也视为待处理：任务开始时整批置 running，若进程中途退出
        （关闭窗口/崩溃），未处理完的行会永久停在 running，不重新拾起即
        成为僵尸数据（用户只能手改库）。
        """
        conn = self._get_conn()
        sql = (
            "SELECT id, filename FROM memes "
            "WHERE (ai_status IS NULL OR ai_status='failed' OR ai_status='running') "
            "AND (stego_of_hash IS NULL OR stego_of_hash='') "
            "ORDER BY id"
        )
        params = []
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def mark_ai_running(self, meme_ids: List[int]) -> int:
        """标记为处理中（防同一批被重复入队），返回更新条数"""
        ids = list(dict.fromkeys(int(x) for x in (meme_ids or [])))
        if not ids:
            return 0
        with self._lock:
            conn = self._get_conn()
            placeholders = ",".join("?" for _ in ids)
            try:
                cur = conn.execute(
                    "UPDATE memes SET ai_status='running' "
                    f"WHERE id IN ({placeholders})",
                    ids,
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def mark_ai_failed(self, meme_ids: List[int], err: str = "") -> int:
        """标记为失败并记录错误（供「重试失败」筛选）"""
        ids = list(dict.fromkeys(int(x) for x in (meme_ids or [])))
        if not ids:
            return 0
        with self._lock:
            conn = self._get_conn()
            placeholders = ",".join("?" for _ in ids)
            try:
                cur = conn.execute(
                    "UPDATE memes SET ai_status='failed', ai_error=? "
                    f"WHERE id IN ({placeholders})",
                    [str(err or "")[:500]] + ids,
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def store_ai_suggestion(self, meme_id: int, payload: dict) -> None:
        """暂存 AI 建议（审核模式：不写 tags/meme_tags，等用户确认）"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ai_suggestions
                        (meme_id, tags, name, description, visible_text,
                         emotions, intents, provider)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(meme_id),
                        json.dumps(payload.get("tags") or [], ensure_ascii=False),
                        payload.get("name") or "",
                        payload.get("description") or "",
                        payload.get("visible_text") or "",
                        json.dumps(payload.get("emotions") or [], ensure_ascii=False),
                        json.dumps(payload.get("intents") or [], ensure_ascii=False),
                        payload.get("provider") or "",
                    ),
                )
                conn.execute(
                    "UPDATE memes SET ai_status='done', ai_error=NULL, "
                    "ai_provider=?, ai_analyzed_at=datetime('now','localtime') "
                    "WHERE id=?",
                    (payload.get("provider") or "", int(meme_id)),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def list_ai_suggestions(self, limit: int = 0) -> List[dict]:
        """取待审核的 AI 建议（含表情文件名，供审核弹窗展示）"""
        conn = self._get_conn()
        sql = (
            "SELECT s.meme_id, s.tags, s.name, s.description, s.visible_text, "
            "s.emotions, s.intents, s.provider, s.created_at, m.filename "
            "FROM ai_suggestions s JOIN memes m ON m.id = s.meme_id "
            "ORDER BY s.created_at, s.meme_id"
        )
        params = []
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
        rows = []
        for r in conn.execute(sql, params).fetchall():
            item = dict(r)
            for key in ("tags", "emotions", "intents"):
                item[key] = _load_json_list(item.get(key))
            rows.append(item)
        return rows

    def count_ai_suggestions(self) -> int:
        """待审核建议数量（前端角标用）"""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) FROM ai_suggestions").fetchone()
        return int(row[0]) if row else 0

    def discard_ai_suggestions(self, meme_ids: List[int] = None) -> int:
        """丢弃建议（不写库）；meme_ids 为空表示全部丢弃"""
        with self._lock:
            conn = self._get_conn()
            try:
                if meme_ids:
                    ids = list(dict.fromkeys(int(x) for x in meme_ids))
                    placeholders = ",".join("?" for _ in ids)
                    cur = conn.execute(
                        f"DELETE FROM ai_suggestions WHERE meme_id IN ({placeholders})",
                        ids,
                    )
                else:
                    cur = conn.execute("DELETE FROM ai_suggestions")
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def list_ai_failed_ids(self) -> List[int]:
        """取打标失败的表情 id（供「重试失败」）"""
        conn = self._get_conn()
        return [
            int(r[0])
            for r in conn.execute(
                "SELECT id FROM memes WHERE ai_status='failed' "
                "AND (stego_of_hash IS NULL OR stego_of_hash='') ORDER BY id"
            ).fetchall()
        ]

    def clear_ai_error(self, meme_ids: List[int]) -> int:
        """把指定表情重置为未处理（重试前调用），返回更新条数"""
        ids = list(dict.fromkeys(int(x) for x in (meme_ids or [])))
        if not ids:
            return 0
        with self._lock:
            conn = self._get_conn()
            placeholders = ",".join("?" for _ in ids)
            try:
                cur = conn.execute(
                    "UPDATE memes SET ai_status=NULL, ai_error=NULL "
                    f"WHERE id IN ({placeholders})",
                    ids,
                )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def apply_ai_result(self, meme_id: int, payload: dict) -> None:
        """写入 AI 结果（审核通过后调用）：标签只追加，绝不覆盖已有标签"""
        mid = int(meme_id)
        tags = [t for t in (payload.get("tags") or []) if str(t).strip()]
        with self._lock:
            conn = self._get_conn()
            try:
                # 对不存在的 id 写 meme_tags 会整批失败（同 add_tags_to_memes）
                if not self._existing_meme_ids(conn, [mid]):
                    raise ValueError("表情不存在: %s" % mid)
                # 标签走合并追加语义（get-or-create + INSERT OR IGNORE），
                # 不调用 _set_tags：人工标签被覆盖是不可逆的数据损失
                for tag in tags:
                    conn.execute(
                        "INSERT OR IGNORE INTO tags (name) VALUES (?)", (str(tag),)
                    )
                for tag in tags:
                    row = conn.execute(
                        "SELECT id FROM tags WHERE name=?", (str(tag),)
                    ).fetchone()
                    if row is None:
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO meme_tags (meme_id, tag_id) "
                        "VALUES (?, ?)",
                        (mid, row[0]),
                    )
                conn.execute(
                    "UPDATE memes SET ai_name=?, ai_description=?, "
                    "ai_visible_text=?, ai_emotions=?, ai_intents=?, "
                    "ai_status='done', ai_error=NULL, "
                    "ai_analyzed_at=datetime('now','localtime') WHERE id=?",
                    (
                        payload.get("name") or "",
                        payload.get("description") or "",
                        payload.get("visible_text") or "",
                        json.dumps(payload.get("emotions") or [], ensure_ascii=False),
                        json.dumps(payload.get("intents") or [], ensure_ascii=False),
                        mid,
                    ),
                )
                conn.execute("DELETE FROM ai_suggestions WHERE meme_id=?", (mid,))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def ai_stats(self) -> dict:
        """AI 打标统计（各状态计数 + 待审核数）"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT COALESCE(ai_status, 'unprocessed') AS s, COUNT(*) AS n "
            "FROM memes WHERE (stego_of_hash IS NULL OR stego_of_hash='') "
            "GROUP BY s"
        ).fetchall()
        stats = {r["s"]: int(r["n"]) for r in rows}
        stats["pending_review"] = self.count_ai_suggestions()
        return stats

    def get_embedding_rows(self, limit: int = 0) -> List[dict]:
        """取已生成向量的记录（供语义检索全量载入）"""
        conn = self._get_conn()
        sql = (
            "SELECT id, embedding, embedding_dim FROM memes "
            "WHERE embedding IS NOT NULL AND embedding_dim > 0 "
            "AND (stego_of_hash IS NULL OR stego_of_hash='')"
        )
        params = []
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_by_ids(self, meme_ids: List[int]) -> List[dict]:
        """按 id 列表取行（供语义检索按相似度顺序装配结果）

        入参顺序不被保留：调用方需自行按 id 重排（语义分数在调用方）。
        空入参返回空列表，不构造 IN () 这种非法 SQL。
        """
        ids = [int(x) for x in (meme_ids or [])]
        if not ids:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in ids)
        sql = (
            "SELECT * FROM memes WHERE id IN (%s) "
            "AND (stego_of_hash IS NULL OR stego_of_hash='')" % placeholders
        )
        return [dict(r) for r in conn.execute(sql, ids).fetchall()]

    def filter_ids_by_scope(
        self,
        meme_ids: List[int],
        tags: List[str] = None,
        collection_id: int = None,
        favorite_only: bool = False,
        uncategorized_only: bool = False,
    ) -> List[int]:
        """把 id 列表按当前视图范围过滤（语义检索须尊重标签/分组/收藏筛选）

        与 search()/count() 的 WHERE 语义保持一致：多标签取交集（HAVING
        COUNT(DISTINCT)），分组含子树时由调用方先展开为 id 列表。
        """
        ids = [int(x) for x in (meme_ids or [])]
        if not ids:
            return []
        conn = self._get_conn()
        placeholders = ",".join("?" for _ in ids)
        where = ["(stego_of_hash IS NULL OR stego_of_hash = '')"]
        params = list(ids)

        if tags:
            tag_ph = ",".join("?" for _ in tags)
            where.append(
                "id IN (SELECT mt.meme_id FROM meme_tags mt "
                "JOIN tags t ON t.id = mt.tag_id "
                "WHERE t.name IN (%s) "
                "GROUP BY mt.meme_id HAVING COUNT(DISTINCT t.id) = ?)" % tag_ph
            )
            params.extend(tags)
            params.append(len(tags))

        if collection_id is not None:
            if isinstance(collection_id, list):
                cid_ph = ",".join("?" for _ in collection_id)
                where.append(
                    "id IN (SELECT meme_id FROM meme_collections "
                    "WHERE collection_id IN (%s))" % cid_ph
                )
                params.extend(collection_id)
            else:
                where.append(
                    "id IN (SELECT meme_id FROM meme_collections "
                    "WHERE collection_id = ?)"
                )
                params.append(collection_id)

        if favorite_only:
            where.append("id IN (SELECT meme_id FROM favorites)")
        if uncategorized_only:
            where.append(
                "NOT EXISTS (SELECT 1 FROM meme_collections WHERE meme_id = memes.id)"
            )

        sql = "SELECT id FROM memes WHERE id IN (%s) AND %s" % (
            placeholders,
            " AND ".join(where),
        )
        rows = conn.execute(sql, params).fetchall()
        return [int(r[0]) for r in rows]

    def list_embed_pending(self, limit: int = 0) -> List[dict]:
        """取待生成向量的记录：已打标完成，且无向量或源文本已变化"""
        conn = self._get_conn()
        sql = (
            "SELECT id, filename, ai_name, ai_description, ai_visible_text, "
            "ai_emotions, ai_intents, embedding, embedding_text_hash FROM memes "
            "WHERE ai_status='done' "
            "AND (stego_of_hash IS NULL OR stego_of_hash='') "
            "ORDER BY id"
        )
        params = []
        if limit and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def apply_embedding(
        self, meme_id: int, blob: bytes, model: str, dim: int, text_hash: str
    ) -> None:
        """写入向量与其元信息（model/dim/hash 用于识别需重建的行）"""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "UPDATE memes SET embedding=?, embedding_model=?, "
                    "embedding_dim=?, embedding_text_hash=?, "
                    "embedded_at=datetime('now','localtime') WHERE id=?",
                    (
                        blob,
                        str(model or ""),
                        int(dim),
                        str(text_hash or ""),
                        int(meme_id),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def clear_embeddings(self, model: str = None) -> int:
        """清空向量（换模型后重建用）；model 非空时只清该模型产出的"""
        with self._lock:
            conn = self._get_conn()
            try:
                if model:
                    cur = conn.execute(
                        "UPDATE memes SET embedding=NULL, embedding_dim=NULL, "
                        "embedding_text_hash=NULL, embedded_at=NULL "
                        "WHERE embedding_model=?",
                        (str(model),),
                    )
                else:
                    cur = conn.execute(
                        "UPDATE memes SET embedding=NULL, embedding_dim=NULL, "
                        "embedding_text_hash=NULL, embedded_at=NULL "
                        "WHERE embedding IS NOT NULL"
                    )
                conn.commit()
                return cur.rowcount
            except Exception:
                conn.rollback()
                raise

    def embed_stats(self) -> dict:
        """嵌入统计（已生成 / 待生成 / 各模型数量）"""
        conn = self._get_conn()
        done = conn.execute(
            "SELECT COUNT(*) FROM memes WHERE embedding IS NOT NULL"
        ).fetchone()
        by_model = conn.execute(
            "SELECT embedding_model AS m, COUNT(*) AS n FROM memes "
            "WHERE embedding IS NOT NULL GROUP BY embedding_model"
        ).fetchall()
        return {
            "embedded": int(done[0]) if done else 0,
            "by_model": {r["m"] or "": int(r["n"]) for r in by_model},
        }

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
        """创建分组；同名(parent_id)已存在则直接返回其 id（不产生重复空分组）"""
        with self._lock:
            conn = self._get_conn()
            if parent_id is not None:
                row = conn.execute(
                    "SELECT id FROM collections WHERE name=? AND parent_id=?",
                    (name, parent_id),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id FROM collections WHERE name=? AND parent_id IS NULL",
                    (name,),
                ).fetchone()
            if row:
                return row[0]
            if parent_id is not None:
                conn.execute(
                    "INSERT INTO collections (name, parent_id) VALUES (?, ?)",
                    (name, parent_id),
                )
            else:
                conn.execute("INSERT INTO collections (name) VALUES (?)", (name,))
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def add_to_collection(self, meme_id: int, collection_id: int):
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT OR IGNORE INTO meme_collections "
                "(meme_id, collection_id) VALUES (?, ?)",
                (meme_id, collection_id),
            )
            conn.commit()

    def add_memes_to_collection(self, meme_ids: List[int], collection_id: int) -> int:
        """批量加入分组（追加语义，单事务），返回实际新增的关联数（重复加入不计）"""
        ids = list(dict.fromkeys(int(x) for x in (meme_ids or [])))
        if not ids:
            return 0
        with self._lock:
            conn = self._get_conn()
            try:
                valid_ids = self._existing_meme_ids(conn, ids)
                if not valid_ids:
                    return 0
                if (
                    conn.execute(
                        "SELECT 1 FROM collections WHERE id=?", (collection_id,)
                    ).fetchone()
                    is None
                ):
                    raise ValueError(f"collection {collection_id} not found")
                added = 0
                for mid in valid_ids:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO meme_collections "
                        "(meme_id, collection_id) VALUES (?, ?)",
                        (mid, collection_id),
                    )
                    added += max(cur.rowcount, 0)
                conn.commit()
                return added
            except Exception:
                conn.rollback()
                raise

    def move_memes_to_collection(
        self, meme_ids: List[int], from_ids: List[int], to_id: int
    ) -> int:
        """批量把实际属于 from_ids（源分组子树）成员的表情移入 to_id（单事务）

        返回实际新增的目标关联数（已在目标分组的重复关联不计）；
        不属于源子树的表情不受删除或移动影响
        """
        ids = list(dict.fromkeys(int(x) for x in (meme_ids or [])))
        froms = list(dict.fromkeys(int(x) for x in (from_ids or [])))
        if not ids or not froms:
            return 0
        with self._lock:
            conn = self._get_conn()
            try:
                valid_ids = self._existing_meme_ids(conn, ids)
                if not valid_ids:
                    return 0
                if (
                    conn.execute(
                        "SELECT 1 FROM collections WHERE id=?", (to_id,)
                    ).fetchone()
                    is None
                ):
                    raise ValueError(f"collection {to_id} not found")
                # 仅纳入实际属于源子树的成员
                ph_from = ",".join("?" for _ in froms)
                ph_mid = ",".join("?" for _ in valid_ids)
                member_rows = conn.execute(
                    f"SELECT DISTINCT meme_id FROM meme_collections "
                    f"WHERE collection_id IN ({ph_from}) AND meme_id IN ({ph_mid})",
                    [*froms, *valid_ids],
                ).fetchall()
                members = [r[0] for r in member_rows]
                if not members:
                    return 0
                ph_members = ",".join("?" for _ in members)
                conn.execute(
                    f"DELETE FROM meme_collections WHERE collection_id IN ({ph_from}) "
                    f"AND meme_id IN ({ph_members})",
                    [*froms, *members],
                )
                moved = 0
                for mid in members:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO meme_collections "
                        "(meme_id, collection_id) VALUES (?, ?)",
                        (mid, to_id),
                    )
                    moved += max(cur.rowcount, 0)
                # 级联清理源子树内变空的分组：只删无成员且无子分组的叶子空组，
                # 逐层迭代直到无删除（支持子组先空、父组后空）；仅限 from_ids 范围，
                # 子树外分组不受影响
                while True:
                    deleted = conn.execute(
                        f"DELETE FROM collections WHERE id IN ({ph_from}) "
                        "AND id NOT IN ("
                        "SELECT DISTINCT collection_id FROM meme_collections) "
                        "AND id NOT IN ("
                        "SELECT DISTINCT parent_id FROM collections "
                        "WHERE parent_id IS NOT NULL)",
                        froms,
                    ).rowcount
                    if deleted == 0:
                        break
                conn.commit()
                return moved
            except Exception:
                conn.rollback()
                raise

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
        rows = conn.execute(
            "SELECT id, name, parent_id, sort_order FROM collections "
            "ORDER BY sort_order ASC"
        ).fetchall()
        # 自然排序回退：sort_order 相同（未拖拽）时数字按数值、中文按拼音
        return [
            (r[0], r[1], r[2], r[3])
            for r in sorted(rows, key=lambda r: (r[3], _name_sort_key(r[1])))
        ]

    def get_child_collections(self, parent_id: int) -> List[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, name, sort_order FROM collections WHERE parent_id=? "
            "ORDER BY sort_order ASC",
            (parent_id,),
        ).fetchall()
        return [
            {"id": r[0], "name": r[1]}
            for r in sorted(rows, key=lambda r: (r[2], _name_sort_key(r[1])))
        ]

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
            kw = f"%{keyword}%"
            where.append(
                "(m.filename LIKE ? OR m.original_name LIKE ? OR m.id IN ("
                "SELECT mt.meme_id FROM meme_tags mt "
                "JOIN tags t ON t.id = mt.tag_id WHERE t.name LIKE ?))"
            )
            params.extend([kw, kw, kw])

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
            if isinstance(collection_id, list):
                placeholders = ",".join("?" for _ in collection_id)
                where.append(f"""m.id IN (
                    SELECT mc.meme_id FROM meme_collections mc
                    WHERE mc.collection_id IN ({placeholders})
                )""")
                params.extend(collection_id)
            else:
                where.append(
                    "m.id IN ("
                    "SELECT mc.meme_id FROM meme_collections mc "
                    "WHERE mc.collection_id = ?)"
                )
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
            # 按主分组的 meme_collections.sort_order 排序（拖拽排序结果）
            primary_cid = (
                collection_id[0] if isinstance(collection_id, list) else collection_id
            )
            sql += """ ORDER BY (
                SELECT mc.sort_order FROM meme_collections mc
                WHERE mc.meme_id = m.id AND mc.collection_id = ?
            ), m.id LIMIT ? OFFSET ?"""
            params.extend([primary_cid, limit, offset])
        else:
            sql += " ORDER BY m.sort_order ASC, m.updated_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count(
        self,
        keyword: str = "",
        tags: List[str] = None,
        collection_id: int = None,
        favorite_only: bool = False,
        uncategorized_only: bool = False,
    ) -> int:
        conn = self._get_conn()
        where = ["(stego_of_hash IS NULL OR stego_of_hash = '')"]
        params = []
        if keyword:
            kw = f"%{keyword}%"
            where.append(
                "(filename LIKE ? OR original_name LIKE ? OR memes.id IN ("
                "SELECT mt.meme_id FROM meme_tags mt "
                "JOIN tags t ON t.id = mt.tag_id WHERE t.name LIKE ?))"
            )
            params.extend([kw, kw, kw])
        if tags:
            placeholders = ",".join("?" for _ in tags)
            where.append(f"""id IN (
                SELECT mt.meme_id FROM meme_tags mt
                JOIN tags t ON t.id = mt.tag_id
                WHERE t.name IN ({placeholders})
                GROUP BY mt.meme_id HAVING COUNT(DISTINCT t.id) = ?
            )""")
            params.extend(tags)
            params.append(len(tags))
        if collection_id is not None:
            if isinstance(collection_id, list):
                placeholders = ",".join("?" for _ in collection_id)
                where.append(f"""id IN (
                    SELECT meme_id FROM meme_collections
                    WHERE collection_id IN ({placeholders})
                )""")
                params.extend(collection_id)
            else:
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

    def get_all_phash(self) -> List[dict]:
        """返回所有可见 meme 的感知哈希快照，供全库相似度比对（排除隐写载体）"""
        with self._lock:
            conn = self._get_conn()
            rows = conn.execute(
                "SELECT id, filename, original_name, perceptual_hash, stego_of_hash "
                "FROM memes WHERE (stego_of_hash IS NULL OR stego_of_hash = '') "
                "ORDER BY sort_order ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def set_perceptual_hash(self, meme_id: int, phash: int):
        """写入/更新某 meme 的感知哈希（hex 文本存储，惰性回填用）"""
        if phash:
            ph_hex = hex(phash)
        elif phash == 0:
            ph_hex = "0"  # 已计算但无感知内容：占位，避免反复回填
        else:
            ph_hex = None
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE memes SET perceptual_hash=? WHERE id=?", (ph_hex, meme_id)
            )
            conn.commit()

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

    def count_recent(self) -> int:
        """统计最近使用表情总数"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) FROM memes m "
            "JOIN recent_uses r ON r.meme_id = m.id "
            "WHERE (m.stego_of_hash IS NULL OR m.stego_of_hash = '')"
        ).fetchone()
        return row[0] if row else 0


# 全局单例
_db = None


def get_db() -> MemeDB:
    global _db
    if _db is None:
        _db = MemeDB()
    return _db
