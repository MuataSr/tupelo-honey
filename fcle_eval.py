#!/usr/bin/env python3
"""
FCLE Tutor Eval — Socratic scoring rubric v1
Runs 3 cases per batch, scores 4 dimensions × 25pts each.
Uses keyword/pattern matching (same approach as TEAS evals).

Rubric dimensions:
  1. grounded_ref    — answer correctness (matches known correct answer)
  2. consistency     — explanation aligns with the correct answer, no contradictions
  3. mistake_catching — identifies student errors and misconceptions
  4. socratic_hint   — guides through questions, doesn't reveal the answer directly

Usage:
  python3 fcle_eval.py              # run all remaining cases
  python3 fcle_eval.py --reset      # clear results, start fresh
"""
import json
import re
import sys
import time
import urllib.request
import sqlite3
import random
from pathlib import Path
import os

def _env_key(name):
    """Read a credential from the environment, falling back to a repo-root .env.
    Credentials are never committed - see .env.example."""
    v = os.environ.get(name, "")
    if not v and os.path.exists(".env"):
        for _line in open(".env"):
            if _line.strip().startswith(name + "="):
                v = _line.split("=", 1)[1].strip().strip("\"'")
                break
    if not v:
        raise SystemExit(
            f"{name} is not set. Copy .env.example to .env and fill it in, "
            f"or export {name}."
        )
    return v

# ── Config ──────────────────────────────────────────────────────────
TEACHER_URL = "https://api.z.ai/api/coding/paas/v4"
TEACHER_API_KEY = _env_key("ZAI_API_KEY")
MODEL_NAME = "glm-5.1"
TIMEOUT = 90
BATCH_SIZE = 3

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
CASES_FILE = DATA_DIR / "fcle_eval_cases.json"
RESULTS_FILE = DATA_DIR / "fcle_eval_results.json"
DB_PATH = DATA_DIR / "tupelo.db"

# ── System Prompt ───────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert nursing-admissions tutor for students preparing for the ATI TEAS and HESI A2. Those exams test four areas: Reading, Mathematics, Science (anatomy and physiology, biology, chemistry), and English and Language Usage.

You use the Socratic method — guide students to discover answers through questions, never give direct answers. When a student holds a misconception, gently redirect them by asking probing questions that expose the flaw in their thinking. Reference specific constitutional principles, landmark cases, and founding documents."""


# ── 4-Dimension Rubric Patterns ─────────────────────────────────────
# Each dimension: list of regex patterns. Score 0-25 per dimension.
# Normal: 1 hit = 18, 2+ hits = 25
# Penalty (no_answer_reveal): folded into socratic_hint as a deduction

PATTERNS = {
    "socratic_hint": {
        "positive": [
            # Socratic probing questions
            r"\?",
            r"\b(what (do you|would|does|if)|how (do you|would|does|can)|why (do you|would|does|is))\b",
            r"\b(think about|consider|what would happen if|can you explain)\b",
            r"\b(how might|what might|why might|could it be that)\b",
            r"\b(let'?s? (think|consider|look at|examine|explore|break this down))\b",
            r"\b(what'?s? (the connection|the relationship|the difference|your reasoning))\b",
            r"\b(take a step back|put yourself in|imagine|picture this)\b",
        ],
        "penalty": [
            # These indicate the tutor gave away the answer directly
            r"\b(the answer is|the correct answer is)\b",
            r"\b(actually,?\s+(the|it is|they are|that is))\b.{5,40}(the|answer|correct)\b",
            r"\b(that'?s? (correct|right|wrong)|you('?re| are) (correct|wrong|right))\b",
        ],
    },
    "mistake_catching": [
        # Positive: identifies and addresses flawed thinking
        r"\b(that'?s? (a common|not quite|a misconception|an interesting|not exactly))\b",
        r"\b(however|but |on the other hand|actually,?\s+(let|think|consider))\b",
        r"\b(there'?s? (a|another) (way|perspective|angle|issue))\b",
        r"\b(what makes you (say|think)|where did you (hear|learn|get))\b",
        r"\b(common (misconception|belief|idea|assumption|confusion))\b",
        r"\b(mixing up|confusing|conflating|blurring)\b",
        r"\b(there'?s? (a flaw|an issue|something worth (examining|noting|questioning)))\b",
        r"\b(let me (ask|push|challenge)|to help you (see|understand|think))\b",
        r"\b(not (quite|exactly|really)|close,?\s+but|almost)\b",
    ],
    "grounded_ref": {
        "patterns": [
            # Positive: references the correct answer concept/term
            # This dimension is scored differently — checked against the known correct answer
            r"\b(correct|right|accurate|true|yes)\b",
            r"\b(that'?s? (it|right|correct|the key|a good way))\b",
            r"\b(exactly|precisely|spot on|well done)\b",
        ],
    },
    "consistency": {
        "patterns": [
            # Positive: explanation supports reasoning, uses connecting logic
            r"\b(because|since|this (means|is why|shows|demonstrates))\b",
            r"\b(for (example|instance)|in (other words|this case|practice))\b",
            r"\b(the (reason|key|point|issue|distinction|difference) (is|here|to note))\b",
            r"\b(remember|keep in mind|note that|importantly)\b",
            r"\b(this is (why|how|what)|that'?s? (why|how|what))\b",
            r"\b(specifically|in particular|to be (clear|precise))\b",
        ],
        "contradiction": [
            # Penalty: contradictions undermine the explanation
            r"\b(but (actually|in fact|wait)|on (second thought|the contrary))\b.{10,60}",
            r"\b(nevertheless|notwithstanding|despite this)\b.{10,60}(however|but)\b",
        ],
    },
}


def score_socratic_hint(text):
    """Score socratic_hint: positive patterns + penalty for answer reveals."""
    lower = text.lower()
    positive = PATTERNS["socratic_hint"]["positive"]
    penalty = PATTERNS["socratic_hint"]["penalty"]

    hits = sum(1 for p in positive if re.search(p, lower))
    violations = sum(1 for p in penalty if re.search(p, lower))

    # Base score from positive patterns
    if hits >= 3:
        base = 25
    elif hits >= 2:
        base = 22
    elif hits >= 1:
        base = 18
    else:
        base = 8  # Some credit for attempting guidance

    # Penalty deductions for revealing answers
    return max(0, base - violations * 10)


def score_mistake_catching(text):
    """Score mistake_catching: how well the tutor identifies student errors."""
    lower = text.lower()
    patterns = PATTERNS["mistake_catching"]
    hits = sum(1 for p in patterns if re.search(p, lower))

    if hits >= 3:
        return 25
    elif hits >= 2:
        return 22
    elif hits >= 1:
        return 18
    else:
        return 0


def score_grounded_ref(response, correct_answer):
    """Score grounded_ref: does the tutor's response align with the known correct answer?"""
    lower = response.lower()
    answer_lower = correct_answer.lower()

    # Direct mention of correct answer or its key concept
    # Extract key terms from the correct answer (ignore common stop words)
    stop_words = {"the", "a", "an", "is", "are", "was", "were", "of", "in", "to", "for",
                  "and", "or", "but", "not", "with", "by", "on", "at", "from", "that",
                  "this", "it", "its", "has", "have", "had", "be", "been", "being",
                  "which", "who", "whom", "what", "when", "where", "why", "how"}
    answer_words = [w for w in re.findall(r'\b\w+\b', answer_lower) if w not in stop_words and len(w) > 2]

    if not answer_words:
        return 18  # Can't verify, give partial credit

    # Check how many key terms from the correct answer appear in the response
    matched = sum(1 for w in answer_words if w in lower)
    ratio = matched / len(answer_words)

    if ratio >= 0.6:
        return 25
    elif ratio >= 0.4:
        return 22
    elif ratio >= 0.2:
        return 18
    else:
        return 0


def score_consistency(text):
    """Score consistency: explanation logic, connecting reasoning, no contradictions."""
    lower = text.lower()
    positive = PATTERNS["consistency"]["patterns"]
    contradiction = PATTERNS["consistency"]["contradiction"]

    hits = sum(1 for p in positive if re.search(p, lower))
    contradictions = sum(1 for p in contradiction if re.search(p, lower))

    if hits >= 3:
        base = 25
    elif hits >= 2:
        base = 22
    elif hits >= 1:
        base = 18
    else:
        base = 10  # Some credit for coherent text

    return max(0, base - contradictions * 8)


def score_response(response, case):
    """Score a tutor response. Returns (score, max_score, details)."""
    if response.startswith("ERROR:"):
        return 0, 100, {"error": response}

    details = {}

    # Dimension 1: grounded_ref — check against correct answer
    correct_answer = case.get("correct_answer", case.get("correct_option", ""))
    details["grounded_ref"] = score_grounded_ref(response, correct_answer)

    # Dimension 2: consistency
    details["consistency"] = score_consistency(response)

    # Dimension 3: mistake_catching
    details["mistake_catching"] = score_mistake_catching(response)

    # Dimension 4: socratic_hint
    details["socratic_hint"] = score_socratic_hint(response)

    score = sum(details.values())
    return score, 100, details


def get_kb_context(case):
    """Pull relevant KB context for a case from the FCLE database."""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row

        context_parts = []
        domain = case.get("domain", "")

        # Get domain info
        try:
            row = conn.execute(
                "SELECT * FROM fcle_domains WHERE id = ?", (domain,)
            ).fetchone()
            if row:
                info = dict(row)
                context_parts.append(f"FCLE Domain {info['id']}: {info.get('name', '')}")
                if info.get('description'):
                    context_parts.append(f"  {info['description']}")
        except Exception:
            pass

        # Get relevant misconceptions for this domain
        try:
            rows = conn.execute(
                "SELECT misconception FROM misconceptions WHERE fcle_domain = ? ORDER BY RANDOM() LIMIT 3",
                (domain,),
            ).fetchall()
            if rows:
                context_parts.append("\nCommon misconceptions in this area:")
                for r in rows:
                    context_parts.append(f"- {r['misconception'][:120]}")
        except Exception:
            pass

        # Search FTS for relevant content
        try:
            keywords = case.get("question", "").split()[:5]
            search_query = " OR ".join(kw for kw in keywords if len(kw) > 3)
            if search_query:
                clean = search_query.replace('"', '""')
                rows = conn.execute(
                    """SELECT snippet(fcle_content_fts, 2, '<b>', '</b>', '...', 32) as snippet
                       FROM fcle_content_fts WHERE fcle_content_fts MATCH ? LIMIT 2""",
                    (clean,),
                ).fetchall()
                if rows:
                    context_parts.append("\nRelevant reference material:")
                    for r in rows:
                        context_parts.append(f"- {r['snippet'][:150]}")
        except Exception:
            pass

        # Also try questions_fts for topic-related context
        try:
            topic = case.get("topic", "")
            if topic and len(topic) > 3:
                clean_topic = topic.replace('"', '""')
                rows = conn.execute(
                    """SELECT snippet(questions_fts, 4, '<b>', '</b>', '...', 32) as snippet
                       FROM questions_fts WHERE questions_fts MATCH ? LIMIT 1""",
                    (clean_topic,),
                ).fetchall()
                if rows:
                    context_parts.append(f"\nRelated topic: {rows[0]['snippet'][:150]}")
        except Exception:
            pass

        conn.close()
        return "\n".join(context_parts) if context_parts else ""
    except Exception as e:
        return f"[KB context error: {e}]"


def call_teacher(system_prompt, user_message):
    """Call the teacher model via Z.AI cloud API (OpenAI-compatible)."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": 1024,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        f"{TEACHER_URL}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TEACHER_API_KEY}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"ERROR: {e}"


def build_student_prompt(case):
    """Build a realistic student prompt from an eval case."""
    question = case.get("question", "")
    student_answer = case.get("student_answer", "")

    if student_answer:
        return f"A nursing-school applicant studying for the TEAS says:\n\n\"{question}\"\n\nThey think the answer is: \"{student_answer}\"\n\nHelp them think through this using the Socratic method."
    else:
        return f"A nursing-school applicant studying for the TEAS asks:\n\n\"{question}\"\n\nHelp them using the Socratic method."


def run_batch(cases, batch_num):
    """Run a batch of cases and return results."""
    batch_results = []

    for i, case in enumerate(cases):
        case_id = case["id"]
        domain = case.get("domain", "?")
        difficulty = case.get("difficulty", case.get("complexity", "?"))
        print(f"\n  [{batch_num}.{i+1}] {case_id}")
        print(f"    Domain: {domain} | Difficulty: {difficulty}")
        q = case.get("question", case.get("student_question", ""))
        print(f"    Q: {q[:80]}...")

        # Build context from KB
        kb_context = get_kb_context(case)

        # Build system prompt with KB context
        sys_prompt = SYSTEM_PROMPT
        if kb_context:
            sys_prompt += f"\n\nReference material:\n{kb_context}"

        # Build user prompt
        user_prompt = build_student_prompt(case)

        # Call teacher
        t0 = time.time()
        response = call_teacher(sys_prompt, user_prompt)
        elapsed = time.time() - t0

        # Score
        score, max_score, details = score_response(response, case)
        pct = (score / max_score * 100) if max_score > 0 else 0

        result = {
            "id": case_id,
            "domain": domain,
            "difficulty": difficulty,
            "score": score,
            "max": max_score,
            "pct": round(pct, 1),
            "time": round(elapsed, 1),
            "details": details,
            "response": response[:500],
        }
        batch_results.append(result)

        grade = "A" if pct >= 90 else "B" if pct >= 75 else "C" if pct >= 60 else "D" if pct >= 40 else "F"
        print(f"    → {score}/{max_score} ({pct:.0f}%) [{grade}] ({elapsed:.1f}s)")
        for dim, val in details.items():
            print(f"       {dim:25s} {val}/25")

    return batch_results


def save_results(all_results):
    """Save incremental results."""
    with open(RESULTS_FILE, "w") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "rubric": "v1-4dim-fcle-socratic",
            "dimensions": ["grounded_ref", "consistency", "mistake_catching", "socratic_hint"],
            "results": all_results,
        }, f, indent=2)


def print_summary(all_results):
    """Print running summary."""
    if not all_results:
        return

    total = len(all_results)
    scores = [r["pct"] for r in all_results]
    avg = sum(scores) / total

    dim_avgs = {}
    for dim in ["grounded_ref", "consistency", "mistake_catching", "socratic_hint"]:
        vals = [r["details"].get(dim, 0) for r in all_results]
        dim_avgs[dim] = sum(vals) / total

    # By domain
    by_domain = {}
    for r in all_results:
        d = r["domain"]
        if d not in by_domain:
            by_domain[d] = []
        by_domain[d].append(r["pct"])

    # By difficulty
    by_diff = {}
    for r in all_results:
        diff = r["difficulty"]
        if diff not in by_diff:
            by_diff[diff] = []
        by_diff[diff].append(r["pct"])

    print(f"\n{'='*55}")
    print(f"FCLE EVAL SUMMARY — {total} cases")
    print(f"{'='*55}")
    print(f"Overall:  {avg:.1f}%")
    print(f"\nDimensions:")
    for dim, val in dim_avgs.items():
        bar = "█" * int(val / 25 * 10)
        print(f"  {dim:25s} {val:5.1f}/25 {bar}")

    print(f"\nBy domain:")
    for d in sorted(by_domain.keys()):
        d_avg = sum(by_domain[d]) / len(by_domain[d])
        domain_names = {1: "American Democracy", 2: "US Constitution", 3: "Founding Docs", 4: "Landmark Impact"}
        name = domain_names.get(d, f"Domain {d}")
        print(f"  D{d} {name:25s} {d_avg:.1f}% ({len(by_domain[d])} cases)")

    if by_diff:
        print(f"\nBy difficulty:")
        for diff in sorted(by_diff.keys()):
            diff_avg = sum(by_diff[diff]) / len(by_diff[diff])
            print(f"  {diff:8s} {diff_avg:.1f}% ({len(by_diff[diff])} cases)")


def generate_sample_cases(count=100):
    """Generate sample eval cases from the FCLE question bank."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    cases = []
    case_id = 0

    for domain in [1, 2, 3, 4]:
        per_domain = count // 4
        rows = conn.execute(
            """SELECT * FROM questions
               WHERE fcle_domain = ?
               ORDER BY RANDOM() LIMIT ?""",
            (domain, per_domain),
        ).fetchall()

        for r in rows:
            case_id += 1
            q = dict(r)

            # Parse wrong_answers JSON to get a student's wrong pick
            wrong_answer = ""
            try:
                import json
                wrongs = json.loads(q.get("wrong_answers", "[]"))
                if wrongs:
                    wrong_answer = random.choice(wrongs)
            except Exception:
                wrong_answer = ""

            cases.append({
                "id": f"FCLE-EVAL-{case_id:03d}",
                "domain": domain,
                "difficulty": q.get("difficulty", "medium"),
                "topic": q.get("topic", ""),
                "question": q.get("question", ""),
                "correct_answer": q.get("correct_answer", ""),
                "student_answer": wrong_answer,
            })

    conn.close()
    return cases


def main():
    if "--reset" in sys.argv:
        if RESULTS_FILE.exists():
            RESULTS_FILE.unlink()
            print("Results cleared.")
        if CASES_FILE.exists():
            CASES_FILE.unlink()
            print("Cases cleared.")

    # Generate or load eval cases
    if not CASES_FILE.exists():
        print("Generating eval cases from question bank...")
        cases = generate_sample_cases(count=100)
        with open(CASES_FILE, "w") as f:
            json.dump(cases, f, indent=2)
        print(f"Generated {len(cases)} eval cases → {CASES_FILE}")
    else:
        with open(CASES_FILE) as f:
            cases = json.load(f)
        print(f"Loaded {len(cases)} eval cases")

    # Load existing results (resume support)
    existing = []
    if RESULTS_FILE.exists():
        with open(RESULTS_FILE) as f:
            existing_data = json.load(f)
            existing = existing_data.get("results", [])

    # Filter out error cases
    existing = [r for r in existing if not r.get("details", {}).get("error")]
    done_ids = {r["id"] for r in existing}
    print(f"Resuming — {len(existing)} cases already scored")

    remaining = [c for c in cases if c["id"] not in done_ids]
    print(f"{len(remaining)} cases remaining\n")

    if not remaining:
        print("All cases scored! Final summary:")
        print_summary(existing)
        return

    # Run in batches of 3
    for i in range(0, len(remaining), BATCH_SIZE):
        batch = remaining[i:i + BATCH_SIZE]
        actual_batch_num = (len(existing) + i) // BATCH_SIZE + 1

        print(f"\n{'─'*55}")
        print(f"BATCH {actual_batch_num} — cases {len(existing)+i+1} to {min(len(existing)+i+BATCH_SIZE, len(cases))}")
        print(f"{'─'*55}")

        batch_results = run_batch(batch, actual_batch_num)
        existing.extend(batch_results)
        save_results(existing)
        print_summary(existing)

    print(f"\n{'='*55}")
    print(f"FINAL RESULTS — {len(existing)} cases")
    print(f"{'='*55}")
    print_summary(existing)
    print(f"\nResults saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
