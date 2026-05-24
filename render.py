import asyncio
import logging
import os
from datetime import date, datetime
from pathlib import Path

import aiofiles
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

logger = logging.getLogger("quill.render")

USER_NAME = os.getenv("USER_NAME", "Lakshmanan Meiyappan")

BASE_DIR        = Path(__file__).parent
TEMPLATES_DIR   = BASE_DIR / "templates"
BIOGRAPHIES_DIR = BASE_DIR / "biographies"
TEMPLATE_PATH   = TEMPLATES_DIR / "bloomsbury.html"

# ── Template injection ────────────────────────────────────────────────────────

def _fill_template(
    content_html: str,
    period_start: date,
    period_end: date,
    entry_count: int,
) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    first_name = USER_NAME.split()[0]
    start_str  = period_start.strftime("%-d %B")
    end_str    = period_end.strftime("%-d %B %Y")

    replacements = {
        "{{ title }}":          f"{USER_NAME} — {period_end.strftime('%B %Y')}",
        "{{ user_name }}":      USER_NAME,
        "{{ subtitle }}":       f"A chronicle of {first_name}'s life, {start_str} to {end_str}",
        "{{ period_start }}":   period_start.strftime("%-d %B %Y"),
        "{{ period_end }}":     period_end.strftime("%-d %B %Y"),
        "{{ content }}":        content_html,
        "{{ generated_date }}": datetime.now().strftime("%-d %B %Y"),
        "{{ entry_count }}":    str(entry_count),
    }

    for placeholder, value in replacements.items():
        template = template.replace(placeholder, value)

    return template

# ── Core render function ──────────────────────────────────────────────────────

async def render(
    content_html: str,
    period_start: date,
    period_end: date,
    entry_count: int = 0,
    biographies_dir: Path = BIOGRAPHIES_DIR,
) -> tuple[Path, Path]:
    """Inject content into the Bloomsbury template and render to HTML + PDF.

    Saves two files:
      biographies/YYYY-MM-DD.html  — complete, self-contained HTML (A4 screen preview)
      biographies/YYYY-MM-DD.pdf   — print-ready A4 PDF via Playwright

    Returns (html_path, pdf_path).
    """
    biographies_dir.mkdir(exist_ok=True)
    stem      = period_end.isoformat()
    html_path = biographies_dir / f"{stem}.html"
    pdf_path  = biographies_dir / f"{stem}.pdf"

    # ── Write full HTML ───────────────────────────────────────────────────────
    full_html = _fill_template(content_html, period_start, period_end, entry_count)
    async with aiofiles.open(html_path, "w", encoding="utf-8") as f:
        await f.write(full_html)
    logger.info("saved HTML → %s", html_path.name)

    # ── Render PDF via Playwright ─────────────────────────────────────────────
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page    = await browser.new_page()

        # Load via file:// so relative font/asset paths resolve correctly
        await page.goto(f"file://{html_path.resolve()}", wait_until="networkidle")

        await page.pdf(
            path=str(pdf_path),
            format="A4",
            print_background=True,
            prefer_css_page_size=True,  # honour @page { size: A4 } from the stylesheet
        )
        await browser.close()

    size_kb = pdf_path.stat().st_size // 1024
    logger.info("saved PDF  → %s (%d KB)", pdf_path.name, size_kb)
    return html_path, pdf_path


async def render_from_file(
    content_path: Path,
    period_start: date,
    period_end: date,
    entry_count: int = 0,
    biographies_dir: Path = BIOGRAPHIES_DIR,
) -> tuple[Path, Path]:
    """Load inner HTML from a *_content.html file and render."""
    async with aiofiles.open(content_path, encoding="utf-8") as f:
        content_html = await f.read()
    return await render(content_html, period_start, period_end, entry_count, biographies_dir)


if __name__ == "__main__":
    import sys
    from datetime import timedelta

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-8s  %(message)s")

    if len(sys.argv) not in (2, 4):
        print("usage: python render.py <YYYY-MM-DD_content.html> [period_start period_end]")
        raise SystemExit(1)

    content_path = Path(sys.argv[1])
    if len(sys.argv) == 4:
        period_start = date.fromisoformat(sys.argv[2])
        period_end   = date.fromisoformat(sys.argv[3])
    else:
        # Infer period from filename stem: YYYY-MM-DD_content
        period_end   = date.fromisoformat(content_path.stem.split("_")[0])
        period_days  = int(os.getenv("BIOGRAPHY_PERIOD_DAYS", "14"))
        period_start = period_end - timedelta(days=period_days - 1)

    html_path, pdf_path = asyncio.run(
        render_from_file(content_path, period_start, period_end)
    )
    print(f"HTML: {html_path}")
    print(f"PDF:  {pdf_path}")
