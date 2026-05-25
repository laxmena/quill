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
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


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
    await update.message.reply_text(
        f"Hello, {first_name}. 👋\n\n"
        "I'm Quill, your personal historian. Send me voice notes, photos, or "
        "text throughout your days and every two weeks I'll weave them into a "
        "biography chapter delivered to your inbox.\n\n"
        "Commands:\n"
        "  /preview      — read a draft chapter right now\n"
        "  /status       — see what's in your chronicle\n"
        "  /delete-last  — remove the last thing you sent\n"
        "  /help         — full guide\n\n"
        "Privacy: your voice notes are transcribed by OpenAI Whisper, photos "
        "described by GPT-4o, and entries synthesised into prose by Claude. "
        "Everything runs on your own server."
    )
    logger.info("/start")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    items = [f for f in INBOX_DIR.iterdir() if f.is_file()] if INBOX_DIR.exists() else []
    count = len(items)
    noun  = "moment" if count == 1 else "moments"

    state: dict = {}
    state_file = LOGS_DIR / "state.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
        except Exception:
            pass

    last_run_str    = state.get("last_run_date")
    biography_count = state.get("biography_count", 0)
    if last_run_str:
        last_run   = date.fromisoformat(last_run_str)
        days_since = (date.today() - last_run).days
        days_until = max(0, BIOGRAPHY_PERIOD_DAYS - days_since)
        plural_c   = "s" if biography_count != 1 else ""
        plural_d   = "s" if days_until != 1 else ""
        bio_line   = (
            f"Last chapter: {last_run.strftime('%-d %B %Y')} "
            f"({biography_count} chapter{plural_c} total)\n"
            f"Next chapter in {days_until} day{plural_d}"
        )
    else:
        bio_line = f"No chapters yet — keep the notes coming."

    await update.message.reply_text(f"📬 {count} {noun} waiting to be woven\n\n{bio_line}")
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
    await update.message.reply_text("Voice note captured. I'll transcribe it tonight. ✦")


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
            "Photo added to your chronicle. 📷 I'll describe it tonight.\n\n"
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
        days_until = max(0, BIOGRAPHY_PERIOD_DAYS - (end - start).days)
        plural = "day" if days_until == 1 else "days"
        header = "📖 Draft chapter preview — the final PDF will be typeset:\n\n"
        footer = f"\n\n[{days_until} {plural} until your next biography chapter]"
        # Telegram hard-caps messages at 4096 chars
        budget = 4096 - len(header) - len(footer)
        if len(text) > budget:
            text = text[:budget - 1] + "…"
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
        "Quill — personal historian\n\n"
        "Commands:\n"
        "  /status        what's in your chronicle\n"
        "  /preview       read a draft chapter right now\n"
        "  /delete-last   remove the last thing you sent\n"
        "  /help          show this message\n\n"
        "Send me:\n"
        "  🎙 Voice notes — transcribed tonight\n"
        "  📷 Photos — described tonight (add a caption for your own words)\n"
        "  🖊 Text — anything worth remembering\n\n"
        f"Every {BIOGRAPHY_PERIOD_DAYS} days I weave everything into a biography "
        "chapter and deliver it to your inbox.\n\n"
        "Privacy: voice → OpenAI Whisper · photos → GPT-4o · entries → Claude"
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
    kind_label = kind_map.get(parts[2] if len(parts) > 2 else "", "item")
    try:
        dt_str = _stem_dt(latest_stem).strftime("%-d %B at %H:%M")
    except Exception:
        dt_str = "just now"

    await update.message.reply_text(
        f"Deleted: {kind_label} from {dt_str}. It won't appear in your biography. 🗑"
    )
    logger.info("/delete-last — removed %d file(s) with stem %s",
                len(latest_files), latest_stem)


async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.reply_text(
        "I can capture voice notes, photos, and text. 🖊\n\n"
        "Try sending one of those!"
    )


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
