import asyncio
import json
import logging
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

from describe import describe_and_save
from deliver import deliver
from notify import notify_owner
from render import render_from_file
from synthesize import synthesize_and_save
from transcribe import transcribe_and_save

load_dotenv()

logger = logging.getLogger("quill.processor")

BIOGRAPHY_PERIOD_DAYS = int(os.getenv("BIOGRAPHY_PERIOD_DAYS", "14"))
PROCESSING_HOUR       = max(0, min(23, int(os.getenv("PROCESSING_HOUR", "2"))))
NUDGE_AFTER_DAYS      = int(os.getenv("NUDGE_AFTER_DAYS", "3"))

BASE_DIR        = Path(__file__).parent
INBOX_DIR       = BASE_DIR / "inbox"
PROCESSED_DIR   = BASE_DIR / "processed"
BIOGRAPHIES_DIR = BASE_DIR / "biographies"
LOGS_DIR        = BASE_DIR / "logs"
STATE_FILE      = LOGS_DIR / "state.json"

# ── State ─────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("state.json is corrupt or unreadable — resetting to defaults")
    return {"last_run_date": None, "biography_count": 0}


def save_state(state: dict) -> None:
    LOGS_DIR.mkdir(exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.rename(STATE_FILE)  # atomic on POSIX — no partial-write exposure

# ── Pipeline steps ────────────────────────────────────────────────────────────

async def process_inbox(inbox_dir: Path = INBOX_DIR) -> tuple[int, list[Path]]:
    """Transcribe .ogg and caption .jpg/.png files that have no .txt yet.

    Processes all pending files in parallel. Returns (success_count, failed_paths).
    """
    tasks: list = []
    pending_paths: list[Path] = []
    for path in sorted(inbox_dir.glob("*")):
        if path.suffix == ".txt":
            continue
        if path.with_suffix(".txt").exists():
            continue
        if path.suffix == ".ogg":
            tasks.append(transcribe_and_save(path))
            pending_paths.append(path)
        elif path.suffix in (".jpg", ".jpeg", ".png"):
            tasks.append(describe_and_save(path))
            pending_paths.append(path)

    if not tasks:
        return 0, []

    results = await asyncio.gather(*tasks, return_exceptions=True)
    failed: list[Path] = []
    for path, r in zip(pending_paths, results):
        if isinstance(r, Exception):
            logger.error("inbox processing error for %s", path.name, exc_info=r)
            failed.append(path)
    count = len(tasks) - len(failed)
    if count:
        logger.info("processed %d file(s) in inbox", count)
    return count, failed


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
    commit: bool = True,
    inbox_dir: Path = INBOX_DIR,
    biographies_dir: Path = BIOGRAPHIES_DIR,
    processed_dir: Path = PROCESSED_DIR,
) -> tuple[Path, Path]:
    """Run the full pipeline for a period and return (html_path, pdf_path).

    Steps: process inbox → synthesize → render → [archive → save state → deliver].
    Pass commit=False to synthesize and render without archiving entries or
    updating state.json (used by `cli preview` so a dry-run never corrupts the
    scheduler's view of the world).
    """
    logger.info("pipeline start  %s → %s  commit=%s", period_start, period_end, commit)
    if commit:
        await notify_owner(
            f"✍️ Your chapter for {period_start.strftime('%-d %b')} – "
            f"{period_end.strftime('%-d %b %Y')} is compiling… I'll let you know when it's ready."
        )

    await process_inbox(inbox_dir=inbox_dir)

    if commit:
        content_path, entry_count = await synthesize_and_save(
            period_start, period_end,
            inbox_dir=inbox_dir,
            biographies_dir=biographies_dir,
        )
    else:
        # Preview mode: synthesize to a tempfile outside biographies/ so
        # _load_prior_chapter's glob never finds this draft in future real runs.
        from synthesize import (  # noqa: PLC0415
            collect_entries as _collect_entries,
            synthesize as _synthesize,
            _load_prior_chapter,
        )
        biographies_dir.mkdir(exist_ok=True)
        prior_html = await _load_prior_chapter(biographies_dir, current_end=period_end)
        entries = await _collect_entries(since=period_start, until=period_end, inbox_dir=inbox_dir)
        if not entries:
            raise ValueError("no entries found for the given period")
        html = await _synthesize(entries, period_start, period_end, prior_html=prior_html)
        entry_count = len(entries)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_content.html", encoding="utf-8", delete=False
        ) as tf:
            tf.write(html)
            content_path = Path(tf.name)

    # Extract the chapter title Claude generated so we can use it in the email subject.
    chapter_title: str | None = None
    try:
        raw = content_path.read_text(encoding="utf-8")
        m = re.search(r"<h2[^>]*>(.*?)</h2>", raw, re.IGNORECASE | re.DOTALL)
        if m:
            chapter_title = re.sub(r"<[^>]+>", "", m.group(1)).strip() or None
    except Exception:
        pass

    html_path, pdf_path = await render_from_file(
        content_path, period_start, period_end, entry_count,
        biographies_dir=biographies_dir,
    )

    if not commit:
        content_path.unlink(missing_ok=True)
        logger.info("pipeline (preview) complete → %s", pdf_path.name)
        return html_path, pdf_path

    # Archive and persist state before delivery so a delivery failure cannot
    # cause a duplicate biography on the next run.
    await archive_inbox(until=period_end, inbox_dir=inbox_dir, processed_dir=processed_dir)

    state = load_state()
    state["last_run_date"]   = period_end.isoformat()
    state["biography_count"] = state.get("biography_count", 0) + 1
    save_state(state)

    if deliver_email:
        await deliver(pdf_path, period_start, period_end, entry_count,
                      chapter_title=chapter_title)

    logger.info("pipeline complete → %s", pdf_path.name)

    if deliver_email:
        start_str = period_start.strftime("%-d %b")
        end_str   = period_end.strftime("%-d %b %Y")
        await notify_owner(
            f"✅ Your biography for {start_str} – {end_str} is on its way to your inbox."
        )

    return html_path, pdf_path

# ── Nudge ─────────────────────────────────────────────────────────────────────

async def _maybe_nudge(
    inbox_dir: Path = INBOX_DIR,
    processed_dir: Path = PROCESSED_DIR,
) -> None:
    """Send a gentle capture reminder if no entry has landed in NUDGE_AFTER_DAYS days."""
    state     = load_state()
    today     = date.today()
    today_str = today.isoformat()
    if state.get("last_nudge_date") == today_str:
        return

    last_date: date | None = None
    for directory in (inbox_dir, processed_dir):
        if not directory.exists():
            continue
        for f in directory.iterdir():
            parts = f.stem.split("_")
            try:
                d = date.fromisoformat(parts[0])
                if last_date is None or d > last_date:
                    last_date = d
            except (ValueError, IndexError):
                pass

    days_silent = (today - last_date).days if last_date else NUDGE_AFTER_DAYS + 1
    if NUDGE_AFTER_DAYS > 0 and days_silent >= NUDGE_AFTER_DAYS:
        await notify_owner(
            "Your chronicle is waiting. 📝\n\n"
            "What happened today — anything worth remembering? "
            "Send me a thought, a voice note, or a photo."
        )
        state["last_nudge_date"] = today_str
        save_state(state)
        logger.info("sent idle nudge (last entry %d day(s) ago)", days_silent)


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

        # Daily: transcribe/caption any new inbox items and confirm to owner
        processed, failed = await process_inbox()
        if processed:
            noun = "item" if processed == 1 else "items"
            await notify_owner(
                f"✨ Processed {processed} {noun} from your inbox "
                "(transcribed and captioned, ready for the next chapter)."
            )
        if failed:
            names = ", ".join(f.name for f in failed[:3])
            extra = f" (and {len(failed) - 3} more)" if len(failed) > 3 else ""
            await notify_owner(
                f"⚠️ {len(failed)} item(s) couldn't be processed: {names}{extra}. "
                "Check logs/quill.log for details — nothing has been lost."
            )

        # Daily: nudge if the chronicle has been quiet
        try:
            await _maybe_nudge()
        except Exception:
            logger.exception("_maybe_nudge failed")

        try:
            state    = load_state()
            last_run = date.fromisoformat(state["last_run_date"]) if state["last_run_date"] else None
        except Exception:
            logger.exception("could not load state — skipping pipeline check")
            continue
        today    = date.today()

        if last_run:
            days_since = (today - last_run).days
            if days_since < BIOGRAPHY_PERIOD_DAYS:
                logger.info("skipping pipeline — last biography %d day(s) ago", days_since)
                # Approaching: notify 2 days before the chapter compiles
                days_until = BIOGRAPHY_PERIOD_DAYS - days_since
                if days_until == 2:
                    stems: set[str] = set()
                    if INBOX_DIR.exists():
                        for _f in INBOX_DIR.iterdir():
                            if _f.is_file():
                                stems.add(_f.stem)
                    inbox_count = len(stems)
                    noun = "moment" if inbox_count == 1 else "moments"
                    await notify_owner(
                        f"📖 Your next chapter arrives in 2 days.\n\n"
                        f"You have {inbox_count} {noun} captured so far — "
                        "keep the notes coming to make it a rich one."
                    )
                continue

        period_end   = today
        period_start = today - timedelta(days=BIOGRAPHY_PERIOD_DAYS - 1)

        try:
            await run_pipeline(period_start, period_end)
        except ValueError as exc:
            # Raised by synthesize() when the inbox is empty for the period.
            logger.info("quiet period — no entries to synthesize: %s", exc)
            await notify_owner(
                "No entries were captured this period — nothing to weave into a chapter. "
                "Add some notes and I'll be ready to write your next one."
            )
        except Exception:
            logger.exception("pipeline failed")
            await notify_owner(
                f"⚠️ Something went wrong building your chapter ({today.isoformat()}).\n\n"
                "No entries have been lost. Check logs/quill.log for details."
            )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")
    asyncio.run(start_scheduler())
