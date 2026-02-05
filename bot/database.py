import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "wishes.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            first_name TEXT,
            pair_code TEXT UNIQUE NOT NULL,
            partner_id INTEGER REFERENCES users(id),
            notification_hour INTEGER DEFAULT 9,
            notification_minute INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wishes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            text TEXT NOT NULL,
            fulfilled INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def generate_pair_code() -> str:
    return uuid.uuid4().hex[:8].upper()


def register_user(telegram_id: int, username: str | None, first_name: str | None) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return dict(existing)

    pair_code = generate_pair_code()
    now = datetime.utcnow().isoformat()

    cursor.execute(
        """
        INSERT INTO users (telegram_id, username, first_name, pair_code, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (telegram_id, username, first_name, pair_code, now),
    )
    conn.commit()

    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = dict(cursor.fetchone())
    conn.close()
    return user


def get_user_by_telegram_id(telegram_id: int) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_pair_code(pair_code: str) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE pair_code = ?", (pair_code.upper(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def pair_users(user_id: int, partner_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET partner_id = ? WHERE id = ?", (partner_id, user_id))
        cursor.execute("UPDATE users SET partner_id = ? WHERE id = ?", (user_id, partner_id))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def unpair_user(user_id: int, partner_id: int) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET partner_id = NULL WHERE id = ?", (user_id,))
    cursor.execute("UPDATE users SET partner_id = NULL WHERE id = ?", (partner_id,))
    conn.commit()
    conn.close()


def add_wish(user_id: int, text: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.utcnow().isoformat()
    cursor.execute(
        "INSERT INTO wishes (user_id, text, created_at) VALUES (?, ?, ?)",
        (user_id, text, now),
    )
    conn.commit()
    wish_id = cursor.lastrowid
    cursor.execute("SELECT * FROM wishes WHERE id = ?", (wish_id,))
    wish = dict(cursor.fetchone())
    conn.close()
    return wish


def get_wishes(user_id: int, include_fulfilled: bool = False) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    if include_fulfilled:
        cursor.execute(
            "SELECT * FROM wishes WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        )
    else:
        cursor.execute(
            "SELECT * FROM wishes WHERE user_id = ? AND fulfilled = 0 ORDER BY created_at DESC",
            (user_id,),
        )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def remove_wish(wish_id: int, user_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM wishes WHERE id = ? AND user_id = ?", (wish_id, user_id))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def fulfill_wish(wish_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE wishes SET fulfilled = 1 WHERE id = ?", (wish_id,))
    updated = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_random_wish(user_id: int) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM wishes WHERE user_id = ? AND fulfilled = 0 ORDER BY RANDOM() LIMIT 1",
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_paired_users() -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE partner_id IS NOT NULL")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def set_notification_time(user_id: int, hour: int, minute: int) -> None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET notification_hour = ?, notification_minute = ? WHERE id = ?",
        (hour, minute, user_id),
    )
    conn.commit()
    conn.close()
