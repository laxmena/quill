import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import aiofiles
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("quill.synthesize")

MOCK      = os.getenv("QUILL_MOCK", "").lower() in ("1", "true")
USER_NAME = os.getenv("USER_NAME", "Alex Rivera")

BASE_DIR        = Path(__file__).parent
INBOX_DIR       = BASE_DIR / "inbox"
BIOGRAPHIES_DIR = BASE_DIR / "biographies"

# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Entry:
    timestamp: datetime
    kind: str   # "note" | "voice" | "photo"
    text: str

# ── Client factory ────────────────────────────────────────────────────────────

def _client():
    if MOCK:
        from mocks import MockAnthropic
        return MockAnthropic()
    from anthropic import AsyncAnthropic
    return AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a literary biographer in the tradition of the Bloomsbury group — precise,
evocative, and deeply attentive to the texture of daily life.

You are writing a chapter of {name}'s personal biography. You will receive diary
entries, voice note transcriptions, and photo captions in chronological order.
Weave them into flowing biographical prose. Do not list entries mechanically —
find themes, rhythms, and meaning across them.

Output rules (strictly observed):
- Return only inner HTML; no <html>, <head>, or <body> tags
- <h2> for the chapter title
- <h3> for section headings within the chapter
- <p> for body text
- <blockquote> for a particularly resonant phrase or reflection
- <div class="moment"> with <p class="moment-date"> and <p class="moment-text">
  to isolate one vivid scene or day worth holding apart from the flow
- <div class="divider">✦</div> between major sections
- Write in third person; refer to the subject by first name only
"""


def _build_prompt(entries: list[Entry], period_start: date, period_end: date) -> str:
    start_str = period_start.strftime("%-d %B")
    end_str   = period_end.strftime("%-d %B %Y")
    lines = [
        f"Period: {start_str} – {end_str}",
        f"Subject: {USER_NAME}",
        "",
        "Entries (chronological):",
    ]
    kind_label = {"note": "Note", "voice": "Voice memo", "photo": "Photo"}
    for e in entries:
        label = kind_label.get(e.kind, e.kind.title())
        lines.append(f"\n[{e.timestamp.strftime('%-d %B, %H:%M')} — {label}]")
        lines.append(e.text.strip())
    return "\n".join(lines)

# ── Core functions ────────────────────────────────────────────────────────────

async def collect_entries(
    since: date,
    until: date,
    inbox_dir: Path = INBOX_DIR,
) -> list[Entry]:
    """Return all processed .txt entries in [since, until], sorted by time."""
    entries: list[Entry] = []

    for txt_path in sorted(inbox_dir.glob("*.txt")):
        # Expected stem: YYYY-MM-DD_HHMMSS_kind
        parts = txt_path.stem.split("_")
        if len(parts) < 3:
            continue
        try:
            ts = datetime.strptime(f"{parts[0]}_{parts[1]}", "%Y-%m-%d_%H%M%S")
        except ValueError:
            continue
        if not (since <= ts.date() <= until):
            continue
        kind = parts[2]
        if kind not in ("note", "voice", "photo"):
            continue
        async with aiofiles.open(txt_path, encoding="utf-8") as f:
            text = await f.read()
        if text.strip():
            entries.append(Entry(timestamp=ts, kind=kind, text=text))

    logger.info("collected %d entries (%s → %s)", len(entries), since, until)
    return entries


async def synthesize(entries: list[Entry], period_start: date, period_end: date) -> str:
    """Call Claude and return biography HTML for the given entries."""
    if not entries:
        raise ValueError("no entries to synthesize for this period")

    msg = await _client().messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system=_SYSTEM.format(name=USER_NAME.split()[0]),
        messages=[
            {"role": "user", "content": _build_prompt(entries, period_start, period_end)}
        ],
    )
    html = msg.content[0].text
    logger.info("synthesized %d entries → %d chars", len(entries), len(html))
    return html


async def synthesize_and_save(
    period_start: date,
    period_end: date,
    inbox_dir: Path = INBOX_DIR,
    biographies_dir: Path = BIOGRAPHIES_DIR,
) -> tuple[Path, int]:
    """Collect → synthesize → save inner HTML.

    Returns (content_html_path, entry_count). The content file is an
    intermediate artifact; render.py injects it into the full template.
    """
    biographies_dir.mkdir(exist_ok=True)
    entries = await collect_entries(since=period_start, until=period_end,
                                    inbox_dir=inbox_dir)
    html = await synthesize(entries, period_start, period_end)
    out_path = biographies_dir / f"{period_end.isoformat()}_content.html"
    async with aiofiles.open(out_path, "w", encoding="utf-8") as f:
        await f.write(html)
    logger.info("saved → %s", out_path.name)
    return out_path, len(entries)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")

    period_days = int(os.getenv("BIOGRAPHY_PERIOD_DAYS", "14"))
    end   = date.today()
    start = end - timedelta(days=period_days - 1)

    if len(sys.argv) == 3:
        start = date.fromisoformat(sys.argv[1])
        end   = date.fromisoformat(sys.argv[2])

    path, count = asyncio.run(synthesize_and_save(start, end))
    print(f"saved: {path}  ({count} entries)")
