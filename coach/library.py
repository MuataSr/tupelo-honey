"""Per-answer content for the question screen.

The answer page used to explain the correct option, and per wrong option why that
option fails. Both are option-centric: they say what is true, never why *this student*
picked what they picked. This module adds that layer by reusing the coach's own
diagnosis, so the two surfaces cannot drift apart.

Everything here is static authored content (misconceptions, sections, the topic->
benchmark map), so it is read once per process and reused. Nothing per-user is cached.
"""
import os

from . import copy, diagnosis, repository, router

_CACHE = {}


def _read(content_db):
    raw = repository.load_content_library(content_db)
    raw["sections_by_id"] = {s["id"]: s for s in raw["sections"]}
    return raw


def load(content_db):
    """The static library for one content database, cached on (mtime, size)."""
    try:
        stamp = (os.path.getmtime(content_db), os.path.getsize(content_db))
    except OSError:
        stamp = None
    hit = _CACHE.get(content_db)
    if hit and hit[0] == stamp:
        return hit[1]
    library = _read(content_db)
    _CACHE[content_db] = (stamp, library)
    return library


def question_domain(question, answer=None, domain=None):
    """The numeric domain id for a question, from whichever shape carries it.

    Three shapes exist and they are not interchangeable. An answer row from the app
    carries `domain` as an id; a question row carries `domain_id`; the coach's own
    fixtures carry `fcle_domain`. The quiz's domain is a SLUG like
    "american-democracy", which is not an id and must never be passed through as one:
    doing that made the misconception lookup match nothing and fail silently.

    Returns an int, or None when nothing usable is available.
    """
    for candidate in (domain, question.get("domain_id"), question.get("fcle_domain"),
                      (answer or {}).get("domain")):
        if candidate is None:
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def benchmark_code(library, domain, topic):
    try:
        domain = int(domain)
    except (TypeError, ValueError):
        return None
    return library["codes"].get((domain, topic or ""))


def directive_for(library, answer, question, domain=None):
    """The coaching directive for one answered question.

    `domain` comes from the quiz (the questions row does not always carry it); the
    topic and the explanation come from the question.
    """
    resolved = question_domain(question, answer, domain)
    topic = question.get("topic", "") or ""
    code = benchmark_code(library, resolved, topic)
    external = library.get("external", {}).get(code)
    if external:
        # A verified external reading target (public-domain or CC-licensed) has no
        # content row, so it is offered directly and rendered as a link on the page.
        section = {"section_title": external["title"], "reading_url": external["url"]}
    else:
        section = library["sections_by_id"].get(library["primary"].get(code)) or {}
        if not router.is_teachable_section(section):
            section = {}          # back matter is not a reading assignment
        elif (code not in library.get("reviewed", set())
              and not router.title_matches_benchmark(library["benchmarks"].get(code), section)):
            # An unreviewed link must still earn its place through the keyword gate. A
            # reviewed link was read and judged by hand, so the gate is skipped: a correct
            # pointer such as SS.7.CG.1.11 -> "2.8. The English Constitutional Heritage"
            # shares no significant word with the benchmark and the gate used to withhold it.
            section = {}
    # build_directive reads the domain off the question, which the app's rows do not
    # carry, so hand it an answer that always does.
    answer = dict(answer, domain=resolved)
    return diagnosis.build_directive(
        answer, question,
        library["misconceptions"], library["sections"],
        benchmark_code=code, read_section=section)


def feedback_view(directive):
    """Template-ready feedback. Every student-facing string comes from copy.py.

    The three states are genuinely different and the page must not flatten them:
    MISCONCEPTION means the student was sure and wrong (a belief that will cost exam
    points), GAP means they did not know, FRAGILE means they were right but unsure.
    Only MISCONCEPTION and GAP can name a specific misconception.
    """
    view = {
        "show": bool(directive.is_teachable),
        "state": directive.state,
        "headline": copy.headline(directive.state) if directive.is_teachable else "",
        "confidence_note": (copy.confidence_note(directive.state)
                            if directive.is_teachable else ""),
        "trap_intro": copy.trap_intro(),
        "trap": directive.misconception_text,
        "correction_intro": copy.correction_intro(),
        "correction": directive.correction,
        "read_intro": copy.reading_intro(),
        "read_section": directive.read_section_title,
        "read_url": directive.read_section_url,
        "next_review_days": directive.next_review_days,
        # A domain-tier match is generic by construction: it says something true about
        # the domain, not about this question. Say so rather than passing it off as
        # specific to what the student got wrong.
        "generic": directive.match_tier == "domain",
        "generic_note": (copy.no_diagnosis_note()
                         if directive.match_tier == "domain" else ""),
        "has_diagnosis": bool(directive.misconception_text),
    }
    return view
