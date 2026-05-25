import json
import logging
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import aiofiles
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN             = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL           = os.getenv("TELEGRAM_WEBHOOK_URL", "")
WEBHOOK_SECRET        = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
USER_NAME             = os.getenv("USER_NAME", "Your Name")
BIOGRAPHY_PERIOD_DAYS = int(os.getenv("BIOGRAPHY_PERIOD_DAYS", "14"))
PROCESSING_HOUR       = max(0, min(23, int(os.getenv("PROCESSING_HOUR", "2"))))
PORT                  = int(os.getenv("PORT", "8443"))

_raw_chat_id = os.getenv("TELEGRAM_ALLOWED_CHAT_ID", "")
ALLOWED_CHAT_ID: int | None = int(_raw_chat_id) if _raw_chat_id.lstrip("-").isdigit() else None

BASE_DIR        = Path(__file__).parent
INBOX_DIR       = BASE_DIR / "inbox"
BIOGRAPHIES_DIR = BASE_DIR / "biographies"
LOGS_DIR        = BASE_DIR / "logs"

# ── Bootstrap directories ─────────────────────────────────────────────────────
INBOX_DIR.mkdir(exist_ok=True)
BIOGRAPHIES_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOGS_DIR / "quill.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("quill.bot")

console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────────
def ts() -> str:
    import secrets
    return datetime.now().strftime("%Y-%m-%d_%H%M%S") + "_" + secrets.token_hex(3)


def _hour_label(h: int) -> str:
    period = "AM" if h < 12 else "PM"
    display = h % 12 or 12
    return f"{display}:00 {period}"


HOUR_LABEL = _hour_label(PROCESSING_HOUR)


def _allowed(update: Update) -> bool:
    if ALLOWED_CHAT_ID is None:
        return True
    if update.effective_chat and update.effective_chat.id == ALLOWED_CHAT_ID:
        return True
    chat_id = update.effective_chat.id if update.effective_chat else "unknown"
    logger.warning("blocked message from unauthorized chat_id=%s", chat_id)
    return False


# ── Preview rendering ─────────────────────────────────────────────────────────

def _html_to_preview(html: str) -> str:
    """Convert biography HTML to structured plain text suitable for Telegram."""
    # Chapter title → bold-style marker
    html = re.sub(r"<h2[^>]*>(.*?)</h2>",
                  lambda m: f"\n✦ {re.sub('<[^>]+>', '', m.group(1)).strip()} ✦\n",
                  html, flags=re.DOTALL | re.IGNORECASE)
    # Section headings
    html = re.sub(r"<h3[^>]*>(.*?)</h3>",
                  lambda m: f"\n— {re.sub('<[^>]+>', '', m.group(1)).strip()} —\n",
                  html, flags=re.DOTALL | re.IGNORECASE)
    # Blockquotes → quoted lines
    html = re.sub(r"<blockquote[^>]*>(.*?)</blockquote>",
                  lambda m: f'\n“{re.sub("<[^>]+>", "", m.group(1)).strip()}”\n',
                  html, flags=re.DOTALL | re.IGNORECASE)
    # Section dividers
    html = re.sub(r'<div[^>]*class="divider"[^>]*>.*?</div>',
                  "\n─ ✦ ─\n", html, flags=re.DOTALL | re.IGNORECASE)
    # Paragraphs → double newlines
    html = re.sub(r"<p[^>]*>(.*?)</p>",
                  lambda m: re.sub("<[^>]+>", "", m.group(1)).strip() + "\n\n",
                  html, flags=re.DOTALL | re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", html)
    # Normalise whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# ── Command handlers ──────────────────────────────────────────────────────────
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    first_name = USER_NAME.split()[0]
    period_desc = "every two weeks" if BIOGRAPHY_PERIOD_DAYS == 14 else f"every {BIOGRAPHY_PERIOD_DAYS} days"
    await update.message.reply_text(
        f"Hello, {first_name}. 👋\n\n"
        f"I'm Quill, your personal historian. Send me voice notes, photos, or "
        f"text throughout your days and {period_desc} I'll weave them into a "
        "biography chapter and deliver it to your inbox. 📬\n\n"
        "If you go quiet for a few days I'll send a gentle nudge to keep the notes coming.\n\n"
        "Commands:\n"
        "  /preview      — read a draft chapter right now\n"
        "  /status       — see what's in your chronicle\n"
        "  /delete-last  — remove the last thing you sent\n"
        "  /help         — full guide\n\n"
        "Privacy: your voice notes are transcribed by OpenAI Whisper, photos described "
        "by GPT-4o Vision, and entries synthesised into prose by Claude. Your data is "
        "processed by OpenAI and Anthropic but never stored by Quill."
    )
    logger.info("/start")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    # Group by stem so a transcribed voice note (ogg + txt) counts as one entry.
    by_stem: dict[str, list[Path]] = defaultdict(list)
    if INBOX_DIR.exists():
        for f in INBOX_DIR.iterdir():
            if f.is_file():
                by_stem[f.stem].append(f)

    kinds: dict[str, int] = {"voice": 0, "photo": 0, "note": 0}
    pending = 0  # entries whose media file has no .txt companion yet
    for stem, files in by_stem.items():
        parts = stem.split("_")
        k = parts[-1] if len(parts) >= 3 else ""
        if k in kinds:
            kinds[k] += 1
        exts = {f.suffix for f in files}
        if exts & {".ogg", ".jpg", ".jpeg", ".png"} and ".txt" not in exts:
            pending += 1

    count = len(by_stem)
    run_hour = HOUR_LABEL
    if count == 0:
        breakdown = "nothing yet"
    else:
        parts_list = []
        if kinds["voice"]:
            parts_list.append(f"{kinds['voice']} voice note{'s' if kinds['voice'] != 1 else ''}")
        if kinds["photo"]:
            parts_list.append(f"{kinds['photo']} photo{'s' if kinds['photo'] != 1 else ''}")
        if kinds["note"]:
            parts_list.append(f"{kinds['note']} text note{'s' if kinds['note'] != 1 else ''}")
        breakdown = ", ".join(parts_list) if parts_list else f"{count} item{'s' if count != 1 else ''}"
        if pending:
            breakdown += f" ({pending} pending processing at {run_hour})"

    state: dict = {}
    state_file = LOGS_DIR / "state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
        except Exception:
            pass

    last_run_str    = state.get("last_run_date")
    biography_count = state.get("biography_count", 0)
    last_run        = None
    if last_run_str:
        try:
            last_run = date.fromisoformat(last_run_str)
        except ValueError:
            last_run_str = None
    if last_run:
        days_since = max(0, (date.today() - last_run).days)
        days_until = max(0, BIOGRAPHY_PERIOD_DAYS - days_since)
        plural_c   = "s" if biography_count != 1 else ""
        if days_until == 0:
            next_line = f"Next chapter due today — compiling at {run_hour}"
        else:
            plural_d = "s" if days_until != 1 else ""
            next_line = f"Next chapter in {days_until} day{plural_d}"
        bio_line   = (
            f"Last chapter: {last_run.strftime('%-d %B %Y')} "
            f"({biography_count} chapter{plural_c} total)\n"
            + next_line
        )
    else:
        now = datetime.now()
        first_when = f"tonight at {run_hour}" if now.hour < PROCESSING_HOUR else f"tomorrow at {run_hour}"
        bio_line = f"No chapters yet — first chapter compiles {first_when}."

    inbox_line = "Nothing captured yet" if count == 0 else f"{breakdown} waiting to be woven"
    await update.message.reply_text(
        f"📬 {inbox_line}\n\n{bio_line}"
    )
    logger.info("/status — %d item(s) in inbox", count)


# ── Message handlers ──────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    filepath = INBOX_DIR / f"{ts()}_note.txt"
    try:
        async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
            await f.write(update.message.text)
    except Exception:
        logger.exception("failed to save text note")
        filepath.unlink(missing_ok=True)
        await update.message.reply_text(
            "I had trouble saving that note — could you try again? 🖊"
        )
        return
    logger.info("saved text  → %s", filepath.name)
    await update.message.reply_text("Noted. I'll weave it in. 🖊")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    filepath = INBOX_DIR / f"{ts()}_voice.ogg"
    try:
        voice_file = await update.message.voice.get_file()
        await voice_file.download_to_drive(filepath)
    except Exception:
        logger.exception("failed to save voice note")
        filepath.unlink(missing_ok=True)
        await update.message.reply_text(
            "I had trouble saving that voice note — could you try again? 🎙"
        )
        return
    logger.info("saved voice → %s", filepath.name)
    await update.message.reply_text(
        f"Voice note captured. I'll transcribe it at {HOUR_LABEL}. ✦"
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    stamp    = ts()
    filepath = INBOX_DIR / f"{stamp}_photo.jpg"
    try:
        photo_file = await update.message.photo[-1].get_file()  # highest resolution
        await photo_file.download_to_drive(filepath)
    except Exception:
        logger.exception("failed to save photo")
        filepath.unlink(missing_ok=True)
        await update.message.reply_text(
            "I had trouble saving that photo — could you try again? 📷"
        )
        return
    logger.info("saved photo → %s", filepath.name)

    caption = getattr(update.message, "caption", None)
    if caption:
        txt_path = INBOX_DIR / f"{stamp}_photo.txt"
        try:
            async with aiofiles.open(txt_path, "w", encoding="utf-8") as f:
                await f.write(caption)
            logger.info("saved caption → %s", txt_path.name)
        except Exception:
            logger.exception("failed to save photo caption")
            txt_path.unlink(missing_ok=True)
            await update.message.reply_text(
                "Photo saved, but I had trouble saving your caption — "
                "send it as a text message and I'll pair them up."
            )
            return
        await update.message.reply_text(
            f"Photo and caption added to your chronicle. 📷\n\n\"{caption}\""
        )
    else:
        await update.message.reply_text(
            f"Photo added to your chronicle. 📷 I'll describe it at {HOUR_LABEL}.\n\n"
            "Tip: send a caption with your photo and I'll use your words instead."
        )


async def handle_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.reply_text("Composing your preview… this may take a moment.")
    try:
        from synthesize import collect_entries, synthesize, _load_prior_chapter
        end   = date.today()
        start = end - timedelta(days=BIOGRAPHY_PERIOD_DAYS - 1)
        entries = await collect_entries(since=start, until=end)
        if not entries:
            await update.message.reply_text(
                "Nothing in your chronicle yet for this period. "
                "Send me some notes, voice memos, or photos first."
            )
            return
        prior_html = await _load_prior_chapter(BIOGRAPHIES_DIR, current_end=end)
        html = await synthesize(entries, start, end, prior_html=prior_html)
        text = _html_to_preview(html)
        # Compute days until next chapter from last_run_date, not from period length.
        state_file = LOGS_DIR / "state.json"
        days_until = BIOGRAPHY_PERIOD_DAYS
        try:
            if state_file.exists():
                async with aiofiles.open(state_file, "r", encoding="utf-8") as _sf:
                    state = json.loads(await _sf.read())
                last_run_str = state.get("last_run_date")
                if last_run_str:
                    last = date.fromisoformat(last_run_str)
                    days_until = max(0, BIOGRAPHY_PERIOD_DAYS - (end - last).days)
        except Exception:
            pass
        entry_noun = "entry" if len(entries) == 1 else "entries"
        header = f"📖 Draft chapter preview ({len(entries)} {entry_noun}) — the final PDF will be typeset:\n\n"
        if days_until == 0:
            footer = f"\n\n[Chapter due today — compiling at {HOUR_LABEL}]"
        else:
            plural = "day" if days_until == 1 else "days"
            footer = f"\n\n[{days_until} {plural} until your next biography chapter]"
        # Telegram hard-caps messages at 4096 chars
        truncation_note = "\n\n[Preview trimmed — the full chapter appears in your PDF]"
        budget = 4096 - len(header) - len(footer)
        if len(text) > budget:
            budget -= len(truncation_note)
            text = text[:budget - 1] + "…" + truncation_note
        await update.message.reply_text(header + text + footer)
        logger.info("/preview — sent %d chars to owner", len(header) + len(text) + len(footer))
    except Exception:
        logger.exception("/preview failed")
        await update.message.reply_text(
            "Something went wrong while composing your preview — try again in a moment. "
            "Your notes are all safe."
        )


async def handle_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.reply_text(
        "<b>Quill — personal historian</b>\n\n"
        "<b>Commands</b>\n"
        "  <code>/preview</code>      — read a draft chapter right now\n"
        "  <code>/status</code>       — see what's in your chronicle\n"
        "  <code>/delete-last</code>  — remove the last thing you sent\n"
        "  <code>/help</code>         — show this message\n\n"
        "<b>Send me</b>\n"
        f"  🎙 Voice notes — transcribed at {HOUR_LABEL}\n"
        f"  📷 Photos — described at {HOUR_LABEL} (add a caption for your own words)\n"
        "  🖊 Text — anything worth remembering\n\n"
        + (
            "Every two weeks I weave everything into a biography "
            if BIOGRAPHY_PERIOD_DAYS == 14
            else f"Every {BIOGRAPHY_PERIOD_DAYS} day{'s' if BIOGRAPHY_PERIOD_DAYS != 1 else ''} I weave everything into a biography "
        ) +
        "chapter and deliver it to your inbox.\n\n"
        "<b>Nudge</b>: if you go quiet for a few days I'll send a gentle reminder.\n\n"
        "<b>Privacy</b>: voice → OpenAI Whisper · photos → GPT-4o · entries → Claude",
        parse_mode="HTML",
    )
    logger.info("/help")


async def handle_delete_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    files = [f for f in INBOX_DIR.iterdir() if f.is_file()] if INBOX_DIR.exists() else []
    if not files:
        await update.message.reply_text("Your inbox is empty — nothing to delete.")
        return

    def _stem_dt(stem: str) -> datetime:
        parts = stem.split("_")
        try:
            return datetime.strptime(f"{parts[0]}_{parts[1]}", "%Y-%m-%d_%H%M%S")
        except (ValueError, IndexError):
            return datetime.min

    by_stem: dict[str, list[Path]] = defaultdict(list)
    for f in files:
        by_stem[f.stem].append(f)

    latest_stem  = max(by_stem.keys(), key=_stem_dt)
    latest_files = by_stem[latest_stem]
    for f in latest_files:
        f.unlink()
        logger.info("/delete-last removed %s", f.name)

    parts      = latest_stem.split("_")
    kind_map   = {"note": "note", "voice": "voice note", "photo": "photo"}
    kind_label = kind_map.get(parts[-1] if len(parts) > 1 else "", "item")
    try:
        dt_str = _stem_dt(latest_stem).strftime("%-d %B at %H:%M")
    except Exception:
        dt_str = "just now"

    n_files = len(latest_files)
    caption_note = " (including caption)" if n_files > 1 and parts[-1] == "photo" else ""
    await update.message.reply_text(
        f"Deleted: {kind_label} from {dt_str}{caption_note}. It won't appear in your biography. 🗑\n\n"
        "Your chronicle continues — keep sending me notes."
    )
    logger.info("/delete-last — removed %d file(s) with stem %s",
                len(latest_files), latest_stem)


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    msg = update.message
    if msg.video or msg.video_note:
        hint = "Video messages aren't supported yet — try recording a voice note inside Telegram instead. 🎙"
    elif msg.audio:
        hint = "That looks like an audio file. For best results, record directly inside Telegram as a voice note. 🎙"
    elif msg.sticker:
        hint = "Stickers can't be saved to your chronicle — try a text note or photo. 🖊"
    elif msg.document:
        hint = "Documents aren't supported — try sending a photo, voice note, or text. 🖊"
    else:
        hint = "I can capture voice notes, photos, and text. 🖊\n\nTry sending one of those!"
    await update.message.reply_text(hint)


# ── Startup banner ────────────────────────────────────────────────────────────
def _print_startup(mode: str) -> None:
    console.print()
    console.print(Panel.fit("[bold]Quill[/bold]  [dim]personal historian[/dim]",
                            border_style="bright_black"))
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]mode   [/dim]", mode)
    if WEBHOOK_URL:
        t.add_row("[dim]webhook[/dim]", WEBHOOK_URL)
        t.add_row("[dim]port   [/dim]", str(PORT))
    t.add_row("[dim]inbox  [/dim]", str(INBOX_DIR))
    console.print(t)
    console.print()


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        raise SystemExit(1)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",       handle_start))
    app.add_handler(CommandHandler("status",      handle_status))
    app.add_handler(CommandHandler("preview",     handle_preview))
    app.add_handler(CommandHandler("help",        handle_help))
    app.add_handler(CommandHandler("delete-last", handle_delete_last))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(
        ~filters.COMMAND & ~filters.TEXT & ~filters.VOICE & ~filters.PHOTO,
        handle_unknown,
    ))

    if ALLOWED_CHAT_ID is None:
        logger.warning(
            "TELEGRAM_ALLOWED_CHAT_ID is not set — any Telegram user who "
            "finds this bot can invoke commands and burn API quota; set your "
            "numeric chat ID in .env to restrict access"
        )

    if WEBHOOK_URL:
        _print_startup("webhook")
        if not WEBHOOK_SECRET:
            logger.warning(
                "TELEGRAM_WEBHOOK_SECRET is not set — webhook requests are unauthenticated; "
                "set a long random string in .env to enable Telegram's HMAC verification"
            )
        webhook_path     = BOT_TOKEN
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{webhook_path}"
        logger.info("starting webhook on :%d (token path redacted)", PORT)
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=full_webhook_url,
            secret_token=WEBHOOK_SECRET or None,
        )
    else:
        _print_startup("polling  [dim](set TELEGRAM_WEBHOOK_URL to switch to webhook)[/dim]")
        logger.info("starting polling")
        app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
