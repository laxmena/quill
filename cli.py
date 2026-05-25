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
        k = parts[-1] if len(parts) >= 3 else ""
        if k in kinds:
            kinds[k] += 1

    state = load_state()
    pdfs  = sorted(BIOGRAPHIES_DIR.glob("*.pdf")) if BIOGRAPHIES_DIR.exists() else []

    last_run_str = state.get("last_run_date")
    if last_run_str:
        from datetime import date as _date
        last_run   = _date.fromisoformat(last_run_str)
        days_since = (_date.today() - last_run).days
        days_until = max(0, BIOGRAPHY_PERIOD_DAYS - days_since)
        next_str   = "today — compiling tonight" if days_until == 0 else f"in {days_until} day{'s' if days_until != 1 else ''}"
    else:
        next_str = "tonight (first run)"

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]inbox[/dim]",
              f"{len(items)} items  "
              f"({kinds['note']} notes · {kinds['voice']} voice · {kinds['photo']} photos)")
    t.add_row("[dim]last biography[/dim]",      last_run_str or "none yet")
    t.add_row("[dim]next chapter[/dim]",        next_str)
    t.add_row("[dim]biographies generated[/dim]", str(state.get("biography_count", 0)))
    t.add_row("[dim]PDFs on disk[/dim]",         str(len(pdfs)))
    console.print(t)


@cli.command("process-inbox")
def process_inbox_cmd():
    """Transcribe voice notes and describe photos without synthesizing."""
    from processor import process_inbox
    count, failed = asyncio.run(process_inbox())
    console.print(f"Processed [bold]{count}[/bold] file(s).")
    if failed:
        console.print(f"[yellow]⚠️  {len(failed)} file(s) could not be processed — check logs/quill.log[/yellow]")


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
    try:
        html_path, pdf_path = asyncio.run(run_pipeline(start, end, deliver_email=not no_email))
    except ValueError as exc:
        console.print(f"[yellow]Nothing to synthesize: {exc}[/yellow]")
        raise SystemExit(1)
    console.print("[green]✓ Done[/green]")
    console.print(f"  HTML: {html_path}")
    console.print(f"  PDF:  {pdf_path}")


@cli.command()
@click.option("--from", "from_date", type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
@click.option("--to",   "to_date",   type=click.DateTime(formats=["%Y-%m-%d"]), default=None)
def preview(from_date, to_date):
    """Synthesize and render without sending email, then open the HTML in a browser."""
    import webbrowser
    from processor import run_pipeline
    end   = to_date.date()   if to_date   else date.today()
    start = from_date.date() if from_date else end - timedelta(days=BIOGRAPHY_PERIOD_DAYS - 1)
    console.print(f"Previewing [bold]{start}[/bold] → [bold]{end}[/bold] …")
    try:
        html_path, pdf_path = asyncio.run(run_pipeline(start, end, deliver_email=False, commit=False))
    except ValueError as exc:
        console.print(f"[yellow]Nothing to synthesize: {exc}[/yellow]")
        raise SystemExit(1)
    console.print(f"[green]✓ Done[/green]")
    console.print(f"  HTML: {html_path}")
    console.print(f"  PDF:  {pdf_path}")
    webbrowser.open(str(html_path))


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
    full_url     = f"{base.rstrip('/')}/{token}"
    payload_dict = {"url": full_url}
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if secret:
        payload_dict["secret_token"] = secret
    payload = _json.dumps(payload_dict).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setWebhook",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = _json.loads(resp.read())
    except Exception as exc:
        console.print(f"[red]Error contacting Telegram: {type(exc).__name__} — check your token and network[/red]")
        raise SystemExit(1)
    if result.get("ok"):
        console.print("[green]✓ Webhook registered[/green]")
    else:
        console.print(f"[red]Failed: {result.get('description', result)}[/red]")
        raise SystemExit(1)


@cli.command("set-commands")
def set_commands():
    """Register the bot command menu with Telegram for native autocomplete."""
    import json as _json
    import urllib.request
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        console.print("[red]TELEGRAM_BOT_TOKEN must be set in .env[/red]")
        raise SystemExit(1)
    commands = [
        {"command": "start",       "description": "Welcome — how Quill works"},
        {"command": "preview",     "description": "Read a draft chapter right now"},
        {"command": "status",      "description": "See what's in your chronicle"},
        {"command": "delete-last", "description": "Remove the last thing you sent"},
        {"command": "help",        "description": "List all commands"},
    ]
    payload = _json.dumps({"commands": commands}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/setMyCommands",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = _json.loads(resp.read())
    except Exception as exc:
        console.print(f"[red]Error contacting Telegram: {type(exc).__name__} — check your token and network[/red]")
        raise SystemExit(1)
    if result.get("ok"):
        console.print("[green]✓ Command menu registered with Telegram[/green]")
    else:
        console.print(f"[red]Failed: {result.get('description', result)}[/red]")
        raise SystemExit(1)


@cli.command()
def start():
    """Start the background scheduler (runs indefinitely)."""
    from processor import start_scheduler
    asyncio.run(start_scheduler())


if __name__ == "__main__":
    cli()
