"""Shared fixtures. Real bank data where it matters, synthetic where it must be exact."""

import json
import os
from datetime import datetime, timedelta, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)


def real():
    with open(os.path.join(_HERE, "real_data.json")) as fh:
        return json.load(fh)


def answer(qid, domain, topic, correct=True, confidence=3, age_days=0,
           selected="b", code=None):
    return {
        "question_id": qid, "domain": domain, "topic": topic,
        "selected_answer": selected,
        "correct_answer": "a", "is_correct": correct,
        "confidence": confidence,
        "answered_at": (NOW - timedelta(days=age_days)).isoformat(),
        "benchmark_code": code,
    }


def question(qid=1, domain=1, topic="Natural rights and social contract"):
    return {
        "id": qid, "fcle_domain": domain, "topic": topic,
        "difficulty": "medium",
        "question": "Which principle holds that government derives its power from the people?",
        "correct_answer": "Popular sovereignty",
        "wrong_answers": ["Divine right of kings", "Judicial review", "Federal supremacy"],
        "wrong_explanations": [
            "Divine right places authority in a monarch, not the people.",
            "Judicial review concerns courts assessing laws, not the source of authority.",
            "Federal supremacy concerns which level of government prevails.",
        ],
        "explanation": "Popular sovereignty means political power rests with the people.",
        "stimulus": None,
    }


def answers_grid(per_domain=20, correct_rate=0.7, confidence=3):
    out, qid = [], 1
    topics = {1: "Natural rights and social contract", 2: "Federalism",
              3: "Declaration of Independence", 4: "Marbury v Madison"}
    for d in (1, 2, 3, 4):
        n_correct = int(round(per_domain * correct_rate))
        for i in range(per_domain):
            out.append(answer(qid, d, topics[d], correct=i < n_correct,
                              confidence=confidence))
            qid += 1
    return tuple(out)
