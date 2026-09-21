"""Generate questions for one FCLE benchmark, drafted by the local fleet.

Usage: python3 gen_questions.py SS.7.CG.3.10 6

Drafter = Qwen3.5-9B on :8085 (the workhorse). Output goes through a strict
structural gate; a second model reviews, and a human verifies facts. Nothing is
written to the database from this script.
"""
import json
import re
import sqlite3
import sys
import urllib.request

# (benchmark, topic, fcle_domain). Domain follows the official FCLE competency areas
# (1 American Democracy, 2 US Constitution, 3 Founding Documents, 4 Landmark Impact).
# REVIEWABLE: this mapping is my best-effort and is corrected by changing one integer.
COVERAGE = {
    "SS.7.CG.1.5":  ("British colonial policies and the Declaration", 3),
    "SS.7.CG.2.1":  ("Citizenship and naturalization", 1),
    "SS.7.CG.2.2":  ("Obligations and responsibilities of citizenship", 1),
    "SS.7.CG.2.7":  ("Qualifications for public office", 2),
    "SS.7.CG.2.10": ("Citizens addressing state and local problems", 1),
    "SS.7.CG.3.4":  ("Federalism and the Tenth Amendment", 2),
    "SS.7.CG.3.10": ("Sources and types of law", 2),
    "SS.7.CG.3.12": ("Comparing the U.S. and Florida constitutions", 2),
    "SS.7.CG.3.15": ("Economic systems: capitalism and alternatives", 1),
    "SS.7.CG.4.1":  ("Foreign and domestic policy", 1),
    "SS.7.CG.4.2":  ("International organizations", 1),
    "SS.7.CG.4.3":  ("U.S. involvement in international conflicts", 1),
}

SCHEMA = """Return ONLY a JSON array of question objects, no prose. Each object:
{
  "difficulty": "easy" | "medium" | "hard",
  "question": "the stem, scenario-based where possible",
  "correct_answer": "the one right answer as a full sentence",
  "wrong_answers": ["distractor 1", "distractor 2", "distractor 3"],
  "explanation": "why the correct answer is right",
  "wrong_explanations": ["why distractor 1 is wrong", "...2...", "...3..."]
}"""

RULES = """
Hard rules - violating any of these fails the batch:
- Exactly 3 wrong_answers and exactly 3 wrong_explanations, one explanation per distractor.
- Every answer is a full sentence, never a bare word or a letter.
- No "all of the above", "none of the above", "A and B only".
- Never reveal the answer: no "the correct answer is", no letter labels, no hint in the stem.
- No overclaiming: never say "will pass", "guarantee", "ensure you pass", "proves".
- Every claim must be a fact a Florida civics teacher would accept. Do not invent case names,
  statutes, dates, or documents. If unsure of a specific fact, write a question about a
  principle instead.
- Mix difficulty across the batch. Each clarification of the benchmark must be covered by at
  least one question.
- Distractors must be plausible and genuinely wrong; the wrong_explanations must say WHY each
  is wrong (not just that it is).
"""


def get_benchmark(db, code):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    r = c.execute("SELECT * FROM benchmarks WHERE code=?", (code,)).fetchone()
    return dict(r) if r else None


def draft(code, topic, n, model="Qwen3.5-9B", base="http://127.0.0.1:8085"):
    b = get_benchmark("data/fcle.db", code)
    prompt = (
        "You are writing multiple-choice questions for the Florida Civic Literacy Exam (FCLE), "
        "a college-level civics exam. Write %d questions for this benchmark.\n\n"
        "BENCHMARK: %s\nDESCRIPTION: %s\nWHAT STUDENTS MUST DO (clarifications):\n%s\n\n"
        "TOPIC LABEL to use for these questions: %s\n\n"
        "%s\n\n%s\n"
        % (n, code, b["description"], b["clarifications"], topic, SCHEMA, RULES))
    body = json.dumps({"model": model,
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.7, "max_tokens": 12000}).encode()
    req = urllib.request.Request(base + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())["choices"][0]["message"]["content"]


def extract_json(text):
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    # find the first '[' ... last ']'
    a, b = text.find("["), text.rfind("]")
    if a == -1 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None


def validate(items, n):
    errors = []
    if not isinstance(items, list):
        return ["not a JSON array"]
    if len(items) < n:
        errors.append("wanted %d, got %d" % (n, len(items)))
    for i, q in enumerate(items):
        for key in ("difficulty", "question", "correct_answer", "explanation"):
            if not q.get(key):
                errors.append("item %d missing %s" % (i, key))
        wa = q.get("wrong_answers")
        we = q.get("wrong_explanations")
        if not isinstance(wa, list) or len(wa) != 3:
            errors.append("item %d wrong_answers not 3" % i)
        if not isinstance(we, list) or len(we) != 3:
            errors.append("item %d wrong_explanations not 3" % i)
        stem = (q.get("question") or "").lower()
        for banned in ("all of the above", "none of the above", "correct answer is",
                       "the answer is", "guarantee", "will pass", "ensure you pass"):
            if banned in stem or banned in (q.get("explanation") or "").lower():
                errors.append("item %d contains banned phrase '%s'" % (i, banned))
    return errors


if __name__ == "__main__":
    code = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    topic, domain = COVERAGE[code]
    raw = draft(code, topic, n)
    items = extract_json(raw)
    if items is None:
        print("DRAFT FAILED TO PARSE. raw output head:")
        print(raw[:1200])
        sys.exit(1)
    errs = validate(items, n)
    if errs:
        print("VALIDATION ERRORS:")
        for e in errs:
            print("  -", e)
    print("=== %s -> topic '%s' (domain %d): %d questions drafted ===" % (code, topic, domain, len(items)))
    for i, q in enumerate(items[:n], 1):
        print("\n(%d) [%s] %s" % (i, q["difficulty"], q["question"][:180]))
        print("    A: %s" % q["correct_answer"][:160])
        for j, w in enumerate(q["wrong_answers"], 1):
            print("    W%d: %s" % (j, w[:120]))
    out = "data/gen_out_%s.json" % code.replace(".", "_")
    json.dump(items, open(out, "w"), indent=1)
    print("\n[saved] %s" % out)
