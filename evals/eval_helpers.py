"""Structural metric extraction from biography HTML."""
import re


def word_count(html: str) -> int:
    plain = re.sub(r"<[^>]+>", " ", html)
    return len(plain.split())


def tag_count(html: str, tag: str) -> int:
    return len(re.findall(rf"<{tag}[\s>]", html, re.IGNORECASE))


def moment_count(html: str) -> int:
    return len(re.findall(r"class=[\"']moment[\"']", html))


def parse_metrics(html: str, entry_count: int) -> dict:
    wc = word_count(html)
    return {
        "word_count": wc,
        "h2_count": tag_count(html, "h2"),
        "h3_count": tag_count(html, "h3"),
        "blockquote_count": tag_count(html, "blockquote"),
        "moment_count": moment_count(html),
        "words_per_entry": round(wc / entry_count, 1) if entry_count else 0,
    }


def check_html_structure(html: str) -> list[str]:
    """Return a list of structural warnings (non-fatal)."""
    warnings = []
    # Unclosed common tags
    for tag in ("p", "h2", "h3", "blockquote"):
        opens = len(re.findall(rf"<{tag}[\s>]", html, re.IGNORECASE))
        closes = len(re.findall(rf"</{tag}>", html, re.IGNORECASE))
        if opens != closes:
            warnings.append(f"<{tag}> opens={opens} closes={closes} mismatch")
    # Over-interpretation signal words (advisory, not hard failures)
    interp_patterns = [
        (r"\breveals that\b", "reveals that"),
        (r"\bthis is (?:a )?recurring\b", "this is recurring"),
        (r"\bwe might (?:note|observe|infer)\b", "we might note/observe/infer"),
        (r"\bperhaps (?:he|she|they) (?:sensed|knew|understood)\b",
         "perhaps he/she/they sensed/knew"),
    ]
    for pattern, label in interp_patterns:
        if re.search(pattern, html, re.IGNORECASE):
            warnings.append(f"possible over-interpretation: '{label}'")
    return warnings
