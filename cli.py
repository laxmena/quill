import asyncio
import os
from datetime import date, timedelta
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

console = Console()

BASE_DIR              = Path(__file__).parent
INBOX_DIR             = BASE_DIR / "inbox"
BIOGRAPHIES_DIR       = BASE_DIR / "biographies"
BIOGRAPHY_PERIOD_DAYS = int(os.getenv("BIOGRAPHY_PERIOD_DAYS", "14"))


@click.group()
def cli():
    """Quill — personal historian."""


@cli.command()
def status():
    """Show inbox item counts and last biography date."""
    from processor import load_state

    items = list(INBOX_DIR.iterdir()) if INBOX_DIR.exists() else []
    kinds = {"note": 0, "voice": 0, "photo": 0}
    for f in items:
        parts = f.stem.split("_")
        k = parts[2] if len(parts) >= 3 else ""
        if k in kinds:
            kinds[k] += 1

    state = load_state()
    pdfs  = sorted(BIOGRAPHIES_DIR.glob("*.pdf")) if BIOGRAPHIES_DIR.exists() else []

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]inbox[/dim]",
              f"{len(items)} items  "
              f"({kinds['note']} notes · {kinds['voice']} voice · {kinds['photo']} photos)")
    t.add_row("[dim]last biography[/dim]",      state.get("last_run_date") or "none yet")
    t.add_row("[dim]biographies generated[/dim]", str(state.get("biography_count", 0)))
    t.add_row("[dim]PDFs on disk[/dim]",         str(len(pdfs)))
    console.print(t)


@cli.command("process-inbox")
def process_inbox_cmd():
    """Transcribe voice notes and describe photos without synthesizing."""
    from processor import process_inbox
    n = asyncio.run(process_inbox())
    console.print(f"Processed [bold]{n}[/bold] file(s).")


@cli.command()
@click.option("--from", "from_date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None,
              help="Period start (YYYY-MM-DD). Defaults to today − BIOGRAPHY_PERIOD_DAYS.")
@click.option("--to",   "to_date",   type=click.DateTime(formats=["%Y-%m-%d"]), default=None,
              help="Period end (YYYY-MM-DD). Defaults to today.")
@click.option("--no-email", is_flag=True, default=False, help="Skip email delivery.")
def run(from_date, to_date, no_email):
    """Run the full pipeline: transcribe → synthesize → render → deliver."""
    from processor import run_pipeline
    end   = to_date.date()   if to_date   else date.today()
    start = from_date.date() if from_date else end - timedelta(days=BIOGRAPHY_PERIOD_DAYS - 1)
    console.print(f"Running pipeline [bold]{start}[/bold] → [bold]{end}[/bold] …")
    html_path, pdf_path = asyncio.run(run_pipeline(start, end, deliver_email=not no_email))
    console.print("[green]✓ Done[/green]")
    console.print(f"  HTML: {html_path}")
    console.print(f"  PDF:  {pdf_path}")


@cli.command()
@click.option("--from", "from_date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--to",   "to_date",   type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
def preview(from_date, to_date):
    """Synthesize and render without sending email."""
    from processor import run_pipeline
    end   = to_date.date()   if to_date   else date.today()
    start = from_date.date() if from_date else end - timedelta(days=BIOGRAPHY_PERIOD_DAYS - 1)
    console.print(f"Previewing [bold]{start}[/bold] → [bold]{end}[/bold] …")
    html_path, pdf_path = asyncio.run(run_pipeline(start, end, deliver_email=False))
    console.print(f"[green]✓ Done[/green]  open {html_path}")


@cli.command("set-webhook")
def set_webhook():
    """Register the Telegram webhook URL from .env with Telegram's API."""
    import json as _json
    import urllib.request
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    base  = os.getenv("TELEGRAM_WEBHOOK_URL", "")
    if not token or not base:
        console.print("[red]TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_URL must be set in .env[/red]")
        raise SystemExit(1)
    full_url = f"{base.rstrip('/')}/{token}"
    payload  = _json.dumps({"url": full_url}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setWebhook",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        result = _json.loads(resp.read())
    console.print(result)


@cli.command()
def start():
    """Start the background scheduler (runs indefinitely)."""
    from processor import start_scheduler
    asyncio.run(start_scheduler())


if __name__ == "__main__":
    cli()
