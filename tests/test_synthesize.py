import pytest
from datetime import date, datetime
from synthesize import (
    Entry, collect_entries, synthesize, synthesize_and_save,
    _build_prompt, _load_prior_chapter,
)


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


async def test_collect_parses_new_format_with_hex_suffix(tmp_inbox):
    """Files saved by ts() now have a 4-part stem; kind is the last segment."""
    (tmp_inbox / "2024-05-10_143022_a1b2c3_note.txt").write_text("New format entry.")
    entries = await collect_entries(date(2024, 5, 1), date(2024, 5, 14), inbox_dir=tmp_inbox)
    assert len(entries) == 1
    assert entries[0].kind == "note"
    assert entries[0].text == "New format entry."


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


# ── continuity ─────────────────────────────────────────────────────────────────

def test_build_prompt_includes_prior_text():
    entries = [Entry(datetime(2024, 5, 10, 9, 0), "note", "A walk.")]
    prompt = _build_prompt(entries, date(2024, 5, 1), date(2024, 5, 14),
                           prior_text="The winter had been long.")
    assert "Previous chapter" in prompt
    assert "The winter had been long." in prompt
    assert "A walk." in prompt


def test_build_prompt_omits_prior_section_when_none():
    entries = [Entry(datetime(2024, 5, 10, 9, 0), "note", "A walk.")]
    prompt = _build_prompt(entries, date(2024, 5, 1), date(2024, 5, 14))
    assert "Previous chapter" not in prompt


def test_build_prompt_includes_entry_count():
    entries = [
        Entry(datetime(2024, 5, 1, 9, 0), "note", "Morning walk."),
        Entry(datetime(2024, 5, 5, 20, 0), "voice", "Team meeting."),
        Entry(datetime(2024, 5, 10, 14, 0), "photo", "Reservoir."),
    ]
    prompt = _build_prompt(entries, date(2024, 5, 1), date(2024, 5, 14))
    assert "3 total" in prompt


async def test_load_prior_chapter_returns_none_when_empty(tmp_biographies):
    result = await _load_prior_chapter(tmp_biographies)
    assert result is None


async def test_load_prior_chapter_returns_most_recent(tmp_biographies):
    (tmp_biographies / "2024-04-30_content.html").write_text("<p>April</p>")
    (tmp_biographies / "2024-05-14_content.html").write_text("<p>May</p>")
    result = await _load_prior_chapter(tmp_biographies)
    assert result == "<p>May</p>"


async def test_load_prior_chapter_excludes_current_end(tmp_biographies):
    (tmp_biographies / "2024-04-30_content.html").write_text("<p>April</p>")
    (tmp_biographies / "2024-05-14_content.html").write_text("<p>May</p>")
    result = await _load_prior_chapter(tmp_biographies, current_end=date(2024, 5, 14))
    assert result == "<p>April</p>"


async def test_synthesize_and_save_passes_prior_chapter(
    tmp_inbox, tmp_biographies, period, monkeypatch
):
    start, end = period
    (tmp_inbox / "2024-05-10_120000_note.txt").write_text("A fine day.")
    (tmp_biographies / "2024-04-30_content.html").write_text("<p>April prose.</p>")

    captured: list[str | None] = []

    async def fake_synthesize(entries, ps, pe, prior_html=None):
        captured.append(prior_html)
        return "<p>mock output</p>"

    monkeypatch.setattr("synthesize.synthesize", fake_synthesize)
    await synthesize_and_save(start, end, inbox_dir=tmp_inbox,
                              biographies_dir=tmp_biographies)

    assert len(captured) == 1
    assert captured[0] is not None
    assert "April prose." in captured[0]
