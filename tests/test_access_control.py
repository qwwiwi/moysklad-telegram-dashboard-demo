import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from access_control import is_allowed
from telegram_demo_bot import reply_to_start

class AccessTests(unittest.TestCase):
    def test_default_denies(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_allowed(1))
    def test_explicit_membership(self):
        with patch.dict(os.environ, {"ALLOWED_TELEGRAM_IDS":"1,2"}, clear=True):
            self.assertTrue(is_allowed(1))
            self.assertFalse(is_allowed(3))
            self.assertFalse(is_allowed(True))
    def test_unknown_bot_user_cannot_get_login_link(self):
        calls=[]
        with patch.dict(os.environ, {"ALLOWED_TELEGRAM_IDS":"1"}, clear=True):
            reply_to_start(lambda method,**fields:calls.append((method,fields)),{
                "callback_query":{"id":"test","from":{"id":2},"data":"browser_login",
                                  "message":{"chat":{"id":2,"type":"private"}}}
            },"bot","https://app.moyskladdemo.xyz/")
        self.assertEqual([x[0] for x in calls],["answerCallbackQuery"])
        self.assertIn("Доступ",calls[0][1]["text"])
