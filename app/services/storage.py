from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models import AnalysisResult


def _db_path() -> str:
    return get_settings().database_path


def init_db() -> None:
    db = Path(_db_path())
    db.parent.mkdir(parents=True, exist_ok=True) if db.parent != Path(".") else None
    with closing(sqlite3.connect(_db_path())) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                score INTEGER NOT NULL,
                risk TEXT NOT NULL,
                bias TEXT NOT NULL,
                setup TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.commit()


def save_analysis(result: AnalysisResult) -> int:
    payload = result.model_dump(mode="json")
    with closing(sqlite3.connect(_db_path())) as conn:
        cur = conn.execute(
            """
            INSERT INTO signals(symbol, timeframe, score, risk, bias, setup, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.symbol,
                result.timeframe,
                result.score,
                result.risk,
                result.bias,
                result.setup,
                json.dumps(payload),
                result.created_at.isoformat(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_signals(limit: int = 50, symbol: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 500))
    with closing(sqlite3.connect(_db_path())) as conn:
        conn.row_factory = sqlite3.Row
        if symbol:
            rows = conn.execute(
                """
                SELECT * FROM signals
                WHERE UPPER(symbol) = UPPER(?)
                ORDER BY datetime(created_at) DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM signals
                ORDER BY datetime(created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item["payload"])
        except Exception:
            pass
        results.append(item)
    return results
