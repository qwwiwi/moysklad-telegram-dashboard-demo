"""User-scoped revocable supplier API credentials, stored as digests only."""
import hashlib
import re
import secrets
import sqlite3
import time
from contextlib import closing


def _open(path):
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS supplier_keys (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
        digest TEXT UNIQUE NOT NULL, prefix TEXT NOT NULL, created_at INTEGER NOT NULL,
        revoked_at INTEGER, last_used_at INTEGER)""")
    return db


def create(path, user_id, name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c) < 32 for c in name):
        raise ValueError("Provide a key name up to 80 characters")
    key = "tvn_" + secrets.token_urlsafe(32)
    created = int(time.time())
    prefix = key[:12]
    with closing(_open(path)) as db, db:
        row = db.execute("INSERT INTO supplier_keys(user_id,name,digest,prefix,created_at) VALUES(?,?,?,?,?)",
                         (user_id, name.strip(), hashlib.sha256(key.encode()).hexdigest(), prefix, created))
        return {"id": row.lastrowid, "name": name.strip(), "prefix": prefix,
                "created_at": created, "key": key}


def list_keys(path, user_id):
    with closing(_open(path)) as db:
        return [dict(row) for row in db.execute(
            "SELECT id,name,prefix,created_at,revoked_at,last_used_at FROM supplier_keys WHERE user_id=? ORDER BY id DESC", (user_id,))]


def revoke(path, user_id, key_id):
    if type(key_id) is not int or key_id <= 0:
        raise ValueError("Invalid key ID")
    with closing(_open(path)) as db, db:
        result = db.execute("UPDATE supplier_keys SET revoked_at=COALESCE(revoked_at,?) WHERE id=? AND user_id=?",
                            (int(time.time()), key_id, user_id))
        return bool(result.rowcount)


def authenticate(path, value):
    if not isinstance(value, str) or not re.fullmatch(r"tvn_[A-Za-z0-9_-]{43}", value):
        return None
    with closing(_open(path)) as db, db:
        row = db.execute("SELECT id,user_id,name FROM supplier_keys WHERE digest=? AND revoked_at IS NULL",
                         (hashlib.sha256(value.encode()).hexdigest(),)).fetchone()
        if row is None:
            return None
        db.execute("UPDATE supplier_keys SET last_used_at=? WHERE id=?", (int(time.time()), row["id"]))
        return dict(row)
