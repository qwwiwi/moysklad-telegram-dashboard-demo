"""Launch the public TOVARNO training dashboard from a private Telegram chat."""
import json
import os
import re
import sys
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class TelegramError(Exception):
    def __init__(self, code, retry_after=0):
        self.code = code
        self.retry_after = retry_after
        super().__init__(f"Telegram API status {code}")


def create_client(token):
    if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
        raise ValueError("Configure BOT_TOKEN.")

    def call(method, **fields):
        request = Request(
            f"https://api.telegram.org/bot{token}/{method}",
            data=json.dumps(fields).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=50) as response:
                body = json.load(response)
        except HTTPError as error:
            try:
                body = json.load(error)
            except (ValueError, OSError, HTTPException):
                body = {}
            raise TelegramError(error.code, body.get("parameters", {}).get("retry_after", 0)) from None
        except (URLError, OSError, HTTPException, ValueError):
            raise TelegramError(503) from None
        if not body.get("ok"):
            raise TelegramError(body.get("error_code", 503), body.get("parameters", {}).get("retry_after", 0))
        return body["result"]

    return call


def reply_to_start(call, update, username, app_url):
    message = update.get("message", {})
    chat = message.get("chat", {})
    words = message.get("text", "").split(maxsplit=1)
    if chat.get("type") != "private" or not words:
        return
    if words[0].lower() not in {"/start", f"/start@{username.lower()}"}:
        return
    button = {"text": "Открыть ТОВАРНО", "web_app": {"url": app_url}}
    call("sendMessage", chat_id=chat["id"],
         text="ТОВАРНО — учебная панель магазина. Откройте приложение, чтобы посмотреть остатки, финансы и план закупок.",
         reply_markup={"inline_keyboard": [[button]]})


def run(call, app_url):
    url = urlsplit(app_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("PUBLIC_URL must be a public HTTPS URL.")
    username = None
    offset = 0
    delay = 1
    while True:
        try:
            if username is None:
                identity = call("getMe")
                call("setChatMenuButton", menu_button={
                    "type": "web_app", "text": "ТОВАРНО", "web_app": {"url": app_url},
                })
                username = identity["username"]
                print(f"@{username} ready.", flush=True)
            updates = call("getUpdates", offset=offset, timeout=35, allowed_updates=["message"])
            for update in updates:
                try:
                    reply_to_start(call, update, username, app_url)
                except TelegramError as error:
                    if error.code != 403:  # A blocked chat should not stall the queue.
                        raise
                offset = update["update_id"] + 1
            delay = 1
        except TelegramError as error:
            if error.code != 429 and error.code < 500:
                raise
            print(f"{error}. Retrying.", file=sys.stderr, flush=True)
            time.sleep(max(delay, error.retry_after))
            delay = min(delay * 2, 60)


if __name__ == "__main__":
    try:
        run(create_client(os.environ.get("BOT_TOKEN", "")), os.environ.get("PUBLIC_URL", ""))
    except (TelegramError, ValueError) as error:
        sys.exit(str(error))
