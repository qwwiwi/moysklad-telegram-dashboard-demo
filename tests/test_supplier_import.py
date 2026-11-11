import tempfile
import sqlite3
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import supplier_import as importer
from seed_moysklad import BASE, SeedError


def entity(kind, identifier, **fields):
    return {"id": identifier, "meta": {"href": BASE + "/entity/" + kind + "/" + identifier,
                                      "type": kind, "mediaType": "application/json"}, **fields}


class FakeClient:
    def __init__(self):
        self.data = {
            "product": [entity("product", "p1", name="Термокружка Север", code="P1", article="A1")],
            "organization": [entity("organization", "org")],
            "currency": [entity("currency", "rub", default=True, isoCode="RUB")],
        }
        self.writes = 0
    def get_all(self, route):
        return self.data.get(route.split("/")[-1], [])
    def get(self, route, params=None):
        _, kind, identifier = route.split("/")
        return next(row for row in self.data[kind] if row["id"] == identifier)
    def request(self, method, route, payload):
        self.writes += 1
        kind = route.split("/")[-1]
        row = entity(kind, str(self.writes), **payload)
        self.data.setdefault(kind, []).append(row)
        return row


class SupplierImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "report.csv"
        self.path.write_text(",".join(importer.HEADERS) + "\n2026-11-11,ORDER-1,Ozon,P1,Термокружка Север,2,100,150\n")

    def test_preview_execute_retry_and_drift(self):
        client = FakeClient()
        with patch.object(importer, "_client", return_value=client), patch.dict("os.environ", {"INTAKE_UPLOAD_DIR": self.tmp.name}):
            preview = importer.import_file(self.path, self.path.name)
            self.assertEqual(preview["totals"], {"quantity": 2, "purchase": 200, "revenue": 300, "gross": 100})
            self.assertEqual(client.writes, 0)
            first = importer.import_file(self.path, self.path.name, execute=True)
            self.assertEqual(first["status"], "posted")
            writes = client.writes
            importer.import_file(self.path, self.path.name, execute=True)
            self.assertEqual(client.writes, writes)
            self.path.write_text(self.path.read_text().replace(",2,100,150", ",3,100,150"))
            with self.assertRaises(SeedError):
                importer.import_file(self.path, self.path.name, execute=True)
            self.assertEqual(client.writes, writes)

    def test_supplier_orders_are_isolated_and_retries_do_not_write(self):
        client = FakeClient()
        with patch.object(importer, "_client", return_value=client), patch.dict("os.environ", {"INTAKE_UPLOAD_DIR": self.tmp.name, "INTAKE_DB": self.tmp.name + "/intake.db"}):
            first = importer.import_file(self.path, self.path.name, execute=True, supplier_id="101")
            second = importer.import_file(self.path, self.path.name, execute=True, supplier_id="202")
            self.assertEqual(len(client.data["supply"]), 2)
            self.assertEqual(len(client.data["demand"]), 2)
            self.assertNotEqual(client.data["supply"][0]["agent"], client.data["supply"][1]["agent"])
            self.assertNotEqual(first["documents"][0]["href"], second["documents"][0]["href"])
            writes = client.writes
            for supplier in ("101", "202"):
                importer.import_file(self.path, self.path.name, execute=True, supplier_id=supplier)
            self.assertEqual(client.writes, writes)

    def test_legacy_order_requires_migration_before_scoped_import(self):
        client = FakeClient()
        with patch.object(importer, "_client", return_value=client), patch.dict("os.environ", {"INTAKE_UPLOAD_DIR": self.tmp.name, "INTAKE_DB": self.tmp.name + "/intake.db"}):
            importer.import_file(self.path, self.path.name, execute=True)
            writes = client.writes
            with self.assertRaisesRegex(SeedError, "старого формата"):
                importer.import_file(self.path, self.path.name, execute=True, supplier_id="101")
            self.assertEqual(client.writes, writes)

    def test_completed_legacy_journal_retry_uses_stored_result(self):
        client = FakeClient()
        db_path = self.tmp.name + "/intake.db"
        with patch.object(importer, "_client", return_value=client), patch.dict("os.environ", {"INTAKE_UPLOAD_DIR": self.tmp.name, "INTAKE_DB": db_path}):
            first = importer.import_file(self.path, self.path.name, execute=True)
            with sqlite3.connect(db_path) as db:
                db.execute("CREATE TABLE import_results(journal_id INTEGER PRIMARY KEY,result TEXT NOT NULL)")
                db.execute("INSERT INTO import_results VALUES(?,?)", (7, json.dumps(first)))
            writes = client.writes
            retry = importer.import_file(self.path, self.path.name, execute=True, journal_id=7, supplier_id="101")
            self.assertEqual(retry, first)
            self.assertEqual(client.writes, writes)
            self.path.write_text(self.path.read_text().replace(",2,100,150", ",3,100,150"))
            with self.assertRaisesRegex(SeedError, "изменилось"):
                importer.import_file(self.path, self.path.name, execute=True, journal_id=7, supplier_id="101")
            self.assertEqual(client.writes, writes)

    def test_explicit_name_mapping_only(self):
        client = FakeClient()
        self.path.write_text(self.path.read_text().replace("P1,Термокружка Север", ",термокружечка"))
        result = importer.prepare(self.path, self.path.name, client)
        self.assertEqual(result["status"], "needs_review")
        self.assertTrue(result["unmatched"])
        mapped = importer.prepare(self.path, self.path.name, client, {"термокружечка": "P1"})
        self.assertEqual(mapped["status"], "ready")

    def test_mismatching_article_name_needs_confirmation(self):
        self.path.write_text(self.path.read_text().replace("Термокружка Север", "Другой товар"))
        self.assertEqual(importer.prepare(self.path, self.path.name, FakeClient())["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
