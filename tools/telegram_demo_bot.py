"""Launch the public TOVARNO training dashboard from a private Telegram chat."""
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
from intake_store import connect
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

    def download(file_path, destination):
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", file_path) or ".." in file_path:
            raise ValueError("Invalid Telegram file path.")
        try:
            request = Request(f"https://api.telegram.org/file/bot{token}/{file_path}")
            with urlopen(request, timeout=50) as response:
                data = response.read(5 * 1024 * 1024 + 1)
            if len(data) > 5 * 1024 * 1024:
                raise ValueError("File exceeds upload limit.")
            destination.write_bytes(data)
            destination.chmod(0o600)
        except (URLError, OSError, HTTPException):
            raise TelegramError(503) from None
    call.download = download
    return call


def main_buttons(app_url):
    return {"inline_keyboard": [
        [{"text": "Открыть ТОВАРНО", "style": "success", "web_app": {"url": app_url}}],
        [{"text": "Вход по ссылке", "callback_data": "browser_login"}],
        [{"text": "API для вашего агента", "web_app": {"url": app_url.rstrip("/") + "/#api"}}],
        [{"text": "Загрузить документы", "callback_data": "upload"}],
        [{"text": "Открыть журнал", "web_app": {"url": app_url + "#journal"}}],
        [{"text": "Как работать с ТОВАРНО", "url": "https://docs.moyskladdemo.xyz/"}],
    ]}


def role_buttons():
    return {"inline_keyboard": [
        [{"text": "Я поставщик", "callback_data": "supplier"},
         {"text": "Я сотрудник", "callback_data": "employee"}],
        [{"text": "Главное меню", "callback_data": "home"}],
    ]}


def reply_to_start(call, update, username, app_url):
    """Handle private messages, retaining the old entrypoint name for callers."""
    callback = update.get("callback_query")
    if callback:
        call("answerCallbackQuery", callback_query_id=callback["id"])
        action = callback.get("data")
        if action in {"browser_login", "web_upload"}:
            message = callback.get("message", {})
            chat = message.get("chat", {})
            user_id = callback.get("from", {}).get("id")
            if chat.get("type") == "private" and chat.get("id") == user_id and user_id:
                from browser_auth import issue_link
                url = app_url.rstrip("/") + ("/?next=upload#login=" if action=="web_upload" else "/#login=") + issue_link(user_id)
                call("sendMessage", chat_id=user_id, protect_content=True,
                     text="Войдите в личный кабинет. Чтобы открыть его на компьютере, скопируйте ссылку в свой браузер. Она действует 10 минут и подходит для одного входа.",
                     reply_markup={"inline_keyboard": [
                         [{"text": "Открыть личный кабинет", "style": "success", "url": url}],
                         [{"text": "Скопировать ссылку", "copy_text": {"text": url}}],
                     ]})
            return
        command = {"upload": "Загрузить документы", "supplier": "Я поставщик",
                   "employee": "Я сотрудник", "home": "/menu"}.get(action)
        if not command:
            return
        update = {"message": {**callback.get("message", {}),
                              "from": callback["from"], "text": command}}
    message = update.get("message", {})
    chat = message.get("chat", {})
    author = message.get("from", {})
    if chat.get("type") != "private" or not author.get("id"):
        return
    from voice_notes import handle_voice
    if handle_voice(call, message, app_url):
        return
    text = message.get("text", "").strip()
    chat_id = chat["id"]
    def say(body, markup=None):
        call("sendMessage", chat_id=chat_id, text=body,
             **({"reply_markup": markup} if markup else {}))
    if text == "Старт" or text.split(maxsplit=1)[:1] in [["/start"], [f"/start@{username}"], ["/menu"]]:
        if not callback:
            call("sendMessage", chat_id=chat_id, text="ТОВАРНО — товары, финансы и документы.",
                 reply_markup={"keyboard": [[{"text": "Старт"}]], "resize_keyboard": True, "is_persistent": True})
        call("sendPhoto", chat_id=chat_id,
             photo=app_url.rstrip("/") + "/assets/tovarno-iphone-1080.jpg",
             caption="Ваш личный кабинет ТОВАРНО. Откройте панель, загрузите документы или посмотрите историю отправок.",
             reply_markup=main_buttons(app_url))
        return
    from supplier_bot_flow import clarify_submission
    if clarify_submission(call, chat_id, author["id"], text):
        return
    if text == "Загрузить документы":
        say("Кто отправляет документы?", role_buttons())
        return
    roles = {"Я поставщик": "supplier", "Я сотрудник": "employee"}
    with connect() as db:
        if text in roles:
            db.execute("INSERT INTO profiles VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET role=excluded.role", (author["id"], roles[text]))
            db.commit()
            role_label = {"supplier": "Поставщик", "employee": "Сотрудник"}[roles[text]]
            call("sendPhoto", chat_id=chat_id, photo=app_url.rstrip("/") + "/assets/tovarno-upload.jpg",
                 reply_markup={"inline_keyboard":[[{"text":"Загрузить большой файл на сайте","callback_data":"web_upload"}]]},
                 caption=f"Ваша роль — {role_label}. Прикрепите Excel (.xlsx) или CSV до 5 МБ. Можно написать об отгрузке текстом или переслать сообщение из рабочего чата. После приёма бот сообщит номер записи в журнале.")
            return
        profile = db.execute("SELECT role FROM profiles WHERE user_id=?", (author["id"],)).fetchone()
        if text in {"Загрузить файл", "Написать отгрузку"}:
            say("Прикрепите документ .xlsx или .csv до 5 МБ, либо перешлите файл из рабочего чата." if text == "Загрузить файл" else "Напишите дату отгрузки, номер заказа, артикул, количество и сумму. Можно переслать сообщение из рабочего чата.")
            return
        if not profile:
            say("Выберите роль, затем повторно отправьте документ или сообщение.", role_buttons())
            return
        if db.execute("SELECT id FROM journal WHERE chat_id=? AND message_id=?", (chat_id, message["message_id"])).fetchone():
            return
        document = message.get("document")
        path = None
        filename = ""
        kind = "text"
        if document:
            filename = Path(document.get("file_name", "file")).name
            extension = Path(filename).suffix.lower()
            if extension not in {".xlsx", ".csv"} or document.get("file_size", 0) > 5 * 1024 * 1024:
                say("Пришлите .xlsx или .csv до 5 МБ.")
                return
            folder = Path(os.environ.get("INTAKE_UPLOAD_DIR", "/var/lib/tovarno/uploads"))
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = folder / (uuid.uuid4().hex + extension)
            info = call("getFile", file_id=document["file_id"])
            try:
                call.download(info["file_path"], path)
            except ValueError:
                say("Файл превышает лимит 5 МБ или его адрес недоступен.")
                return
            text = message.get("caption", "")
            kind = "file"
        elif not text or text.startswith("/"):
            say("Отправьте текст отгрузки или документ .xlsx/.csv.")
            return
        origin = "Прямое сообщение"
        forwarded = message.get("forward_origin")
        if forwarded:
            origin = "Переслано"
            source = forwarded.get("chat", {})
            sender = forwarded.get("sender_user", {})
            label = source.get("title") or forwarded.get("sender_user_name") or " ".join(filter(None, [sender.get("first_name"), sender.get("last_name")]))
            if label:
                origin += " · " + label
        name = " ".join(filter(None, [author.get("first_name"), author.get("last_name")])) or author.get("username", str(author["id"]))
        cursor = db.execute("""INSERT INTO journal(user_id,display_name,role,received_at,kind,filename,text,origin,message_id,chat_id,storage_path)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (author["id"], name, profile["role"], datetime.now(timezone.utc).isoformat(), kind, filename, text, origin, message["message_id"], chat_id, str(path) if path else None))
        record_id = cursor.lastrowid
    say(f"Получено. Запись №{record_id} сохранена в журнале со статусом «Получено». Данные ожидают проверки перед внесением в учёт.",
        {"inline_keyboard": [[{"text": "Открыть журнал", "web_app": {"url": app_url + "#journal"}}]]})
    if kind == "file":
        from supplier_bot_flow import process_submission
        process_submission(call, chat_id, record_id)


def run(call, app_url):
    url = urlsplit(app_url)
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("PUBLIC_URL must be a public HTTPS URL.")
    username = None
    with connect() as db:
        saved = db.execute("SELECT value FROM bot_state WHERE key='offset'").fetchone()
    offset = int(saved[0]) if saved else 0
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
            updates = call("getUpdates", offset=offset, timeout=35, allowed_updates=["message", "callback_query"])
            for update in updates:
                try:
                    reply_to_start(call, update, username, app_url)
                except TelegramError as error:
                    if error.code != 403:  # A blocked chat should not stall the queue.
                        raise
                offset = update["update_id"] + 1
                with connect() as db:
                    db.execute("INSERT INTO bot_state VALUES('offset',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(offset),))
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
