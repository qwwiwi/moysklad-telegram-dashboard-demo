import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from intake_api import MAX_UPLOAD_BYTES, UploadError, receive_upload, upload_name
from intake_store import connect


class BoundedStream(io.BytesIO):
    def read(self, size=-1):
        if size < 0 or size > 65536:
            raise AssertionError("Unbounded read")
        return super().read(size)


class LargeUploadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "uploads"
        self.env = patch.dict(os.environ, INTAKE_DB=self.temp.name + "/intake.sqlite3")
        self.env.start()
        self.addCleanup(self.env.stop)
        with connect() as db:
            db.execute("INSERT INTO profiles VALUES(1,'supplier')")

    def test_stream_to_private_file_and_journal(self):
        content = b"date,sku,qty\n" * 18000
        result = receive_upload(BoundedStream(content), len(content), "Отгрузка.csv", 1, self.folder)
        with connect() as db:
            row = db.execute("SELECT * FROM journal WHERE id=?", (result["id"],)).fetchone()
        path = Path(row["storage_path"])
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(row["origin"], "Загрузка через сайт")
        self.assertEqual(row["role"], "supplier")
        self.assertEqual(row["filename"], "Отгрузка.csv")

    def test_partial_upload_has_no_record_or_partial_file(self):
        with self.assertRaises(UploadError):
            receive_upload(io.BytesIO(b"a"), 20, "partial.csv", 1, self.folder)
        self.assertEqual(list(self.folder.iterdir()), [])
        with connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM journal").fetchone()[0], 0)

    def test_limit_and_role(self):
        for length, user in [(MAX_UPLOAD_BYTES + 1, 1), (0, 1), (1, 2)]:
            with self.assertRaises(UploadError):
                receive_upload(io.BytesIO(), length, "data.csv", user, self.folder)

    def test_filename(self):
        self.assertEqual(upload_name(quote("Отгрузка.xlsx")), "Отгрузка.xlsx")
        for name in ["../x.csv", "a%2Fb.csv", "a%5Cb.xlsx", "file.exe", "x%00.csv"]:
            with self.assertRaises(UploadError):
                upload_name(name)


if __name__ == "__main__":
    unittest.main()
