"""
Offline LLM evals for synthesis quality.

Run with a real API key:
    ANTHROPIC_API_KEY=sk-... pytest evals/ -v

Each test loads a fixture from evals/fixtures/, calls the real Claude API,
and asserts structural constraints (word count, section count, tag limits).
Metrics are appended to logs/eval_history.jsonl for drift tracking over time.
"""
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

# Ensure project root and evals/ are importable
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from eval_helpers import check_html_structure, parse_metrics

FIXTURES_DIR = Path(__file__).parent / "fixtures"
LOGS_DIR     = Path(__file__).parent.parent / "logs"
PROJECT_ROOT = Path(__file__).parent.parent


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text())


def fixture_to_entries(fixture: dict):
    """Convert fixture JSON to synthesize.Entry objects."""
    from synthesize import Entry
    return [
        Entry(
            timestamp=datetime.fromisoformat(e["timestamp"]),
            kind=e["kind"],
            text=e["text"],
        )
        for e in fixture["entries"]
    ]


async def _call_claude(fixture: dict) -> str:
    """Build prompt from fixture and call the real Claude API."""
    import anthropic
    from synthesize import _SYSTEM, _build_prompt

    entries    = fixture_to_entries(fixture)
    start      = date.fromisoformat(fixture["period_start"])
    end        = date.fromisoformat(fixture["period_end"])
    prior_html = fixture.get("prior_html")

    prior_text = None
    if prior_html:
        import re
        plain = re.sub(r"<[^>]+>", " ", prior_html)
        prior_text = re.sub(r"[ \t]+", " ", plain).strip()

    user_name = os.getenv("USER_NAME", "Your Name")
    system    = _SYSTEM.format(name=user_name.split()[0])
    prompt    = _build_prompt(entries, start, end, prior_text=prior_text)
    model     = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")

    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = await client.messages.create(
        model=model,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text


def _record_metrics(fixture_id: str, metrics: dict, model: str) -> None:
    """Append a metrics record to logs/eval_history.jsonl."""
    LOGS_DIR.mkdir(exist_ok=True)
    record = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "fixture": fixture_id,
        "model": model,
        **metrics,
    }
    with open(LOGS_DIR / "eval_history.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.mark.eval
async def test_sparse_period_economy():
    """5 entries: output must be concise and structurally restrained."""
    fixture  = load_fixture("sparse")
    html     = await _call_claude(fixture)
    a        = fixture["assertions"]
    metrics  = parse_metrics(html, len(fixture["entries"]))
    warnings = check_html_structure(html)
    model    = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")

    _record_metrics(fixture["id"], metrics, model)

    print(f"\n--- sparse metrics ---")
    print(json.dumps(metrics, indent=2))
    if warnings:
        print("warnings:", warnings)
    print("--- output ---")
    print(html[:800])

    assert metrics["word_count"] >= a["min_words"], (
        f"Too sparse: {metrics['word_count']} words for {len(fixture['entries'])} entries "
        f"(min {a['min_words']})"
    )
    assert metrics["word_count"] <= a["max_words"], (
        f"Too verbose: {metrics['word_count']} words for {len(fixture['entries'])} entries "
        f"(max {a['max_words']}). words_per_entry={metrics['words_per_entry']}"
    )
    assert metrics["h3_count"] <= a["max_h3"], (
        f"Too many sections: {metrics['h3_count']} <h3> tags (max {a['max_h3']})"
    )
    assert metrics["blockquote_count"] <= a["max_blockquote"], (
        f"Too many blockquotes: {metrics['blockquote_count']} (max {a['max_blockquote']})"
    )
    assert metrics["moment_count"] <= a["max_moment"], (
        f"Too many moment divs: {metrics['moment_count']} (max {a['max_moment']})"
    )
    assert metrics["h2_count"] == 1, (
        f"Expected exactly 1 chapter title <h2>, got {metrics['h2_count']}"
    )


@pytest.mark.eval
async def test_rich_period_hard_cap():
    """12 entries: output must not exceed the 800-word hard cap."""
    fixture  = load_fixture("rich")
    html     = await _call_claude(fixture)
    a        = fixture["assertions"]
    metrics  = parse_metrics(html, len(fixture["entries"]))
    warnings = check_html_structure(html)
    model    = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")

    _record_metrics(fixture["id"], metrics, model)

    print(f"\n--- rich metrics ---")
    print(json.dumps(metrics, indent=2))
    if warnings:
        print("warnings:", warnings)

    assert metrics["word_count"] >= a["min_words"], (
        f"Too sparse: {metrics['word_count']} words for {len(fixture['entries'])} entries"
    )
    assert metrics["word_count"] <= a["max_words"], (
        f"Hard cap exceeded: {metrics['word_count']} words (max {a['max_words']})"
    )
    assert metrics["h3_count"] <= a["max_h3"], (
        f"Too many sections: {metrics['h3_count']} (max {a['max_h3']})"
    )
    assert metrics["blockquote_count"] <= a["max_blockquote"], (
        f"Too many blockquotes: {metrics['blockquote_count']} (max {a['max_blockquote']})"
    )
    assert metrics["moment_count"] <= a["max_moment"], (
        f"Too many moment divs: {metrics['moment_count']} (max {a['max_moment']})"
    )
    assert metrics["h2_count"] == 1, (
        f"Expected exactly 1 chapter title <h2>, got {metrics['h2_count']}"
    )


@pytest.mark.eval
async def test_continuity_no_reintroduction():
    """3 entries with prior chapter: people and themes must not be re-introduced."""
    fixture  = load_fixture("continuity")
    html     = await _call_claude(fixture)
    a        = fixture["assertions"]
    metrics  = parse_metrics(html, len(fixture["entries"]))
    warnings = check_html_structure(html)
    model    = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")

    _record_metrics(fixture["id"], metrics, model)

    print(f"\n--- continuity metrics ---")
    print(json.dumps(metrics, indent=2))
    if warnings:
        print("warnings:", warnings)
    print("--- output ---")
    print(html)

    assert metrics["word_count"] >= a["min_words"], (
        f"Too sparse: {metrics['word_count']} words"
    )
    assert metrics["word_count"] <= a["max_words"], (
        f"Too verbose: {metrics['word_count']} words (max {a['max_words']})"
    )
    assert metrics["h3_count"] <= a["max_h3"], (
        f"Too many sections: {metrics['h3_count']} (max {a['max_h3']})"
    )
    assert metrics["h2_count"] == 1, (
        f"Expected exactly 1 chapter title <h2>, got {metrics['h2_count']}"
    )

    # Continuity check: "Jordan" should not be introduced as if new.
    # The prior chapter already established her. A re-introduction looks like
    # "Jordan, his [partner/friend/colleague]" — a parenthetical gloss.
    import re
    reintro_pattern = r"Jordan,?\s+(?:his|her|their)\s+\w+"
    assert not re.search(reintro_pattern, html, re.IGNORECASE), (
        "Continuity failure: Jordan appears to be re-introduced despite being "
        "established in the prior chapter"
    )
