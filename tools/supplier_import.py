"""Validated, resumable direct-supplier receipt and sale import."""
import difflib
import fcntl
import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from document_preview import summarize
from seed_moysklad import Client, Seeder, SeedError, load_token, meta_ref, NAMESPACE

HEADERS = ["Дата", "Заказ", "Площадка", "Артикул", "Наименование", "Количество",
           "Закупка ₽/шт", "Продажа ₽/шт"]


def normalized(value):
    return " ".join(str(value).strip().casefold().split())


def _money(value):
    amount = Decimal(str(value).replace(" ", "").replace(",", "."))
    if not amount.is_finite() or amount < 0 or amount > 10000000 or amount * 100 != (amount * 100).to_integral():
        raise ValueError()
    return int(amount * 100)


def _client():
    token = os.environ.get("MOYSKLAD_API_TOKEN")
    return Client(token or load_token(Path("/etc/tovarno/moysklad.env")))


HEADER_ALIASES = [
    {"дата", "дата отгрузки", "date"}, {"заказ", "номер заказа", "order"},
    {"площадка", "маркетплейс", "marketplace"}, {"артикул", "sku", "код товара"},
    {"наименование", "товар", "наименование товара", "name"},
    {"количество", "кол-во", "кол во", "qty"},
    {"закупка ₽/шт", "закупочная цена", "закупка", "цена закупки"},
    {"продажа ₽/шт", "цена продажи", "продажа", "розничная цена"},
]


def _saved_mappings(supplier_id):
    db_path = os.environ.get("INTAKE_DB", "/var/lib/tovarno/intake.sqlite3")
    if supplier_id is None or not Path(db_path).is_file():
        return {}
    with sqlite3.connect(db_path) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='supplier_aliases'").fetchone():
            return {}
        return dict(db.execute("SELECT raw_name,code FROM supplier_aliases WHERE supplier_id=?", (str(supplier_id),)))


def prepare(path, filename, client, mappings=None):
    table = summarize(path, filename)
    errors = []
    if table.get("truncated") or not table.get("rows") or len(table["rows"]) > 20:
        return {"status": "needs_review", "errors": ["Импорт поддерживает полностью прочитанную таблицу до 20 строк."], "rows": []}
    columns = [normalized(column) for column in table["columns"]]
    indexes = [[i for i, column in enumerate(columns) if column in aliases] for aliases in HEADER_ALIASES]
    if any(len(index) != 1 for index in indexes):
        return {"status": "needs_review", "errors": ["Неоднозначные или пропущенные колонки. Используйте шаблон: " + ", ".join(HEADERS)], "rows": []}
    mappings = {normalized(k): str(v).strip() for k, v in (mappings or {}).items()}
    unmatched = []
    products = client.get_all("entity/product")
    rows = []
    for index, values in enumerate(table["rows"], 2):
        date, order, platform, article, name, qty, purchase, sale = [values[index[0]] for index in indexes]
        issues = []
        try:
            parsed_date = datetime.strptime(str(date), "%Y-%m-%d")
            if parsed_date.strftime("%Y-%m-%d") != date:
                raise ValueError()
            quantity = Decimal(str(qty))
            if not quantity.is_finite() or quantity <= 0 or quantity > 10000 or quantity != quantity.to_integral():
                raise ValueError()
            purchase_minor, sale_minor = _money(purchase), _money(sale)
            if purchase_minor == 0 or sale_minor == 0:
                raise ValueError()
        except (ValueError, InvalidOperation):
            issues.append("Проверьте дату, целое количество и положительные цены с точностью до копейки.")
        if not order or len(str(order)) > 100 or not platform or len(str(platform)) > 80:
            issues.append("Не указаны корректные номер заказа и площадка.")
        matches = [p for p in products if normalized(article) in {normalized(p.get("code", "")), normalized(p.get("article", ""))}] if article else [
            p for p in products if normalized(p.get("name", "")) == normalized(name)]
        mapping_code = mappings.get(normalized(name))
        mapped = [p for p in products if p.get("code") == mapping_code] if mapping_code else []
        if mapping_code and len(mapped) == 1:
            # A supplied article must not silently be overridden by a name mapping.
            if not matches or len(matches) == 1 and matches[0]["id"] == mapped[0]["id"]:
                matches = mapped
                confirmed_mapping = True
            else:
                confirmed_mapping = False
        else:
            confirmed_mapping = False
        if len(matches) != 1:
            suggestions = difflib.get_close_matches(str(name), [p.get("name", "") for p in products], n=3, cutoff=.4)
            candidates = [p for p in products if p.get("name") in suggestions]
            unmatched.append({"row": index, "raw_name": name, "article": article,
                              "suggestions": [{"code": p.get("code"), "name": p.get("name")} for p in candidates]})
            issues.append("Товар не найден однозначно. Уточните артикул или точное название." +
                          (" Возможные названия: " + " | ".join(suggestions) if suggestions else ""))
        elif article and name and not confirmed_mapping and normalized(name) != normalized(matches[0].get("name", "")):
            unmatched.append({"row": index, "raw_name": name, "article": article,
                              "suggestions": [{"code": matches[0].get("code"), "name": matches[0]["name"]}]})
            issues.append("Артикул найден, но название отличается. Подтвердите товар, исправив название на «" + matches[0]["name"] + "».")
        if issues:
            errors.extend("Строка " + str(index) + ": " + issue for issue in issues)
            continue
        rows.append({"date": date, "order": str(order), "platform": str(platform), "code": matches[0].get("code", ""),
                     "name": matches[0]["name"], "quantity": int(quantity),
                     "purchase_minor": purchase_minor, "sale_minor": sale_minor, "product": meta_ref(matches[0])})
    purchase = sum(r["quantity"] * r["purchase_minor"] for r in rows) / 100
    revenue = sum(r["quantity"] * r["sale_minor"] for r in rows) / 100
    return {"status": "needs_review" if errors else "ready", "errors": errors, "rows": rows, "unmatched": unmatched,
            "totals": {"quantity": sum(r["quantity"] for r in rows), "purchase": purchase,
                       "revenue": revenue, "gross": round(revenue - purchase, 2)},
            "note": "Приёмка увеличит долг поставщику, отгрузка создаст задолженность покупателя. Платежи не создаются."}


def _order_code(date, platform, order, supplier_id=None):
    identity = [date, normalized(platform), normalized(order)]
    if supplier_id is not None:
        identity.insert(0, str(supplier_id))
    return "DIRECT-" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:24]


def _post_plan(client, rows, apply, supplier_id=None):
    currencies = client.get_all("entity/currency")
    default = [c for c in currencies if c.get("default")]
    if len(default) != 1 or default[0].get("isoCode") != "RUB":
        raise SeedError("Основная валюта должна быть RUB")
    organizations = client.get_all("entity/organization")
    if len(organizations) != 1:
        raise SeedError("Для демо требуется одна организация, иначе нужно выбрать её явно")
    organization = meta_ref(organizations[0])
    seed = Seeder(client, apply=apply)
    if supplier_id is not None:
        legacy_codes = {_order_code(row["date"], row["platform"], row["order"]) for row in rows}
        for kind in ("supply", "demand"):
            existing = seed._collection(kind)
            if any(NAMESPACE + code + "-" + kind in existing for code in legacy_codes):
                raise SeedError("Найден заказ старого формата без поставщика. Требуется проверка владельца перед переносом, повторное проведение остановлено.")
    supplier_scope = "-" + hashlib.sha256(str(supplier_id).encode()).hexdigest()[:16] if supplier_id is not None else ""
    store = seed.ensure("store", "DIRECT-SUPPLIER-STORE", {"name": "ТОВАРНО | Прямая отгрузка поставщика", "code": "TOVARNO-DIRECT"})
    supplier = seed.ensure("counterparty", "DIRECT-SUPPLIER" + supplier_scope, {"name": "ТОВАРНО | Поставщик прямых отгрузок" + (" | " + str(supplier_id) if supplier_id is not None else ""), "code": "TOVARNO-DIRECT-SUPPLIER" + supplier_scope})
    buyer = seed.ensure("counterparty", "DIRECT-BUYER", {"name": "ТОВАРНО | Покупатели прямых отгрузок", "code": "TOVARNO-DIRECT-BUYER"})
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["date"], row["platform"], row["order"])].append(row)
    documents = []
    for (date, platform, order), positions in grouped.items():
        code = _order_code(date, platform, order, supplier_id)
        stamp = datetime.strptime(date, "%Y-%m-%d").replace(hour=12)
        for kind, agent, price, delta in [("supply", supplier, "purchase_minor", 0), ("demand", buyer, "sale_minor", 1)]:
            fields = {"name": code + "-" + kind, "code": code + "-" + kind,
                      "moment": (stamp + timedelta(minutes=delta)).strftime("%Y-%m-%d %H:%M:%S"),
                      "organization": organization, "store": store, "agent": agent,
                      "description": "ТОВАРНО | " + platform + " | Заказ " + order,
                      "applicable": True, "vatEnabled": False,
                      "positions": [{"quantity": r["quantity"], "price": r[price], "assortment": r["product"],
                                     "vat": 0, "vatEnabled": False} for r in positions]}
            reference = seed.ensure(kind, code + "-" + kind, fields)
            documents.append({"kind": kind, "order": order, "href": reference["meta"]["href"]})
    return {"documents": documents, "counts": dict(seed.counts)}


def import_file(path, filename, execute=False, journal_id=None, supplier_id=None, mappings=None):
    """Read-only preview by default. Execution never silently remaps products."""
    client = _client()
    if mappings is not None and (not isinstance(mappings, dict) or len(mappings) > 20 or any(not isinstance(k, str) or not isinstance(v, str) or len(k) > 2000 or len(v) > 100 for k,v in mappings.items())):
        raise SeedError("Некорректная таблица соответствий")
    merged_mappings = {**_saved_mappings(supplier_id), **{normalized(k):v for k,v in (mappings or {}).items()}}
    result = prepare(path, filename, client, merged_mappings)
    if result["status"] != "ready":
        return result
    # File changes or overlapping reports are checked against immutable order keys.
    lock_dir = Path(os.environ.get("INTAKE_UPLOAD_DIR", "/var/lib/tovarno/uploads"))
    lock_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (lock_dir / ".supplier-import.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        db_path = Path(os.environ.get("INTAKE_DB", "/var/lib/tovarno/intake.sqlite3"))
        if execute and journal_id is not None and db_path.is_file():
            with sqlite3.connect(db_path) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='import_results'").fetchone():
                    previous = db.execute("SELECT result FROM import_results WHERE journal_id=?", (journal_id,)).fetchone()
                    if previous:
                        stored = json.loads(previous[0])
                        if stored.get("status") == "posted":
                            if stored.get("rows") != result["rows"]:
                                raise SeedError("Содержание проведённого документа изменилось. Требуется проверка владельца.")
                            return stored
        _post_plan(client, result["rows"], False, supplier_id)
        if execute:
            result.update(_post_plan(client, result["rows"], True, supplier_id))
            result["status"] = "posted"
            if supplier_id is not None and mappings:
                with sqlite3.connect(os.environ.get("INTAKE_DB", "/var/lib/tovarno/intake.sqlite3")) as db:
                    db.execute("CREATE TABLE IF NOT EXISTS supplier_aliases(supplier_id TEXT,raw_name TEXT,code TEXT,PRIMARY KEY(supplier_id,raw_name))")
                    for raw_name, code in mappings.items():
                        db.execute("INSERT INTO supplier_aliases VALUES(?,?,?) ON CONFLICT(supplier_id,raw_name) DO UPDATE SET code=excluded.code",
                                   (str(supplier_id), normalized(raw_name), code))
    return result
