"""Draft + review + validate all 12 uncovered benchmarks, writing one batch file each.

Drafter = Qwen3.5-9B :8085. Reviewer = gemma-4-26B-vision :8083. Nothing is written to the
database here - the batches are reviewed by the orchestrator before any ingest.
"""
import json
import sys
import urllib.request

sys.path.insert(0, "scripts")
from gen_questions import (COVERAGE, get_benchmark, draft, extract_json, validate)  # noqa: E402

REVIEWER = "gemma-4-26B-vision"
REVIEWER_URL = "http://127.0.0.1:8083/v1/chat/completions"


def review(code, topic, questions):
    b = get_benchmark("data/fcle.db", code)
    qtext = json.dumps(questions, indent=1)
    prompt = (
        "You are fact-checking multiple-choice questions for the Florida Civic Literacy Exam.\n\n"
        "BENCHMARK: %s\nDESCRIPTION: %s\nCLARIFICATIONS: %s\n\n"
        "QUESTIONS (JSON array):\n%s\n\n"
        "For each question, check: (1) the correct answer is factually true and the only right "
        "answer; (2) each distractor is genuinely wrong AND its wrong_explanation correctly says "
        "why; (3) the stem does not reveal the answer; (4) no invented case name, statute, date, "
        "or document; (5) the question actually tests this benchmark, not something else.\n\n"
        "Return ONLY a JSON object: {\"issues\": [{\"index\": 0, \"problem\": \"...\", \"fix\": \"...\"}]}. "
        "If a question is fine, do not list it. If everything is fine, return {\"issues\": []}."
        % (code, b["description"], b["clarifications"], qtext))
    body = json.dumps({"model": REVIEWER, "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0.1, "max_tokens": 2000}).encode()
    req = urllib.request.Request(REVIEWER_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=400) as resp:
            out = json.loads(resp.read().decode())["choices"][0]["message"]["content"]
        issues = extract_json(out)
        return issues.get("issues", []) if isinstance(issues, dict) else []
    except Exception as exc:  # noqa: BLE001
        return [{"index": -1, "problem": "reviewer failed", "fix": "manual check: %s" % exc}]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    codes = sys.argv[2:] or list(COVERAGE)
    for code in codes:
        topic, domain = COVERAGE[code]
        print("== %s (%s) ==" % (code, topic), flush=True)
        items = extract_json(draft(code, topic, n))
        if items is None:
            print("   DRAFT PARSE FAIL", flush=True)
            continue
        errs = validate(items, n)
        issues = review(code, topic, items[:n])
        batch = {"code": code, "topic": topic, "domain": domain,
                 "questions": items[:n], "validation_errors": errs, "review_issues": issues}
        fn = "data/batch_%s.json" % code.replace(".", "_")
        json.dump(batch, open(fn, "w"), indent=1)
        print("   drafted %d | validation errors %d | review issues %d | %s"
              % (len(items[:n]), len(errs), len(issues), fn), flush=True)
        if errs:
            for e in errs:
                print("      V:", e, flush=True)
        for it in issues:
            if it.get("index") is not None:
                print("      R[%s]: %s" % (it.get("index"), str(it.get("problem"))[:130]), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
