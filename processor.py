import asyncio
import json
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from describe import describe_and_save
from deliver import deliver
from render import render_from_file
from synthesize import synthesize_and_save
from transcribe import transcribe_and_save

load_dotenv()

logger = logging.getLogger("quill.processor")

BIOGRAPHY_PERIOD_DAYS = int(os.getenv("BIOGRAPHY_PERIOD_DAYS", "14"))
PROCESSING_HOUR       = int(os.getenv("PROCESSING_HOUR", "2"))

BASE_DIR        = Path(__file__).parent
INBOX_DIR       = BASE_DIR / "inbox"
PROCESSED_DIR   = BASE_DIR / "processed"
BIOGRAPHIES_DIR = BASE_DIR / "biographies"
LOGS_DIR        = BASE_DIR / "logs"
STATE_FILE      = LOGS_DIR / "state.json"

# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_run_date": None, "biography_count": 0}


def save_state(state: dict) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))

# ── Pipeline steps ────────────────────────────────────────────────────────────

async def process_inbox(inbox_dir: Path = INBOX_DIR) -> int:
    """Transcribe .ogg and caption .jpg/.png files that have no .txt yet.

    Returns the number of files processed.
    """
    count = 0
    for path in sorted(inbox_dir.glob("*")):
        if path.suffix == ".txt":
            continue
        if path.with_suffix(".txt").exists():
            continue
        if path.suffix == ".ogg":
            await transcribe_and_save(path)
            count += 1
        elif path.suffix in (".jpg", ".jpeg", ".png"):
            await describe_and_save(path)
            count += 1
    if count:
        logger.info("processed %d file(s) in inbox", count)
    return count


async def archive_inbox(
    until: date,
    inbox_dir: Path = INBOX_DIR,
    processed_dir: Path = PROCESSED_DIR,
) -> int:
    """Move files dated on or before *until* from inbox/ to processed/.

    Returns the number of files moved.
    """
    processed_dir.mkdir(exist_ok=True)
    count = 0
    for path in sorted(inbox_dir.glob("*")):
        parts = path.stem.split("_")
        try:
            file_date = date.fromisoformat(parts[0])
        except (ValueError, IndexError):
            continue
        if file_date <= until:
            path.rename(processed_dir / path.name)
            count += 1
    if count:
        logger.info("archived %d file(s) → processed/", count)
    return count


async def run_pipeline(
    period_start: date,
    period_end: date,
    deliver_email: bool = True,
    inbox_dir: Path = INBOX_DIR,
    biographies_dir: Path = BIOGRAPHIES_DIR,
    processed_dir: Path = PROCESSED_DIR,
) -> tuple[Path, Path]:
    """Run the full pipeline for a period and return (html_path, pdf_path).

    Steps: process inbox → synthesize → render → deliver → archive → save state.
    """
    logger.info("pipeline start  %s → %s", period_start, period_end)

    await process_inbox(inbox_dir=inbox_dir)

    content_path, entry_count = await synthesize_and_save(
        period_start, period_end,
        inbox_dir=inbox_dir,
        biographies_dir=biographies_dir,
    )

    html_path, pdf_path = await render_from_file(
        content_path, period_start, period_end, entry_count,
        biographies_dir=biographies_dir,
    )

    if deliver_email:
        await deliver(pdf_path, period_start, period_end, entry_count)

    await archive_inbox(until=period_end, inbox_dir=inbox_dir, processed_dir=processed_dir)

    state = load_state()
    state["last_run_date"]   = period_end.isoformat()
    state["biography_count"] = state.get("biography_count", 0) + 1
    save_state(state)

    logger.info("pipeline complete → %s", pdf_path.name)
    return html_path, pdf_path

# ── Scheduler ─────────────────────────────────────────────────────────────────

def next_run_dt(from_dt: datetime | None = None) -> datetime:
    """Return the next scheduled run datetime (daily at PROCESSING_HOUR)."""
    now    = from_dt or datetime.now()
    target = now.replace(hour=PROCESSING_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


async def start_scheduler() -> None:
    """Block forever, running the pipeline on schedule."""
    logger.info(
        "scheduler started  (daily at %02d:00, biography every %d days)",
        PROCESSING_HOUR, BIOGRAPHY_PERIOD_DAYS,
    )
    while True:
        nxt       = next_run_dt()
        wait_secs = (nxt - datetime.now()).total_seconds()
        logger.info("next run: %s  (in %.0fs)", nxt.strftime("%Y-%m-%d %H:%M"), wait_secs)
        await asyncio.sleep(wait_secs)

        state    = load_state()
        last_run = date.fromisoformat(state["last_run_date"]) if state["last_run_date"] else None
        today    = date.today()

        if last_run and (today - last_run).days < BIOGRAPHY_PERIOD_DAYS:
            logger.info("skipping — last biography %d day(s) ago", (today - last_run).days)
            continue

        period_end   = today
        period_start = today - timedelta(days=BIOGRAPHY_PERIOD_DAYS - 1)

        try:
            await run_pipeline(period_start, period_end)
        except Exception:
            logger.exception("pipeline failed")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    asyncio.run(start_scheduler())
