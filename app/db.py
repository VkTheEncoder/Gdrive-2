from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from typing import Optional, Tuple

from .config import DB_PATH

def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                user_id INTEGER PRIMARY KEY,
                email TEXT,
                creds_json TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS states (
                state TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                user_id INTEGER PRIMARY KEY,
                drive_folder_id TEXT
            );
            """
        )

def save_state(state: str, user_id: int):
    with _conn() as con:
        con.execute(
            "REPLACE INTO states(state, user_id, created_at) VALUES(?,?,?)",
            (state, user_id, int(time.time())),
        )

def pop_state(state: str) -> Optional[int]:
    with _conn() as con:
        cur = con.execute("SELECT user_id FROM states WHERE state=?", (state,))
        row = cur.fetchone()
        if not row:
            return None
        con.execute("DELETE FROM states WHERE state=?", (state,))
        return int(row["user_id"])

def save_creds(user_id: int, email: str, creds_json: str):
    with _conn() as con:
        con.execute(
            "REPLACE INTO oauth_tokens(user_id, email, creds_json, created_at) VALUES(?,?,?,?)",
            (user_id, email, creds_json, int(time.time())),
        )

def load_creds(user_id: int) -> Optional[Tuple[str, str]]:
    with _conn() as con:
        cur = con.execute("SELECT email, creds_json FROM oauth_tokens WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        if not row:
            return None
        return row["email"], row["creds_json"]

def delete_creds(user_id: int):
    with _conn() as con:
        con.execute("DELETE FROM oauth_tokens WHERE user_id=?", (user_id,))

def set_folder(user_id: int, folder_id: Optional[str]):
    with _conn() as con:
        con.execute("REPLACE INTO settings(user_id, drive_folder_id) VALUES(?,?)", (user_id, folder_id))

def get_folder(user_id: int) -> Optional[str]:
    with _conn() as con:
        cur = con.execute("SELECT drive_folder_id FROM settings WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row["drive_folder_id"] if row and row["drive_folder_id"] else None
