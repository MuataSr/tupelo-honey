#!/usr/bin/env python3
"""P0.2b - apply the reviewed misconception re-key to the database.

Reads the CSV that scripts/rekey_misconceptions.py produced and writes the accepted
codes onto the placeholder rows. Nothing else is touched.

Safety
------
- Every code is re-validated here, independently of the harness: it must be one of
  the 36 real standards AND must serve the row's own domain. A bad row is skipped
  and reported, never written.
- The UPDATE is guarded with `AND benchmark_code = 'FCLE'`, so this can only ever
  replace placeholders. A row that already carries a real code cannot be clobbered,
  even if the CSV is stale.
- The database is copied to fcle.db.pre-rekey-<timestamp> before the first write.
- `--dry-run` reports exactly what would change without touching the file.

Usage:
    python3 scripts/apply_rekey.py --dry-run
    python3 scripts/apply_rekey.py
"""
import argparse
import csv
import os
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import misconception_codes as mc  # noqa: E402

DB = os.path.join(ROOT, "data", "tupelo.db")
CSV_PATH = os.path.join(ROOT, "data", "rekey.csv")
PLACEHOLDER = mc.PLACEHOLDER


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=CSV_PATH)
    ap.add_argument("--db", default=DB)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        raise SystemExit("no CSV at %s - run scripts/rekey_misconceptions.py first" % args.csv)

    known = mc.all_codes(args.db)
    per_domain = {d: set(mc.domain_codes(d, args.db)) for d in (1, 2, 3, 4)}

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    before = con.execute("SELECT COUNT(*) FROM misconceptions WHERE benchmark_code = ?",
                         (PLACEHOLDER,)).fetchone()[0]

    accepted, skipped, already = [], [], 0
    with open(args.csv) as fh:
        for row in csv.DictReader(fh):
            code = (row.get("new_code") or "").strip()
            if not code:
                skipped.append((row["id"], row.get("source"), "no code accepted"))
                continue
            try:
                rid = int(row["id"])
                domain = int(row["domain"])
            except (TypeError, ValueError):
                skipped.append((row["id"], row.get("source"), "unparseable id/domain"))
                continue
            if code not in known:
                skipped.append((rid, row.get("source"), "not a real standard: %s" % code))
                continue
            if code not in per_domain.get(domain, set()):
                skipped.append((rid, row.get("source"), "code %s does not serve domain %s"
                                % (code, domain)))
                continue
            current = con.execute("SELECT benchmark_code FROM misconceptions WHERE id = ?",
                                  (rid,)).fetchone()
            if current is None:
                skipped.append((rid, row.get("source"), "row does not exist"))
                continue
            if current["benchmark_code"] != PLACEHOLDER:
                already += 1
                continue
            accepted.append((rid, domain, code))

    print("placeholder rows before : %d" % before)
    print("accepted for re-key      : %d" % len(accepted))
    print("already had a real code  : %d" % already)
    print("skipped                  : %d" % len(skipped))
    for rid, source, why in skipped[:25]:
        print("   skip %-6s %-18s %s" % (rid, source, why))
    if len(skipped) > 25:
        print("   ... and %d more" % (len(skipped) - 25))

    if args.dry_run:
        print("\n[dry-run] nothing written")
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = "%s.pre-rekey-%s" % (args.db, stamp)
        shutil.copy2(args.db, backup)
        print("\nbackup written: %s" % backup)
        cur = con.cursor()
        # NOTE: cur.rowcount only reflects the LAST statement, so count changes instead.
        before_changes = con.total_changes
        for rid, domain, code in accepted:
            cur.execute("UPDATE misconceptions SET benchmark_code = ? "
                        "WHERE id = ? AND benchmark_code = ?", (code, rid, PLACEHOLDER))
        con.commit()
        print("rows actually updated  : %d" % (con.total_changes - before_changes))

    after = con.execute("SELECT COUNT(*) FROM misconceptions WHERE benchmark_code = ?",
                        (PLACEHOLDER,)).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM misconceptions").fetchone()[0]
    distinct = con.execute("SELECT COUNT(DISTINCT benchmark_code) FROM misconceptions").fetchone()[0]
    print("\nplaceholder rows after  : %d" % after)
    print("total misconceptions    : %d" % total)
    print("distinct codes in use   : %d" % distinct)
    print("integrity_check         : %s" % con.execute("PRAGMA integrity_check").fetchone()[0])
    if not args.dry_run:
        bad = con.execute("SELECT COUNT(*) FROM misconceptions "
                          "WHERE benchmark_code IS NULL OR benchmark_code = ''").fetchone()[0]
        print("rows with no code       : %d" % bad)
    con.close()


if __name__ == "__main__":
    main()
