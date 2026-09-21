"""Ingest the reviewed question batches into the content DB, and register their topics.

Run only after the batches have been reviewed and any fatal issues fixed. Takes a backup,
inserts questions + topic_benchmarks rows, then reports coverage before/after.
"""
import glob
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime


def main():
    DB = "data/fcle.db"
    backup = DB + ".pre-questions-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy(DB, backup)
    print("backup:", backup)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    files = sorted(glob.glob("data/batch_*.json"))
    if not files:
        print("no batch files found")
        sys.exit(1)

    before_q = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    added = 0
    for f in files:
        b = json.load(open(f))
        code, topic, domain = b["code"], b["topic"], b["domain"]
        qs = b.get("questions", [])
        if not qs:
            print("  !! %s has no questions - skipping" % code)
            continue
        # guard against double-ingest
        existing = con.execute("SELECT COUNT(*) FROM topic_benchmarks WHERE topic=?",
                               (topic,)).fetchone()[0]
        if existing:
            print("  !! topic '%s' already mapped - skipping %s" % (topic, code))
            continue
        for q in qs:
            con.execute(
                "INSERT INTO questions (fcle_domain, topic, difficulty, question, "
                "correct_answer, wrong_answers, explanation, stimulus, created_at, "
                "wrong_explanations) VALUES (?,?,?,?,?,?,?,NULL,datetime('now'),?)",
                (domain, topic, q["difficulty"], q["question"], q["correct_answer"],
                 json.dumps(q["wrong_answers"]), q["explanation"],
                 json.dumps(q["wrong_explanations"])))
        con.execute(
            "INSERT INTO topic_benchmarks (topic, fcle_domain, primary_code, "
            "secondary_codes, n_questions, decided_by, note) VALUES (?,?,?,NULL,?,?,?)",
            (topic, domain, code, len(qs), "ann-e-questions-coverage",
             "question coverage for a previously uncovered benchmark"))
        added += len(qs)
        print("  %-14s -> topic '%-48s' domain %d  %d questions"
              % (code, topic, domain, len(qs)))

    con.commit()

    # coverage after
    codes = {r[0] for r in con.execute("SELECT code FROM benchmarks")}
    mapped = {r[0] for r in con.execute("SELECT DISTINCT primary_code FROM topic_benchmarks")}
    uncovered = sorted(codes - mapped)
    after_q = con.execute("SELECT COUNT(*) FROM questions").fetchone()[0]

    print()
    print("questions: %d -> %d  (+%d)" % (before_q, after_q, added))
    print("benchmarks covered: %d of %d" % (len(codes & mapped), len(codes)))
    print("still uncovered:", uncovered if uncovered else "NONE")
    print("integrity:", con.execute("PRAGMA integrity_check").fetchone()[0])
    con.close()


if __name__ == "__main__":
    main()
