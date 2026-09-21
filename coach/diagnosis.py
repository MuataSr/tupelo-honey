"""Turn a single answered question into a coaching directive.

This is where the app's confidence capture earns its keep. `answers.confidence`
is 1/2/3 (not sure / kinda sure / sure) and multiplying it by correctness gives
six states with genuinely different coaching responses. The valuable one is
SURE + WRONG: a belief held confidently that will cost exam points. It is the
top of the coach's queue and no competitor surfaces it.
"""

import json
from dataclasses import dataclass, field

from . import router, rules

STATE_MASTERED = "MASTERED"
STATE_FRAGILE = "FRAGILE"
STATE_MISCONCEPTION = "MISCONCEPTION"
STATE_GAP = "GAP"
STATE_UNSEEN = "UNSEEN"

# confidence x is_correct -> state
QUADRANTS = {
    (rules.CONFIDENCE_SURE, True): STATE_MASTERED,
    (rules.CONFIDENCE_SURE, False): STATE_MISCONCEPTION,
    (rules.CONFIDENCE_KINDA, True): STATE_FRAGILE,
    (rules.CONFIDENCE_KINDA, False): STATE_GAP,
    (rules.CONFIDENCE_UNSURE, True): STATE_FRAGILE,
    (rules.CONFIDENCE_UNSURE, False): STATE_GAP,
}

# Which states are worth showing the whole teach block for.
TEACH_STATES = (STATE_MISCONCEPTION, STATE_GAP, STATE_FRAGILE)


@dataclass
class Directive:
    """Everything the UI needs to render one answer's feedback."""
    question_id: int
    domain: int
    topic: str
    state: str
    confidence: int
    misconception_id: int = None
    misconception_text: str = ""
    correction: str = ""
    refutation: str = ""
    explanation: str = ""
    benchmark_code: str = None
    match_tier: str = "none"      # benchmark | topic | domain | none
    next_review_days: int = rules.SRS_FIRST_INTERVAL_DAYS
    read_section_id: int = None
    read_section_title: str = ""
    read_section_url: str = ""

    @property
    def is_teachable(self):
        return self.state in TEACH_STATES


def normalise_confidence(value):
    """Never raise on junk, and never COERCE junk into a real value.

    `int(2.7)` is 2, which would silently turn a nonsensical input into "kinda
    sure". Only an exact 1/2/3 - as int, whole float, or numeric string - is
    accepted; everything else degrades to the unsure path.
    """
    if isinstance(value, bool):
        return rules.DEFAULT_CONFIDENCE
    if isinstance(value, int):
        n = value
    elif isinstance(value, float):
        if value != int(value):
            return rules.DEFAULT_CONFIDENCE
        n = int(value)
    elif isinstance(value, str):
        text = value.strip()
        if text not in ("1", "2", "3"):
            return rules.DEFAULT_CONFIDENCE
        n = int(text)
    else:
        return rules.DEFAULT_CONFIDENCE
    return n if n in rules.VALID_CONFIDENCE else rules.DEFAULT_CONFIDENCE


def classify(confidence, is_correct):
    """The six-cell classifier. Total: every input maps to exactly one state."""
    return QUADRANTS[(normalise_confidence(confidence), bool(is_correct))]


def _tokens(text):
    return {t for t in (text or "").lower().replace("/", " ").replace("-", " ").split() if len(t) > 2}


def token_overlap(a, b):
    return len(_tokens(a) & _tokens(b))


def next_review_days(state, confidence):
    """Misconceptions come back tomorrow; confident-correct ones go away longest."""
    if state == STATE_MISCONCEPTION:
        return rules.MISCONCEPTION_RETEST_DAYS
    if state == STATE_MASTERED:
        return rules.SRS_FIRST_INTERVAL_DAYS * int(rules.SRS_CORRECT_FACTOR)
    if state == STATE_FRAGILE:
        return rules.SRS_FIRST_INTERVAL_DAYS
    return rules.SRS_FIRST_INTERVAL_DAYS


def as_list(value):
    """Accept a parsed list OR the raw JSON text the database stores.

    `questions.wrong_answers` and `wrong_explanations` are JSON-encoded columns.
    A caller may hand us either the parsed form (kb.py parses on read) or the raw
    row. Accepting both is not defensiveness for its own sake: getting this wrong
    silently drops the refutation, which is the whole feature.
    """
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def refutation_for(question, selected_answer):
    """The authored refutation for the exact distractor the student chose.

    Returns "" rather than raising when the lists are absent or misaligned
    (5 of 2175 rows in the live bank carry no refutations).
    """
    wrongs = as_list(question.get("wrong_answers"))
    refs = as_list(question.get("wrong_explanations"))
    if not wrongs or not refs:
        return ""
    try:
        idx = wrongs.index(selected_answer)
    except ValueError:
        return ""
    if 0 <= idx < len(refs):
        return str(refs[idx] or "")
    return ""


def match_misconception(domain, topic, misconceptions, benchmark_code=None):
    """Three-tier match, most precise first. Returns (row, tier) or (None, "none").

    Tier 1 (benchmark) needs the topic->benchmark map loaded; until then tier 2
    carries the load. Tier 3 is a last resort and is flagged as generic.
    """
    if not misconceptions:
        return None, "none"

    same_domain = [m for m in misconceptions if m.get("fcle_domain") == domain]

    if benchmark_code:
        for m in same_domain:
            if m.get("benchmark_code") == benchmark_code:
                return m, "benchmark"

    best, best_score = None, 0
    for m in same_domain:
        score = token_overlap(topic, m.get("misconception", ""))
        if score > best_score:
            best, best_score = m, score
    if best is not None and best_score >= rules.MISCONCEPTION_TOKEN_MIN:
        return best, "topic"

    return (same_domain[0], "domain") if same_domain else (None, "none")


def build_directive(answer, question, misconceptions=(), sections=(),
                    benchmark_code=None, read_section=None):
    """Compose the full directive for one answered question.

    `answer`    - one answers-table row (dict)
    `question`  - one questions-table row (dict)
    `sections`  - candidate content rows for the reading router
    """
    confidence = normalise_confidence(answer.get("confidence"))
    is_correct = bool(answer.get("is_correct"))
    state = classify(confidence, is_correct)
    domain = question.get("fcle_domain", answer.get("domain", 0))
    topic = question.get("topic", answer.get("topic", ""))

    row, tier = (None, "none")
    if state in (STATE_MISCONCEPTION, STATE_GAP):
        row, tier = match_misconception(domain, topic, list(misconceptions), benchmark_code)

    return Directive(
        question_id=question.get("id", answer.get("question_id")),
        domain=domain,
        topic=topic,
        state=state,
        confidence=confidence,
        misconception_id=(row or {}).get("id"),
        misconception_text=(row or {}).get("misconception", ""),
        correction=(row or {}).get("correction", ""),
        refutation="" if is_correct else refutation_for(
            question, answer.get("selected_answer")),
        explanation=question.get("explanation", "") or "",
        benchmark_code=benchmark_code,
        match_tier=tier,
        next_review_days=next_review_days(state, confidence),
        read_section_id=(read_section or {}).get("id"),
        # Normalise here, not in each surface: the stored titles carry trailing '*'
        # markers and NBSPs, and the reading card is not the only place they render.
        read_section_title=router.display_title(read_section or {}),
        read_section_url=(read_section or {}).get("reading_url") or "",
    )
