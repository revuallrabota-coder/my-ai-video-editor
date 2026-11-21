"""Best-effort durable progress events for an iPad app that may be closed.

Progress is stored in the OWNER-ONLY Cloudflare Worker, not the browser.
Each stage gets its own 72-hour TTL-backed KV key. The Telegram bot's own
text messages are sent by process_uploaded_video, independently of this.
"""
from __future__ import annotations

import logging
import re
import time
import requests

LOG=logging.getLogger("montage_progress")
STAGES=frozenset((
    "queued","downloading","joining","transcribing","review",
    "planning","rendering","publishing","done","failed",
))


def publish_progress(
    worker_url: str, upload_id: str, bot_token: str,
    stage: str, message: str = "",
) -> bool:
    if stage not in STAGES:
        raise ValueError("Unknown montage progress stage")
    if not re.fullmatch(r"[a-f0-9-]{36}",upload_id):
        raise ValueError("Invalid upload id")
    if not re.fullmatch(r"https://[a-z0-9-]+(?:\.[a-z0-9-]+)*\.workers\.dev",
                        worker_url):
        raise ValueError("Invalid Cloudflare origin")
    url=f"{worker_url.rstrip('/')}/internal/upload/{upload_id}/progress"
    headers={"Authorization":"Bearer "+bot_token}
    payload={"stage":stage,"message":str(message)[:180]}
    for attempt in range(2):
        try:
            response=requests.post(url,json=payload,headers=headers,timeout=6)
            if response.ok:
                return True
            if response.status_code not in (409,429,500,502,503,504):
                LOG.warning("Cloudflare progress stage %s rejected, status %s",
                            stage,response.status_code)
                return False
        except requests.RequestException:
            pass
        if attempt<1:
            time.sleep(1.0)
    LOG.warning("Cloudflare progress update for stage %s unavailable",stage)
    return False
