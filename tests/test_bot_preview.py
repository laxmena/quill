"""
Tests for bot.py /preview handler.

The telegram package's Rust crypto bindings are broken in this test
environment, so we stub sys.modules before importing bot. The stubs
provide enough surface for the handler logic without a real PTB install.
"""
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Stub telegram packages before bot.py is imported
for _mod in ("telegram", "telegram.ext"):
    sys.modules[_mod] = MagicMock()

import bot  # noqa: E402 — must come after the stubs above

import pytest
from datetime import date


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def update():
    u = MagicMock()
    u.effective_chat = MagicMock()
    u.effective_chat.id = 99999
    u.message = MagicMock()
    u.message.reply_text = AsyncMock()
    return u


@pytest.fixture(autouse=True)
def allow_all(monkeypatch):
    """Allow all chat IDs so _allowed() never blocks in these tests."""
    monkeypatch.setattr(bot, "ALLOWED_CHAT_ID", None)


# ── /preview tests ─────────────────────────────────────────────────────────────

async def test_preview_sends_composing_first(update):
    with patch("synthesize.collect_entries", new=AsyncMock(return_value=[])):
        await bot.handle_preview(update, MagicMock())
    first_reply = update.message.reply_text.call_args_list[0][0][0]
    assert "Composing" in first_reply


async def test_preview_empty_entries_sends_nothing_yet(update):
    with patch("synthesize.collect_entries", new=AsyncMock(return_value=[])):
        await bot.handle_preview(update, MagicMock())
    all_text = " ".join(c[0][0] for c in update.message.reply_text.call_args_list)
    assert "Nothing in your chronicle" in all_text


async def test_preview_strips_html_tags(update):
    fake_entry = MagicMock()
    with patch("synthesize.collect_entries", new=AsyncMock(return_value=[fake_entry])), \
         patch("synthesize.synthesize", new=AsyncMock(return_value="<h2>May</h2><p>A fine morning.</p>")):
        await bot.handle_preview(update, MagicMock())
    last_reply = update.message.reply_text.call_args_list[-1][0][0]
    assert "<" not in last_reply
    assert "May" in last_reply
    assert "A fine morning." in last_reply


async def test_preview_truncates_long_content(update):
    long_html = "<p>" + "x" * 4000 + "</p>"
    with patch("synthesize.collect_entries", new=AsyncMock(return_value=[MagicMock()])), \
         patch("synthesize.synthesize", new=AsyncMock(return_value=long_html)):
        await bot.handle_preview(update, MagicMock())
    last_reply = update.message.reply_text.call_args_list[-1][0][0]
    assert len(last_reply) <= 4096
    assert "fortnightly PDF" in last_reply


async def test_preview_handles_synthesis_error(update):
    with patch("synthesize.collect_entries", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await bot.handle_preview(update, MagicMock())  # must not raise
    all_text = " ".join(c[0][0] for c in update.message.reply_text.call_args_list)
    assert "went wrong" in all_text


async def test_preview_blocked_for_unauthorized_chat(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_CHAT_ID", 11111)
    u = MagicMock()
    u.effective_chat = MagicMock()
    u.effective_chat.id = 99999  # different from ALLOWED_CHAT_ID
    u.message = MagicMock()
    u.message.reply_text = AsyncMock()
    await bot.handle_preview(u, MagicMock())
    u.message.reply_text.assert_not_called()
