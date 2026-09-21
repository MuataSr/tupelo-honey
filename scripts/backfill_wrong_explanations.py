#!/usr/bin/env python3
"""
Backfill wrong_explanations for FCLE questions.
Batches 5 questions per API call to amortize reasoning overhead.

Usage:
    python3 backfill_wrong_explanations.py --domain 1 --limit 25
    python3 backfill_wrong_explanations.py --domain 2 --limit 25 --dry-run
"""
import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.request
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
API_URL = "https://api.z.ai/api/coding/paas/v4/chat/completions"
API_KEY = _env_key("ZAI_API_KEY")
MODEL = "glm-5.1"
BATCH_SIZE = 5  # questions per API call
MAX_RETRIES = 2

DB_PATH = "/home/muatasr/.nanobot/workspace/fcle-study-app/data/fcle.db"

SYSTEM_PROMPT = """You are an expert civics educator. For each question below, explain why each wrong answer is wrong.

Return a JSON object where keys are the question IDs (as strings) and values are arrays of exactly 3 explanation strings.

Example:
{"385": ["Reason wrong answer 1 is wrong.", "Reason wrong answer 2 is wrong.", "Reason wrong answer 3 is wrong."], "386": [...]}

Rules:
- Each explanation: 1-2 sentences, 50-200 characters
- Explain the specific misconception or factual error
- Return ONLY valid JSON, no markdown code blocks"""


def call_api(prompt):
    """Call Z.AI API with retry."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            payload = json.dumps({
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 2000
            }).encode()

            req = urllib.request.Request(
                API_URL,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {API_KEY}"
                }
            )

            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
                return data["choices"][0]["message"]["content"]

        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(3 ** attempt)
            else:
                return f"ERROR: {e}"


def parse_response(text, qids):
    """Parse the API response into {id: [3 explanations]} dict."""
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()

    # Try direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in text
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None


def validate_explanations(explanations):
    """Check if a list of 3 explanations meets quality criteria."""
    if not isinstance(explanations, list) or len(explanations) != 3:
        return False
    return all(isinstance(s, str) and 20 <= len(s) <= 400 for s in explanations)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", type=int, required=True, choices=[1, 2, 3, 4])
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Get questions needing wrong_explanations for this domain
    c.execute("""
        SELECT id, question, correct_answer, wrong_answers
        FROM questions
        WHERE fcle_domain = ?
          AND (wrong_explanations IS NULL OR wrong_explanations = '')
        ORDER BY id
        LIMIT ?
    """, (args.domain, args.limit))

    questions = [dict(row) for row in c.fetchall()]

    if not questions:
        print(f"Domain {args.domain}: No questions need wrong_explanations. Done!")
        conn.close()
        return

    print(f"Domain {args.domain}: Found {len(questions)} questions to process ({(len(questions) + BATCH_SIZE - 1) // BATCH_SIZE} batches)")

    if args.dry_run:
        for q in questions[:3]:
            print(f"  ID {q['id']}: {q['question'][:80]}...")
        conn.close()
        return

    updated = 0
    failed = 0

    # Process in batches of BATCH_SIZE
    for batch_start in range(0, len(questions), BATCH_SIZE):
        batch = questions[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(questions) + BATCH_SIZE - 1) // BATCH_SIZE

        # Build prompt with all questions in batch
        prompt_parts = []
        for q in batch:
            try:
                wrong = json.loads(q['wrong_answers']) if isinstance(q['wrong_answers'], str) else q['wrong_answers']
            except (json.JSONDecodeError, TypeError):
                continue
            prompt_parts.append(
                f"Question ID {q['id']}:\n"
                f"Q: {q['question']}\n"
                f"Correct: {q['correct_answer']}\n"
                f"Wrong answers: {json.dumps(wrong)}\n"
            )

        prompt = "Explain why each wrong answer is wrong for these questions:\n\n" + "\n".join(prompt_parts)
        prompt += f"\nReturn a JSON object with IDs {json.dumps([str(q['id']) for q in batch])} as keys, each with an array of 3 explanation strings."

        response = call_api(prompt)

        if response.startswith("ERROR:"):
            failed += len(batch)
            print(f"  Batch {batch_num}/{total_batches}: API ERROR ({response[:100]})")
            continue

        parsed = parse_response(response, [q['id'] for q in batch])

        if parsed is None:
            failed += len(batch)
            print(f"  Batch {batch_num}/{total_batches}: PARSE FAILED")
            print(f"    Raw: {response[:200]}")
            continue

        batch_updated = 0
        for q in batch:
            qid = str(q['id'])
            if qid in parsed and validate_explanations(parsed[qid]):
                explanations_json = json.dumps(parsed[qid], ensure_ascii=False)
                c.execute(
                    "UPDATE questions SET wrong_explanations = ? WHERE id = ?",
                    (explanations_json, q['id'])
                )
                batch_updated += 1
                updated += 1
            else:
                failed += 1

        conn.commit()
        print(f"  Batch {batch_num}/{total_batches}: {batch_updated}/{len(batch)} updated")

    conn.close()

    print(f"\nDomain {args.domain} COMPLETE: {updated} updated, {failed} failed out of {len(questions)}")
    print(f"RESULT:updated={updated},failed={failed},total={len(questions)}")

    if failed > len(questions) * 0.3:
        print(f"WARNING: High failure rate ({failed}/{len(questions)})")
        sys.exit(1)


if __name__ == "__main__":
    main()
