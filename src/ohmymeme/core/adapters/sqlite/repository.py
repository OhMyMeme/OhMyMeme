"""保持历史 OhMyMeme SQLite 格式的类型化查询适配器。"""

import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .schema import (
    FINAL_COLUMNS,
    INDEXES,
    MIGRATIONS,
    SCHEMA,
    TABLES,
    UnknownDatabaseSchema,
)

_MIGRATION_ATTEMPTS = 5
_MIGRATION_RETRY_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class SqliteMemeQuery:
    keyword: str = ""
    tags: tuple[str, ...] = ()
    collection_ids: tuple[int, ...] = ()
    favorite_only: bool = False
    uncategorized_only: bool = False
    offset: int = 0
    limit: int = 100


@dataclass(frozen=True, slots=True)
class MemeRecord:
    id: int
    filename: str
    file_hash: str
    original_name: str
    width: int
    height: int
    file_size: int
    mime_type: str
    sort_order: int
    stego_of_hash: str | None
    from_stego: int
    perceptual_hash: str | None
    created_at: str
    updated_at: str

    def legacy_row(self) -> dict[str, int | str | None]:
        return {
            "id": self.id,
            "filename": self.filename,
            "file_hash": self.file_hash,
            "original_name": self.original_name,
            "width": self.width,
            "height": self.height,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "sort_order": self.sort_order,
            "stego_of_hash": self.stego_of_hash,
            "from_stego": self.from_stego,
            "perceptual_hash": self.perceptual_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class SqliteMemeRepository:
    """为每个线程持有连接，并在首次访问时完成兼容升级。"""

    def __init__(
        self,
        database_path: Path,
        connection_factory: Callable[..., sqlite3.Connection] = sqlite3.connect,
    ) -> None:
        self._database_path = database_path
        self._connection_factory = connection_factory
        self._local = threading.local()
        self._opened = False

    def open(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connection()
        self._assert_known_tables(connection)
        for attempt in range(_MIGRATION_ATTEMPTS):
            try:
                self._configure(connection)
                self._upgrade(connection)
                self._opened = True
                return
            except sqlite3.OperationalError as error:
                connection.rollback()
                if not self._is_locked(error) or attempt == _MIGRATION_ATTEMPTS - 1:
                    raise
                time.sleep(_MIGRATION_RETRY_SECONDS * (attempt + 1))
            except sqlite3.Error:
                connection.rollback()
                raise

    def connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self._connection_factory(
                str(self._database_path), timeout=5.0, check_same_thread=False
            )
            connection.row_factory = sqlite3.Row
            if self._opened:
                self._configure(connection)
            self._local.connection = connection
        return connection

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            self._local.connection = None

    def search(self, query: SqliteMemeQuery) -> tuple[MemeRecord, ...]:
        where, parameters = self._where(query, "m")
        statement = "SELECT m.* FROM memes m WHERE " + " AND ".join(where)
        if query.collection_ids:
            statement += (
                " ORDER BY (SELECT mc.sort_order FROM meme_collections mc "
                "WHERE mc.meme_id = m.id AND mc.collection_id = ?) ASC, "
                "m.updated_at DESC, m.id ASC LIMIT ? OFFSET ?"
            )
            parameters.extend((query.collection_ids[0], query.limit, query.offset))
        else:
            statement += (
                " ORDER BY m.sort_order ASC, m.updated_at DESC, m.id ASC "
                "LIMIT ? OFFSET ?"
            )
            parameters.extend((query.limit, query.offset))
        rows = self.connection().execute(statement, parameters)
        return tuple(self._record(row) for row in rows)

    def count(self, query: SqliteMemeQuery) -> int:
        where, parameters = self._where(query, "")
        statement = "SELECT COUNT(*) FROM memes WHERE " + " AND ".join(where)
        row = self.connection().execute(statement, parameters).fetchone()
        return int(row[0]) if row is not None else 0

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA busy_timeout=250")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")

    def _upgrade(self, connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")
        for statement in SCHEMA:
            connection.execute(statement)
        for table, column, definition in MIGRATIONS:
            self._add_column(connection, table, column, definition)
        for statement in INDEXES:
            connection.execute(statement)
        self._verify_schema(connection)
        connection.commit()

    @staticmethod
    def _is_locked(error: sqlite3.OperationalError) -> bool:
        return "locked" in str(error).lower()

    @staticmethod
    def _add_column(
        connection: sqlite3.Connection, table: str, column: str, definition: str
    ) -> None:
        try:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        except sqlite3.OperationalError as error:
            if "duplicate column name" not in str(error).lower():
                raise

    def _assert_known_tables(self, connection: sqlite3.Connection) -> None:
        unknown = self._table_names(connection) - TABLES
        if unknown:
            raise UnknownDatabaseSchema(f"unknown database tables: {sorted(unknown)}")

    def _verify_schema(self, connection: sqlite3.Connection) -> None:
        if self._table_names(connection) != TABLES:
            raise UnknownDatabaseSchema(
                "database table set does not match final schema"
            )
        for table, expected in FINAL_COLUMNS.items():
            columns = frozenset(
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            )
            if columns != expected:
                raise UnknownDatabaseSchema(
                    f"columns do not match final schema: {table}"
                )
        if tuple(connection.execute("PRAGMA foreign_key_check")):
            raise UnknownDatabaseSchema("foreign key corruption detected")

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> frozenset[str]:
        statement = (
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
        return frozenset(row[0] for row in connection.execute(statement))

    @staticmethod
    def _record(row: sqlite3.Row) -> MemeRecord:
        return MemeRecord(
            int(row["id"]),
            str(row["filename"]),
            str(row["file_hash"]),
            str(row["original_name"]),
            int(row["width"]),
            int(row["height"]),
            int(row["file_size"]),
            str(row["mime_type"]),
            int(row["sort_order"]),
            row["stego_of_hash"],
            int(row["from_stego"]),
            row["perceptual_hash"],
            str(row["created_at"]),
            str(row["updated_at"]),
        )

    @staticmethod
    def _where(query: SqliteMemeQuery, alias: str) -> tuple[list[str], list[int | str]]:
        prefix = f"{alias}." if alias else ""
        where = [f"({prefix}stego_of_hash IS NULL OR {prefix}stego_of_hash = '')"]
        parameters: list[int | str] = []
        if query.keyword:
            where.append(
                f"({prefix}filename LIKE ? OR {prefix}original_name LIKE ? OR "
                f"{prefix}id IN (SELECT mt.meme_id FROM meme_tags mt "
                "JOIN tags t ON t.id = mt.tag_id WHERE t.name LIKE ?))"
            )
            keyword = f"%{query.keyword}%"
            parameters.extend((keyword, keyword, keyword))
        if query.tags:
            placeholders = ",".join("?" for _ in query.tags)
            where.append(
                f"{prefix}id IN (SELECT mt.meme_id FROM meme_tags mt "
                f"JOIN tags t ON t.id = mt.tag_id WHERE t.name IN ({placeholders}) "
                "GROUP BY mt.meme_id HAVING COUNT(DISTINCT t.id) = ?)"
            )
            parameters.extend(query.tags)
            parameters.append(len(query.tags))
        if query.collection_ids:
            placeholders = ",".join("?" for _ in query.collection_ids)
            where.append(
                f"{prefix}id IN (SELECT meme_id FROM meme_collections "
                f"WHERE collection_id IN ({placeholders}))"
            )
            parameters.extend(query.collection_ids)
        if query.favorite_only:
            where.append(f"{prefix}id IN (SELECT meme_id FROM favorites)")
        if query.uncategorized_only:
            where.append(
                "NOT EXISTS (SELECT 1 FROM meme_collections "
                f"WHERE meme_id = {prefix}id)"
            )
        return where, parameters
