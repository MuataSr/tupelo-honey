#!/usr/bin/env python3
"""
Re-grade D1 easy questions to correct difficulty distribution.

D1 currently: 78 easy / 2 medium / 0 hard
Target:       24 easy / 36 medium / 20 hard

Strategy:
1. Fetch all 78 D1 easy questions
2. Send batches to LLM for difficulty classification (easy/medium/hard)
3. Assign: keep 24 as easy, bump 34→medium, bump 20→hard
4. Delete the remaining extras
5. Fix D4 (79→80)
6. Validate final distribution

Uses local llama-server on port 8082 (Qwen 3.5 4B).

Usage:
  python3 regrade_d1.py           # full re-grade
  python3 regrade_d1.py --dry-run # classify only, don't modify DB
  python3 regrade_d1.py --status  # print current distribution
"""

import sqlite3
import json
import urllib.request
import urllib.error
import time
import argparse
import os
import sys
import random

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "..", "data", "tupelo.db")
LLM_URL = "http://0.0.0.0:8082/v1/chat/completions"

# Actual distribution from DIFFICULTY_POOL (30/45/25) for 80 questions:
# indices 0-29=easy(30), 30-74=medium(45), 75-79=hard(5)
TARGETS = {1: {"easy": 30, "medium": 45, "hard": 5},
           2: {"easy": 30, "medium": 45, "hard": 5},
           3: {"easy": 30, "medium": 45, "hard": 5},
           4: {"easy": 30, "medium": 45, "hard": 5}}
TARGET_TOTAL = 80

BATCH_SIZE = 6  # questions per LLM call


def load_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_distribution(conn):
    """Return distribution dict."""
    dist = {}
    for d in range(1, 5):
        dist[d] = {}
        for diff in ["easy", "medium", "hard"]:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM questions WHERE fcle_domain=? AND difficulty=?",
                (d, diff)
            ).fetchone()
            dist[d][diff] = row["cnt"]
        dist[d]["total"] = sum(dist[d].values())
    return dist


def print_distribution(conn):
    dist = get_distribution(conn)
    print("Domain | Easy | Med | Hard | Total")
    print("-" * 40)
    for d in range(1, 5):
        t = dist[d]
        print(f"  D{d}   | {t['easy']:4d} | {t['medium']:3d} | {t['hard']:4d} | {t['total']:5d}")
    print(f"Total:  {sum(dist[d]['easy'] for d in dist):4d} | "
          f"{sum(dist[d]['medium'] for d in dist):3d} | "
          f"{sum(dist[d]['hard'] for d in dist):4d} | "
          f"{sum(dist[d]['total'] for d in dist):5d}")


def classify_batch(questions, conn):
    """Send a batch of questions to LLM for difficulty classification.
    
    Returns list of (question_id, classified_difficulty) tuples.
    """
    q_list = "\n\n".join(
        f"[Q{q['id']}] {q['question']}\n"
        f"Correct: {q['correct_answer']}\n"
        f"Wrong: {q['wrong_answers']}"
        for q in questions
    )

    prompt = f"""You are an expert question difficulty classifier for the Florida Civic Literacy Exam (FCLE).

Classify each question as easy, medium, or hard based on cognitive demand:

- EASY: Factual recall — "Which document established...", "Who wrote...", "What is the main purpose of..."
- MEDIUM: Conceptual understanding — requires connecting ideas, understanding principles, explaining relationships
- HARD: Application/analysis — "If a state law conflicts with...", "Which scenario best illustrates...", comparing multiple concepts

QUESTIONS:
{q_list}

Respond ONLY with a JSON object mapping each question ID to its difficulty.
Example: {{"Q1": "easy", "Q2": "medium", "Q3": "hard"}}

No explanation. Just the JSON."""

    payload = json.dumps({
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": 0.2,
        "top_p": 0.9,
    }).encode()

    headers = {"Content-Type": "application/json"}
    
    for attempt in range(3):
        try:
            req = urllib.request.Request(LLM_URL, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = resp.read().decode()
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"].strip()
                
                # Strip thinking tags
                if "</think" in content:
                    content = content.split("</think")[-1].strip()
                if "<think" in content:
                    content = content.split("<think")[0].strip()
                
                # Extract JSON
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                classifications = json.loads(content)
                results = []
                for q in questions:
                    qid = f"Q{q['id']}"
                    diff = classifications.get(qid, "medium").lower().strip()
                    if diff not in ("easy", "medium", "hard"):
                        diff = "medium"
                    results.append((q['id'], diff))
                return results
                
        except Exception as e:
            print(f"    Retry {attempt+1}/3: {e}")
            time.sleep((attempt + 1) * 3)
    
    # Fallback: mark all as medium
    print("    ⚠ LLM failed, defaulting to medium")
    return [(q['id'], 'medium') for q in questions]


def regrade_d1(conn, dry_run=False):
    """Re-grade ALL D1 questions to target distribution (30/45/5)."""
    print("\n=== D1 RE-GRADE ===")

    # Fetch ALL D1 questions (not just easy)
    questions = conn.execute(
        "SELECT id, question, correct_answer, wrong_answers, difficulty FROM questions "
        "WHERE fcle_domain=1 ORDER BY id"
    ).fetchall()

    current_total = len(questions)
    target_total = TARGET_TOTAL
    gap = target_total - current_total

    print(f"Current: {current_total} questions")
    print(f"Target:  {target_total} ({TARGETS[1]['easy']}/{TARGETS[1]['medium']}/{TARGETS[1]['hard']} easy/med/hard)")
    if gap > 0:
        print(f"Gap:     {gap} questions to generate after re-grade")

    # Classify ALL existing questions in batches
    all_classifications = []
    for i in range(0, len(questions), BATCH_SIZE):
        batch = questions[i:i+BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(questions) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  Classifying batch {batch_num}/{total_batches} ({len(batch)} questions)...")

        results = classify_batch(batch, conn)
        all_classifications.extend(results)

        easy_so_far = sum(1 for _, d in all_classifications if d == "easy")
        med_so_far = sum(1 for _, d in all_classifications if d == "medium")
        hard_so_far = sum(1 for _, d in all_classifications if d == "hard")
        print(f"    Running: easy={easy_so_far} medium={med_so_far} hard={hard_so_far}")

    # Build pools by LLM classification
    easy_pool = sorted([qid for qid, d in all_classifications if d == "easy"])
    med_pool = sorted([qid for qid, d in all_classifications if d == "medium"])
    hard_pool = sorted([qid for qid, d in all_classifications if d == "hard"])

    te, tm, th = TARGETS[1]["easy"], TARGETS[1]["medium"], TARGETS[1]["hard"]

    # Assign from pools, truncating to targets (no deletion since we need all + gap)
    # Priority: take as many as the LLM says up to the target
    easy_assign = easy_pool[:te]
    med_assign = med_pool[:tm]
    hard_assign = hard_pool[:th]

    # Leftover questions from each pool that exceed targets → reassign to fill gaps
    leftover = []
    leftover.extend([(qid, "easy") for qid in easy_pool[te:]])
    leftover.extend([(qid, "medium") for qid in med_pool[tm:]])
    leftover.extend([(qid, "hard") for qid in hard_pool[th:]])

    # Fill gaps with leftovers
    easy_gap = te - len(easy_assign)
    for qid, orig in leftover:
        if easy_gap <= 0:
            break
        easy_assign.append(qid)
        easy_gap -= 1
    leftover = [(qid, orig) for qid, orig in leftover if qid not in set(easy_assign)]

    med_gap = tm - len(med_assign)
    for qid, orig in leftover:
        if med_gap <= 0:
            break
        med_assign.append(qid)
        med_gap -= 1
    leftover = [(qid, orig) for qid, orig in leftover if qid not in set(med_assign)]

    hard_gap = th - len(hard_assign)
    for qid, orig in leftover:
        if hard_gap <= 0:
            break
        hard_assign.append(qid)
        hard_gap -= 1
    leftover = [(qid, orig) for qid, orig in leftover if qid not in set(hard_assign)]

    # Still have leftovers? These exceed total target — delete them
    delete_ids = [qid for qid, _ in leftover]

    # Calculate what we still need to generate
    still_need_easy = te - len(easy_assign)
    still_need_med = tm - len(med_assign)
    still_need_hard = th - len(hard_assign)

    print(f"\n  After re-grade:")
    print(f"    Easy:   {len(easy_assign)} (need {still_need_easy} more)")
    print(f"    Medium: {len(med_assign)} (need {still_need_med} more)")
    print(f"    Hard:   {len(hard_assign)} (need {still_need_hard} more)")
    print(f"    Delete: {len(delete_ids)}")
    print(f"    Generate: {still_need_easy + still_need_med + still_need_hard}")

    if dry_run:
        print("\n  [DRY RUN] No changes made")
        return still_need_easy, still_need_med, still_need_hard

    # Execute difficulty updates
    for qid in easy_assign:
        conn.execute("UPDATE questions SET difficulty='easy' WHERE id=?", (qid,))
    for qid in med_assign:
        conn.execute("UPDATE questions SET difficulty='medium' WHERE id=?", (qid,))
    for qid in hard_assign:
        conn.execute("UPDATE questions SET difficulty='hard' WHERE id=?", (qid,))

    for qid in delete_ids:
        conn.execute("DELETE FROM questions WHERE id=?", (qid,))

    conn.commit()
    print(f"  ✅ D1 re-grade complete")

    return still_need_easy, still_need_med, still_need_hard


def fix_d4(conn, dry_run=False):
    """Generate 1 more D4 question to hit 80."""
    current = conn.execute(
        "SELECT COUNT(*) as cnt FROM questions WHERE fcle_domain=4"
    ).fetchone()["cnt"]
    
    if current >= TARGET_TOTAL:
        print(f"\n=== D4: {current}/{TARGET_TOTAL} — already at target, skipping ===")
        return
    
    needed = TARGET_TOTAL - current
    print(f"\n=== D4 FIX: {current}/{TARGET_TOTAL}, need {needed} more ===")
    
    if dry_run:
        print("  [DRY RUN] Would generate 1 question")
        return
    
    # Pick a topic that's underrepresented
    d4_topics = [
        "Marbury v Madison", "McCulloch v Maryland", "Brown v Board of Education",
        "Gideon v Wainwright", "Miranda v Arizona", "Tinker v Des Moines",
        "Schenck v United States", "Civil Rights Act 1964", "Voting Rights Act 1965",
        "ADA and landmark legislation"
    ]
    
    topic_counts = {}
    for t in d4_topics:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM questions WHERE fcle_domain=4 AND topic=?", (t,)
        ).fetchone()
        topic_counts[t] = row["cnt"]
    
    # Pick topic with fewest questions
    weakest = min(topic_counts, key=topic_counts.get)
    
    # Pick difficulty with fewest
    diff_counts = {}
    for diff in ["easy", "medium", "hard"]:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM questions WHERE fcle_domain=4 AND difficulty=?", (diff,)
        ).fetchone()
        diff_counts[diff] = row["cnt"]
    
    weakest_diff = min(diff_counts, key=diff_counts.get)
    
    print(f"  Generating: topic='{weakest}' ({topic_counts[weakest]} exist), difficulty={weakest_diff}")
    
    prompt = f"""Generate exactly 1 multiple-choice question for the Florida Civic Literacy Exam.

Topic: {weakest}
Difficulty: {weakest_diff}
Domain: Landmark Supreme Court cases and legislation impact

Requirements:
- The question should test {weakest_diff}-level understanding of {weakest}
- Provide 3 plausible wrong answers (same length/tone as correct answer)
- Explanation must be 250+ characters explaining why the correct answer is right AND why common wrong answers are wrong
- No "All of the above" or "None of the above"
- No negative phrasing ("Which is NOT...")

Respond ONLY with valid JSON:
{{"question": "...", "correct_answer": "...", "wrong_answers": ["...", "...", "..."], "explanation": "..."}}"""

    payload = json.dumps({
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 600,
        "temperature": 0.75,
        "top_p": 0.9,
    }).encode()
    headers = {"Content-Type": "application/json"}
    
    for attempt in range(3):
        try:
            req = urllib.request.Request(LLM_URL, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = resp.read().decode()
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"].strip()
                
                if "</think" in content:
                    content = content.split("</think")[-1].strip()
                if "<think" in content:
                    content = content.split("<think")[0].strip()
                
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                
                q = json.loads(content)
                
                if (q.get("question") and q.get("correct_answer") and 
                    isinstance(q.get("wrong_answers"), list) and len(q["wrong_answers"]) >= 3 and
                    len(q.get("explanation", "")) >= 250):
                    
                    conn.execute(
                        "INSERT INTO questions (fcle_domain, topic, difficulty, question, correct_answer, wrong_answers, explanation) VALUES (?,?,?,?,?,?,?)",
                        (4, weakest, weakest_diff, q["question"].strip(), q["correct_answer"].strip(),
                         json.dumps(q["wrong_answers"][:3]), q["explanation"].strip())
                    )
                    conn.commit()
                    print(f"  ✅ Inserted D4 question (ID: {conn.execute('SELECT last_insert_rowid()').fetchone()[0]})")
                    return
                else:
                    print(f"  ⚠ Parse OK but validation failed (short explanation or missing fields), retrying...")
                    
        except Exception as e:
            print(f"  Retry {attempt+1}/3: {e}")
            time.sleep((attempt + 1) * 3)
    
    print("  ⚠ Failed to generate D4 question after 3 attempts")


def generate_d1_gap(conn, need_easy, need_med, need_hard):
    """Generate missing D1 questions to fill gaps after re-grade."""
    if need_easy + need_med + need_hard == 0:
        return

    D1_TOPICS = {
        "Natural rights and social contract": "Locke, Montesquieu, consent of the governed",
        "Limited government and rule of law": "constitutional limits, due process, separation of powers",
        "Popular sovereignty": "We the People, consent of governed",
        "Citizen participation": "voting, contacting officials, public comment",
        "Political parties and elections": "two-party system, primaries, electoral process",
        "Interest groups and lobbying": "PACs, lobbying strategies, influence on policy",
        "Media and public opinion": "media bias, agenda-setting, framing",
        "Political socialization": "family, school, peers as agents",
        "Political culture and ideology": "liberalism, conservatism, political spectrum",
        "Federalism basics": "expressed, implied, concurrent, reserved powers",
    }

    # Pick underrepresented topics
    topic_counts = {}
    for t in D1_TOPICS:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM questions WHERE fcle_domain=1 AND topic=?", (t,)
        ).fetchone()
        topic_counts[t] = row["cnt"]

    topics_by_need = sorted(topic_counts, key=topic_counts.get)

    to_generate = []
    for _ in range(need_easy):
        to_generate.append(("easy", topics_by_need[len(to_generate) % len(topics_by_need)]))
    for _ in range(need_med):
        to_generate.append(("medium", topics_by_need[len(to_generate) % len(topics_by_need)]))
    for _ in range(need_hard):
        to_generate.append(("hard", topics_by_need[len(to_generate) % len(topics_by_need)]))

    random.shuffle(to_generate)

    print(f"\n=== GENERATING {len(to_generate)} D1 QUESTIONS ===")

    for i, (diff, topic) in enumerate(to_generate):
        print(f"  [{i+1}/{len(to_generate)}] {diff} - {topic}...", end=" ", flush=True)

        prompt = f"""Generate 1 multiple-choice question for the Florida Civic Literacy Exam.

Domain: American Democracy
Topic: {topic}
Difficulty: {diff}

Requirements:
- {diff}-level question about {topic} and {D1_TOPICS[topic]}
- 3 plausible wrong answers (same length/tone as correct)
- Explanation 250+ characters
- No "All of the above", "None of the above", or negative phrasing

JSON only:
{{"question": "...", "correct_answer": "...", "wrong_answers": ["...", "...", "..."], "explanation": "..."}}"""

        payload = json.dumps({
            "model": "local",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 600,
            "temperature": 0.75,
            "top_p": 0.9,
        }).encode()
        headers = {"Content-Type": "application/json"}

        inserted = False
        for attempt in range(3):
            try:
                req = urllib.request.Request(LLM_URL, data=payload, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=90) as resp:
                    body = resp.read().decode()
                    result = json.loads(body)
                    content = result["choices"][0]["message"]["content"].strip()

                    if "</think" in content:
                        content = content.split("</think")[-1].strip()
                    if "<think" in content:
                        content = content.split("<think")[0].strip()
                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0].strip()

                    q = json.loads(content)
                    if (q.get("question") and q.get("correct_answer") and
                        isinstance(q.get("wrong_answers"), list) and len(q["wrong_answers"]) >= 3 and
                        len(q.get("explanation", "")) >= 250):

                        conn.execute(
                            "INSERT INTO questions (fcle_domain, topic, difficulty, question, correct_answer, wrong_answers, explanation) VALUES (?,?,?,?,?,?,?)",
                            (1, topic, diff, q["question"].strip(), q["correct_answer"].strip(),
                             json.dumps(q["wrong_answers"][:3]), q["explanation"].strip())
                        )
                        conn.commit()
                        print("✅")
                        inserted = True
                        break
            except Exception as e:
                time.sleep((attempt + 1) * 2)

        if not inserted:
            print("⚠ failed")


def validate(conn):
    """Final validation checks."""
    print("\n=== VALIDATION ===")
    dist = get_distribution(conn)
    
    ok = True
    for d in range(1, 5):
        for diff in ["easy", "medium", "hard"]:
            actual = dist[d][diff]
            target = TARGETS[d][diff]
            if actual != target:
                print(f"  ⚠ D{d} {diff}: {actual} (target {target})")
                ok = False
        if dist[d]["total"] != TARGET_TOTAL:
            print(f"  ⚠ D{d} total: {dist[d]['total']} (target {TARGET_TOTAL})")
            ok = False
    
    # Check no bad distractors
    none_ct = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE wrong_answers LIKE '%None of the above%'"
    ).fetchone()[0]
    all_ct = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE wrong_answers LIKE '%All of the above%'"
    ).fetchone()[0]
    not_ct = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE question LIKE '%is NOT%' OR question LIKE '%is NOT %'"
    ).fetchone()[0]
    
    if none_ct > 0 or all_ct > 0 or not_ct > 0:
        print(f"  ⚠ Bad patterns: None={none_ct}, All={all_ct}, NOT={not_ct}")
        ok = False
    
    # Check explanation lengths
    short = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE LENGTH(explanation) < 250"
    ).fetchone()[0]
    if short > 0:
        print(f"  ⚠ Short explanations: {short}")
        ok = False
    
    if ok:
        print("  ✅ All checks passed!")
    
    return ok


def main():
    parser = argparse.ArgumentParser(description="Re-grade FCLE D1 questions")
    parser.add_argument("--dry-run", action="store_true", help="Classify only, don't modify DB")
    parser.add_argument("--status", action="store_true", help="Print current distribution and exit")
    args = parser.parse_args()
    
    conn = load_db()
    
    if args.status:
        print_distribution(conn)
        conn.close()
        return
    
    print("=== BEFORE ===")
    print_distribution(conn)
    
    regrade_d1(conn, dry_run=args.dry_run)

    if not args.dry_run:
        # Generate gap questions if needed
        dist = get_distribution(conn)
        need_easy = max(0, TARGETS[1]["easy"] - dist[1]["easy"])
        need_med = max(0, TARGETS[1]["medium"] - dist[1]["medium"])
        need_hard = max(0, TARGETS[1]["hard"] - dist[1]["hard"])

        if need_easy + need_med + need_hard > 0:
            generate_d1_gap(conn, need_easy, need_med, need_hard)

    fix_d4(conn, dry_run=args.dry_run)
    
    print("\n=== AFTER ===")
    print_distribution(conn)
    
    if not args.dry_run:
        validate(conn)
    
    conn.close()


if __name__ == "__main__":
    main()
