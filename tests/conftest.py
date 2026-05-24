import os

# Must be set before any source module is imported so every module-level
# MOCK = os.getenv("QUILL_MOCK") resolves to True across the whole test run.
os.environ["QUILL_MOCK"] = "true"

import pytest
from datetime import date
from pathlib import Path


@pytest.fixture
def tmp_inbox(tmp_path):
    d = tmp_path / "inbox"
    d.mkdir()
    return d


@pytest.fixture
def tmp_biographies(tmp_path):
    d = tmp_path / "biographies"
    d.mkdir()
    return d


@pytest.fixture
def tmp_processed(tmp_path):
    d = tmp_path / "processed"
    d.mkdir()
    return d


@pytest.fixture
def ogg_file(tmp_inbox):
    f = tmp_inbox / "2024-05-10_143022_voice.ogg"
    f.write_bytes(b"fake ogg data")
    return f


@pytest.fixture
def jpg_file(tmp_inbox):
    f = tmp_inbox / "2024-05-10_150000_photo.jpg"
    # minimal JPEG header
    f.write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * 16)
    return f


@pytest.fixture
def period():
    return date(2024, 5, 1), date(2024, 5, 14)


@pytest.fixture
def mock_playwright(monkeypatch):
    """Patch render.async_playwright so tests never launch a real browser."""
    from unittest.mock import AsyncMock, MagicMock
    from pathlib import Path

    async def fake_pdf(path, **kwargs):
        Path(path).write_bytes(b"%PDF-1.4 mock")

    mock_page = AsyncMock()
    mock_page.pdf.side_effect = fake_pdf
    mock_page.goto = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.new_page.return_value = mock_page
    mock_browser.close = AsyncMock()

    mock_pw = AsyncMock()
    mock_pw.chromium.launch.return_value = mock_browser
    mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
    mock_pw.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("render.async_playwright", MagicMock(return_value=mock_pw))
    return mock_pw
