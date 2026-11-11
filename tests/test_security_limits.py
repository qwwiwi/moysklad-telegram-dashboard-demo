"""Exercise bounded request and accounting-worker capacity."""
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from intake_api import BoundedHTTPServer, JournalHandler, _IMPORT_SLOTS


class RequestLimitTests(unittest.TestCase):
    def test_unfinished_request_does_not_spawn_unbounded_threads(self):
        server = BoundedHTTPServer(("127.0.0.1", 0), JournalHandler)
        server.request_slots = threading.BoundedSemaphore(1)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        first = socket.create_connection(server.server_address, timeout=2)
        second = None
        try:
            first.sendall(b"POST /api/login HTTP/1.1\r\n")
            deadline = time.monotonic() + 2
            while server.request_slots._value and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(server.request_slots._value, 0)
            second = socket.create_connection(server.server_address, timeout=2)
            second.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
            self.assertIn(b"503 Service Unavailable", second.recv(1024))
            first.close()
            deadline = time.monotonic() + 2
            while not server.request_slots._value and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(server.request_slots._value, 1)
        finally:
            first.close()
            if second:
                second.close()
            server.shutdown()
            server.server_close()
            thread.join(2)

    def test_full_processing_capacity_preserves_document_for_review(self):
        with tempfile.TemporaryDirectory() as folder:
            database = str(Path(folder) / "test.db")
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE journal(id INTEGER,status TEXT,text TEXT)")
                db.execute("INSERT INTO journal VALUES(1,'received','')")
            held = 0
            try:
                for _ in range(4):
                    self.assertTrue(_IMPORT_SLOTS.acquire(blocking=False))
                    held += 1
                handler = SimpleNamespace(server=SimpleNamespace(db_path=database))
                JournalHandler.process_supplier_document(handler, 1, 1)
                with sqlite3.connect(database) as db:
                    status, text = db.execute("SELECT status,text FROM journal WHERE id=1").fetchone()
                self.assertEqual(status, "needs_review")
                self.assertIn("Обработка занята", text)
            finally:
                for _ in range(held):
                    _IMPORT_SLOTS.release()


if __name__ == "__main__":
    unittest.main()
