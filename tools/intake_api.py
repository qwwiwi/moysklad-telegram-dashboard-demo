from access_control import is_allowed
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
import supplier_keys
import fcntl
import re
import threading
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


def receive_upload(stream, length, filename, user_id, folder, expected_hash=None, idempotency=None, origin="Загрузка через сайт"):
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
    from storage_limits import check_storage
    try:
        check_storage(folder, length, user_id)
    except ValueError:
        raise UploadError(507, "Workspace storage quota reached") from None
    if shutil.disk_usage(folder).free < length + 1024**3:
        raise UploadError(507, "Storage temporarily full")
    target = folder / (uuid.uuid4().hex + Path(filename).suffix.lower())
    published = False
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as destination:
            remaining = length
            content_hash = hashlib.sha256()
            while remaining:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    raise UploadError(400, "Upload interrupted")
                destination.write(chunk)
                content_hash.update(chunk)
                remaining -= len(chunk)
            if expected_hash and not hmac.compare_digest(content_hash.hexdigest(), expected_hash):
                raise UploadError(422, "Content checksum mismatch")
            destination.flush()
            os.fsync(destination.fileno())
        with closing(connect()) as db, db:
            record = db.execute(
                "INSERT INTO journal(user_id,display_name,role,received_at,kind,filename,text,origin,status,storage_path) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (user_id, previous["display_name"] if previous else "Telegram " + str(user_id),
                 profile["role"], datetime.now(timezone.utc).isoformat(), "file", filename, "",
                 origin, "received", str(target)),
            )
            record_id = record.lastrowid
            if idempotency:
                db.execute("INSERT INTO supplier_requests(user_id,request_key,content_hash,filename,size,journal_id) VALUES(?,?,?,?,?,?)",
                           (user_id,idempotency,expected_hash,filename,length,record_id))
        published = True
        return {"id": record_id, "filename": filename, "status": "received", "size": length}
    finally:
        if not published:
            target.unlink(missing_ok=True)


_PREVIEW_SLOTS = threading.BoundedSemaphore(2)
_IMPORT_SLOTS = threading.BoundedSemaphore(4)


class BoundedHTTPServer(ThreadingHTTPServer):
    """Bound concurrent requests, including slow headers and incomplete bodies."""
    def __init__(self, *args, **kwargs):
        self.request_slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.request_slots.acquire(blocking=False):
            try:
                request.settimeout(2)
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\nRetry-After: 5\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.request_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.request_slots.release()


class JournalHandler(BaseHTTPRequestHandler):
    server_version = "TovarnoJournal"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

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
            if not is_allowed(user_id):
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
            self.process_supplier_document(user_id, result["id"])
        except AuthenticationError:
            self.respond(401, {"error": "Sign in through the bot"})
        except UploadError as error:
            self.respond(error.status, {"error": str(error)})
        except (ValueError, TypeError, UnicodeError, CookieError):
            self.respond(400, {"error": "Invalid upload"})
        except (sqlite3.Error, OSError):
            self.respond(503, {"error": "Upload temporarily unavailable"})

    def supplier_identity(self):
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise AuthenticationError("API key required")
        identity = supplier_keys.authenticate(self.server.db_path, authorization[7:])
        if identity is None or not is_allowed(identity["user_id"]):
            raise AuthenticationError("Invalid API key")
        return identity

    def process_supplier_document(self, user_id, record_id):
        if not _IMPORT_SLOTS.acquire(blocking=False):
            with sqlite3.connect(self.server.db_path) as db:
                db.execute("UPDATE journal SET status='needs_review',text=? WHERE id=? AND status='received'",
                           ("Обработка занята. Проверьте документ и запустите проведение из журнала.", record_id))
            return

        def process():
            try:
                from supplier_bot_flow import process_submission
                from telegram_demo_bot import create_client
                process_submission(create_client(self.server.bot_token), user_id, record_id)
            finally:
                _IMPORT_SLOTS.release()

        try:
            threading.Thread(target=process, daemon=True).start()
        except RuntimeError:
            _IMPORT_SLOTS.release()
            with sqlite3.connect(self.server.db_path) as db:
                db.execute("UPDATE journal SET status='needs_review' WHERE id=? AND status='received'", (record_id,))

    def supplier_upload(self):
        self.close_connection = True
        try:
            identity = self.supplier_identity()
            origin = self.headers.get("Origin")
            if (origin and origin != self.server.public_origin) or self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise UploadError(403, "Invalid origin")
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise UploadError(411, "Content-Length required")
            length = int(self.headers["Content-Length"])
            if not 0 < length <= MAX_UPLOAD_BYTES:
                raise UploadError(413, "File limit is 100 MB")
            if self.headers.get_content_type() != "application/octet-stream":
                raise UploadError(415, "Use application/octet-stream")
            filename = upload_name(self.headers.get("X-File-Name"))
            request_key = self.headers.get("Idempotency-Key", "")
            digest = self.headers.get("X-Content-SHA256", "")
            if not re.fullmatch(r"[\x21-\x7e]{1,100}", request_key) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                raise UploadError(400, "Provide Idempotency-Key and X-Content-SHA256")
            user_id = identity["user_id"]
            folder = Path(os.environ.get("INTAKE_UPLOAD_DIR", "/var/lib/tovarno/uploads"))
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock_name = hashlib.sha256((str(user_id)+":"+request_key).encode()).hexdigest()
            self.connection.settimeout(90)
            with (folder / (".api-"+lock_name+".lock")).open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with closing(connect()) as db, db:
                    db.execute("""CREATE TABLE IF NOT EXISTS supplier_requests(
                        user_id INTEGER NOT NULL, request_key TEXT NOT NULL,
                        content_hash TEXT NOT NULL, filename TEXT NOT NULL,
                        size INTEGER NOT NULL, journal_id INTEGER NOT NULL,
                        PRIMARY KEY(user_id,request_key))""")
                    previous = db.execute("SELECT * FROM supplier_requests WHERE user_id=? AND request_key=?",
                                          (user_id, request_key)).fetchone()
                if previous:
                    if previous["content_hash"] != digest or previous["filename"] != filename or previous["size"] != length:
                        raise UploadError(409, "Idempotency key already used for a different document")
                    self.respond(200, {"id":previous["journal_id"],"filename":filename,
                                       "status":"received","size":length,"reused":True})
                    return
                result = receive_upload(self.rfile, length, filename, user_id, folder,
                                        expected_hash=digest, idempotency=request_key,
                                        origin="API · "+identity["name"])
            self.respond(201, result)
            self.process_supplier_document(user_id,result["id"])
        except AuthenticationError:
            self.respond(401, {"error":"Invalid API key"})
        except UploadError as error:
            self.respond(error.status,{"error":str(error)})
        except (ValueError,TypeError,UnicodeError):
            self.respond(400,{"error":"Invalid upload"})
        except (sqlite3.Error,OSError):
            self.respond(503,{"error":"Upload temporarily unavailable"})

    def supplier_get(self):
        try:
            identity = self.supplier_identity()
            user_id = identity["user_id"]
            if self.path == "/api/v1/documents":
                self.respond(200,read_journal(self.server.db_path,user_id,False))
                return
            match = re.fullmatch(r"/api/v1/documents/([1-9][0-9]*)",self.path)
            if not match:
                self.respond(404,{"error":"Not found"})
                return
            with sqlite3.connect(self.server.db_path) as db:
                db.row_factory = sqlite3.Row
                row = db.execute("SELECT id,user_id,display_name,role,received_at,kind,filename,text,origin,status FROM journal WHERE id=? AND user_id=?",
                                 (int(match[1]),user_id)).fetchone()
                if row is None:
                    self.respond(404,{"error":"Document not found"})
                    return
                processing = None
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='import_results'").fetchone():
                    result = db.execute("SELECT result FROM import_results WHERE journal_id=?",(row["id"],)).fetchone()
                    if result:
                        processing = json.loads(result[0])
            self.respond(200,{"document":dict(row),"processing":processing})
        except AuthenticationError:
            self.respond(401,{"error":"Invalid API key"})
        except (sqlite3.Error,OSError,ValueError):
            self.respond(503,{"error":"Documents temporarily unavailable"})

    def do_POST(self):
        if self.path == "/api/v1/documents":
            self.supplier_upload()
            return
        if self.path == "/api/upload":
            self.upload()
            return
        if self.path not in {"/api/journal", "/api/login", "/api/session", "/api/logout", "/api/people", "/api/file/preview", "/api/file/download", "/api/import/preview", "/api/import/execute", "/api/import/status", "/api/keys/list", "/api/keys/create", "/api/keys/revoke"}:
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
                self.respond(200, {"authenticated": is_allowed(user_id)})
                return
            if not is_allowed(user_id):
                raise AuthenticationError("Invalid session")
            if self.path.startswith("/api/keys/"):
                if self.path.endswith("/list"):
                    self.respond(200, {"keys": supplier_keys.list_keys(db_path,user_id)})
                elif self.path.endswith("/create"):
                    self.respond(201, supplier_keys.create(db_path,user_id,payload.get("name")))
                else:
                    if not supplier_keys.revoke(db_path,user_id,payload.get("id")):
                        self.respond(404, {"error":"Key not found"})
                        return
                    self.respond(200, {"revoked":True})
                return
            if self.path.startswith("/api/import/"):
                if user_id not in self.server.owner_ids:
                    self.respond(403, {"error": "Owner access required"})
                    return
                with sqlite3.connect(db_path) as db:
                    db.execute("CREATE TABLE IF NOT EXISTS import_results(journal_id INTEGER PRIMARY KEY,result TEXT NOT NULL)")
                    if self.path.endswith("/status"):
                        values = [json.loads(r[0]) for r in db.execute("SELECT result FROM import_results ORDER BY journal_id DESC")]
                        self.respond(200, {"imports": values})
                        return
                    record_id = payload.get("id")
                    if type(record_id) is not int:
                        raise ValueError("Invalid record")
                    row = db.execute("SELECT filename,storage_path,user_id FROM journal WHERE id=? AND kind IN ('file','voice')", (record_id,)).fetchone()
                if row is None:
                    self.respond(404, {"error": "File not found"})
                    return
                path = Path(row[1]).resolve()
                folder = Path(os.environ.get("INTAKE_UPLOAD_DIR", "/var/lib/tovarno/uploads")).resolve()
                if not path.is_relative_to(folder) or not path.is_file():
                    raise ValueError("Invalid file")
                from supplier_import import import_file
                from seed_moysklad import SeedError
                try:
                    result = import_file(path, row[0], execute=self.path.endswith("/execute"),
                                         journal_id=record_id, supplier_id=str(row[2]),
                                         mappings=payload.get("mappings"))
                except SeedError as error:
                    self.respond(200, {"status":"needs_review","errors":[str(error)],"rows":[]})
                    return
                if self.path.endswith("/execute") and result.get("status") == "posted":
                    with sqlite3.connect(db_path) as db:
                        db.execute("INSERT INTO import_results VALUES(?,?) ON CONFLICT(journal_id) DO UPDATE SET result=excluded.result",
                                   (record_id, json.dumps(result,ensure_ascii=False)))
                        db.execute("UPDATE journal SET status='posted' WHERE id=?", (record_id,))
                self.respond(200, result)
                return
            if self.path in {"/api/file/preview", "/api/file/download"}:
                record_id = payload.get("id")
                if type(record_id) is not int or record_id <= 0:
                    raise ValueError("Invalid file")
                with sqlite3.connect(db_path) as db:
                    row = db.execute("SELECT user_id,filename,storage_path FROM journal WHERE id=? AND kind IN ('file','voice')", (record_id,)).fetchone()
                if row is None or (row[0] != user_id and user_id not in self.server.owner_ids):
                    self.respond(404, {"error": "File not found"})
                    return
                path = Path(row[2]).resolve()
                folder = Path(os.environ.get("INTAKE_UPLOAD_DIR", "/var/lib/tovarno/uploads")).resolve()
                if not path.is_relative_to(folder) or not path.is_file():
                    self.respond(404, {"error": "File unavailable"})
                    return
                if self.path.endswith("/preview"):
                    if path.suffix.lower() in {".ogg",".mp3",".m4a",".wav"}:
                        self.respond(200, {"summary":"Голосовое пояснение. Расшифровка отображается в журнале.","columns":[],"rows":[],"size":path.stat().st_size})
                        return
                    if not _PREVIEW_SLOTS.acquire(blocking=False):
                        self.respond(429, {"error": "Preview busy. Retry shortly"})
                        return
                    try:
                        from document_preview import summarize
                        result = summarize(path, row[1])
                        result["size"] = path.stat().st_size
                    finally:
                        _PREVIEW_SLOTS.release()
                    self.respond(200, result)
                else:
                    from urllib.parse import quote
                    with path.open("rb") as source:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(path.stat().st_size))
                        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(row[1], safe=""))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.end_headers()
                        shutil.copyfileobj(source, self.wfile, 65536)
                return
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
            with sqlite3.connect(db_path) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal_links'").fetchone():
                    links=dict(db.execute("SELECT child_id,parent_id FROM journal_links"))
                    for entry in result["entries"]:
                        entry["parent_record_id"]=links.get(entry["id"])

            self.respond(200, result)
        except AuthenticationError:
            self.respond(401, {"error": "Open the journal from Telegram"})
        except (ValueError, TypeError, UnicodeError, CookieError):
            self.respond(400, {"error": "Invalid request"})
        except (sqlite3.Error, OSError):
            self.respond(503, {"error": "Journal temporarily unavailable"})

    def do_GET(self):
        if self.path.startswith("/api/v1/"):
            self.supplier_get()
            return
        self.respond(405, {"error": "Use POST"})


def main():
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Configure BOT_TOKEN")
    try:
        owners = {int(value.strip()) for value in os.environ.get("OWNER_TELEGRAM_IDS", "").split(",") if value.strip()}
    except ValueError:
        raise SystemExit("OWNER_TELEGRAM_IDS must contain numeric IDs") from None
    server = BoundedHTTPServer(("127.0.0.1", 8766), JournalHandler)
    server.public_origin = os.environ.get("PUBLIC_URL", "https://app.moyskladdemo.xyz").rstrip("/")
    server.bot_token = token
    server.db_path = os.environ.get("INTAKE_DB", "/var/lib/tovarno/intake.sqlite3")
    server.owner_ids = owners
    server.serve_forever()


if __name__ == "__main__":
    main()
