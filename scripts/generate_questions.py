#!/usr/bin/env python3
"""
Batch question generator for FCLE study app.
Calls local llama-server (4B model on port 8082) to generate questions per domain/topic.
Fully resumable — safe to re-run at any time.

Usage:
  python3 generate_questions.py                    # generate all domains
  python3 generate_questions.py --domain 1         # single domain
  python3 generate_questions.py --domain 2 --limit 10
  python3 generate_questions.py --status
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
LOG_PATH = os.path.join(SCRIPT_DIR, "..", "data", "generate_log.jsonl")
LLM_URL = "http://0.0.0.0:8082/v1/chat/completions"
TARGET_PER_DOMAIN = 500
DELAY_BETWEEN = 0.5
STIMULUS_CHANCE = 0.3  # 30% of questions include a stimulus passage

# FCLE topic guidance per domain
DOMAIN_TOPICS = {
    1: {  # American Democracy
        "Natural rights and social contract": "Locke, Montesquieu, consent of the governed, natural rights philosophy",
        "Limited government and rule of law": "constitutional limits, rule of law, due process, separation of powers",
        "Popular sovereignty": "We the People, consent of governed, government derives power from citizens",
        "Citizen participation": "voting, contacting officials, public comment, civil engagement",
        "Political parties and elections": "two-party system, primaries, general elections, electoral process",
        "Interest groups and lobbying": "types of interest groups, PACs, lobbying strategies, influence on policy",
        "Media and public opinion": "media bias, agenda-setting, framing, public opinion formation",
        "Political socialization": "family, school, peers, media as agents of political socialization",
        "Political culture and ideology": "liberalism, conservatism, libertarianism, political spectrum",
        "Federalism basics": "expressed, implied, concurrent, reserved powers; cooperative federalism",
    },
    2: {  # US Constitution
        "Articles of Confederation": "weaknesses, Shays Rebellion, why it failed, no taxing power",
        "Constitutional Convention": "Great Compromise, 3/5 Compromise, ratification debates",
        "Legislative branch": "bicameral, enumerated powers, impeachment, necessary and proper clause",
        "Executive branch": "presidential powers, commander in chief, veto, appointment power, cabinet",
        "Judicial branch": "judicial review, Marbury v Madison, jurisdiction, lifetime appointment",
        "Checks and balances": "veto override, judicial review, impeachment, Senate advice and consent",
        "Amendment process": "proposal and ratification, Bill of Rights, key amendments 13-27",
        "Bill of Rights": "1st Amendment freedoms, 2nd Amendment, 4th-8th Amendment protections",
        "Key amendments": "13th, 14th, 15th, 19th, 26th Amendment — purpose and impact",
        "Federalism": "supremacy clause, commerce clause, 10th Amendment, McCulloch v Maryland",
    },
    3: {  # Founding Documents
        "Declaration of Independence": "natural rights, grievances, social contract, purpose and audience",
        "Federalist No. 10": "factions, large republic, controlling effects of faction, majority tyranny",
        "Federalist No. 51": "separation of powers, checks and balances, ambition counteracting ambition",
        "Federalist No. 78": "judicial independence, judicial review as check on legislature",
        "Anti-Federalist arguments": "Brutus essays, Bill of Rights demand, fear of consolidated power",
        "Articles of Confederation structure": "unicameral Congress, no executive, supermajority requirements",
        "Constitutional ratification": "Federalist vs Anti-Federalist, state conventions, promise of Bill of Rights",
        "Constitution Preamble": "We the People, purposes of government, popular sovereignty",
        "Constitution key articles": "Article I-VII structure, amendment process in Article V",
        "Three-Fifths Compromise and Great Compromise": "representation debates, Connecticut Plan",
    },
    4: {  # Landmark Impact
        "Marbury v Madison": "judicial review establishment, Chief Justice Marshall, significance",
        "McCulloch v Maryland": "implied powers, supremacy clause, necessary and proper clause",
        "Brown v Board of Education": "separate but equal overturned, desegregation, Brown II",
        "Gideon v Wainwright": "right to counsel, 6th Amendment incorporation, public defenders",
        "Miranda v Arizona": "Miranda rights, 5th Amendment, custodial interrogation",
        "Tinker v Des Moines": "student speech, symbolic speech, school environment limitation",
        "Schenck v United States": "clear and present danger, 1st Amendment limits, Brandenburg",
        "Civil Rights Act 1964": "discrimination prohibition, Title II and VII, filibuster override",
        "Voting Rights Act 1965": "preclearance, literacy test ban, 15th Amendment enforcement",
        "ADA and landmark legislation": "Americans with Disabilities Act, New Deal, Great Society",
    },
}

# Difficulty distribution: 30/45/25 easy/medium/hard
DIFFICULTY_POOL = ["easy"] * 30 + ["medium"] * 45 + ["hard"] * 25


def load_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_domain_counts(conn):
    """Return current question count per domain."""
    counts = {}
    for d in range(1, 5):
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM questions WHERE fcle_domain=?", (d,)
        ).fetchone()
        counts[d] = row["cnt"]
    return counts


def get_kb_context(conn, domain, topic):
    """Pull relevant KB content, key terms, and misconceptions for context."""
    parts = []

    # Key terms for this domain (limit to 15 most relevant)
    terms = conn.execute(
        "SELECT term, definition FROM key_terms WHERE fcle_domain=? ORDER BY RANDOM() LIMIT 15",
        (domain,)
    ).fetchall()
    if terms:
        parts.append("KEY TERMS:\n" + "\n".join(
            f"- {t['term']}: {t['definition']}" for t in terms
        ))

    # Misconceptions for this domain (limit to 5)
    miscs = conn.execute(
        "SELECT misconception, correction FROM misconceptions WHERE fcle_domain=? ORDER BY RANDOM() LIMIT 5",
        (domain,)
    ).fetchall()
    if miscs:
        parts.append("COMMON MISCONCEPTIONS:\n" + "\n".join(
            f"- WRONG: {m['misconception']}\n  RIGHT: {m['correction']}" for m in miscs
        ))

    # Content sections for this domain (limit to 2)
    sections = conn.execute(
        "SELECT section_title, text FROM content WHERE fcle_domain=? ORDER BY RANDOM() LIMIT 2",
        (domain,)
    ).fetchall()
    if sections:
        for s in sections:
            text = s["text"][:600] if s["text"] else ""
            if text:
                parts.append(f"REFERENCE: {s['section_title']}\n{text}")

    return "\n\n".join(parts)


def build_queue(conn, domain, limit=None):
    """Build generation queue: (domain, topic, difficulty) tuples.

    Smart distribution: fills difficulty gaps first, then rounds out to target.
    """
    current_total = conn.execute(
        "SELECT COUNT(*) as cnt FROM questions WHERE fcle_domain=?", (domain,)
    ).fetchone()["cnt"]

    easy = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE fcle_domain=? AND difficulty='easy'", (domain,)
    ).fetchone()[0]
    medium = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE fcle_domain=? AND difficulty='medium'", (domain,)
    ).fetchone()[0]
    hard = conn.execute(
        "SELECT COUNT(*) FROM questions WHERE fcle_domain=? AND difficulty='hard'", (domain,)
    ).fetchone()[0]

    # Target per difficulty (30/45/25 of 500)
    target_easy = int(TARGET_PER_DOMAIN * 0.30)
    target_medium = int(TARGET_PER_DOMAIN * 0.45)
    target_hard = int(TARGET_PER_DOMAIN * 0.25)

    gap_easy = max(0, target_easy - easy)
    gap_medium = max(0, target_medium - medium)
    gap_hard = max(0, target_hard - hard)

    total_gap = gap_easy + gap_medium + gap_hard
    if total_gap <= 0:
        return []

    if limit:
        # Proportionally reduce gaps to fit limit
        if total_gap > limit:
            scale = limit / total_gap
            gap_easy = int(gap_easy * scale)
            gap_medium = int(gap_medium * scale)
            gap_hard = int(gap_hard * scale)
            # Put remainder into medium (biggest bucket)
            remainder = limit - gap_easy - gap_medium - gap_hard
            gap_medium += remainder

    topics = DOMAIN_TOPICS.get(domain, {})
    topic_list = list(topics.keys())
    random.shuffle(topic_list)

    queue = []
    # Build difficulty-ordered queue: fill gaps proportionally
    diff_queue = ["easy"] * gap_easy + ["medium"] * gap_medium + ["hard"] * gap_hard
    random.shuffle(diff_queue)

    for i, diff in enumerate(diff_queue):
        topic = topic_list[i % len(topic_list)]
        queue.append((domain, topic, diff))

    return queue


def call_llm(prompt, max_retries=3):
    """Call local llama-server and return content string."""
    payload = json.dumps({
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 900,
        "temperature": 0.75,
        "top_p": 0.9,
    }).encode()
    headers = {"Content-Type": "application/json"}

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(LLM_URL, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = resp.read().decode()
                if not body.strip():
                    if attempt < max_retries - 1:
                        time.sleep((attempt + 1) * 3)
                        continue
                    return None
                result = json.loads(body)
                content = result["choices"][0]["message"]["content"].strip()
                # Strip thinking tags
                if "</think" in content:
                    content = content.split("</think")[-1].strip()
                if "<think" in content:
                    content = content.split("<think")[0].strip()
                return content
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 3)
            else:
                print(f"  ✗ LLM error: {e}")
                return None
    return None


def parse_response(content, domain, topic, difficulty):
    """Parse LLM JSON output into a question dict. Returns None on failure."""
    try:
        json_str = content
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        q = json.loads(json_str)

        required = ["question", "correct_answer", "wrong_answers", "explanation"]
        for field in required:
            if field not in q or not str(q[field]).strip():
                return None

        if not isinstance(q["wrong_answers"], list) or len(q["wrong_answers"]) < 3:
            return None

        # Validate no empty strings
        if not q["question"].strip() or not q["correct_answer"].strip():
            return None
        if any(not str(w).strip() for w in q["wrong_answers"][:3]):
            return None

        return {
            "fcle_domain": domain,
            "topic": topic,
            "difficulty": difficulty,
            "question": q["question"].strip(),
            "correct_answer": q["correct_answer"].strip(),
            "wrong_answers": json.dumps(q["wrong_answers"][:3]),
            "explanation": q["explanation"].strip(),
            "stimulus": q.get("stimulus", "").strip() or None,
        }
    except (json.JSONDecodeError, KeyError, TypeError, IndexError):
        return None


def generate_prompt(domain, topic, difficulty, kb_context, force_stimulus=False):
    domain_names = {1: "American Democracy", 2: "US Constitution",
                    3: "Founding Documents", 4: "Landmark Impact"}

    diff_guidance = {
        "easy": "Straightforward recall of facts, definitions, or basic concepts. Question should be answerable by anyone who has studied the basics.",
        "medium": "Requires understanding relationships, applying concepts to scenarios, or distinguishing between similar ideas. Student must go beyond memorization.",
        "hard": "Requires analysis, synthesis, or evaluation. May involve applying concepts to unfamiliar situations, comparing perspectives, or identifying nuanced distinctions.",
    }

    use_stimulus = force_stimulus or (random.random() < STIMULUS_CHANCE)

    stimulus_instruction = ""
    if use_stimulus:
        stimulus_instruction = """
STIMULUS-BASED QUESTION: This question MUST include a stimulus passage.
- Provide a short excerpt (2-4 sentences) from a founding document, court opinion, speech, or historical text
- The question should require the student to analyze or interpret the stimulus
- The stimulus should be real or highly realistic — not fabricated quotes
- The stimulus field MUST contain the passage text"""

    return f"""You are a Florida Civic Literacy Exam (FCLE) question writer for college students.

DOMAIN: {domain_names[domain]}
TOPIC: {topic}
DIFFICULTY: {difficulty} — {diff_guidance[difficulty]}

REFERENCE MATERIAL:
{kb_context}
{stimulus_instruction}
RULES:
- Write ONE clear, unambiguous multiple-choice question with exactly 4 answer choices (A, B, C, D)
- The correct answer must be definitively correct — no ambiguity
- Wrong answers must be plausible distractors that test real student misconceptions (not obviously wrong)
- Each distractor should represent a SPECIFIC wrong belief or confusion — not just random incorrect facts
- Explanation must be substantive (3+ sentences explaining the correct answer AND why each distractor is wrong)
- Postsecondary level — appropriate for college students preparing for the FCLE
- Questions should test understanding and application, NOT rote memorization of dates/names
- For medium/hard: use scenarios, "which of the following," application, or comparison questions
- Avoid questions that can be answered by process of elimination without knowing the material
- Use precise constitutional/legal terminology where appropriate

Return ONLY valid JSON in this exact format:
{{
  "question": "Your question text here?",
  "correct_answer": "The correct answer text",
  "wrong_answers": ["Plausible distractor 1", "Plausible distractor 2", "Plausible distractor 3"],
  "explanation": "Substantive explanation of why the correct answer is right and why the wrong answers are wrong.",
  "stimulus": "Short passage or quote if stimulus-based, otherwise empty string."
}}

Generate the question now:"""


def log_entry(action, domain, topic, difficulty, status, note=""):
    entry = {
        "action": action,
        "domain": domain,
        "topic": topic,
        "difficulty": difficulty,
        "status": status,
        "note": note[:200] if note else "",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")


def check_server():
    try:
        req = urllib.request.Request("http://0.0.0.0:8082/v1/models")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return True
    except Exception:
        return False


def show_status(conn):
    counts = get_domain_counts(conn)
    domain_names = {1: "American Democracy", 2: "US Constitution",
                    3: "Founding Documents", 4: "Landmark Impact"}
    total = sum(counts.values())

    print(f"\n{'='*55}")
    print(f"FCLE QUESTION STATUS (target: {TARGET_PER_DOMAIN}/domain)")
    print(f"{'='*55}")
    for d in range(1, 5):
        cnt = counts[d]
        pct = cnt / TARGET_PER_DOMAIN * 100
        bar_full = min(int(pct / 2), 40)
        bar_empty = 40 - bar_full
        bar = "█" * bar_full + "░" * bar_empty
        status = "✅ DONE" if cnt >= TARGET_PER_DOMAIN else f"need {TARGET_PER_DOMAIN - cnt}"
        print(f"  D{d} {domain_names[d]:25s} [{bar}] {cnt:3d}/{TARGET_PER_DOMAIN}  {status}")

    # Difficulty breakdown
    print(f"\n  TOTAL: {total}/{TARGET_PER_DOMAIN * 4}")
    for d in range(1, 5):
        easy = conn.execute("SELECT COUNT(*) FROM questions WHERE fcle_domain=? AND difficulty='easy'", (d,)).fetchone()[0]
        med = conn.execute("SELECT COUNT(*) FROM questions WHERE fcle_domain=? AND difficulty='medium'", (d,)).fetchone()[0]
        hard = conn.execute("SELECT COUNT(*) FROM questions WHERE fcle_domain=? AND difficulty='hard'", (d,)).fetchone()[0]
        print(f"  D{d} difficulty: {easy} easy / {med} medium / {hard} hard")


def main():
    parser = argparse.ArgumentParser(description="FCLE question generator")
    parser.add_argument("--domain", type=int, choices=[1, 2, 3, 4], help="Single domain to generate")
    parser.add_argument("--limit", type=int, help="Max questions to generate this run")
    parser.add_argument("--status", action="store_true", help="Show current counts")
    args = parser.parse_args()

    conn = load_db()

    if args.status:
        show_status(conn)
        conn.close()
        return

    if not check_server():
        print("✗ llama-server not responding on port 8082")
        conn.close()
        sys.exit(1)

    domains = [args.domain] if args.domain else [1, 2, 3, 4]
    domain_names = {1: "American Democracy", 2: "US Constitution",
                    3: "Founding Documents", 4: "Landmark Impact"}

    total_generated = 0
    total_failed = 0

    for domain in domains:
        queue = build_queue(conn, domain, args.limit)
        if not queue:
            print(f"\nD{domain} {domain_names[domain]}: ✅ already at target")
            continue

        print(f"\n{'='*55}")
        print(f"D{domain} {domain_names[domain]}: {len(queue)} questions to generate")
        print(f"{'='*55}")

        for i, (d, topic, difficulty) in enumerate(queue):
            # Get KB context for this domain+topic
            kb_context = get_kb_context(conn, d, topic)

            prompt = generate_prompt(d, topic, difficulty, kb_context)
            content = call_llm(prompt)

            if not content:
                total_failed += 1
                log_entry("generate", d, topic, difficulty, "failed", "empty LLM response")
                print(f"  ✗ [{i+1}/{len(queue)}] {topic} ({difficulty}) — empty response")
                continue

            parsed = parse_response(content, d, topic, difficulty)
            if not parsed:
                total_failed += 1
                log_entry("generate", d, topic, difficulty, "failed", f"parse error: {content[:100]}")
                print(f"  ✗ [{i+1}/{len(queue)}] {topic} ({difficulty}) — parse error")
                continue

            # Insert into DB
            conn.execute(
                """INSERT INTO questions
                   (fcle_domain, topic, difficulty, question, correct_answer,
                    wrong_answers, explanation, stimulus)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (parsed["fcle_domain"], parsed["topic"], parsed["difficulty"],
                 parsed["question"], parsed["correct_answer"], parsed["wrong_answers"],
                 parsed["explanation"], parsed["stimulus"])
            )
            conn.commit()

            total_generated += 1
            log_entry("generate", d, topic, difficulty, "ok", f"qid={conn.execute('SELECT last_insert_rowid()').fetchone()[0]}")

            # Progress
            current = conn.execute(
                "SELECT COUNT(*) FROM questions WHERE fcle_domain=?", (d,)
            ).fetchone()[0]
            pct = current / TARGET_PER_DOMAIN * 100
            print(f"  ✓ [{i+1}/{len(queue)}] {topic[:30]:30s} ({difficulty:6s}) → D{d}: {current}/{TARGET_PER_DOMAIN} ({pct:.0f}%)")

            time.sleep(DELAY_BETWEEN)

    # Final status
    print(f"\n{'='*55}")
    print(f"RUN COMPLETE: {total_generated} generated, {total_failed} failed")
    show_status(conn)

    conn.close()


if __name__ == "__main__":
    main()
