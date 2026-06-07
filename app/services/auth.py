from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status

from app.config import get_settings


def _db_path() -> str:
    return get_settings().database_path


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if "@" not in normalized or "." not in normalized.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return normalized


def _hash_password(password: str, salt: str | None = None) -> str:
    if len(password or "") < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 120_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt, expected = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = _hash_password(password, salt).split("$", 2)[-1]
    return hmac.compare_digest(candidate, expected)


def _public_user(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"] or row["email"].split("@")[0],
        "created_at": row["created_at"],
    }


def _create_session(conn: sqlite3.Connection, user_id: int) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    created_at = _now()
    expires_at = created_at + timedelta(days=30)
    conn.execute(
        """
        INSERT INTO sessions(token, user_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (token, user_id, created_at.isoformat(), expires_at.isoformat()),
    )
    return {"access_token": token, "token_type": "bearer", "expires_at": expires_at.isoformat()}


def register_user(email: str, password: str, display_name: str | None = None) -> dict[str, Any]:
    normalized = _normalize_email(email)
    password_hash = _hash_password(password)
    created_at = _now().isoformat()
    try:
        with closing(sqlite3.connect(_db_path())) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                """
                INSERT INTO users(email, display_name, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (normalized, (display_name or "").strip() or None, password_hash, created_at),
            )
            session = _create_session(conn, int(cur.lastrowid))
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE id = ?", (int(cur.lastrowid),)).fetchone()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    return {"user": _public_user(row), **session}


def login_user(email: str, password: str) -> dict[str, Any]:
    normalized = _normalize_email(email)
    with closing(sqlite3.connect(_db_path())) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE email = ?", (normalized,)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")
        session = _create_session(conn, int(row["id"]))
        conn.commit()
    return {"user": _public_user(row), **session}


def user_from_token(token: str | None) -> dict[str, Any]:
    raw = (token or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing session token.")
    with closing(sqlite3.connect(_db_path())) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT users.* FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ? AND datetime(sessions.expires_at) > datetime(?)
            """,
            (raw, _now().isoformat()),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid.")
    return _public_user(row)


def logout_user(token: str | None) -> dict[str, bool]:
    raw = (token or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if raw:
        with closing(sqlite3.connect(_db_path())) as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (raw,))
            conn.commit()
    return {"ok": True}
