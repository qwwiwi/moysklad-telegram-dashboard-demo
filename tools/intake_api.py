"""Authenticated, read-only Telegram intake journal endpoint."""
import hashlib
import hmac
import json
import os
import sqlite3
import time
import shutil
import uuid
from datetime import datetime, timezone
from contextlib import closing
from intake_store import connect
from http.cookies import SimpleCookie, CookieError
import browser_auth
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, unquote


class AuthenticationError(ValueError):
    pass


def verify_init_data(init_data, bot_token, now=None):
    """Validate the Telegram bot-token signature and return the numeric user ID."""
    if not isinstance(init_data, str) or not init_data or len(init_data) > 24000:
        raise AuthenticationError("Invalid Telegram session")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError("Duplicate fields")
        supplied_hash = fields.pop("hash")
        check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied_hash):
            raise ValueError("Invalid signature")
        timestamp = int(fields["auth_date"])
        current = time.time() if now is None else now
        if timestamp < current - 86400 or timestamp > current + 60:
            raise ValueError("Expired session")
        user = json.loads(fields["user"])
        user_id = user["id"]
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("Invalid user")
        return user_id
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise AuthenticationError("Invalid or expired Telegram session") from None


def read_journal(db_path, user_id, owner=False):
    """Select public journal fields, scoped to the authenticated submitter."""
    path = Path(db_path)
    if not path.is_file():
        return {"entries": [], "counts": {}, "scope": "all" if owner else "own"}
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        condition = "" if owner else " WHERE user_id = ?"
        parameters = () if owner else (user_id,)
        has_people = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='people'").fetchone()
        alias = "(SELECT name FROM people WHERE people.user_id=journal.user_id)" if has_people else "NULL"
        rows = connection.execute(
            "SELECT " + alias + " AS alias, id, user_id, display_name, role, received_at, kind, filename, "
            "substr(text, 1, 1000) AS text, origin, status FROM journal"
            + condition + " ORDER BY id DESC LIMIT 100", parameters,
        ).fetchall()
        counts = connection.execute(
            "SELECT status, count(*) AS count FROM journal" + condition + " GROUP BY status", parameters,
        ).fetchall()
        return {
            "entries": [dict(row) for row in rows],
            "counts": {row["status"]: row["count"] for row in counts},
            "scope": "all" if owner else "own",
        }
    finally:
        connection.close()


MAX_UPLOAD_BYTES = 100 * 1024 * 1024


class UploadError(ValueError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def upload_name(value):
    if not value or len(value) > 2048:
        raise UploadError(400, "Provide a file name")
    name = unquote(value, encoding="utf-8", errors="strict")
    if (len(name) > 240 or "/" in name or "\\" in name
            or any(ord(char) < 32 for char in name)
            or Path(name).suffix.lower() not in {".xlsx", ".csv"}):
        raise UploadError(400, "Use an XLSX or CSV file")
    return name


def receive_upload(stream, length, filename, user_id, folder):
    """Store one private stream and publish its journal record after completion."""
    if not 0 < length <= MAX_UPLOAD_BYTES:
        raise UploadError(413, "File limit is 100 MB")
    with closing(connect()) as db:
        profile = db.execute("SELECT role FROM profiles WHERE user_id=?", (user_id,)).fetchone()
        if profile is None or profile["role"] not in {"supplier", "employee"}:
            raise UploadError(400, "Select supplier or employee in the bot first")
        previous = db.execute(
            "SELECT display_name FROM journal WHERE user_id=? AND display_name IS NOT NULL ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if shutil.disk_usage(folder).free < length + MAX_UPLOAD_BYTES:
        raise UploadError(507, "Storage temporarily full")
    target = folder / (uuid.uuid4().hex + Path(filename).suffix.lower())
    published = False
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as destination:
            remaining = length
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    raise UploadError(400, "Upload interrupted")
                destination.write(chunk)
                remaining -= len(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        with closing(connect()) as db, db:
            record = db.execute(
                "INSERT INTO journal(user_id,display_name,role,received_at,kind,filename,text,origin,status,storage_path) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (user_id, previous["display_name"] if previous else "Telegram " + str(user_id),
                 profile["role"], datetime.now(timezone.utc).isoformat(), "file", filename, "",
                 "Загрузка через сайт", "received", str(target)),
            )
            record_id = record.lastrowid
        published = True
        return {"id": record_id, "filename": filename, "status": "received", "size": length}
    finally:
        if not published:
            target.unlink(missing_ok=True)


class JournalHandler(BaseHTTPRequestHandler):
    server_version = "TovarnoJournal"
    sys_version = ""

    def log_message(self, format, *args):
        # Request bodies, Telegram initData and credential-bearing values stay private.
        return

    def respond(self, status, payload, cookie=None):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie is not None:
            age = browser_auth.SESSION_SECONDS if cookie else 0
            self.send_header("Set-Cookie", f"{browser_auth.COOKIE_NAME}={cookie}; Path=/; Max-Age={age}; Secure; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body)

    def upload(self):
        self.close_connection = True
        origin = self.headers.get("Origin")
        if origin != self.server.public_origin or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.respond(403, {"error": "Invalid origin"})
            return
        try:
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            session = cookies.get(browser_auth.COOKIE_NAME)
            user_id = browser_auth.authenticate(session.value if session else None, self.server.db_path)
            if user_id is None:
                raise AuthenticationError()
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise UploadError(411, "Content-Length required")
            length = int(self.headers["Content-Length"])
            if not 0 < length <= MAX_UPLOAD_BYTES:
                raise UploadError(413, "File limit is 100 MB")
            if self.headers.get_content_type() != "application/octet-stream":
                raise UploadError(415, "Use application/octet-stream")
            filename = upload_name(self.headers.get("X-File-Name"))
            self.connection.settimeout(90)
            result = receive_upload(self.rfile, length, filename, user_id,
                                    os.environ.get("INTAKE_UPLOAD_DIR", "/var/lib/tovarno/uploads"))
            self.respond(201, result)
        except AuthenticationError:
            self.respond(401, {"error": "Sign in through the bot"})
        except UploadError as error:
            self.respond(error.status, {"error": str(error)})
        except (ValueError, TypeError, UnicodeError, CookieError):
            self.respond(400, {"error": "Invalid upload"})
        except (sqlite3.Error, OSError):
            self.respond(503, {"error": "Upload temporarily unavailable"})

    def do_POST(self):
        if self.path == "/api/upload":
            self.upload()
            return
        if self.path not in {"/api/journal", "/api/login", "/api/session", "/api/logout", "/api/people"}:
            self.respond(404, {"error": "Not found"})
            return
        try:
            if self.headers.get_content_type() != "application/json":
                self.respond(415, {"error": "Use application/json"})
                return
            origin = self.headers.get("Origin")
            if (origin and origin != self.server.public_origin) or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.respond(403, {"error": "Invalid origin"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 32768:
                self.respond(413, {"error": "Invalid request size"})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Invalid payload")
            db_path = self.server.db_path
            if self.path == "/api/login":
                value = browser_auth.exchange(payload.get("token"), db_path)
                if value is None:
                    raise AuthenticationError("Expired link")
                self.respond(200, {"authenticated": True}, cookie=value)
                return
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            session = cookies.get(browser_auth.COOKIE_NAME)
            value = session.value if session else None
            if self.path == "/api/logout":
                browser_auth.logout(value, db_path)
                self.respond(200, {"authenticated": False}, cookie="")
                return
            user_id = (verify_init_data(payload["initData"], self.server.bot_token)
                       if payload.get("initData") else browser_auth.authenticate(value, db_path))
            if self.path == "/api/session":
                self.respond(200, {"authenticated": user_id is not None})
                return
            if user_id is None:
                raise AuthenticationError("Invalid session")
            if self.path == "/api/people":
                if user_id not in self.server.owner_ids:
                    self.respond(403, {"error": "Owner access required"})
                    return
                person_id = payload.get("user_id")
                name = payload.get("name")
                if (type(person_id) is not int or person_id <= 0 or not isinstance(name, str)
                        or not 1 <= len(name.strip()) <= 120 or any(ord(c) < 32 for c in name)):
                    raise ValueError("Invalid person")
                with closing(connect()) as db, db:
                    db.execute("CREATE TABLE IF NOT EXISTS people(user_id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
                    if not db.execute("SELECT 1 FROM journal WHERE user_id=? LIMIT 1", (person_id,)).fetchone():
                        self.respond(404, {"error": "Author not found"})
                        return
                    db.execute("INSERT INTO people VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name",
                               (person_id, name.strip()))
                self.respond(200, {"user_id": person_id, "name": name.strip()})
                return
            result = read_journal(self.server.db_path, user_id, user_id in self.server.owner_ids)
            self.respond(200, result)
        except AuthenticationError:
            self.respond(401, {"error": "Open the journal from Telegram"})
        except (ValueError, TypeError, UnicodeError, CookieError):
            self.respond(400, {"error": "Invalid request"})
        except (sqlite3.Error, OSError):
            self.respond(503, {"error": "Journal temporarily unavailable"})

    def do_GET(self):
        self.respond(405, {"error": "Use POST"})


def main():
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Configure BOT_TOKEN")
    try:
        owners = {int(value.strip()) for value in os.environ.get("OWNER_TELEGRAM_IDS", "").split(",") if value.strip()}
    except ValueError:
        raise SystemExit("OWNER_TELEGRAM_IDS must contain numeric IDs") from None
    server = ThreadingHTTPServer(("127.0.0.1", 8766), JournalHandler)
    server.public_origin = os.environ.get("PUBLIC_URL", "https://app.moyskladdemo.xyz").rstrip("/")
    server.bot_token = token
    server.db_path = os.environ.get("INTAKE_DB", "/var/lib/tovarno/intake.sqlite3")
    server.owner_ids = owners
    server.serve_forever()


if __name__ == "__main__":
    main()
