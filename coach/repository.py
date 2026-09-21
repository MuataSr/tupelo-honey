"""The only module in the coach that touches a database.

It FETCHES. It does not compute, decide or format - that all belongs above, so
the logic stays testable without any database at all.

The question bank and the runtime data live in SEPARATE SQLite files, so this
module reads both and merges in Python rather than trying to join across
connections.
"""

import sqlite3
from datetime import datetime, timezone

from .engine import State


def _rows(cur, sql, params=()):
    cur.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return tuple(dict(zip(cols, r)) for r in cur.fetchall())


def _connect(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _question_index(content):
    """{question_id: (domain, topic)} from the content DB."""
    idx = {}
    for r in _rows(content.cursor(), "SELECT id, fcle_domain, topic FROM questions"):
        idx[r["id"]] = (r["fcle_domain"], r["topic"])
    return idx


def _topic_benchmark_map(content):
    """{(domain, topic): benchmark_code} from the topic_benchmarks table."""
    bmap = {}
    try:
        for r in _rows(content.cursor(),
                       "SELECT fcle_domain, topic, primary_code FROM topic_benchmarks"):
            bmap[(r["fcle_domain"], r["topic"])] = r["primary_code"]
    except sqlite3.Error:
        pass            # table not loaded yet: coach still works, at topic tier
    return bmap


def _primary_sections(content):
    out = {}
    try:
        for r in _rows(content.cursor(), """
                SELECT benchmark_code, section_id FROM benchmark_sections
                 WHERE is_primary=1 ORDER BY relevance_score DESC"""):
            out.setdefault(r["benchmark_code"], r["section_id"])
    except sqlite3.Error:
        pass
    return out


def load_content_library(content_db):
    """Every static content row the answer screen needs, in one pass.

    The answer screen runs on each submit, so it wants a single call rather than five.
    Read-only, like every other read here. All of it is authored content - no user
    state - which is what makes caching it upstream safe.
    """
    con = _connect(content_db)
    try:
        cur = con.cursor()
        misconceptions = _rows(cur, "SELECT id, benchmark_code, misconception, correction, "
                                   "difficulty, fcle_domain FROM misconceptions")
        sections = _rows(cur, "SELECT id, section_title, char_count, fcle_domain FROM content")
        codes = _topic_benchmark_map(con)
        primary = _primary_sections(con)
        try:
            reviewed = {r["benchmark_code"] for r in _rows(
                cur, "SELECT benchmark_code FROM benchmark_sections "
                     "WHERE is_primary = 1 AND reviewed = 1")}
        except sqlite3.Error:
            # an older DB without the reviewed column: nothing is reviewed, so the
            # keyword gate applies everywhere - the pre-review behaviour, and safe.
            reviewed = set()
        try:
            external = {r["benchmark_code"]: {"title": r["reading_title"], "url": r["reading_url"]}
                        for r in _rows(cur, "SELECT benchmark_code, reading_title, reading_url "
                                            "FROM benchmark_sections WHERE is_primary = 1 "
                                            "AND reading_url IS NOT NULL AND reading_url != ''")}
        except sqlite3.Error:
            # a DB without the reading_url column simply has no external targets
            external = {}
        try:
            benchmarks = {r["code"]: r for r in _rows(
                cur, "SELECT code, standard, description, clarifications FROM benchmarks")}
        except sqlite3.Error:
            benchmarks = {}
    finally:
        con.close()
    return {"misconceptions": misconceptions, "sections": sections, "codes": codes,
            "primary": primary, "benchmarks": benchmarks, "reviewed": reviewed,
            "external": external}


def _load_answers(run, qidx, bmap):
    """Runtime answers enriched with domain, topic and benchmark code."""
    out = []
    for r in _rows(run.cursor(), """
            SELECT question_id, selected_answer, is_correct, confidence, answered_at
              FROM answers ORDER BY answered_at, id"""):
        domain, topic = qidx.get(r["question_id"], (None, None))
        out.append({
            "question_id": r["question_id"],
            "domain": domain,
            "topic": topic,
            "selected_answer": r["selected_answer"],
            "is_correct": bool(r["is_correct"]),
            "confidence": r["confidence"],
            "answered_at": r["answered_at"],
            "benchmark_code": bmap.get((domain, topic)),
        })
    return tuple(out)


def load_state(user_id, content_db, runtime_db, now=None):
    """Load everything the coach needs for one student. Read-only."""
    now = now or datetime.now(timezone.utc)
    content = _connect(content_db)
    run = _connect(runtime_db)
    try:
        users = _rows(run.cursor(), "SELECT * FROM users WHERE id=?", (user_id,))
        user = users[0] if users else {}

        qidx = _question_index(content)
        bmap = _topic_benchmark_map(content)

        try:
            due = _rows(run.cursor(), """
                SELECT question_id FROM review_queue
                 WHERE user_id=? AND (next_review IS NULL OR next_review <= ?)
                 ORDER BY next_review, id""", (user_id, now.isoformat()))
            due_ids = tuple(r["question_id"] for r in due)
        except sqlite3.Error:
            due_ids = ()

        return State(
            user=user,
            answers=_load_answers(run, qidx, bmap),
            due_review_ids=due_ids,
            misconceptions=_rows(content.cursor(),
                                 "SELECT id, benchmark_code, misconception, correction, "
                                 "difficulty, fcle_domain FROM misconceptions"),
            sections=_rows(content.cursor(),
                           "SELECT id, section_title, char_count, fcle_domain FROM content"),
            benchmark_map=bmap,
            benchmark_primary_section=_primary_sections(content),
            now=now,
        )
    finally:
        content.close()
        run.close()
