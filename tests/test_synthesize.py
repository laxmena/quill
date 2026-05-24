import pytest
from datetime import date, datetime
from synthesize import Entry, collect_entries, synthesize, synthesize_and_save


# ── collect_entries ────────────────────────────────────────────────────────────

async def test_collect_empty_inbox(tmp_inbox):
    entries = await collect_entries(date(2024, 5, 1), date(2024, 5, 14), inbox_dir=tmp_inbox)
    assert entries == []


async def test_collect_parses_note(tmp_inbox):
    (tmp_inbox / "2024-05-10_143022_note.txt").write_text("Had coffee this morning.")
    entries = await collect_entries(date(2024, 5, 1), date(2024, 5, 14), inbox_dir=tmp_inbox)
    assert len(entries) == 1
    assert entries[0].kind == "note"
    assert entries[0].text == "Had coffee this morning."
    assert entries[0].timestamp == datetime(2024, 5, 10, 14, 30, 22)


async def test_collect_parses_voice_and_photo(tmp_inbox):
    (tmp_inbox / "2024-05-10_090000_voice.txt").write_text("Recorded a memo.")
    (tmp_inbox / "2024-05-10_120000_photo.txt").write_text("A sunny afternoon.")
    entries = await collect_entries(date(2024, 5, 1), date(2024, 5, 14), inbox_dir=tmp_inbox)
    assert len(entries) == 2
    assert {e.kind for e in entries} == {"voice", "photo"}


async def test_collect_filters_by_date(tmp_inbox):
    (tmp_inbox / "2024-04-30_120000_note.txt").write_text("before range")
    (tmp_inbox / "2024-05-07_120000_note.txt").write_text("inside range")
    (tmp_inbox / "2024-05-15_120000_note.txt").write_text("after range")
    entries = await collect_entries(date(2024, 5, 1), date(2024, 5, 14), inbox_dir=tmp_inbox)
    assert len(entries) == 1
    assert entries[0].text == "inside range"


async def test_collect_skips_empty_files(tmp_inbox):
    (tmp_inbox / "2024-05-10_120000_note.txt").write_text("   \n  ")
    entries = await collect_entries(date(2024, 5, 1), date(2024, 5, 14), inbox_dir=tmp_inbox)
    assert entries == []


async def test_collect_skips_unknown_kind(tmp_inbox):
    (tmp_inbox / "2024-05-10_120000_other.txt").write_text("unknown kind")
    entries = await collect_entries(date(2024, 5, 1), date(2024, 5, 14), inbox_dir=tmp_inbox)
    assert entries == []


async def test_collect_sorted_chronologically(tmp_inbox):
    (tmp_inbox / "2024-05-10_180000_note.txt").write_text("evening")
    (tmp_inbox / "2024-05-10_090000_note.txt").write_text("morning")
    entries = await collect_entries(date(2024, 5, 1), date(2024, 5, 14), inbox_dir=tmp_inbox)
    assert entries[0].text == "morning"
    assert entries[1].text == "evening"


# ── synthesize ─────────────────────────────────────────────────────────────────

async def test_synthesize_returns_nonempty_string(period):
    start, end = period
    entries = [Entry(datetime(2024, 5, 10, 14, 30), "note", "Had coffee.")]
    result = await synthesize(entries, start, end)
    assert isinstance(result, str)
    assert result.strip()


async def test_synthesize_raises_on_empty_entries(period):
    start, end = period
    with pytest.raises(ValueError, match="no entries"):
        await synthesize([], start, end)


# ── synthesize_and_save ────────────────────────────────────────────────────────

async def test_synthesize_and_save_creates_content_file(tmp_inbox, tmp_biographies, period):
    start, end = period
    (tmp_inbox / "2024-05-10_120000_note.txt").write_text("A quiet morning.")
    path, count = await synthesize_and_save(
        start, end, inbox_dir=tmp_inbox, biographies_dir=tmp_biographies
    )
    assert path.exists()
    assert path.name == f"{end.isoformat()}_content.html"
    assert count == 1


async def test_synthesize_and_save_returns_entry_count(tmp_inbox, tmp_biographies, period):
    start, end = period
    (tmp_inbox / "2024-05-10_090000_note.txt").write_text("Morning walk.")
    (tmp_inbox / "2024-05-11_140000_voice.txt").write_text("Afternoon call.")
    _, count = await synthesize_and_save(
        start, end, inbox_dir=tmp_inbox, biographies_dir=tmp_biographies
    )
    assert count == 2
