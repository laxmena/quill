import os
from datetime import date
from pathlib import Path

from render import _fill_template, render, render_from_file


CONTENT_HTML = "<h2>Test Chapter</h2><p>A quiet fortnight.</p>"


# ── _fill_template ─────────────────────────────────────────────────────────────

def test_fill_template_no_leftover_placeholders(period):
    start, end = period
    result = _fill_template(CONTENT_HTML, start, end, entry_count=10)
    assert "{{" not in result
    assert "}}" not in result


def test_fill_template_injects_content(period):
    start, end = period
    result = _fill_template(CONTENT_HTML, start, end, entry_count=5)
    assert CONTENT_HTML in result


def test_fill_template_injects_username(period):
    start, end = period
    result = _fill_template(CONTENT_HTML, start, end, entry_count=5)
    user = os.getenv("USER_NAME", "Lakshmanan Meiyappan")
    assert user in result


def test_fill_template_injects_entry_count(period):
    start, end = period
    result = _fill_template(CONTENT_HTML, start, end, entry_count=42)
    assert "42" in result


def test_fill_template_produces_valid_html(period):
    start, end = period
    result = _fill_template(CONTENT_HTML, start, end, entry_count=1)
    assert result.startswith("<!DOCTYPE html>")
    assert "</html>" in result


# ── render ─────────────────────────────────────────────────────────────────────

async def test_render_saves_html(tmp_biographies, period, mock_playwright):
    start, end = period
    html_path, _ = await render(CONTENT_HTML, start, end, entry_count=3,
                                biographies_dir=tmp_biographies)
    assert html_path.exists()
    content = html_path.read_text()
    assert "{{" not in content
    assert CONTENT_HTML in content


async def test_render_saves_pdf(tmp_biographies, period, mock_playwright):
    start, end = period
    _, pdf_path = await render(CONTENT_HTML, start, end, entry_count=3,
                               biographies_dir=tmp_biographies)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


async def test_render_filenames_use_period_end(tmp_biographies, period, mock_playwright):
    start, end = period
    html_path, pdf_path = await render(CONTENT_HTML, start, end,
                                       biographies_dir=tmp_biographies)
    assert html_path.stem == end.isoformat()
    assert pdf_path.stem == end.isoformat()


async def test_render_from_file(tmp_path, tmp_biographies, period, mock_playwright):
    start, end = period
    content_file = tmp_path / f"{end.isoformat()}_content.html"
    content_file.write_text(CONTENT_HTML)
    html_path, pdf_path = await render_from_file(
        content_file, start, end, biographies_dir=tmp_biographies
    )
    assert html_path.exists()
    assert pdf_path.exists()
