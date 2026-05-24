import pytest
from datetime import date
from pathlib import Path
from deliver import _build_message, deliver


@pytest.fixture
def pdf_file(tmp_path):
    f = tmp_path / "2024-05-14.pdf"
    f.write_bytes(b"%PDF-1.4 mock content for testing")
    return f


# ── mock mode ─────────────────────────────────────────────────────────────────

async def test_deliver_mock_succeeds(pdf_file, period):
    start, end = period
    await deliver(pdf_file, start, end, entry_count=5)  # must not raise


async def test_deliver_mock_does_not_call_smtp(pdf_file, period, monkeypatch):
    smtp_called = []
    monkeypatch.setattr("deliver._send_sync", lambda msg: smtp_called.append(True))
    start, end = period
    await deliver(pdf_file, start, end, entry_count=5)
    assert not smtp_called


# ── real mode validation ───────────────────────────────────────────────────────

async def test_deliver_real_raises_without_credentials(tmp_path, period, monkeypatch):
    monkeypatch.setattr("deliver.MOCK", False)
    monkeypatch.setattr("deliver.GMAIL_ADDRESS", "")
    monkeypatch.setattr("deliver.GMAIL_APP_PASSWORD", "")
    monkeypatch.setattr("deliver.BIOGRAPHY_RECIPIENT_EMAIL", "")
    pdf = tmp_path / "2024-05-14.pdf"
    pdf.write_bytes(b"%PDF mock")
    start, end = period
    with pytest.raises(ValueError, match="must all be set"):
        await deliver(pdf, start, end)


# ── message construction ──────────────────────────────────────────────────────

def test_build_message_subject_contains_year(pdf_file, period):
    start, end = period
    msg = _build_message(pdf_file, b"%PDF mock", start, end, entry_count=7)
    assert "2024" in msg["Subject"]
    assert msg["Subject"].startswith("Your Quill Biography")


def test_build_message_has_html_body_and_pdf(pdf_file, period):
    start, end = period
    msg = _build_message(pdf_file, b"%PDF mock", start, end, entry_count=7)
    payloads = msg.get_payload()
    assert len(payloads) == 2
    assert payloads[0].get_content_type() == "text/html"
    assert payloads[1].get_content_type() == "application/pdf"


def test_build_message_pdf_filename(pdf_file, period):
    start, end = period
    msg = _build_message(pdf_file, b"%PDF mock", start, end, entry_count=3)
    attachment = msg.get_payload()[1]
    assert pdf_file.name in attachment.get("Content-Disposition", "")


def test_build_message_entry_count_in_body(pdf_file, period):
    start, end = period
    msg = _build_message(pdf_file, b"%PDF mock", start, end, entry_count=23)
    body_html = msg.get_payload()[0].get_payload(decode=True).decode("utf-8")
    assert "23" in body_html
