"""
kb.py — Tupelo Nursing Exam Prep knowledge base.

Reads questions from fcle.db (SQLite + FTS5).
Four domains: American Democracy, US Constitution, Founding Documents, Landmark Impact.
Questions may include stimulus passages (text excerpts to read before answering).
"""

import json
import os
import random
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "tupelo.db")


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Domain Metadata
# ---------------------------------------------------------------------------

def get_domains():
    """Return all FCLE domains with metadata."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM fcle_domains ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_domain_by_id(domain_id):
    """Return a single domain dict by its integer ID."""
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM fcle_domains WHERE id=?", (domain_id,)).fetchone()
        return dict(row) if row else None


def get_domain_topics(domain_id):
    """Return distinct topics for a domain as [{name, count}, ...]."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT topic, COUNT(*) AS count FROM questions WHERE fcle_domain=? GROUP BY topic ORDER BY topic",
            (domain_id,),
        ).fetchall()
        return [{"name": r["topic"], "slug": r["topic"].lower().replace(" ", "-"), "count": r["count"]} for r in rows]


# ---------------------------------------------------------------------------
# Quiz Question Retrieval
# ---------------------------------------------------------------------------

def _build_options(correct_answer, wrong_answers_json):
    """Build a shuffled 4-option list with correct_index.

    Args:
        correct_answer: str, the correct answer text.
        wrong_answers_json: str, JSON array of 3 wrong answer strings.

    Returns:
        (options_list, correct_index) where options_list[correct_index] == correct_answer.
    """
    wrongs = json.loads(wrong_answers_json)
    options = [correct_answer] + wrongs[:3]
    random.shuffle(options)
    correct_index = options.index(correct_answer)
    return options, correct_index


def get_domain_quiz_questions(domain_id=None, topic=None, count=5, difficulty=None):
    """Get quiz questions for a domain, optionally filtered by topic and difficulty.

    Returns list of dicts with:
        id, domain_id, domain_name, topic, difficulty,
        question_text, stimulus, options, correct_index, correct_answer, explanation
    """
    with _get_conn() as conn:
        query = "SELECT q.*, d.name AS domain_name FROM questions q JOIN fcle_domains d ON q.fcle_domain = d.id WHERE 1=1"
        params = []

        if domain_id is not None:
            query += " AND q.fcle_domain = ?"
            params.append(domain_id)
        if topic:
            query += " AND q.topic = ?"
            params.append(topic)
        if difficulty:
            query += " AND q.difficulty = ?"
            params.append(difficulty)

        query += " ORDER BY RANDOM() LIMIT ?"
        params.append(count)

        rows = conn.execute(query, params).fetchall()

    questions = []
    for r in rows:
        options, correct_index = _build_options(r["correct_answer"], r["wrong_answers"])
        questions.append({
            "id": r["id"],
            "domain_id": r["fcle_domain"],
            "domain_name": r["domain_name"],
            "topic": r["topic"],
            "difficulty": r["difficulty"],
            "question_text": r["question"],
            "stimulus": r["stimulus"],
            "options": options,
            "correct_index": correct_index,
            "correct_answer": options[correct_index],
            "explanation": r["explanation"],
            "wrong_answers": json.loads(r["wrong_answers"]) if r["wrong_answers"] else [],
            "wrong_explanations": json.loads(r["wrong_explanations"]) if r["wrong_explanations"] else [],
        })

    return questions


def get_all_quiz_questions(count=5):
    """Get random questions across all domains (mixed review)."""
    return get_domain_quiz_questions(count=count)


def get_mixed_quiz_questions(count=10):
    """Get questions distributed across all 4 domains evenly."""
    per_domain = max(1, count // 4)
    remainder = count % 4
    all_questions = []

    domain_ids = [1, 2, 3, 4]
    for i, did in enumerate(domain_ids):
        n = per_domain + (1 if i < remainder else 0)
        qs = get_domain_quiz_questions(domain_id=did, count=n)
        all_questions.extend(qs)

    random.shuffle(all_questions)
    return all_questions[:count]


# ---------------------------------------------------------------------------
# Per-Domain Convenience Functions
# ---------------------------------------------------------------------------

def get_reading_questions(topic=None, count=5, difficulty=None):
    return get_domain_quiz_questions(domain_id=1, topic=topic, count=count, difficulty=difficulty)

def get_math_questions(topic=None, count=5, difficulty=None):
    return get_domain_quiz_questions(domain_id=2, topic=topic, count=count, difficulty=difficulty)

def get_science_questions(topic=None, count=5, difficulty=None):
    return get_domain_quiz_questions(domain_id=3, topic=topic, count=count, difficulty=difficulty)

def get_english_questions(topic=None, count=5, difficulty=None):
    return get_domain_quiz_questions(domain_id=4, topic=topic, count=count, difficulty=difficulty)


def get_reading_topics():
    return get_domain_topics(1)

def get_math_topics():
    return get_domain_topics(2)

def get_science_topics():
    return get_domain_topics(3)

def get_english_topics():
    return get_domain_topics(4)


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------

def get_total_questions():
    """Total questions in the bank. One COUNT, for live counts shown in the UI.

    UI surfaces must never hardcode the size of the bank: it changes as content
    is added, and a stale count is a false claim. Marketing copy uses a rounded
    floor ("2,000+"); in-product surfaces show this live number.
    """
    with _get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]


def get_question_counts():
    """Return {domain_name: total, domain_name_easy: n, ...} for all domains."""
    domains = get_domains()
    counts = {}
    with _get_conn() as conn:
        for d in domains:
            total = conn.execute("SELECT COUNT(*) FROM questions WHERE fcle_domain=?", (d["id"],)).fetchone()[0]
            easy = conn.execute("SELECT COUNT(*) FROM questions WHERE fcle_domain=? AND difficulty='easy'", (d["id"],)).fetchone()[0]
            medium = conn.execute("SELECT COUNT(*) FROM questions WHERE fcle_domain=? AND difficulty='medium'", (d["id"],)).fetchone()[0]
            hard = conn.execute("SELECT COUNT(*) FROM questions WHERE fcle_domain=? AND difficulty='hard'", (d["id"],)).fetchone()[0]
            stim = conn.execute("SELECT COUNT(*) FROM questions WHERE fcle_domain=? AND stimulus IS NOT NULL AND stimulus != ''", (d["id"],)).fetchone()[0]
            counts[d["name"]] = {"total": total, "easy": easy, "medium": medium, "hard": hard, "stimulus": stim}
    return counts


def get_stimulus_questions(domain_id=None, count=5):
    """Fetch questions that have stimulus passages, optionally filtered by domain."""
    with _get_conn() as conn:
        if domain_id:
            rows = conn.execute(
                "SELECT * FROM questions WHERE fcle_domain=? AND stimulus IS NOT NULL AND stimulus != '' ORDER BY RANDOM() LIMIT ?",
                (domain_id, count),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM questions WHERE stimulus IS NOT NULL AND stimulus != '' ORDER BY RANDOM() LIMIT ?",
                (count,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_stimulus_topics(domain_id=None):
    """Return topics that have stimulus questions."""
    with _get_conn() as conn:
        if domain_id:
            rows = conn.execute(
                "SELECT topic, COUNT(*) AS count FROM questions WHERE fcle_domain=? AND stimulus IS NOT NULL AND stimulus != '' GROUP BY topic ORDER BY topic",
                (domain_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT topic, COUNT(*) AS count FROM questions WHERE stimulus IS NOT NULL AND stimulus != '' GROUP BY topic ORDER BY topic",
            ).fetchall()
        return [{"name": r["topic"], "slug": r["topic"].lower().replace(" ", "-"), "count": r["count"]} for r in rows]
