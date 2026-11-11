import concurrent.futures
from contextlib import closing
import pathlib
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
import browser_auth


class BrowserLoginTests(unittest.TestCase):
    def test_single_redemption_race_and_logout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "db"
            token = browser_auth.issue_link(42, path)
            with concurrent.futures.ThreadPoolExecutor(4) as pool:
                sessions = list(pool.map(lambda _: browser_auth.exchange(token, path), range(4)))
            session, = [value for value in sessions if value]
            self.assertEqual(browser_auth.authenticate(session, path), 42)
            self.assertIsNone(browser_auth.authenticate(token, path))
            browser_auth.logout(session, path)
            self.assertIsNone(browser_auth.authenticate(session, path))

    def test_expiry_and_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "db"
            with patch("browser_auth.time.time", return_value=10):
                token = browser_auth.issue_link(17, path)
                other = browser_auth.issue_link(17, path)
                session = browser_auth.exchange(other, path)
            with closing(sqlite3.connect(path)) as db:
                stored = {r[0] for r in db.execute("SELECT digest FROM browser_credentials")}
            self.assertTrue(stored.isdisjoint([session, token]))
            with patch("browser_auth.time.time", return_value=610):
                self.assertIsNone(browser_auth.exchange(token, path))
            with patch("browser_auth.time.time", return_value=43210):
                self.assertIsNone(browser_auth.authenticate(session, path))


if __name__ == "__main__":
    unittest.main()
