"""Progress updates are authenticated and cannot block the video render."""
from __future__ import annotations
import unittest
from unittest.mock import patch
from montage_progress import publish_progress


class ProgressTests(unittest.TestCase):
    def test_private_progress_report_for_closed_miniapp(self):
        class Response:
            status_code=200
            ok=True
        with patch("montage_progress.requests.post",return_value=Response()) as post:
            result=publish_progress(
                "https://video.workers.dev","a"*36,"BOT_SECRET",
                "review","Жду /ok"
            )
        self.assertTrue(result)
        kwargs=post.call_args.kwargs
        self.assertEqual(kwargs["json"],{
            "stage":"review","message":"Жду /ok"
        })
        self.assertEqual(kwargs["headers"],{
            "Authorization":"Bearer BOT_SECRET"
        })
        self.assertTrue(post.call_args.args[0].endswith("/progress"))

    def test_unavailable_status_update_does_not_block_render(self):
        class Failed:
            ok=False
            status_code=403
        with patch("montage_progress.requests.post",return_value=Failed()):
            self.assertFalse(publish_progress(
                "https://video.workers.dev","a"*36,"T","rendering","Работаю"
            ))

    def test_invalid_stages_not_sent_to_cloudflare(self):
        with patch("montage_progress.requests.post") as post:
            with self.assertRaises(ValueError):
                publish_progress("https://video.workers.dev","a"*36,
                                 "SECRET","not-a-real-stage")
            post.assert_not_called()


if __name__=="__main__":
    unittest.main()
