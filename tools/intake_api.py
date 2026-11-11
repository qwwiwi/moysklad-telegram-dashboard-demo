"""Authenticated, read-only Telegram intake journal endpoint."""
import hashlib
import hmac
import json
import os
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl


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
        rows = connection.execute(
            "SELECT id, user_id, display_name, role, received_at, kind, filename, "
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


class JournalHandler(BaseHTTPRequestHandler):
    server_version = "TovarnoJournal"
    sys_version = ""

    def log_message(self, format, *args):
        # Request bodies, Telegram initData and credential-bearing values stay private.
        return

    def respond(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/journal":
            self.respond(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 32768:
                self.respond(413, {"error": "Invalid request size"})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Invalid payload")
            user_id = verify_init_data(payload.get("initData"), self.server.bot_token)
            result = read_journal(self.server.db_path, user_id, user_id in self.server.owner_ids)
            self.respond(200, result)
        except AuthenticationError:
            self.respond(401, {"error": "Open the journal from Telegram"})
        except (ValueError, TypeError, UnicodeError):
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
    server.bot_token = token
    server.db_path = os.environ.get("INTAKE_DB", "/var/lib/tovarno/intake.sqlite3")
    server.owner_ids = owners
    server.serve_forever()


if __name__ == "__main__":
    main()
