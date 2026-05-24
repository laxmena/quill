import asyncio
import logging
import os
import smtplib
from datetime import date, datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import aiofiles
from dotenv import load_dotenv
from retries import with_retry

load_dotenv()

logger = logging.getLogger("quill.deliver")

MOCK                      = os.getenv("QUILL_MOCK", "").lower() in ("1", "true")
GMAIL_ADDRESS             = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD        = os.getenv("GMAIL_APP_PASSWORD", "")
BIOGRAPHY_RECIPIENT_EMAIL = os.getenv("BIOGRAPHY_RECIPIENT_EMAIL", "")
USER_NAME                 = os.getenv("USER_NAME", "Alex Rivera")

BASE_DIR        = Path(__file__).parent
BIOGRAPHIES_DIR = BASE_DIR / "biographies"

# ── Email template ────────────────────────────────────────────────────────────

_HTML_BODY = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>
    body        {{ font-family: Georgia, serif; max-width: 520px; margin: 40px auto; color: #1a1a18; }}
    .rule       {{ width: 40px; height: 2px; background: #1a1a18; margin-bottom: 24px; }}
    .label      {{ font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase;
                   color: #888; margin-bottom: 16px; }}
    h1          {{ font-size: 26px; font-weight: normal; margin: 0 0 8px; }}
    .period     {{ font-size: 13px; color: #888; margin-bottom: 32px; }}
    p           {{ line-height: 1.7; color: #444; }}
    .footer     {{ margin-top: 40px; font-size: 11px; color: #aaa;
                   border-top: 1px solid #e0d8cc; padding-top: 16px; }}
  </style>
</head>
<body>
  <div class="rule"></div>
  <p class="label">Your Personal Chronicle</p>
  <h1>{name}</h1>
  <p class="period">{period_start} — {period_end}</p>
  <p>Your biography for the past {period_days} days is attached as a PDF.</p>
  <p>
    It was woven from {entry_count} moment{s} — notes, voice memos, and photographs
    you captured between {period_start} and {period_end}.
  </p>
  <p class="footer">Composed by Quill &middot; {generated_date}</p>
</body>
</html>
"""

# ── Message builder ───────────────────────────────────────────────────────────

def _build_message(
    pdf_path: Path,
    pdf_bytes: bytes,
    period_start: date,
    period_end: date,
    entry_count: int,
) -> MIMEMultipart:
    period_days = (period_end - period_start).days + 1
    start_str   = period_start.strftime("%-d %B %Y")
    end_str     = period_end.strftime("%-d %B %Y")

    msg = MIMEMultipart("mixed")
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = BIOGRAPHY_RECIPIENT_EMAIL
    msg["Subject"] = (
        f"Your Quill Biography — "
        f"{period_start.strftime('%-d %b')} – {period_end.strftime('%-d %b %Y')}"
    )

    body = _HTML_BODY.format(
        name=USER_NAME,
        period_start=start_str,
        period_end=end_str,
        period_days=period_days,
        entry_count=entry_count,
        s="" if entry_count == 1 else "s",
        generated_date=datetime.now().strftime("%-d %B %Y"),
    )
    msg.attach(MIMEText(body, "html"))

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=pdf_path.name)
    msg.attach(attachment)

    return msg

# ── SMTP (sync, run in executor) ──────────────────────────────────────────────

def _send_sync(msg: MIMEMultipart) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        smtp.sendmail(GMAIL_ADDRESS, BIOGRAPHY_RECIPIENT_EMAIL, msg.as_string())

# ── Public API ────────────────────────────────────────────────────────────────

async def deliver(
    pdf_path: Path,
    period_start: date,
    period_end: date,
    entry_count: int = 0,
) -> None:
    """Email the biography PDF to BIOGRAPHY_RECIPIENT_EMAIL.

    In mock mode logs what would be sent without opening a socket.
    """
    async with aiofiles.open(pdf_path, "rb") as f:
        pdf_bytes = await f.read()

    msg = _build_message(pdf_path, pdf_bytes, period_start, period_end, entry_count)
    size_kb = len(pdf_bytes) // 1024

    if MOCK:
        logger.info(
            "[mock] would deliver '%s' → %s  (%d KB, %d entries)",
            msg["Subject"],
            BIOGRAPHY_RECIPIENT_EMAIL or "<BIOGRAPHY_RECIPIENT_EMAIL not set>",
            size_kb,
            entry_count,
        )
        return

    if not all([GMAIL_ADDRESS, GMAIL_APP_PASSWORD, BIOGRAPHY_RECIPIENT_EMAIL]):
        raise ValueError(
            "GMAIL_ADDRESS, GMAIL_APP_PASSWORD, and BIOGRAPHY_RECIPIENT_EMAIL "
            "must all be set in .env"
        )

    await with_retry(
        lambda: asyncio.to_thread(_send_sync, msg),
        attempts=3, base_delay=5.0, timeout=30.0, label="smtp",
    )
    logger.info(
        "delivered '%s' → %s  (%d KB)",
        msg["Subject"],
        BIOGRAPHY_RECIPIENT_EMAIL,
        size_kb,
    )


if __name__ == "__main__":
    import sys
    from datetime import timedelta

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")

    if len(sys.argv) < 2:
        print("usage: python deliver.py <biography.pdf> [period_start period_end]")
        raise SystemExit(1)

    pdf_path = Path(sys.argv[1])
    if len(sys.argv) == 4:
        period_start = date.fromisoformat(sys.argv[2])
        period_end   = date.fromisoformat(sys.argv[3])
    else:
        # Infer period from filename stem: YYYY-MM-DD
        period_end   = date.fromisoformat(pdf_path.stem)
        period_days  = int(os.getenv("BIOGRAPHY_PERIOD_DAYS", "14"))
        period_start = period_end - timedelta(days=period_days - 1)

    asyncio.run(deliver(pdf_path, period_start, period_end))
