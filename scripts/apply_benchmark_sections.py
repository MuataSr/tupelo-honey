#!/usr/bin/env python3
"""Apply the reviewed benchmark->section mapping from the CSV. No models involved.

Kept separate from rebuild_benchmark_sections.py on purpose: that script's --apply
re-ran the whole model pipeline before writing, which is both slow and pointless when
the reviewed CSV already holds the decision. This step is deterministic and re-runnable.

What it writes
--------------
- For each code with an accepted section: that section becomes the ONE primary link.
  Runners-up are not written - only is_primary=1 is ever read, and writing unconfirmed
  alternatives would imply a confidence the reviewer did not give.
- For each code with no accepted section: its existing links are DELETED. Leaving them
  means leaving the old heuristic's output in place, which is what pointed a dozen
  unrelated standards at the back-matter row.

Validation before any write: the section must exist in `content` and must not be one of
the oversized back-matter rows.
"""
import argparse
import csv
import os
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "tupelo.db")
CSV_PATH = os.path.join(ROOT, "data", "benchmark-sections.csv")
MAX_SECTION_CHARS = 60000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV_PATH,
                    help="the reviewed CSV to apply")
    ap.add_argument("--db", default=DB)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    dry = not args.apply
    rows = list(csv.DictReader(open(args.csv)))
    print("csv: %s" % args.csv)
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    content = {r["id"]: dict(r) for r in con.execute(
        "SELECT id, section_title, char_count FROM content")}
    before_rows = con.execute("SELECT COUNT(*) FROM benchmark_sections").fetchone()[0]
    before_primaries = con.execute(
        "SELECT COUNT(DISTINCT benchmark_code) FROM benchmark_sections WHERE is_primary=1"
    ).fetchone()[0]

    accepted, rejected, unresolved = [], [], []
    for r in rows:
        code = r["code"]
        want = (r.get("accepted_section_id") or "").strip()
        if not want:
            unresolved.append((code, r.get("source", "")))
            continue
        try:
            sid = int(want)
        except ValueError:
            rejected.append((code, want, "not an integer"))
            continue
        sec = content.get(sid)
        if sec is None:
            rejected.append((code, want, "section does not exist"))
            continue
        if (sec["char_count"] or 0) > MAX_SECTION_CHARS:
            rejected.append((code, want, "back matter, not a section"))
            continue
        accepted.append((code, sid, r.get("source", ""), sec["section_title"]))

    print("codes in CSV            : %d" % len(rows))
    print("accepted for writing    : %d" % len(accepted))
    print("unresolved (links purged): %d" % len(unresolved))
    print("rejected by validation  : %d" % len(rejected))
    for code, sid, why in rejected:
        print("   reject %-14s %s (%s)" % (code, sid, why))
    print()
    print("existing rows           : %d" % before_rows)
    print("existing codes w/ primary: %d" % before_primaries)
    print()
    print("=== mapping to be written (primary link per code) ===")
    for code, sid, source, title in accepted:
        print("   %-14s -> sec %-4s %-46s  [%s]" % (code, sid, title[:46], source))
    if unresolved:
        print()
        print("=== codes getting NO link (their old links are removed) ===")
        print("   " + ", ".join("%s(%s)" % (c, s) for c, s in unresolved))

    if dry:
        print("\n[dry] nothing written. Re-run with --apply.")
        con.close()
        return

    backup = "%s.pre-sections-%s" % (DB, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(DB, backup)
    print("\nbackup written: %s" % backup)

    cur = con.cursor()
    changes = con.total_changes
    for code, sid, _source, _title in accepted:
        cur.execute("DELETE FROM benchmark_sections WHERE benchmark_code = ?", (code,))
        cur.execute("INSERT INTO benchmark_sections "
                    "(benchmark_code, section_id, relevance_score, is_primary) "
                    "VALUES (?,?,?,?)", (code, sid, 100.0, 1))
    for code, _source in unresolved:
        cur.execute("DELETE FROM benchmark_sections WHERE benchmark_code = ?", (code,))
    con.commit()
    print("row changes: %d" % (con.total_changes - changes))

    dangling = con.execute("SELECT COUNT(*) FROM benchmark_sections "
                           "WHERE section_id != 0 AND section_id NOT IN (SELECT id FROM content)").fetchone()[0]
    print("rows now                : %d" % con.execute(
        "SELECT COUNT(*) FROM benchmark_sections").fetchone()[0])
    print("codes with a primary    : %d" % con.execute(
        "SELECT COUNT(DISTINCT benchmark_code) FROM benchmark_sections "
        "WHERE is_primary = 1").fetchone()[0])
    print("dangling section ids    : %d" % dangling)
    print("links to section 77     : %d" % con.execute(
        "SELECT COUNT(*) FROM benchmark_sections WHERE section_id = 77").fetchone()[0])
    print("integrity_check         : %s" % con.execute("PRAGMA integrity_check").fetchone()[0])
    con.close()

    if dangling:
        raise SystemExit("dangling links present - investigate before deploying")


if __name__ == "__main__":
    main()
