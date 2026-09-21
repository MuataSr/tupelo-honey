#!/usr/bin/env python3
"""Read unfilled questions for a given domain, output as JSON."""
import sqlite3, json, sys

def main():
    domain = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    db_path = '/home/muatasr/.nanobot/workspace/fcle-study-app/data/fcle.db'
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, question, correct_answer, wrong_answers, explanation, fcle_domain, topic
        FROM questions 
        WHERE (wrong_explanations IS NULL OR wrong_explanations = '' OR wrong_explanations = '[]' OR wrong_explanations = '{}')
        AND fcle_domain = ?
        ORDER BY id LIMIT ?
    """, (domain, limit))
    
    rows = cur.fetchall()
    results = []
    for r in rows:
        results.append({
            'id': r[0],
            'question': r[1],
            'correct_answer': r[2],
            'wrong_answers': json.loads(r[3]) if r[3] else [],
            'explanation': r[4],
            'domain': r[5],
            'topic': r[6]
        })
    
    print(json.dumps(results, indent=2))
    conn.close()

if __name__ == '__main__':
    main()
