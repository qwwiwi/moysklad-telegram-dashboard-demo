"""Private Telegram audio intake and local CPU transcription."""
import os
import threading
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from intake_store import connect

_MAX_BYTES = 5 * 1024 * 1024
_SLOTS = threading.BoundedSemaphore(4)
_MODEL_LOCK = threading.Lock()
_MODEL = None


def _transcribe(path):
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel
            _MODEL = WhisperModel(
                os.environ.get("WHISPER_MODEL_PATH", "/opt/tovarno/models/base"),
                device="cpu", compute_type="int8", cpu_threads=2, num_workers=1,
            )
        segments, _ = _MODEL.transcribe(str(path), language="ru", beam_size=3,
                                       vad_filter=True, condition_on_previous_text=False)
        return " ".join(segment.text.strip() for segment in segments).strip()[:20000]


def _notify(call, chat_id, text, app_url):
    call("sendMessage", chat_id=chat_id, text=text,
         reply_markup={"inline_keyboard": [[{"text": "Открыть журнал", "web_app": {
             "url": app_url.rstrip("/") + "/#journal"}}]]})


def _worker(call, chat_id, record_id, path, app_url):
    try:
        try:
            transcript = _transcribe(path)
            text = transcript or "Речь не распознана. Отправьте пояснение текстом или запишите сообщение ещё раз."
            status = "received" if transcript else "transcription_failed"
        except Exception:
            text = "Не удалось распознать речь. Аудио сохранено. Можно отправить пояснение текстом."
            status = "transcription_failed"
        with closing(connect()) as db, db:
            db.execute("UPDATE journal SET text=?,status=? WHERE id=?", (text, status, record_id))
        try:
            _notify(call, chat_id, f"Голосовое №{record_id}.\n" + text[:3500], app_url)
        except Exception:
            pass  # The completed transcript remains available in the journal.
    finally:
        _SLOTS.release()


def handle_voice(call, message, app_url):
    """Consume private voice/audio messages, preserving original audio and author."""
    media = message.get("voice") or message.get("audio")
    if not media:
        return False
    chat = message.get("chat", {})
    author = message.get("from", {})
    if chat.get("type") != "private" or not author.get("id"):
        return True
    chat_id, user_id = chat["id"], author["id"]
    duration, size = media.get("duration", 0), media.get("file_size", 0)
    if not isinstance(duration, (int, float)) or duration < 0 or duration > 120 or not isinstance(size, int) or size < 0 or size > _MAX_BYTES:
        call("sendMessage", chat_id=chat_id, text="Пришлите голосовое до 2 минут и 5 МБ.")
        return True
    with closing(connect()) as db:
        if db.execute("SELECT 1 FROM journal WHERE chat_id=? AND message_id=?", (chat_id, message["message_id"])).fetchone():
            return True
        profile = db.execute("SELECT role FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    if not profile:
        call("sendMessage", chat_id=chat_id, text="Сначала выберите роль поставщика или сотрудника, затем отправьте голосовое повторно.")
        return True
    if not _SLOTS.acquire(blocking=False):
        call("sendMessage", chat_id=chat_id, text="Сейчас обрабатываются другие голосовые. Отправьте сообщение немного позже.")
        return True
    queued = False
    path = None
    inserted = False
    try:
        extension = ".ogg" if message.get("voice") else ".mp3"
        folder = Path(os.environ.get("INTAKE_UPLOAD_DIR", "/var/lib/tovarno/uploads"))
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        from storage_limits import check_storage
        check_storage(folder, size or _MAX_BYTES, user_id)
        path = folder / (uuid.uuid4().hex + extension)
        info = call("getFile", file_id=media["file_id"])
        call.download(info["file_path"], path)
        if path.stat().st_size > _MAX_BYTES:
            raise ValueError("Audio limit exceeded")
        path.chmod(0o600)
        timestamp = datetime.now(timezone.utc)
        display_name = " ".join(filter(None, [author.get("first_name"), author.get("last_name")])) or author.get("username", str(user_id))
        filename = "Голосовое сообщение" + extension
        with closing(connect()) as db, db:
            existing = db.execute("SELECT id FROM journal WHERE chat_id=? AND message_id=?", (chat_id, message["message_id"])).fetchone()
            if existing:
                return True
            parent = None
            reply_id = message.get("reply_to_message", {}).get("message_id")
            if reply_id:
                parent = db.execute("SELECT id FROM journal WHERE user_id=? AND chat_id=? AND message_id=? AND kind='file'", (user_id, chat_id, reply_id)).fetchone()
            if parent is None:
                parent = db.execute("SELECT id FROM journal WHERE user_id=? AND kind='file' AND received_at>=? ORDER BY id DESC LIMIT 1", (user_id, (timestamp - timedelta(minutes=30)).isoformat())).fetchone()
            cursor = db.execute("""INSERT INTO journal(user_id,display_name,role,received_at,kind,filename,text,origin,status,message_id,chat_id,storage_path)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (user_id, display_name, profile["role"], timestamp.isoformat(), "voice", filename, "", "Голосовое в Telegram", "transcribing", message["message_id"], chat_id, str(path)))
            record_id = cursor.lastrowid
            inserted = True
            db.execute("CREATE TABLE IF NOT EXISTS journal_links(child_id INTEGER PRIMARY KEY,parent_id INTEGER NOT NULL)")
            if parent:
                db.execute("INSERT INTO journal_links VALUES(?,?)", (record_id, parent["id"]))
        try:
            suffix = f" Пояснение связано с документом №{parent['id']}." if parent else ""
            _notify(call, chat_id, f"Голосовое №{record_id} сохранено. Распознаём речь." + suffix, app_url)
        except Exception:
            pass
        thread = threading.Thread(target=_worker, args=(call, chat_id, record_id, path, app_url), daemon=True)
        thread.start()
        queued = True
    except Exception:
        if inserted:
            with closing(connect()) as db, db:
                db.execute("UPDATE journal SET status='transcription_failed',text=? WHERE chat_id=? AND message_id=?", ("Транскрибация не запущена. Аудио сохранено.", chat_id, message["message_id"]))
        call("sendMessage", chat_id=chat_id, text="Не удалось обработать голосовое. Повторите отправку или напишите пояснение текстом.")
    finally:
        if not queued:
            _SLOTS.release()
            if path and not inserted:
                path.unlink(missing_ok=True)
    return True
