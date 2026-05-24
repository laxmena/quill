import logging
import os

import aiohttp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("quill.notify")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_raw = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "")
OWNER_CHAT_ID: int | None = int(_raw) if _raw.lstrip("-").isdigit() else None

_API_BASE = "https://api.telegram.org"


async def notify_owner(text: str) -> None:
    """Send a Telegram message to the owner via the Bot API. Never raises."""
    if not BOT_TOKEN or OWNER_CHAT_ID is None:
        logger.debug("notify_owner: not configured, skipping")
        return
    try:
        url = f"{_API_BASE}/bot{BOT_TOKEN}/sendMessage"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, json={"chat_id": OWNER_CHAT_ID, "text": text}, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if not resp.ok:
                    body = await resp.text()
                    logger.warning("notify_owner HTTP %d: %s", resp.status, body[:200])
                    return
        logger.info("notified owner (%d chars)", len(text))
    except Exception:
        logger.warning("notify_owner failed", exc_info=True)
