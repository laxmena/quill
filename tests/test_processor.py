import json
import pytest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch
from processor import (
    archive_inbox,
    load_state,
    next_run_dt,
    process_inbox,
    run_pipeline,
    save_state,
    _maybe_nudge,
)


# ── process_inbox ──────────────────────────────────────────────────────────────

async def test_process_inbox_transcribes_ogg(tmp_inbox, ogg_file):
    count, errors = await process_inbox(inbox_dir=tmp_inbox)
    assert count == 1
    assert errors == []
    assert ogg_file.with_suffix(".txt").exists()


async def test_process_inbox_describes_jpg(tmp_inbox, jpg_file):
    count, errors = await process_inbox(inbox_dir=tmp_inbox)
    assert count == 1
    assert errors == []
    assert jpg_file.with_suffix(".txt").exists()


async def test_process_inbox_skips_already_processed(tmp_inbox, ogg_file):
    ogg_file.with_suffix(".txt").write_text("already transcribed")
    count, errors = await process_inbox(inbox_dir=tmp_inbox)
    assert count == 0
    assert errors == []


async def test_process_inbox_skips_txt_files(tmp_inbox):
    (tmp_inbox / "2024-05-10_120000_note.txt").write_text("just a note")
    count, errors = await process_inbox(inbox_dir=tmp_inbox)
    assert count == 0
    assert errors == []


async def test_process_inbox_handles_mixed_files(tmp_inbox, ogg_file, jpg_file):
    (tmp_inbox / "2024-05-10_130000_note.txt").write_text("a note")  # already a txt
    count, errors = await process_inbox(inbox_dir=tmp_inbox)
    assert count == 2  # ogg + jpg, not the .txt
    assert errors == []


async def test_process_inbox_returns_error_paths(tmp_inbox, ogg_file, monkeypatch):
    async def _fail(path):
        raise RuntimeError("boom")
    monkeypatch.setattr("processor.transcribe_and_save", _fail)
    count, errors = await process_inbox(inbox_dir=tmp_inbox)
    assert count == 0
    assert len(errors) == 1
    assert errors[0] == ogg_file


# ── archive_inbox ──────────────────────────────────────────────────────────────

async def test_archive_moves_old_files(tmp_inbox, tmp_processed):
    (tmp_inbox / "2024-05-10_120000_note.txt").write_text("old note")
    (tmp_inbox / "2024-05-20_120000_note.txt").write_text("new note")
    count = await archive_inbox(
        until=date(2024, 5, 14), inbox_dir=tmp_inbox, processed_dir=tmp_processed
    )
    assert count == 1
    assert (tmp_processed / "2024-05-10_120000_note.txt").exists()
    assert (tmp_inbox / "2024-05-20_120000_note.txt").exists()


async def test_archive_moves_boundary_date(tmp_inbox, tmp_processed):
    (tmp_inbox / "2024-05-14_235959_note.txt").write_text("boundary day")
    count = await archive_inbox(
        until=date(2024, 5, 14), inbox_dir=tmp_inbox, processed_dir=tmp_processed
    )
    assert count == 1


async def test_archive_empty_inbox(tmp_inbox, tmp_processed):
    count = await archive_inbox(
        until=date(2024, 5, 14), inbox_dir=tmp_inbox, processed_dir=tmp_processed
    )
    assert count == 0


# ── next_run_dt ────────────────────────────────────────────────────────────────

def test_next_run_dt_is_in_the_future():
    assert next_run_dt() > datetime.now()


def test_next_run_dt_same_day_when_before_hour(monkeypatch):
    monkeypatch.setattr("processor.PROCESSING_HOUR", 14)
    from_dt = datetime(2024, 5, 10, 13, 0, 0)  # 1 hour before
    assert next_run_dt(from_dt) == datetime(2024, 5, 10, 14, 0, 0)


def test_next_run_dt_next_day_when_past_hour(monkeypatch):
    monkeypatch.setattr("processor.PROCESSING_HOUR", 2)
    from_dt = datetime(2024, 5, 10, 3, 0, 0)  # 1 hour after
    assert next_run_dt(from_dt) == datetime(2024, 5, 11, 2, 0, 0)


def test_next_run_dt_advances_across_month_boundary(monkeypatch):
    monkeypatch.setattr("processor.PROCESSING_HOUR", 2)
    from_dt = datetime(2024, 5, 31, 3, 0, 0)
    assert next_run_dt(from_dt) == datetime(2024, 6, 1, 2, 0, 0)


# ── state ──────────────────────────────────────────────────────────────────────

def test_state_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("processor.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("processor.LOGS_DIR", tmp_path)
    save_state({"last_run_date": "2024-05-14", "biography_count": 3})
    state = load_state()
    assert state["last_run_date"] == "2024-05-14"
    assert state["biography_count"] == 3


def test_load_state_returns_defaults_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("processor.STATE_FILE", tmp_path / "nonexistent.json")
    state = load_state()
    assert state["last_run_date"] is None
    assert state["biography_count"] == 0


def test_load_state_recovers_from_corrupt_json(tmp_path, monkeypatch):
    state_file = tmp_path / "state.json"
    state_file.write_text("{corrupt")
    monkeypatch.setattr("processor.STATE_FILE", state_file)
    state = load_state()
    assert state["last_run_date"] is None
    assert state["biography_count"] == 0


def test_save_state_atomic_no_partial_file(tmp_path, monkeypatch):
    monkeypatch.setattr("processor.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("processor.LOGS_DIR", tmp_path)
    save_state({"last_run_date": "2024-05-14", "biography_count": 1})
    # .tmp should not persist after successful write
    assert not (tmp_path / "state.tmp").exists()
    assert (tmp_path / "state.json").exists()


# ── _maybe_nudge ───────────────────────────────────────────────────────────────

async def test_maybe_nudge_sends_when_silent(tmp_inbox, tmp_processed, tmp_path, monkeypatch):
    monkeypatch.setattr("processor.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("processor.LOGS_DIR", tmp_path)
    monkeypatch.setattr("processor.NUDGE_AFTER_DAYS", 3)
    # Inbox and processed are empty → silent since forever
    sent = []
    with patch("processor.notify_owner", new=AsyncMock(side_effect=lambda t: sent.append(t))):
        await _maybe_nudge(inbox_dir=tmp_inbox, processed_dir=tmp_processed)
    assert len(sent) == 1
    assert "waiting" in sent[0].lower() or "chronicle" in sent[0].lower()


async def test_maybe_nudge_skips_when_recent_activity(
    tmp_inbox, tmp_processed, tmp_path, monkeypatch
):
    monkeypatch.setattr("processor.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("processor.LOGS_DIR", tmp_path)
    monkeypatch.setattr("processor.NUDGE_AFTER_DAYS", 3)
    today_str = date.today().isoformat()
    (tmp_inbox / f"{today_str}_120000_note.txt").write_text("today's entry")
    sent = []
    with patch("processor.notify_owner", new=AsyncMock(side_effect=lambda t: sent.append(t))):
        await _maybe_nudge(inbox_dir=tmp_inbox, processed_dir=tmp_processed)
    assert sent == []


async def test_maybe_nudge_skips_when_already_nudged_today(
    tmp_inbox, tmp_processed, tmp_path, monkeypatch
):
    monkeypatch.setattr("processor.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("processor.LOGS_DIR", tmp_path)
    monkeypatch.setattr("processor.NUDGE_AFTER_DAYS", 3)
    save_state({"last_run_date": None, "biography_count": 0,
                "last_nudge_date": date.today().isoformat()})
    sent = []
    with patch("processor.notify_owner", new=AsyncMock(side_effect=lambda t: sent.append(t))):
        await _maybe_nudge(inbox_dir=tmp_inbox, processed_dir=tmp_processed)
    assert sent == []


async def test_maybe_nudge_disabled_when_zero(
    tmp_inbox, tmp_processed, tmp_path, monkeypatch
):
    monkeypatch.setattr("processor.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("processor.LOGS_DIR", tmp_path)
    monkeypatch.setattr("processor.NUDGE_AFTER_DAYS", 0)
    sent = []
    with patch("processor.notify_owner", new=AsyncMock(side_effect=lambda t: sent.append(t))):
        await _maybe_nudge(inbox_dir=tmp_inbox, processed_dir=tmp_processed)
    assert sent == []


# ── run_pipeline ───────────────────────────────────────────────────────────────

async def test_run_pipeline_end_to_end(
    tmp_inbox, tmp_biographies, tmp_processed, tmp_path, period, mock_playwright, monkeypatch
):
    start, end = period
    monkeypatch.setattr("processor.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("processor.LOGS_DIR", tmp_path)
    (tmp_inbox / "2024-05-10_120000_note.txt").write_text("A quiet morning in May.")

    html_path, pdf_path = await run_pipeline(
        start, end,
        deliver_email=False,
        inbox_dir=tmp_inbox,
        biographies_dir=tmp_biographies,
        processed_dir=tmp_processed,
    )

    assert html_path.exists()
    assert pdf_path.exists()
    # Source file archived after pipeline
    assert not (tmp_inbox / "2024-05-10_120000_note.txt").exists()
    assert (tmp_processed / "2024-05-10_120000_note.txt").exists()
    # State updated
    state = load_state()
    assert state["last_run_date"] == end.isoformat()
    assert state["biography_count"] == 1


async def test_run_pipeline_commit_false_does_not_archive_or_update_state(
    tmp_inbox, tmp_biographies, tmp_processed, tmp_path, period, mock_playwright, monkeypatch
):
    """commit=False (cli preview mode) must not archive entries or mutate state.json."""
    start, end = period
    monkeypatch.setattr("processor.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("processor.LOGS_DIR", tmp_path)
    note = tmp_inbox / "2024-05-10_120000_note.txt"
    note.write_text("A quiet morning in May.")

    html_path, pdf_path = await run_pipeline(
        start, end,
        deliver_email=False,
        commit=False,
        inbox_dir=tmp_inbox,
        biographies_dir=tmp_biographies,
        processed_dir=tmp_processed,
    )

    assert html_path.exists()
    assert pdf_path.exists()
    # Entry must remain in inbox — not archived
    assert note.exists()
    assert not (tmp_processed / note.name).exists()
    # state.json must not have been written
    state = load_state()
    assert state["last_run_date"] is None
    assert state["biography_count"] == 0
    # Intermediate content.html must be deleted so it doesn't contaminate prior-chapter context
    content_files = list(tmp_biographies.glob("*_content.html"))
    assert content_files == [], f"content.html left behind: {content_files}"


async def test_run_pipeline_raises_valueerror_for_empty_inbox(
    tmp_inbox, tmp_biographies, tmp_processed, tmp_path, period, mock_playwright, monkeypatch
):
    """Empty inbox propagates ValueError so start_scheduler can send a friendly message."""
    start, end = period
    monkeypatch.setattr("processor.STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("processor.LOGS_DIR", tmp_path)
    # inbox is empty — no .txt entries for synthesize to use
    with pytest.raises(ValueError, match="no entries"):
        await run_pipeline(
            start, end,
            deliver_email=False,
            inbox_dir=tmp_inbox,
            biographies_dir=tmp_biographies,
            processed_dir=tmp_processed,
        )
