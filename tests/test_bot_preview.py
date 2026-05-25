"""
Tests for bot.py handlers.

The telegram package's Rust crypto bindings are broken in this test
environment, so we stub sys.modules before importing bot. The stubs
provide enough surface for the handler logic without a real PTB install.
"""
import sys
from pathlib import Path
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
    u.message.caption = None
    return u


@pytest.fixture(autouse=True)
def allow_all(monkeypatch):
    """Allow all chat IDs so _allowed() never blocks in these tests."""
    monkeypatch.setattr(bot, "ALLOWED_CHAT_ID", None)


# ── /preview ──────────────────────────────────────────────────────────────────

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
         patch("synthesize.synthesize", new=AsyncMock(return_value="<h2>May</h2><p>A fine morning.</p>")), \
         patch("synthesize._load_prior_chapter", new=AsyncMock(return_value=None)):
        await bot.handle_preview(update, MagicMock())
    last_reply = update.message.reply_text.call_args_list[-1][0][0]
    assert "<" not in last_reply
    assert "May" in last_reply
    assert "A fine morning." in last_reply


async def test_preview_uses_prior_chapter(update):
    """Ensure /preview passes prior_html to synthesize (continuity fix)."""
    fake_entry = MagicMock()
    captured_prior = []

    async def fake_synthesize(entries, start, end, prior_html=None):
        captured_prior.append(prior_html)
        return "<p>prose</p>"

    with patch("synthesize.collect_entries", new=AsyncMock(return_value=[fake_entry])), \
         patch("synthesize.synthesize", new=fake_synthesize), \
         patch("synthesize._load_prior_chapter", new=AsyncMock(return_value="<p>prior</p>")):
        await bot.handle_preview(update, MagicMock())

    assert len(captured_prior) == 1
    assert captured_prior[0] == "<p>prior</p>"


async def test_preview_truncates_long_content(update):
    long_html = "<p>" + "x" * 4000 + "</p>"
    with patch("synthesize.collect_entries", new=AsyncMock(return_value=[MagicMock()])), \
         patch("synthesize.synthesize", new=AsyncMock(return_value=long_html)), \
         patch("synthesize._load_prior_chapter", new=AsyncMock(return_value=None)):
        await bot.handle_preview(update, MagicMock())
    last_reply = update.message.reply_text.call_args_list[-1][0][0]
    assert len(last_reply) <= 4096
    assert "fortnightly PDF" in last_reply


async def test_preview_handles_synthesis_error(update):
    with patch("synthesize.collect_entries", new=AsyncMock(side_effect=RuntimeError("boom"))):
        await bot.handle_preview(update, MagicMock())  # must not raise
    all_text = " ".join(c[0][0] for c in update.message.reply_text.call_args_list)
    assert "went wrong" in all_text
    assert "logs/" not in all_text  # error message must not reference log files


async def test_preview_blocked_for_unauthorized_chat(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_CHAT_ID", 11111)
    u = MagicMock()
    u.effective_chat = MagicMock()
    u.effective_chat.id = 99999
    u.message = MagicMock()
    u.message.reply_text = AsyncMock()
    await bot.handle_preview(u, MagicMock())
    u.message.reply_text.assert_not_called()


# ── /start ───────────────────────────────────────────────────────────────────

async def test_start_lists_preview_with_description(update):
    await bot.handle_start(update, MagicMock())
    reply = update.message.reply_text.call_args[0][0]
    assert "/preview" in reply
    # Must have a description alongside the command, not just list commands bare
    preview_idx = reply.index("/preview")
    assert "—" in reply[preview_idx:preview_idx + 40] or "draft" in reply[preview_idx:preview_idx + 40]


# ── /help ─────────────────────────────────────────────────────────────────────

async def test_help_lists_all_commands(update):
    await bot.handle_help(update, MagicMock())
    reply = update.message.reply_text.call_args[0][0]
    for cmd in ("/status", "/preview", "/delete-last", "/help"):
        assert cmd in reply


async def test_help_mentions_privacy(update):
    await bot.handle_help(update, MagicMock())
    reply = update.message.reply_text.call_args[0][0]
    assert "Privacy" in reply or "OpenAI" in reply


# ── /delete-last ──────────────────────────────────────────────────────────────

async def test_delete_last_removes_most_recent(update, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(bot, "INBOX_DIR", inbox)
    (inbox / "2024-05-10_090000_note.txt").write_text("morning")
    (inbox / "2024-05-10_150000_note.txt").write_text("afternoon")

    await bot.handle_delete_last(update, MagicMock())

    remaining = list(inbox.iterdir())
    assert len(remaining) == 1
    assert "090000" in remaining[0].name
    reply = update.message.reply_text.call_args[0][0]
    assert "Deleted" in reply


async def test_delete_last_removes_all_files_with_same_stem(update, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(bot, "INBOX_DIR", inbox)
    (inbox / "2024-05-10_143022_voice.ogg").write_bytes(b"audio")
    (inbox / "2024-05-10_143022_voice.txt").write_text("transcript")

    await bot.handle_delete_last(update, MagicMock())

    assert list(inbox.iterdir()) == []


async def test_delete_last_empty_inbox(update, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(bot, "INBOX_DIR", inbox)

    await bot.handle_delete_last(update, MagicMock())

    reply = update.message.reply_text.call_args[0][0]
    assert "empty" in reply


# ── handle_photo caption pairing ──────────────────────────────────────────────

async def test_photo_with_caption_saves_txt(update, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(bot, "INBOX_DIR", inbox)
    update.message.caption = "She walked!"

    mock_file = AsyncMock()
    mock_file.download_to_drive = AsyncMock()
    update.message.photo = [MagicMock()]
    update.message.photo[-1].get_file = AsyncMock(return_value=mock_file)

    await bot.handle_photo(update, MagicMock())

    txt_files = list(inbox.glob("*_photo.txt"))
    assert len(txt_files) == 1
    assert txt_files[0].read_text() == "She walked!"
    reply = update.message.reply_text.call_args[0][0]
    assert "She walked!" in reply


async def test_photo_without_caption_no_txt(update, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(bot, "INBOX_DIR", inbox)
    update.message.caption = None

    mock_file = AsyncMock()
    mock_file.download_to_drive = AsyncMock()
    update.message.photo = [MagicMock()]
    update.message.photo[-1].get_file = AsyncMock(return_value=mock_file)

    await bot.handle_photo(update, MagicMock())

    assert list(inbox.glob("*_photo.txt")) == []
    reply = update.message.reply_text.call_args[0][0]
    assert "describe" in reply.lower() or "tonight" in reply.lower()


# ── download error handling ───────────────────────────────────────────────────

async def test_voice_download_error_replies_gracefully(update, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(bot, "INBOX_DIR", inbox)
    update.message.voice = MagicMock()
    update.message.voice.get_file = AsyncMock(side_effect=RuntimeError("network error"))

    await bot.handle_voice(update, MagicMock())

    reply = update.message.reply_text.call_args[0][0]
    assert "trouble" in reply.lower() or "try again" in reply.lower()
    assert list(inbox.glob("*.ogg")) == []


async def test_photo_download_error_replies_gracefully(update, tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(bot, "INBOX_DIR", inbox)
    update.message.photo = [MagicMock()]
    update.message.photo[-1].get_file = AsyncMock(side_effect=RuntimeError("network error"))

    await bot.handle_photo(update, MagicMock())

    reply = update.message.reply_text.call_args[0][0]
    assert "trouble" in reply.lower() or "try again" in reply.lower()
    assert list(inbox.glob("*.jpg")) == []


# ── fallback handler ─────────────────────────────────────────────────────────

async def test_unknown_message_type_replies_with_hint(update):
    await bot.handle_unknown(update, MagicMock())
    reply = update.message.reply_text.call_args[0][0]
    assert "voice" in reply.lower() or "photo" in reply.lower()


async def test_unknown_blocked_for_unauthorized_chat(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_CHAT_ID", 11111)
    u = MagicMock()
    u.effective_chat = MagicMock()
    u.effective_chat.id = 99999
    u.message = MagicMock()
    u.message.reply_text = AsyncMock()
    await bot.handle_unknown(u, MagicMock())
    u.message.reply_text.assert_not_called()
