"""Coverage audit: can the corpus actually teach each standard?

The retrieval experiment showed the benchmark->section problem is not only a ranking
bug. SS.7.CG.1.8 asks about the Preamble, and the word "preamble" appears in 2 of 82
sections (3 times in total, once as a passing mention in a foreign-policy chapter).
A standard the corpus does not cover cannot be mapped to it by any ranker.

So before spending model time, measure how many of the 36 standards the corpus can
actually support. For each standard, take its DISTINCTIVE terms - the words from its
description and clarifications that are neither boilerplate shared with other
standards nor common across the corpus - and ask how many of them any single section
contains.
"""
import collections
import re
import sqlite3
import sys

ROOT = "/home/muatasr/.nanobot/workspace/fcle-study-app"
sys.path.insert(0, ROOT)
sys.path.insert(0, ROOT + "/scripts")
import rebuild_benchmark_sections as R  # noqa: E402

con = sqlite3.connect(ROOT + "/data/fcle.db")
con.row_factory = sqlite3.Row

secs = [dict(r) for r in con.execute(
    "SELECT id, section_title, text, char_count, fcle_domain FROM content")]
benches = [dict(r) for r in con.execute(
    "SELECT code, standard, description, clarifications FROM benchmarks")]
print("sections: %d   benchmarks: %d" % (len(secs), len(benches)))

# is the stored text complete, or truncated?
mismatch = [(s["id"], s["char_count"], len(s["text"])) for s in secs
            if abs((s["char_count"] or 0) - len(s["text"])) > 50]
print("sections whose char_count disagrees with len(text): %d" % len(mismatch))
for sid, declared, actual in mismatch[:5]:
    print("   section %-4s declared %-7s actual %-7s" % (sid, declared, actual))
counts = sorted(len(s["text"]) for s in secs)
print("text length: min=%d median=%d max=%d" % (counts[0], counts[len(counts) // 2], counts[-1]))

# terms shared across many sections are not discriminative
doc_terms = {s["id"]: set(R.tokens(s["text"])) for s in secs}
term_df = collections.Counter()
for terms in doc_terms.values():
    for t in terms:
        term_df[t] += 1
COMMON = {t for t, n in term_df.items() if n > 0.35 * len(secs)}
print("terms present in >35%% of sections (treated as non-discriminative): %d" % len(COMMON))

# boilerplate: words shared by many standards' own official text
std_terms = collections.Counter()
for b in benches:
    for t in set(R.tokens(" ".join(str(b[k] or "") for k in
                                   ("standard", "description", "clarifications")))):
        std_terms[t] += 1
BOILER = {t for t, n in std_terms.items() if n > 0.5 * len(benches)}
print("terms in >50%% of the standards themselves (boilerplate): %d" % len(BOILER))

rows = []
for b in benches:
    own = R.tokens(" ".join(str(b[k] or "") for k in ("description", "clarifications")))
    distinctive = {t for t in own if t not in COMMON and t not in BOILER}
    if not distinctive:
        rows.append((b["code"], 0.0, None, "", 0, 0))
        continue
    best = (0.0, None, "")
    for s in secs:
        present = distinctive & doc_terms[s["id"]]
        cov = len(present) / len(distinctive)
        if cov > best[0]:
            best = (cov, s["id"], R.clean(s["section_title"]))
    rows.append((b["code"], best[0], best[1],
                 best[2] if best[1] is not None else "",
                 len(distinctive), len(distinctive & doc_terms[best[1]]) if best[1] else 0))

print()
print("=== coverage of each standard by its single best section ===")
STRONG, PARTIAL, NONE = 0.6, 0.3, None
buckets = collections.Counter()
for code, cov, sid, title, ndist, nhit in sorted(rows):
    band = "STRONG" if cov >= STRONG else ("PARTIAL" if cov >= PARTIAL else "NONE")
    buckets[band] += 1
    print("  %-14s %5.0f%%  %-9s best: %-46s (%d/%d terms)"
          % (code, cov * 100, band, title[:46], nhit, ndist))
print()
print("=== summary ===")
print("  STRONG (>=60%% of the standard's distinctive terms live in one section): %d"
      % buckets["STRONG"])
print("  PARTIAL (30-60%%): %d" % buckets["PARTIAL"])
print("  NONE (<30%%): %d" % buckets["NONE"])
print()
workable = [r for r in rows if r[1] >= PARTIAL]
print("  candidates worth a model pass: %d of %d" % (len(workable), len(rows)))
