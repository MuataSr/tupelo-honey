#!/usr/bin/env python3
"""Verify the 11 children's recommendations before any of them reach the product.

Child output is a SOURCE POINTER, NEVER EVIDENCE. A subagent reporting a clean,
confident answer is not proof the answer is right, and this workload has a measured
history of fabricated citations on correctly-found pages. So every claim is re-checked
here, and nothing is written to the database.

Per kind:
  in_corpus  the section id must exist; the section must be teachable (not reference
             apparatus, not back matter); and the "evidence" string must appear
             VERBATIM in that section's text after whitespace normalisation. A quote
             that does not appear is treated as fabricated, not as a paraphrase.
  external   the URL is listed for the orchestrator to re-open and confirm by hand. A
             child's word that a page says something is worth nothing.
  none       accepted as-is, and listed: "no good target" is a legitimate answer.

Usage: python3 scripts/verify_code11.py /path/to/out-dir
"""
import csv
import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "tupelo.db")
CSV_OUT = os.path.join(ROOT, "data", "code11-verified.csv")
REPORT = os.path.join(ROOT, "data", "code11-verification.md")

REQUIRED = ("code", "kind", "confidence", "evidence", "why")
ALLOWED_KINDS = ("in_corpus", "external", "none")
OK_LICENCES = ("public domain", "cc0", "cc by", "cc by-sa", "oer", "government",
               "us government", "florida government")


def normalise(text):
    text = str(text or "").replace("\uf0b7", " ").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else "/tmp/code11out"
    files = sorted(f for f in os.listdir(outdir) if f.endswith(".json"))
    print("recommendation files found: %d" % len(files))

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    content = {r["id"]: dict(r) for r in con.execute(
        "SELECT id, section_title, text, char_count FROM content")}
    try:
        from coach import rules as coach_rules
    except Exception:                                   # noqa: BLE001
        coach_rules = None

    verified, needs_fetch, refused, rejected = [], [], [], []
    for name in files:
        path = os.path.join(outdir, name)
        raw = open(path).read()
        try:
            rec = json.loads(raw)
        except Exception as exc:                        # noqa: BLE001
            rejected.append((name, "not valid JSON: %s" % exc))
            continue
        if not isinstance(rec, dict):
            rejected.append((name, "top level is not an object"))
            continue

        missing = [k for k in REQUIRED if not rec.get(k)]
        if missing:
            rejected.append((name, "missing required field(s): %s" % ", ".join(missing)))
            continue
        kind = str(rec.get("kind", "")).strip().lower()
        if kind not in ALLOWED_KINDS:
            rejected.append((name, "kind %r is not one of %s" % (kind, ALLOWED_KINDS)))
            continue

        code = rec["code"]
        if kind == "none":
            verified.append({"code": code, "kind": "none", "section_id": "",
                             "note": rec.get("notes", "") or rec.get("why", ""),
                             "confidence": rec.get("confidence", "")})
            continue

        if kind == "external":
            url = (rec.get("source_url") or "").strip()
            lic = (rec.get("license") or "").strip().lower()
            problems = []
            if not url.startswith("http"):
                problems.append("no usable source_url")
            if not any(ok in lic for ok in OK_LICENCES):
                problems.append("licence %r is not on the allowed list" % lic)
            if problems:
                refused.append((code, name, "; ".join(problems)))
                continue
            needs_fetch.append({"code": code, "file": name, "url": url,
                                "title": rec.get("source_title", ""),
                                "publisher": rec.get("publisher", ""),
                                "license": rec.get("license", ""),
                                "evidence": rec.get("evidence", ""),
                                "why": rec.get("why", ""),
                                "confidence": rec.get("confidence", "")})
            continue

        # in_corpus - the strict one
        try:
            sid = int(rec.get("section_id"))
        except (TypeError, ValueError):
            refused.append((code, name, "in_corpus without a usable section_id"))
            continue
        sec = content.get(sid)
        if sec is None:
            refused.append((code, name, "section_id %s does not exist" % sid))
            continue
        if coach_rules is not None:
            title = re.sub(r"\s+", " ", str(sec["section_title"] or "")).strip().rstrip("*").strip().lower()
            if title in coach_rules.NON_SECTION_TITLES:
                refused.append((code, name, "section %s is reference apparatus" % sid))
                continue
            if (sec["char_count"] or 0) > coach_rules.MAX_READING_SECTION_CHARS:
                refused.append((code, name, "section %s is back matter" % sid))
                continue

        quote = normalise(rec.get("evidence"))
        body = normalise(sec["text"])
        if len(quote) < 15:
            refused.append((code, name, "evidence quote too short to check (%d chars)" % len(quote)))
            continue
        if quote not in body:
            # try the longest 12-word window of the quote, in case of light paraphrase
            words = quote.split()
            hit = False
            for i in range(0, max(1, len(words) - 12)):
                if " ".join(words[i:i + 12]) in body:
                    hit = True
                    break
            refused.append((code, name,
                            "EVIDENCE NOT FOUND in section %s%s"
                            % (sid, " (a 12-word window does match - light paraphrase)"
                               if hit else " - treat as fabricated")))
            continue

        verified.append({"code": code, "kind": "in_corpus", "section_id": sid,
                         "section_title": re.sub(r"\s+", " ", str(sec["section_title"])).strip(),
                         "note": rec.get("why", ""), "confidence": rec.get("confidence", "")})

    with open(CSV_OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "kind", "accepted_section_id", "section_title", "note", "confidence"])
        for v in verified:
            w.writerow([v["code"], v["kind"], v.get("section_id", ""),
                        v.get("section_title", ""), v.get("note", ""), v["confidence"]])

    lines = ["# 11-code recommendations - verification", ""]
    lines.append("Verified in_corpus: **%d**" % sum(1 for v in verified if v["kind"] == "in_corpus"))
    lines.append("")
    lines.append("Awaiting a human re-fetch of the URL: **%d**" % len(needs_fetch))
    lines.append("")
    lines.append("Refused: **%d**" % len(refused))
    lines.append("")
    lines.append("Rejected as malformed: **%d**" % len(rejected))
    lines.append("")
    lines += ["## Verified in_corpus (evidence quoted verbatim from the section)", ""]
    for v in verified:
        if v["kind"] == "in_corpus":
            lines.append("- `%s` -> section %s \"%s\" (%s)"
                         % (v["code"], v["section_id"], v.get("section_title", "")[:60],
                            v["confidence"]))
    lines += ["", "## 'No good target' answers (legitimate, nothing written)", ""]
    for v in verified:
        if v["kind"] == "none":
            lines.append("- `%s` - %s" % (v["code"], v["note"][:160]))
    lines += ["", "## External sources - MUST be re-opened by hand before use", ""]
    for n in needs_fetch:
        lines.append("- `%s` [%s] %s" % (n["code"], n["license"], n["url"]))
        lines.append("  - claimed: %s" % n["evidence"][:200])
    lines += ["", "## Refused", ""]
    for code, name, why in refused:
        lines.append("- `%s` (%s): %s" % (code, name, why))
    lines += ["", "## Rejected as malformed", ""]
    for name, why in rejected:
        lines.append("- %s: %s" % (name, why))
    open(REPORT, "w").write("\n".join(lines) + "\n")

    print()
    print("verified in_corpus : %d" % sum(1 for v in verified if v["kind"] == "in_corpus"))
    print("answered 'none'    : %d" % sum(1 for v in verified if v["kind"] == "none"))
    print("external to re-fetch: %d" % len(needs_fetch))
    print("refused            : %d" % len(refused))
    print("rejected malformed : %d" % len(rejected))
    for code, name, why in refused:
        print("   refuse %-14s %s" % (code, why))
    for name, why in rejected:
        print("   reject %-14s %s" % (name, why))
    print("\n[out] %s" % CSV_OUT)
    print("[out] %s" % REPORT)
    con.close()


if __name__ == "__main__":
    main()
