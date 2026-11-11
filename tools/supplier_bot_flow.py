"""Telegram messages for validated supplier imports and explicit name mappings."""
import json
import os
import re
from contextlib import closing

from intake_store import connect
from supplier_import import import_file


def _record(record_id):
    with closing(connect()) as db:
        return db.execute("SELECT id,user_id,filename,storage_path,kind FROM journal WHERE id=?", (record_id,)).fetchone()


def _save(record_id, result):
    with closing(connect()) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS import_results(journal_id INTEGER PRIMARY KEY,result TEXT NOT NULL)")
        old = db.execute("SELECT result FROM import_results WHERE journal_id=?", (record_id,)).fetchone()
        if old and json.loads(old[0]).get("status") == "posted":
            return
        db.execute("INSERT INTO import_results VALUES(?,?) ON CONFLICT(journal_id) DO UPDATE SET result=excluded.result",
                   (record_id, json.dumps(result, ensure_ascii=False)))
        db.execute("UPDATE journal SET status=? WHERE id=?", (result.get("status", "needs_review"), record_id))


def _money(value):
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def _notice(call, chat_id, record_id, result, uploader_id):
    if result.get("status") == "posted":
        totals = result.get("totals", {})
        text = (f"Запись №{record_id} проведена в МойСклад.\n"
                f"Товаров — {totals.get('quantity', 0)} шт.\n"
                f"Закупка — {_money(totals.get('purchase', 0))}\n"
                f"Продажи — {_money(totals.get('revenue', 0))}\n"
                f"Разница до комиссий, доставки и налогов — {_money(totals.get('gross', 0))}\n"
                "Созданы приёмки и отгрузки. Расчёты ожидают фактической оплаты.")
    else:
        errors = result.get("errors") or ["Не удалось завершить проведение. Проверьте документ и повторите после устранения причины."]
        text = f"Запись №{record_id} требует уточнения.\n" + "\n".join(str(error)[:350] for error in errors[:5])
        unmatched = result.get("unmatched", [])
        if unmatched:
            item = unmatched[0]
            name = str(item.get("raw_name", "Название товара"))[:300]
            suggestions = item.get("suggestions", [])
            if suggestions:
                text += "\nВарианты для проверки:\n" + "\n".join(
                    str(candidate.get("name", ""))[:180] + " — " + str(candidate.get("code", ""))[:100]
                    for candidate in suggestions[:3])
            text += f"\nПодтвердите соответствие сообщением:\nУточнить {record_id}: {name} = АРТИКУЛ"
        text += "\nМожно исправить исходный файл и загрузить его повторно."
    url = os.environ.get("PUBLIC_URL", "https://app.moyskladdemo.xyz/").rstrip("/") + "/#journal"
    markup = {"inline_keyboard": [[{"text": "Открыть журнал", "web_app": {"url": url}}]]}
    call("sendMessage", chat_id=chat_id, text=text[:4000], reply_markup=markup)
    if result.get("status") != "posted":
        try:
            alert_id = int(os.environ.get("ALERT_CHAT_ID", "164795011"))
        except ValueError:
            return
        if alert_id != chat_id:
            try:
                call("sendMessage", chat_id=alert_id,
                     text=f"Загрузка от Telegram ID {uploader_id}.\n" + text[:3800], reply_markup=markup)
            except Exception:
                # A blocked owner notification must not interrupt the user's result.
                pass


def _process(call, chat_id, row, mappings=None):
    record_id = row["id"]
    with closing(connect()) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS pending_mappings(journal_id INTEGER PRIMARY KEY, mappings TEXT NOT NULL)")
        saved = db.execute("SELECT mappings FROM pending_mappings WHERE journal_id=?", (record_id,)).fetchone()
        mappings = {**(json.loads(saved[0]) if saved else {}), **(mappings or {})}
        if mappings:
            db.execute("INSERT INTO pending_mappings VALUES(?,?) ON CONFLICT(journal_id) DO UPDATE SET mappings=excluded.mappings",
                       (record_id,json.dumps(mappings,ensure_ascii=False)))
    try:
        result = import_file(row["storage_path"], row["filename"], execute=True,
                             journal_id=record_id, supplier_id=str(row["user_id"]), mappings=mappings)
    except Exception:
        result = {"status": "needs_review", "errors": [
            "Сервис учёта временно недоступен или проведение требует проверки. Сохранённый файл остаётся в журнале."]}
    _save(record_id, result)
    _notice(call, chat_id, record_id, result, row["user_id"])
    return result


def process_submission(call, chat_id, record_id):
    """Post a committed journal file without holding an intake transaction."""
    row = _record(record_id)
    if row is None or row["kind"] != "file" or not row["storage_path"]:
        return None
    return _process(call, chat_id, row)


def clarify_submission(call, chat_id, user_id, text):
    """Handle only an explicit, authorized mapping command."""
    match = re.fullmatch(r"Уточнить\s+(\d+):\s*(.{1,2000}?)\s*=\s*([^\s=]{1,100})\s*", text, re.IGNORECASE)
    if not match:
        return False
    record_id = int(match[1])
    row = _record(record_id)
    owners = {int(value.strip()) for value in os.environ.get("OWNER_TELEGRAM_IDS", "").split(",") if value.strip().isdigit()}
    if row is None or row["kind"] != "file" or not row["storage_path"] or (user_id != row["user_id"] and user_id not in owners):
        call("sendMessage", chat_id=chat_id, text="Документ недоступен для уточнения.")
        return True
    _process(call, chat_id, row, {match[2].strip(): match[3].strip()})
    return True
