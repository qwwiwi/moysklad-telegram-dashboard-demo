import os
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import voice_notes
from intake_store import connect


class InlineThread:
    def __init__(self, target, args, **kwargs):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class VoiceNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"INTAKE_DB": self.temp.name + "/journal.db", "INTAKE_UPLOAD_DIR": self.temp.name + "/uploads"})
        self.env.start()
        self.calls = []
        def call(method, **fields):
            self.calls.append((method, fields))
            return {"file_path": "voice/file.oga"}
        call.download = lambda remote, destination: destination.write_bytes(b"fake-audio")
        self.call = call
        self.message = {"voice": {"file_id": "abc", "duration": 15, "file_size": 10}, "chat": {"id": 42, "type": "private"}, "from": {"id": 42, "first_name": "Example"}, "message_id": 9}
        with closing(connect()) as db, db:
            db.execute("INSERT INTO profiles VALUES(42,'supplier')")
            db.execute("INSERT INTO journal(id,user_id,kind,received_at,chat_id,message_id) VALUES(3,42,'file','2099-01-01T00:00:00+00:00',42,7)")

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_transcript_link_and_duplicate(self):
        with patch.object(voice_notes, "_transcribe", return_value="Сегодня отправили три заказа."), patch.object(voice_notes.threading, "Thread", InlineThread):
            self.assertTrue(voice_notes.handle_voice(self.call, self.message, "https://example.com/"))
            voice_notes.handle_voice(self.call, self.message, "https://example.com/")
        with closing(connect()) as db:
            records = db.execute("SELECT * FROM journal WHERE kind='voice'").fetchall()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["text"], "Сегодня отправили три заказа.")
            self.assertEqual(records[0]["status"], "received")
            self.assertEqual(db.execute("SELECT parent_id FROM journal_links").fetchone()[0], 3)
            self.assertEqual(Path(records[0]["storage_path"]).stat().st_mode & 0o777, 0o600)

    def test_failed_transcript_keeps_original(self):
        with patch.object(voice_notes, "_transcribe", side_effect=RuntimeError()), patch.object(voice_notes.threading, "Thread", InlineThread):
            voice_notes.handle_voice(self.call, self.message, "https://example.com/")
        with closing(connect()) as db:
            row = db.execute("SELECT status,storage_path FROM journal WHERE kind='voice'").fetchone()
            self.assertEqual(row["status"], "transcription_failed")
            self.assertTrue(Path(row["storage_path"]).is_file())

    def test_long_audio_rejected(self):
        self.message["voice"]["duration"] = 121
        voice_notes.handle_voice(self.call, self.message, "https://example.com/")
        with closing(connect()) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM journal WHERE kind='voice'").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
