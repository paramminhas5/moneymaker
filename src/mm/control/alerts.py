"""Telegram alerts. A silent no-op when no bot token is configured, so dev runs need nothing."""

from __future__ import annotations

import httpx

from mm.logging import get_logger
from mm.secrets import get_secret, has_secret

log = get_logger(__name__)


def send_alert(text: str, *, timeout: float = 10.0) -> bool:
    if not (has_secret("telegram_bot_token") and has_secret("telegram_chat_id")):
        log.info("alert_skipped_no_telegram", text=text)
        return False
    token = get_secret("telegram_bot_token").reveal()
    chat_id = get_secret("telegram_chat_id").reveal()
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=timeout,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        # Log the type only: the exception message contains the URL, which contains the token.
        log.warning("alert_failed", error_type=type(exc).__name__)
        return False
    return True
