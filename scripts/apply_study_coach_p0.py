#!/usr/bin/env python3
"""
Study Coach Phase 0 — content-DB prep.

  P0.0  Repair the `benchmarks` table: `description` is the literal string 'Strand'
        in all 36 rows and `clarifications` is empty in 33 of 36. Fill both from
        FLDOE's Revised Civics and Government Standards (source: the mapping JSON).
  P0.1  Create `topic_benchmarks`: the reviewed topic -> benchmark map.

Idempotent: safe to re-run. Only fills fields that are missing/placeholder;
never overwrites authored content.

Run from anywhere. The DB path is anchored to the REPO ROOT, not the script's
directory (a seed script that resolves paths from __file__ silently writes into
scripts/data/ instead of data/).
"""
import json, os, sqlite3, sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(REPO_ROOT, "data", "tupelo.db")
SRC = os.path.join(REPO_ROOT, "data", "fcle_topic_benchmarks.json")

PLACEHOLDER = {"", "strand", "n/a", "none"}


def main():
    if not os.path.exists(DB):
        sys.exit(f"DB not found: {DB}")
    if not os.path.exists(SRC):
        sys.exit(f"mapping source not found: {SRC}")

    data = json.load(open(SRC))
    mapping = data["mapping"]
    btext = data["benchmark_text"]

    c = sqlite3.connect(DB)
    c.execute("PRAGMA foreign_keys=ON")
    report = []

    # ---- P0.0 repair the benchmarks table --------------------------------
    bcols = [r[1] for r in c.execute("PRAGMA table_info(benchmarks)")]
    fixed_desc = fixed_clar = 0
    for code, info in btext.items():
        row = c.execute("SELECT description, clarifications FROM benchmarks WHERE code=?",
                        (code,)).fetchone()
        if not row:
            continue
        cur_desc, cur_clar = (row[0] or ""), (row[1] or "")
        new_desc = cur_desc
        if cur_desc.strip().lower() in PLACEHOLDER:
            new_desc = info.get("description", "").strip()
            if new_desc:
                fixed_desc += 1
        new_clar = cur_clar
        if cur_clar.strip().lower() in PLACEHOLDER:
            cl = info.get("clarifications") or []
            if cl:
                new_clar = "\n".join(f"- {x}" for x in cl)
                fixed_clar += 1
        if (new_desc, new_clar) != (cur_desc, cur_clar):
            c.execute("UPDATE benchmarks SET description=?, clarifications=? WHERE code=?",
                      (new_desc, new_clar, code))
    report.append(f"benchmarks: filled description on {fixed_desc} rows, "
                  f"clarifications on {fixed_clar} rows")

    # ---- P0.1 topic_benchmarks ------------------------------------------
    c.execute("""
        CREATE TABLE IF NOT EXISTS topic_benchmarks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            topic           TEXT    NOT NULL,
            fcle_domain     INTEGER NOT NULL,
            primary_code    TEXT    NOT NULL,
            secondary_codes TEXT,
            n_questions     INTEGER,
            decided_by      TEXT,
            note            TEXT,
            UNIQUE (fcle_domain, topic)
        )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tb_primary ON topic_benchmarks(primary_code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tb_domain  ON topic_benchmarks(fcle_domain)")

    valid = set(btext)
    bad = [r for r in mapping if r["primary_code"] not in valid]
    if bad:
        sys.exit(f"refusing to load: {len(bad)} rows carry a code outside the 36-code set")

    for r in mapping:
        c.execute("""
            INSERT INTO topic_benchmarks
                (topic, fcle_domain, primary_code, secondary_codes, n_questions, decided_by, note)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(fcle_domain, topic) DO UPDATE SET
                primary_code=excluded.primary_code,
                secondary_codes=excluded.secondary_codes,
                n_questions=excluded.n_questions,
                decided_by=excluded.decided_by,
                note=excluded.note""",
            (r["topic"], r["domain"], r["primary_code"],
             json.dumps(r.get("secondary_codes") or []),
             r.get("n"), r.get("decided_by", ""), r.get("note", "")))

    c.commit()

    # ---- verification ----------------------------------------------------
    n_tb = c.execute("SELECT COUNT(*) FROM topic_benchmarks").fetchone()[0]
    n_pairs = c.execute("SELECT COUNT(*) FROM (SELECT DISTINCT fcle_domain, topic "
                        "FROM topic_benchmarks)").fetchone()[0]
    n_still_stub = c.execute("SELECT COUNT(*) FROM benchmarks "
                             "WHERE LOWER(TRIM(COALESCE(description,''))) IN ('','strand')").fetchone()[0]
    n_orjan = c.execute("SELECT COUNT(*) FROM topic_benchmarks WHERE primary_code IS NULL "
                        "OR TRIM(primary_code)=''").fetchone()[0]
    for name, dom in [("American Democracy", 1), ("US Constitution", 2),
                      ("Founding Documents", 3), ("Landmark Impact", 4)]:
        n = c.execute("SELECT COUNT(*) FROM topic_benchmarks WHERE fcle_domain=?", (dom,)).fetchone()[0]
        report.append(f"  D{dom} {name}: {n} topics")
    report.append(f"topic_benchmarks rows={n_tb} distinct(domain,topic)={n_pairs}")
    report.append(f"benchmarks still showing the 'Strand' stub: {n_still_stub}")
    report.append(f"topic_benchmarks rows with a missing code: {n_orjan}")
    report.append("sample: " + ", ".join(
        f"{r[0]}=>{r[1]}" for r in c.execute(
            "SELECT topic, primary_code FROM topic_benchmarks ORDER BY fcle_domain, n_questions DESC LIMIT 5")))

    print(f"DB: {DB}")
    for line in report:
        print(line)

    ok = (n_tb == 67 and n_pairs == 67 and n_still_stub == 0 and n_orjan == 0)
    c.close()
    print("RESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
