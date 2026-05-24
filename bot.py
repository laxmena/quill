import logging
import os
import re
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
USER_NAME             = os.getenv("USER_NAME", "Lakshmanan Meiyappan")
BIOGRAPHY_PERIOD_DAYS = int(os.getenv("BIOGRAPHY_PERIOD_DAYS", "14"))
PORT                  = 8443

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


def last_biography() -> str | None:
    pdfs = sorted(BIOGRAPHIES_DIR.glob("*.pdf"))
    return pdfs[-1].stem if pdfs else None


# ── Command handlers ──────────────────────────────────────────────────────────
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    first_name = USER_NAME.split()[0]
    await update.message.reply_text(
        f"Hello, {first_name}. 👋\n\n"
        "I'm Quill, your personal historian. Send me anything — "
        "a thought, a voice note, or a photo — and I'll remember it for you. "
        "Every two weeks I'll weave it all into a biography and deliver it "
        "to your inbox.\n\n"
        "Use /status to see what I've collected so far, "
        "or /preview to read a draft of what's been written."
    )
    logger.info("/start")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    items = list(INBOX_DIR.iterdir()) if INBOX_DIR.exists() else []
    count = len(items)
    noun  = "item" if count == 1 else "items"
    bio   = last_biography()
    bio_line = f"Last biography: {bio}" if bio else "No biographies generated yet."
    await update.message.reply_text(f"📬 {count} {noun} in inbox\n{bio_line}")
    logger.info("/status — %d item(s) in inbox", count)


# ── Message handlers ──────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    filepath = INBOX_DIR / f"{ts()}_note.txt"
    async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
        await f.write(update.message.text)
    logger.info("saved text  → %s", filepath.name)
    await update.message.reply_text("Noted. I'll weave it in. 🖊")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    filepath  = INBOX_DIR / f"{ts()}_voice.ogg"
    voice_file = await update.message.voice.get_file()
    await voice_file.download_to_drive(filepath)
    logger.info("saved voice → %s", filepath.name)
    await update.message.reply_text("Voice note captured. I'll transcribe it tonight. ✦")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    filepath   = INBOX_DIR / f"{ts()}_photo.jpg"
    photo_file = await update.message.photo[-1].get_file()  # highest resolution
    await photo_file.download_to_drive(filepath)
    logger.info("saved photo → %s", filepath.name)
    await update.message.reply_text("Photo added to your chronicle. 📷")


async def handle_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.reply_text("Composing your preview… this may take a moment.")
    try:
        from synthesize import collect_entries, synthesize
        end   = date.today()
        start = end - timedelta(days=BIOGRAPHY_PERIOD_DAYS - 1)
        entries = await collect_entries(since=start, until=end)
        if not entries:
            await update.message.reply_text(
                "Nothing in your chronicle yet for this period. "
                "Send me some notes, voice memos, or photos first."
            )
            return
        html = await synthesize(entries, start, end)
        # Strip HTML tags and normalise whitespace for plain-text preview
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        # Telegram hard-caps messages at 4096 chars
        if len(text) > 3800:
            text = text[:3800] + "…\n\n[Full biography arrives in your fortnightly PDF]"
        await update.message.reply_text(text)
        logger.info("/preview — sent %d chars to owner", len(text))
    except Exception:
        logger.exception("/preview failed")
        await update.message.reply_text(
            "Something went wrong while composing your preview. "
            "Check logs/quill.log for details."
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

    app.add_handler(CommandHandler("start",   handle_start))
    app.add_handler(CommandHandler("status",  handle_status))
    app.add_handler(CommandHandler("preview", handle_preview))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

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
