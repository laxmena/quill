"""
Unit tests for evals/eval_helpers.py.

These run in the normal test suite (QUILL_MOCK=true, no API calls)
since eval_helpers is pure-function code with no external dependencies.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "evals"))

from eval_helpers import (
    check_html_structure,
    moment_count,
    parse_metrics,
    tag_count,
    word_count,
)

_SAMPLE = (
    "<h2>Chapter One</h2>"
    "<h3>Morning</h3>"
    "<p>He sat by the window.</p>"
    "<blockquote>The street was empty.</blockquote>"
    '<div class="moment"><p class="moment-date">3 May</p><p class="moment-text">Coffee.</p></div>'
    "<h3>Evening</h3>"
    "<p>Dinner with Jordan.</p>"
)


def test_word_count_strips_tags():
    assert word_count("<p>Hello world</p>") == 2


def test_word_count_ignores_nested_tags():
    assert word_count("<p>One <em>two</em> three</p>") == 3


def test_tag_count_basic():
    assert tag_count(_SAMPLE, "h3") == 2
    assert tag_count(_SAMPLE, "h2") == 1
    assert tag_count(_SAMPLE, "blockquote") == 1


def test_tag_count_case_insensitive():
    assert tag_count("<H3>Title</H3>", "h3") == 1


def test_moment_count_double_quotes():
    html = '<div class="moment"><p>text</p></div>'
    assert moment_count(html) == 1


def test_moment_count_single_quotes():
    html = "<div class='moment'><p>text</p></div>"
    assert moment_count(html) == 1


def test_moment_count_zero():
    assert moment_count("<p>no moments here</p>") == 0


def test_parse_metrics_full():
    m = parse_metrics(_SAMPLE, entry_count=3)
    assert m["h2_count"] == 1
    assert m["h3_count"] == 2
    assert m["blockquote_count"] == 1
    assert m["moment_count"] == 1
    assert m["word_count"] > 0
    assert m["words_per_entry"] == round(m["word_count"] / 3, 1)


def test_parse_metrics_zero_entries_no_divide_by_zero():
    m = parse_metrics("<p>text</p>", entry_count=0)
    assert m["words_per_entry"] == 0


def test_check_html_structure_balanced():
    warnings = check_html_structure("<p>Hello</p><h3>Title</h3>")
    assert not any("mismatch" in w for w in warnings)


def test_check_html_structure_unclosed_tag():
    warnings = check_html_structure("<p>Hello<p>World</p>")
    assert any("p" in w and "mismatch" in w for w in warnings)


def test_check_html_structure_flags_interpretation():
    html = "<p>This reveals that he distrusted ornate language.</p>"
    warnings = check_html_structure(html)
    assert any("reveals that" in w for w in warnings)
