import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import aiofiles
from dotenv import load_dotenv
from retries import with_retry

load_dotenv()

logger = logging.getLogger("quill.synthesize")

MOCK      = os.getenv("QUILL_MOCK", "").lower() in ("1", "true")
USER_NAME = os.getenv("USER_NAME", "Your Name")

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

This biography spans multiple chapters. If the user message includes a prior
chapter, maintain narrative continuity: do not re-introduce people or settings
already established, develop recurring themes, and let the reader sense the
passage of time across a single, continuous life.

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

Craft principles (follow these as closely as the output rules):
- Select, do not cover. Choose the 2–3 most vivid or meaningful moments; leave
  the rest out entirely. A chapter that says one true thing is better than one
  that accounts for everything.
- Show, do not interpret. Render the scene or the moment in concrete detail. Do
  not explain what a detail reveals about the subject's psychology, character, or
  word choices — trust the reader to feel it.
- Earn your sections. Use <h3> only to mark a genuine thematic or temporal shift,
  not to introduce each entry. A chapter of five entries should have at most 2–3
  sections.
- Use <blockquote> sparingly: at most once per chapter, for a phrase that
  genuinely needs to stand alone. Same rule for <div class="moment">.
- Where entries are sparse or uneventful, write a shorter chapter. Resist padding
  with reflection. Aim for roughly 60–80 words per entry; never exceed 800 words
  regardless of entry count.
"""


def _build_prompt(
    entries: list[Entry],
    period_start: date,
    period_end: date,
    prior_text: str | None = None,
) -> str:
    start_str = period_start.strftime("%-d %B")
    end_str   = period_end.strftime("%-d %B %Y")
    lines: list[str] = []
    if prior_text:
        lines += [
            "=== Previous chapter (narrative context — do not repeat) ===",
            prior_text.strip(),
            "",
            "=== New entries for this chapter ===",
        ]
    lines += [
        f"Period: {start_str} – {end_str}",
        f"Subject: {USER_NAME}",
        "",
        f"Entries ({len(entries)} total, chronological):",
    ]
    kind_label = {"note": "Note", "voice": "Voice memo", "photo": "Photo"}
    for e in entries:
        label = kind_label.get(e.kind, e.kind.title())
        lines.append(f"\n[{e.timestamp.strftime('%-d %B, %H:%M')} — {label}]")
        lines.append(e.text.strip())
    return "\n".join(lines)

# ── Prior-chapter loader ──────────────────────────────────────────────────────

async def _load_prior_chapter(
    biographies_dir: Path,
    current_end: date | None = None,
) -> str | None:
    """Return the HTML of the most recent chapter before *current_end*, if any.

    File names are YYYY-MM-DD_content.html, so lexicographic sort == chronological.
    """
    content_files = sorted(biographies_dir.glob("*_content.html"))
    if current_end:
        exclude = f"{current_end.isoformat()}_content.html"
        content_files = [f for f in content_files if f.name < exclude]
    if not content_files:
        return None
    async with aiofiles.open(content_files[-1], encoding="utf-8") as f:
        html = await f.read()
    logger.info("loaded prior chapter: %s", content_files[-1].name)
    return html

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
        kind = parts[-1]
        if kind not in ("note", "voice", "photo"):
            continue
        async with aiofiles.open(txt_path, encoding="utf-8") as f:
            text = await f.read()
        if text.strip():
            entries.append(Entry(timestamp=ts, kind=kind, text=text))

    logger.info("collected %d entries (%s → %s)", len(entries), since, until)
    return entries


async def synthesize(
    entries: list[Entry],
    period_start: date,
    period_end: date,
    prior_html: str | None = None,
) -> str:
    """Call Claude and return biography HTML for the given entries.

    If *prior_html* is provided it is stripped to plain text and prepended to
    the prompt so Claude can maintain narrative continuity across chapters.
    """
    if not entries:
        raise ValueError("no entries to synthesize for this period")

    prior_text: str | None = None
    if prior_html:
        plain = re.sub(r"<[^>]+>", " ", prior_html)
        plain = re.sub(r"[ \t]+", " ", plain)
        prior_text = plain.strip()

    client = _client()
    prompt = _build_prompt(entries, period_start, period_end, prior_text=prior_text)
    system = _SYSTEM.format(name=USER_NAME.split()[0])

    model = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")
    msg = await with_retry(
        lambda: client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        ),
        attempts=3, base_delay=4.0, timeout=90.0, label="claude",
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
    prior_html = await _load_prior_chapter(biographies_dir, current_end=period_end)
    entries = await collect_entries(since=period_start, until=period_end,
                                    inbox_dir=inbox_dir)
    html = await synthesize(entries, period_start, period_end, prior_html=prior_html)
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
