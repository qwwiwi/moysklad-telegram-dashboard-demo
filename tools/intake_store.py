"""Private SQLite journal for Telegram intake."""
import os
import sqlite3
from pathlib import Path


def connect():
    os.umask(0o077)
    path = Path(os.environ.get("INTAKE_DB", "/var/lib/tovarno/intake.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(path, timeout=15)
    os.chmod(path, 0o600)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS profiles(user_id INTEGER PRIMARY KEY, role TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS journal(
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, display_name TEXT,
            role TEXT, received_at TEXT, kind TEXT, filename TEXT, text TEXT,
            origin TEXT, status TEXT DEFAULT 'received', message_id INTEGER,
            chat_id INTEGER, storage_path TEXT,
            UNIQUE(chat_id, message_id)
        );
        CREATE TABLE IF NOT EXISTS bot_state(key TEXT PRIMARY KEY, value TEXT);
    """)
    return db


def list_entries(user_id, owner=False):
    with connect() as db:
        query = "SELECT id,user_id,display_name,role,received_at,kind,filename,text,origin,status FROM journal"
        args = ()
        if not owner:
            query += " WHERE user_id=?"
            args = (user_id,)
        return [dict(row) for row in db.execute(query + " ORDER BY id DESC LIMIT 200", args)]
