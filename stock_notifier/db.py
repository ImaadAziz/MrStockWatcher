from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WatchRecord:
    id: int
    chat_id: int
    name: str
    url: str
    color: str
    size: str
    interval_minutes: int
    variant_id: str
    last_in_stock: str | None
    last_checked_at: int


class WatchRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS watches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    color TEXT NOT NULL,
                    size TEXT NOT NULL,
                    interval_minutes INTEGER NOT NULL DEFAULT 10,
                    variant_id TEXT NOT NULL DEFAULT '',
                    variant_label TEXT NOT NULL DEFAULT '',
                    last_in_stock TEXT,
                    last_checked_at INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )

    def add_watch(
        self,
        chat_id: int,
        name: str,
        url: str,
        color: str,
        size: str,
        interval_minutes: int,
        variant_id: str,
        variant_label: str,
        last_in_stock: str | None,
    ) -> int:
        created_at = int(time.time())
        with self._connect() as connection:
            existing = connection.execute(
                """
                SELECT id FROM watches
                WHERE chat_id = ?
                  AND url = ?
                  AND lower(color) = lower(?)
                  AND lower(size) = lower(?)
                """,
                (chat_id, url, color, size),
            ).fetchone()
            if existing is not None:
                raise ValueError("duplicate_watch")
            cursor = connection.execute(
                """
                INSERT INTO watches (
                    chat_id, name, url, color, size, interval_minutes,
                    variant_id, variant_label, last_in_stock, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    name,
                    url,
                    color,
                    size,
                    interval_minutes,
                    variant_id,
                    variant_label,
                    last_in_stock,
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def list_watches(self, chat_id: int) -> list[WatchRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, chat_id, name, url, color, size, interval_minutes,
                       variant_id, last_in_stock, last_checked_at
                FROM watches
                WHERE chat_id = ?
                ORDER BY id
                """,
                (chat_id,),
            ).fetchall()
        return [self._row_to_watch(row) for row in rows]

    def get_watch(self, chat_id: int, watch_id: int) -> WatchRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, chat_id, name, url, color, size, interval_minutes,
                       variant_id, last_in_stock, last_checked_at
                FROM watches
                WHERE chat_id = ? AND id = ?
                """,
                (chat_id, watch_id),
            ).fetchone()
        return self._row_to_watch(row) if row is not None else None

    def remove_watch(self, chat_id: int, watch_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM watches WHERE chat_id = ? AND id = ?",
                (chat_id, watch_id),
            )
            return cursor.rowcount > 0

    def due_watches(self, now_ts: int) -> list[WatchRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, chat_id, name, url, color, size, interval_minutes,
                       variant_id, last_in_stock, last_checked_at
                FROM watches
                WHERE last_checked_at = 0
                   OR last_checked_at + (interval_minutes * 60) <= ?
                ORDER BY last_checked_at ASC, id ASC
                """,
                (now_ts,),
            ).fetchall()
        return [self._row_to_watch(row) for row in rows]

    def update_watch_status(
        self,
        watch_id: int,
        last_in_stock: str,
        checked_at: int,
        variant_id: str,
        variant_label: str,
        name: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE watches
                SET last_in_stock = ?,
                    last_checked_at = ?,
                    variant_id = ?,
                    variant_label = ?,
                    name = ?
                WHERE id = ?
                """,
                (last_in_stock, checked_at, variant_id, variant_label, name, watch_id),
            )

    def get_setting(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row is not None else None

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )

    def _row_to_watch(self, row: sqlite3.Row) -> WatchRecord:
        return WatchRecord(
            id=int(row["id"]),
            chat_id=int(row["chat_id"]),
            name=str(row["name"]),
            url=str(row["url"]),
            color=str(row["color"]),
            size=str(row["size"]),
            interval_minutes=int(row["interval_minutes"]),
            variant_id=str(row["variant_id"] or ""),
            last_in_stock=str(row["last_in_stock"]) if row["last_in_stock"] is not None else None,
            last_checked_at=int(row["last_checked_at"]),
        )
