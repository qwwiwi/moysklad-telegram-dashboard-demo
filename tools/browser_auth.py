"""One-time Telegram links and revocable browser sessions."""
import hashlib
import os
import re
import secrets
import sqlite3
import time
from contextlib import closing

LINK_SECONDS = 600
SESSION_SECONDS = 43200
COOKIE_NAME = "__Host-tovarno_session"


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        return None
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _open(db_path=None):
    path = db_path or os.environ.get("INTAKE_DB", "/var/lib/tovarno/intake.sqlite3")
    db = sqlite3.connect(path, timeout=10)
    db.execute("""CREATE TABLE IF NOT EXISTS browser_credentials (
        digest TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
        kind TEXT NOT NULL, expires INTEGER NOT NULL
    )""")
    return db


def _create(db, user_id, kind, lifetime):
    value = secrets.token_urlsafe(32)
    db.execute("INSERT INTO browser_credentials VALUES (?, ?, ?, ?)",
               (_digest(value), user_id, kind, int(time.time()) + lifetime))
    return value


def issue_link(user_id, db_path=None):
    """Return a raw token to deliver in the private user's Telegram chat."""
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("Invalid Telegram user ID")
    with closing(_open(db_path)) as db, db:
        db.execute("DELETE FROM browser_credentials WHERE expires <= ?", (int(time.time()),))
        return _create(db, user_id, "link", LINK_SECONDS)


def exchange(token, db_path):
    digest = _digest(token)
    if digest is None:
        return None
    with closing(_open(db_path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT user_id FROM browser_credentials WHERE digest=? AND kind='link' AND expires>?",
                         (digest, int(time.time()))).fetchone()
        if row is None:
            return None
        db.execute("DELETE FROM browser_credentials WHERE digest=?", (digest,))
        return _create(db, row[0], "session", SESSION_SECONDS)


def authenticate(value, db_path):
    digest = _digest(value)
    if digest is None:
        return None
    with closing(_open(db_path)) as db:
        row = db.execute("SELECT user_id FROM browser_credentials WHERE digest=? AND kind='session' AND expires>?",
                         (digest, int(time.time()))).fetchone()
        return row[0] if row else None


def logout(value, db_path):
    with closing(_open(db_path)) as db, db:
        db.execute("DELETE FROM browser_credentials WHERE digest=? AND kind='session'", (_digest(value),))
