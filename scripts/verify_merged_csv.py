"""Verify the merged re-key CSV is complete and every code is real and in-domain."""
import collections
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import misconception_codes as mc  # noqa: E402

rows = list(csv.DictReader(open(ROOT + "/data/rekey.csv")))
print("rows in merged CSV          :", len(rows))
print("unique ids                  :", len({r["id"] for r in rows}))
print("source spread               :", collections.Counter(r["source"] for r in rows).most_common())

known = mc.all_codes()
per_domain = {d: set(mc.domain_codes(d)) for d in (1, 2, 3, 4)}
print()
print("allow-list sizes            :", {d: len(per_domain[d]) for d in sorted(per_domain)})

blank = [r for r in rows if not (r["new_code"] or "").strip()]
not_real = [r for r in rows if r["new_code"] and r["new_code"] not in known]
out_dom = [r for r in rows if r["new_code"] and r["new_code"] not in per_domain.get(int(r["domain"]), set())]
placeholder = [r for r in rows if (r["new_code"] or "").strip().upper() == "FCLE"]

print("rows with no code           :", len(blank))
print("rows whose code is not real :", len(not_real))
print("rows out of their domain    :", len(out_dom))
print("rows still 'FCLE'           :", len(placeholder))
for label, bad in [("no code", blank), ("not real", not_real), ("out of domain", out_dom)]:
    for r in bad[:6]:
        print("   %-13s id=%s dom=%s code=%r" % (label, r["id"], r["domain"], r["new_code"]))

print()
print("=== code distribution across the 350 ===")
for (dom, code), n in sorted(collections.Counter(
        (r["domain"], r["new_code"]) for r in rows).items()):
    print("   dom %s -> %-14s x%d" % (dom, code, n))

print()
print("=== per-domain totals (should be 110/110/65/65) ===")
print("   ", collections.Counter(r["domain"] for r in rows).most_common())

ok = not (blank or not_real or out_dom or placeholder) and len(rows) == 350
print()
print("VERDICT:", "ALL 350 ROWS VALID" if ok else "PROBLEMS FOUND - DO NOT APPLY")
