#!/usr/bin/env python3
"""Write wrong explanations to DB. Takes a JSON file with format:
[{"id": 123, "wrong_explanations": ["expl1", "expl2", "expl3"]}, ...]
"""
import sqlite3, json, sys

def main():
    json_file = sys.argv[1]
    db_path = '/home/muatasr/.nanobot/workspace/fcle-study-app/data/fcle.db'
    
    with open(json_file) as f:
        updates = json.load(f)
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    count = 0
    for item in updates:
        qid = item['id']
        expl = json.dumps(item['wrong_explanations'])
        cur.execute('UPDATE questions SET wrong_explanations = ? WHERE id = ?', (expl, qid))
        count += 1
    
    conn.commit()
    conn.close()
    print(f'RESULT: updated={count}, failed=0, total={count}')

if __name__ == '__main__':
    main()
