"""Safety smoke tests for the Telegram-authenticated Mini App backend."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import HTTPException
from editor_api import authenticated_user, validate_settings


class MiniAppApiTests(unittest.TestCase):
    def sign(self, user: int, bot_token: str = "1234:FAKE_TOKEN") -> str:
        params = {
            "auth_date": str(int(time.time())),
            "query_id": "test",
            "user": json.dumps({"id": user}, separators=(",", ":")),
        }
        data = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
        key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        params["hash"] = hmac.new(key, data.encode(), hashlib.sha256).hexdigest()
        return urlencode(params)

    def test_validated_telegram_owner(self):
        with patch.dict(os.environ, {
            "TELEGRAM_BOT_TOKEN": "1234:FAKE_TOKEN",
            "OWNER_TELEGRAM_ID": "777",
        }):
            self.assertEqual(authenticated_user(self.sign(777)), 777)
            with self.assertRaises(HTTPException):
                authenticated_user(self.sign(100))
            with self.assertRaises(HTTPException):
                authenticated_user("")
            with self.assertRaises(HTTPException):
                authenticated_user(self.sign(777).replace("777", "778"))

    def test_bad_settings_rejected(self):
        defaults = validate_settings({})
        self.assertEqual(defaults["mode"], "my_style")
        self.assertEqual(defaults["camera_style"], "cinematic_pan")
        self.assertEqual(defaults["export_quality"], "high")
        self.assertEqual(defaults["font_profile"], "old_money")
        self.assertEqual(defaults["subtitle_style"], "reference_dynamic")
        self.assertEqual(defaults["caption_variant"], "reference_soft")
        self.assertEqual(defaults["insert_style"], "reference_soft")
        settings = validate_settings({
            "mode":"reference", "camera_style":"cinematic_pan",
            "subtitle_style":"reference_dynamic", "font_profile":"bubble",
            "export_quality":"balanced",
            "sound_effects":"soft", "emoji_mode":"on",
            "hook":"Найди ошибку", "hook_position":"end",
        })
        self.assertEqual(settings["hook_position"],"end")
        self.assertEqual(settings["font_profile"],"bubble")
        self.assertEqual(settings["export_quality"],"balanced")
        self.assertEqual(settings["subtitle_style"],"reference_dynamic")
        with self.assertRaises(HTTPException):
            validate_settings({"font_profile":"../../files"})
        with self.assertRaises(HTTPException):
            validate_settings({"speed": 6})
        with self.assertRaises(HTTPException):
            validate_settings({"color":"red;rm -rf /"})
        with self.assertRaises(HTTPException):
            validate_settings({"camera_style":"arbitrary"})
        with self.assertRaises(HTTPException):
            validate_settings({"export_quality":"16k"})


if __name__=="__main__":
    unittest.main()
