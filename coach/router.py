"""Routing: which phase, which chapter, which standard.

All three routers are total functions. There is no fall-through and no None for
an input that is in range (acceptance criteria 6.10, 6.11).
"""

import re

from . import rules


def phase(readiness, days_to_exam, has_data=True):
    """Total function of (readiness, days_to_exam).

    Precedence is deliberate: DATE beats READINESS. A student testing in two
    days gets TAPER even if readiness is low, because introducing new material
    that late is actively harmful.
    """
    if not has_data:
        return rules.PHASE_FOUNDATIONS
    if days_to_exam is not None:
        if days_to_exam <= rules.DAYS_EXAM_EVE:
            return rules.PHASE_EXAM_EVE
        if days_to_exam <= rules.DAYS_TAPER:
            return rules.PHASE_TAPER
    r = 0.0 if readiness is None else max(0.0, min(1.0, readiness))
    if r < rules.FOUNDATIONS_BELOW:
        return rules.PHASE_FOUNDATIONS
    if r <= rules.LAST_MILE_ABOVE:
        return rules.PHASE_CLEANUP
    return rules.PHASE_LAST_MILE


def _tokens(text):
    toks = set()
    for t in re.split(r"[^a-z0-9]+", (text or "").lower()):
        if len(t) > 2:
            toks.add(t)
            if len(t) > 4 and t.endswith("s"):
                toks.add(t[:-1])
    return toks


def reading_section(topic, sections, primary_section_id=None):
    """Pick the chapter to read for a topic. Retrieval, never generation.

    Preference order: the benchmark's primary section, then the section whose
    title best overlaps the topic. Returns None only when nothing is close.
    """
    if primary_section_id is not None:
        for s in sections:
            if s.get("id") == primary_section_id:
                return s
    if not topic:
        return None
    topic_tokens = _tokens(topic)
    if not topic_tokens:
        return None
    best, best_score = None, 0
    for s in sections:
        title_tokens = _tokens(s.get("section_title"))
        score = len(topic_tokens & title_tokens)
        if score > best_score:
            best, best_score = s, score
    return best if best_score >= rules.READING_TOKEN_MIN else None


_SIGNIFICANT = re.compile(r"[A-Za-z]{5,}")


def _significant_words(text):
    return {w.lower() for w in _SIGNIFICANT.findall(str(text or ""))}


def title_matches_benchmark(benchmark, section_title):
    """Does this section plausibly cover this benchmark?

    The stored benchmark->section links came out of a relevance score that plainly
    misfired. SS.7.CG.1.8 (the Preamble and popular sovereignty) resolves to
    "17.4. Approaches to Foreign Policy", and that same foreign-policy section is the
    top link for a dozen unrelated codes. A reading pointer that sends a student to
    the wrong chapter is worse than no pointer, so require the section title to share
    a significant word with the benchmark's own official text before offering it.
    """
    if not benchmark or not section_title:
        return False
    official = _significant_words(benchmark.get("description"))
    official |= _significant_words(benchmark.get("clarifications"))
    official |= _significant_words(benchmark.get("standard"))
    return bool(official & _significant_words(section_title))


def is_teachable_section(section):
    """Is this a section a student could actually be sent to read?

    Rejects the oversized row that carries the book's back matter. A pointer into
    368 KB of appendices, references and index is not a reading assignment, however
    well its words match the standard.
    """
    if not section:
        return False
    if str(display_title(section)).strip().lower() in rules.NON_SECTION_TITLES:
        return False
    try:
        chars = int(section.get("char_count") or 0)
    except (TypeError, ValueError):
        return False
    if chars and chars > rules.MAX_READING_SECTION_CHARS:
        return False
    return True


def display_title(section):
    """The student-facing section title, stripped of stored harvest artifacts.

    The content rows came out of a PDF and carry trailing '*' markers and NBSPs.
    Normalise here, at render. Never mutate the stored rows - other consumers
    (the tutor's retrieval) rely on them as-is.
    """
    if not section:
        return ""
    title = str(section.get("section_title") or "")
    title = title.replace(rules.NON_BREAKING_SPACE, " ").strip()
    changed = True
    while changed and title:
        changed = False
        for artifact in rules.SECTION_TITLE_TRAILING_ARTIFACTS:
            if title.endswith(artifact):
                title = title[: -len(artifact)].rstrip()
                changed = True
    return title


def reading_minutes(section):
    """Rough read time from the stored character count."""
    if not section:
        return None
    chars = section.get("char_count") or 0
    minutes = int(round(chars / float(rules.READING_CHARS_PER_MINUTE))) if chars else 0
    minutes = max(rules.MIN_READING_MINUTES, min(rules.MAX_READING_MINUTES, minutes))
    return minutes


def benchmark_report(per_code, domain):
    """Per-standard miss pattern - FOR DOMAINS 1-3 ONLY.

    Domain 4 is suppressed by design (rules.BENCHMARK_REPORT_DOMAINS). Its topic
    taxonomy is one topic per landmark case and the only case-law benchmark code
    is SS.7.CG.3.11, so 17 of 24 D4 topics collapse onto it. Telling a student
    "you are missing SS.7.CG.3.11" says nothing; D4 reports per case instead.
    """
    if domain not in rules.BENCHMARK_REPORT_DOMAINS:
        return None
    rows = []
    for code, stats in (per_code or {}).items():
        attempted = stats.get("attempted", 0)
        if not attempted:
            continue
        rows.append({
            "code": code,
            "label": stats.get("label", ""),
            "attempted": attempted,
            "miss_rate": round(1.0 - (stats.get("adjusted_accuracy", 0.0)), 4),
        })
    if not rows:
        return None
    rows.sort(key=lambda r: (-r["miss_rate"], r["code"]))
    return {"domain": domain, "rows": tuple(rows)}
