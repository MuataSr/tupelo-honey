#!/usr/bin/env python3
"""Split the bundled back matter out of the oversized content row.

Section 77 is 367,972 characters because the harvest appended the whole back matter of
the book to the last section of the last chapter. Verified structure, by offset:

    0        -  17,917   17.4's own prose (Learning Objectives onward)
   17,917    -  28,998   chapter 17 review: Key Terms, Summary, Review Questions
   28,998    -  38,546   APPENDIX A | Declaration of Independence
   38,546    -  85,940   APPENDIX B | The Constitution of the United States
   85,940    - 116,283   APPENDIX C | Federalist Papers #10 and #51
  116,283    - 116,922   APPENDIX D | Electoral College Votes by State, 2012-2020
  116,922    - 133,564   APPENDIX E | Selected Supreme Court Cases
  133,564    - 149,133   Answer Key
  149,133    - 340,232   References
  340,232    - 367,972   Index

Why it matters beyond tidiness: the appendices are the public-domain primary sources
(Declaration, Constitution, Federalist Papers) and are genuinely teachable, so standards
the corpus could not previously serve - the Preamble above all - get a real home.

Safety
------
- Every boundary is asserted against the marker text expected there, so a drifted offset
  fails loudly instead of cutting mid-sentence.
- Total characters are accounted for before and after; nothing is dropped.
- The original row's text is preserved in a backup database and in the pre-split column
  values written to a JSON sidecar first.

Usage: python3 scripts/split_back_matter.py [--apply]
"""
import json
import os
import shutil
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "tupelo.db")
SIDECAR = os.path.join(ROOT, "data", "content-77-presplit.json")
SOURCE_ID = 77

# (start, end, title, chapter, chapter_title, domain, marker that must sit at `start`)
CUTS = [
    (0, 17917, "17.4. Approaches to Foreign Policy", 17,
     "Chapter 17. Foreign Policy", 4, "17.4 Approaches to Foreign Policy"),
    (17917, 28998, "Chapter 17 Review: Key Terms, Summary and Review Questions", 17,
     "Chapter 17. Foreign Policy", 4, "Key Terms"),
    (28998, 38546, "Appendix A. Declaration of Independence", 18, "Appendices", 3,
     "APPENDIX A | Declaration of Independence"),
    (38546, 85940, "Appendix B. The Constitution of the United States", 18,
     "Appendices", 2, "APPENDIX B | The Constitution of the United States"),
    (85940, 116283, "Appendix C. Federalist Papers #10 and #51", 18, "Appendices", 3,
     "APPENDIX C | Federalist Papers #10 and #51"),
    (116283, 116922, "Appendix D. Electoral College Votes by State, 2012-2020", 18,
     "Appendices", 2, "APPENDIX D | Electoral College Votes by State"),
    (116922, 133564, "Appendix E. Selected Supreme Court Cases", 18, "Appendices", 4,
     "APPENDIX E | Selected Supreme Court Cases"),
    (133564, 149133, "Answer Key", 19, "Back Matter", 4, "Answer Key"),
    (149133, 340232, "References", 19, "Back Matter", 4, "References"),
    (340232, 367972, "Index", 19, "Back Matter", 4, "Index"),
]

# Rows in `Back Matter` are reference apparatus, not reading. The reading surfaces must
# never offer them, which `router.is_teachable_section` enforces by title.
BACK_MATTER_TITLES = ("Answer Key", "References", "Index")


def main():
    dry = "--apply" not in sys.argv
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    row = con.execute("SELECT * FROM content WHERE id = ?", (SOURCE_ID,)).fetchone()
    if row is None:
        raise SystemExit("content row %d not found" % SOURCE_ID)
    raw = row["text"]
    original_len = len(raw)
    print("source row %d: %d chars, title %r" % (SOURCE_ID, original_len, row["section_title"]))

    total_before = con.execute("SELECT SUM(char_count) FROM content").fetchone()[0]
    rows_before = con.execute("SELECT COUNT(*) FROM content").fetchone()[0]

    # 1. every boundary must carry the marker we expect there
    problems = []
    for start, end, title, _ch, _ct, _dom, marker in CUTS:
        if end > original_len:
            problems.append("%s: end %d beyond the text (%d)" % (title, end, original_len))
            continue
        actual = raw[start:start + len(marker)]
        if actual != marker:
            problems.append("%s: expected %r at %d, found %r"
                            % (title, marker, start, raw[start:start + 40]))
    if CUTS[-1][1] != original_len:
        problems.append("last cut ends at %d but the text is %d long"
                        % (CUTS[-1][1], original_len))
    # 2. the cuts must tile the text exactly, with no gap and no overlap
    for (s1, e1, t1, *_r1), (s2, e2, t2, *_r2) in zip(CUTS, CUTS[1:]):
        if e1 != s2:
            problems.append("gap or overlap between %r (ends %d) and %r (starts %d)"
                            % (t1, e1, t2, s2))
    if problems:
        print("\nREFUSING TO SPLIT - boundary checks failed:")
        for p in problems:
            print("   " + p)
        con.close()
        raise SystemExit(1)
    print("boundary checks: all %d markers present, cuts tile the text exactly" % len(CUTS))

    pieces = []
    for start, end, title, chapter, chapter_title, domain, _marker in CUTS:
        text = raw[start:end]
        pieces.append({"title": title, "chapter": chapter, "chapter_title": chapter_title,
                       "domain": domain, "text": text, "chars": len(text)})

    total_after = sum(p["chars"] for p in pieces)
    print()
    print("=== the pieces ===")
    for p in pieces:
        print("   %-58s %7d chars  %s" % (p["title"][:58], p["chars"],
                                          "(reading)" if p["title"] not in BACK_MATTER_TITLES
                                          else "(apparatus)"))
    print()
    print("chars before: %d   chars after: %d   identical: %s"
          % (original_len, total_after, original_len == total_after))
    if total_after != original_len:
        print("REFUSING: the split does not account for every character")
        con.close()
        raise SystemExit(1)

    if dry:
        print("\n[dry] nothing written. Re-run with --apply.")
        con.close()
        return

    shutil.copy2(DB, "%s.pre-split-%s" % (DB, time.strftime("%Y%m%d-%H%M%S")))
    with open(SIDECAR, "w") as fh:
        json.dump({"id": SOURCE_ID, "section_title": row["section_title"],
                   "chapter": row["chapter"], "chapter_title": row["chapter_title"],
                   "fcle_domain": row["fcle_domain"], "char_count": row["char_count"],
                   "text": raw}, fh)
    print("backup written, original text preserved in %s" % os.path.basename(SIDECAR))

    cur = con.cursor()
    changes = con.total_changes
    next_id = (con.execute("SELECT MAX(id) FROM content").fetchone()[0] or 0) + 1
    created = []
    for i, p in enumerate(pieces):
        if i == 0:
            cur.execute("UPDATE content SET section_title = ?, chapter = ?, chapter_title = ?, "
                        "fcle_domain = ?, text = ?, char_count = ? WHERE id = ?",
                        (p["title"], p["chapter"], p["chapter_title"], p["domain"],
                         p["text"], p["chars"], SOURCE_ID))
        else:
            cur.execute("INSERT INTO content (id, chapter, chapter_title, section_title, "
                        "text, char_count, fcle_domain) VALUES (?,?,?,?,?,?,?)",
                        (next_id, p["chapter"], p["chapter_title"], p["title"],
                         p["text"], p["chars"], p["domain"]))
            created.append((next_id, p["title"], p["chars"]))
            next_id += 1
    con.commit()
    print("row changes: %d" % (con.total_changes - changes))
    for cid, title, chars in created:
        print("   created row %-4s %-56s %7d chars" % (cid, title[:56], chars))

    total_now = con.execute("SELECT SUM(char_count) FROM content").fetchone()[0]
    rows_now = con.execute("SELECT COUNT(*) FROM content").fetchone()[0]
    print()
    print("content rows : %d -> %d" % (rows_before, rows_now))
    print("content chars: %d -> %d   preserved: %s"
          % (total_before, total_now, total_before == total_now))
    mismatch = con.execute("SELECT COUNT(*) FROM content WHERE char_count <> length(text)"
                           ).fetchone()[0]
    print("rows where char_count <> len(text): %d" % mismatch)
    print("rows over 60000 chars             : %d" % con.execute(
        "SELECT COUNT(*) FROM content WHERE char_count > 60000").fetchone()[0])
    print("integrity_check                   : %s"
          % con.execute("PRAGMA integrity_check").fetchone()[0])
    con.close()
    if mismatch or total_now != total_before:
        raise SystemExit("verification failed after writing - restore from the backup")


if __name__ == "__main__":
    main()
