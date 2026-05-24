import logging
import os
from datetime import datetime
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
BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")
USER_NAME   = os.getenv("USER_NAME", "Alex Rivera")
PORT        = 8080

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


def last_biography() -> str | None:
    pdfs = sorted(BIOGRAPHIES_DIR.glob("*.pdf"))
    return pdfs[-1].stem if pdfs else None


# ── Command handlers ──────────────────────────────────────────────────────────
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    first_name = USER_NAME.split()[0]
    await update.message.reply_text(
        f"Hello, {first_name}. 👋\n\n"
        "I'm Quill, your personal historian. Send me anything — "
        "a thought, a voice note, or a photo — and I'll remember it for you. "
        "Every two weeks I'll weave it all into a biography and deliver it "
        "to your inbox.\n\n"
        "Use /status to see what I've collected so far."
    )
    logger.info("/start")


async def handle_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = list(INBOX_DIR.iterdir()) if INBOX_DIR.exists() else []
    count = len(items)
    noun  = "item" if count == 1 else "items"
    bio   = last_biography()
    bio_line = f"Last biography: {bio}" if bio else "No biographies generated yet."
    await update.message.reply_text(f"📬 {count} {noun} in inbox\n{bio_line}")
    logger.info("/status — %d item(s) in inbox", count)


# ── Message handlers ──────────────────────────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    filepath = INBOX_DIR / f"{ts()}_note.txt"
    async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
        await f.write(update.message.text)
    logger.info("saved text  → %s", filepath.name)
    await update.message.reply_text("Got it. 🖊")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    filepath  = INBOX_DIR / f"{ts()}_voice.ogg"
    voice_file = await update.message.voice.get_file()
    await voice_file.download_to_drive(filepath)
    logger.info("saved voice → %s", filepath.name)
    await update.message.reply_text("Got it. 🖊")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    filepath   = INBOX_DIR / f"{ts()}_photo.jpg"
    photo_file = await update.message.photo[-1].get_file()  # highest resolution
    await photo_file.download_to_drive(filepath)
    logger.info("saved photo → %s", filepath.name)
    await update.message.reply_text("Got it. 🖊")


# ── Startup banner ────────────────────────────────────────────────────────────
def _print_startup() -> None:
    console.print()
    console.print(Panel.fit("[bold]Quill[/bold]  [dim]personal historian[/dim]",
                            border_style="bright_black"))
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]webhook[/dim]", WEBHOOK_URL or "[red]not set[/red]")
    t.add_row("[dim]inbox  [/dim]", str(INBOX_DIR))
    t.add_row("[dim]port   [/dim]", str(PORT))
    console.print(t)
    console.print()


# ── Entry point ───────────────────────────────────────────────────────────────
def main() -> None:
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set")
        raise SystemExit(1)
    if not WEBHOOK_URL:
        logger.error("TELEGRAM_WEBHOOK_URL is not set")
        raise SystemExit(1)

    _print_startup()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",  handle_start))
    app.add_handler(CommandHandler("status", handle_status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    # Use the bot token as the URL path — prevents unauthenticated POSTs
    webhook_path = BOT_TOKEN
    full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}/{webhook_path}"

    logger.info("starting webhook on :%d → %s", PORT, full_webhook_url)
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=webhook_path,
        webhook_url=full_webhook_url,
    )


if __name__ == "__main__":
    main()
