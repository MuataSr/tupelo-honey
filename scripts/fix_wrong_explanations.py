#!/usr/bin/env python3
"""
Fix wrong_explanations for flagged question IDs.
Used by subagents: reads question + wrong_answers from DB,
generates correct explanations, writes them back.

Usage: python3 scripts/fix_wrong_explanations.py <start_id> <end_id> --apply
       python3 scripts/fix_wrong_explanations.py <start_id> <end_id>  (dry-run)

The script outputs a JSON file with the new explanations for verification.
"""

import sqlite3
import json
import argparse
import os

DB_PATH = "data/fcle.db"
OUTPUT_DIR = "data/fixes"

ALL_FLAGGED_IDS = [
    590, 658, 706, 744, 755, 784, 785, 795, 804, 805, 814, 824, 835, 844, 845, 854, 855, 863, 864, 885, 904, 935, 944, 983, 984, 1014, 1016, 1043, 1094, 1096, 1106, 1114, 1116, 1153, 1224, 1284, 1427, 1465, 1557, 1575, 1577, 1587, 1602, 1606, 1607, 1626, 1634, 1636, 1657, 1706, 1858, 1859, 1878, 1879, 1899, 1908, 1917, 1919, 1921, 1927, 1967, 2017, 2018, 2040, 2130, 2169, 2170, 2172,
]

def get_questions_in_range(db_path, id_list, start, end):
    ids = [i for i in id_list if start <= i <= end]
    if not ids:
        return []
    db = sqlite3.connect(db_path)
    cur = db.cursor()
    placeholders = ','.join(['?'] * len(ids))
    rows = cur.execute(f"""
        SELECT id, question, correct_answer, wrong_answers, wrong_explanations, fcle_domain
        FROM questions
        WHERE id IN ({placeholders})
        ORDER BY id
    """, ids).fetchall()
    db.close()
    return rows

def apply_fixes(db_path, fixes):
    """Apply the fixes to the database."""
    db = sqlite3.connect(db_path)
    cur = db.cursor()
    for fix in fixes:
        cur.execute(
            "UPDATE questions SET wrong_explanations = ? WHERE id = ?",
            (json.dumps(fix['new_explanations']), fix['id'])
        )
    db.commit()
    # Verify
    for fix in fixes:
        row = cur.execute("SELECT wrong_explanations FROM questions WHERE id = ?", (fix['id'],)).fetchone()
        stored = json.loads(row[0])
        if stored != fix['new_explanations']:
            print(f"ERROR: Verification failed for ID {fix['id']}")
            db.close()
            return False
    db.close()
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('start_id', type=int, help='Start of ID range')
    parser.add_argument('end_id', type=int, help='End of ID range')
    parser.add_argument('--apply', action='store_true', help='Apply fixes (otherwise dry-run)')
    parser.add_argument('--fixes-file', help='JSON file with fixes to apply')
    args = parser.parse_args()

    if args.fixes_file:
        # Apply mode: read fixes from file and update DB
        with open(args.fixes_file) as f:
            fixes = json.load(f)
        print(f"Applying {len(fixes)} fixes from {args.fixes_file}...")
        success = apply_fixes(DB_PATH, fixes)
        print(f"{'SUCCESS' if success else 'FAILED'}: Applied {len(fixes)} fixes")
        return

    # Generate mode: output questions that need fixing
    rows = get_questions_in_range(DB_PATH, ALL_FLAGGED_IDS, args.start_id, args.end_id)
    if not rows:
        print(f"No flagged IDs in range {args.start_id}-{args.end_id}")
        return

    print(f"Questions to fix in range {args.start_id}-{args.end_id}: {len(rows)}\n")

    output = []
    for r in rows:
        qid, question, ca, wa_raw, we_raw, domain = r
        wrong_answers = json.loads(wa_raw) if wa_raw else []
        wrong_explanations = json.loads(we_raw) if we_raw else []

        print(f"ID {qid} (D{domain})")
        print(f"Q: {question}")
        print(f"Correct Answer: {ca}")
        for i, wa in enumerate(wrong_answers):
            print(f"Wrong Answer [{i}]: {wa}")
        print()

        output.append({
            'id': qid,
            'domain': domain,
            'question': question,
            'correct_answer': ca,
            'wrong_answers': wrong_answers,
            'old_explanations': wrong_explanations,
        })

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"batch_{args.start_id}_{args.end_id}.json")
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"Written to {out_path}")

if __name__ == "__main__":
    main()
