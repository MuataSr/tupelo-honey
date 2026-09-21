#!/usr/bin/env python3
"""
Regenerate wrong_explanations for a list of flagged question IDs.
Reads the question + wrong_answers, generates proper explanations, writes back to DB.

Usage: python3 scripts/regen_wrong_explanations.py --ids 1114,1153,844 --dry-run
       python3 scripts/regen_wrong_explanations.py --ids 1114,1153,844
"""

import sqlite3
import json
import argparse

DB_PATH = "data/fcle.db"

def get_questions(db_path, ids):
    db = sqlite3.connect(db_path)
    cur = db.cursor()
    placeholders = ','.join(['?'] * len(ids))
    rows = cur.execute(f"""
        SELECT id, question, correct_answer, wrong_answers, wrong_explanations, fcle_domain
        FROM questions
        WHERE id IN ({placeholders})
        ORDER BY fcle_domain, id
    """, ids).fetchall()
    db.close()
    return rows

def count_words(text):
    return len(text.split())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ids', required=True, help='Comma-separated question IDs')
    parser.add_argument('--dry-run', action='store_true', help='Just show what would be regenerated')
    args = parser.parse_args()

    ids = [int(x.strip()) for x in args.ids.split(',')]
    rows = get_questions(DB_PATH, ids)

    print(f"Found {len(rows)} questions out of {len(ids)} requested IDs\n")

    for r in rows:
        qid, question, ca, wa_raw, we_raw, domain = r
        wrong_answers = json.loads(wa_raw) if wa_raw else []
        wrong_explanations = json.loads(we_raw) if we_raw else []

        print(f"ID {qid} (D{domain})")
        print(f"  Q: {question[:150]}...")
        print(f"  Correct: {ca}")
        for i, wa in enumerate(wrong_answers):
            old_expl = wrong_explanations[i] if i < len(wrong_explanations) else "NONE"
            print(f"  Wrong[{i}]: {wa[:100]}")
            print(f"  Old Expl[{i}]: {old_expl[:100]}...")
        print()

if __name__ == "__main__":
    main()
