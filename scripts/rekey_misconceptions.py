#!/usr/bin/env python3
"""P0.2 - re-key the placeholder misconception codes onto real civics benchmarks.

Background
----------
~350 of 704 rows in `misconceptions` carry `benchmark_code = 'FCLE'`, which is a
placeholder, not a standard. The three generators that produced them stamp the
placeholder because their prompts never carried the real codes (see P0.2a, which
fixes that so it cannot recur).

Why it matters
--------------
The Study Coach matches a missed question to a misconception in two tiers:
tier 1 on `benchmark_code`, tier 2 on domain. No answer can ever carry the code
'FCLE', so every placeholder row is stuck in tier 2 - which is how a generic
domain-level misconception ends up quoted against a very specific student error.

Method
------
Split by family, not by convenience:

  drafter  - Qwen3.5-9B (:8085) assigns a code, seeing the row's domain and that
             domain's official benchmark descriptions.
  reviewer - Gemma 4 26B (:8083), a different model family, sees the row plus the
             code the drafter chose and its official description, blind to the
             drafter's reasoning. Answers CONFIRM or DISPUTE + a replacement.
  gate     - deterministic. A code is accepted only if it is one of the 36 real
             SS.7.CG codes AND appears in the row's own domain. Anything else is
             flagged for human review rather than silently written.

Nothing here writes to the database. It emits rekey.csv + disagreements.md; a
separate apply script performs the update after the numbers are reviewed.

Usage:  python3 scripts/rekey_misconceptions.py [--limit N] [--workers 2]
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "tupelo.db")
OUT_DIR = os.path.dirname(DB)
CSV_OUT = os.path.join(OUT_DIR, "rekey.csv")
DISAGREE_OUT = os.path.join(OUT_DIR, "rekey-disagreements.md")
PROGRESS = os.path.join(OUT_DIR, "rekey-progress.jsonl")

DRAFTER = ("http://127.0.0.1:8085/v1/chat/completions", "Qwen3.5-9B")
REVIEWER = ("http://127.0.0.1:8083/v1/chat/completions", "gemma-4-26B-vision")

BATCH = 20
PLACEHOLDER = "FCLE"


# --------------------------------------------------------------------------
# tolerating model output
# --------------------------------------------------------------------------
def extract_json(text):
    """Pull a JSON array out of a model reply that may be wrapped in prose/fences."""
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    for candidate in (text,):
        try:
            return json.loads(candidate)
        except Exception:
            pass
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        blob = m.group(0)
        try:
            return json.loads(blob)
        except Exception:
            pass
        # single-quoted / trailing-comma repairs, last resort
        repaired = re.sub(r",\s*([\]}])", r"\1", blob)
        repaired = repaired.replace("'", '"')
        try:
            return json.loads(repaired)
        except Exception:
            return None
    return None


def call(endpoint, payload, timeout=300):
    req = urllib.request.Request(
        endpoint[0], data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())["choices"][0]["message"]["content"]


def ask(endpoint, system, user, retries=3, max_tokens=2600):
    payload = {
        "model": endpoint[1],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    last = None
    for attempt in range(retries):
        try:
            return call(endpoint, payload)
        except Exception as exc:            # noqa: BLE001 - report and retry
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{endpoint[1]} failed: {last}")


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------
def clean_text(value):
    """Strip the harvest artifacts the content rows carry (bullet glyphs, NBSPs)."""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\uf0b7", " ").replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def load(limit=None):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    codes = {}
    for r in con.execute("SELECT code, description, clarifications, reporting_category "
                         "FROM benchmarks ORDER BY code"):
        codes[r["code"]] = {
            "code": r["code"],
            "description": clean_text(r["description"]),
            "clarifications": clean_text(r["clarifications"]),
            "category": clean_text(r["reporting_category"]),
        }
    by_domain = {}
    for r in con.execute("SELECT DISTINCT fcle_domain, primary_code FROM topic_benchmarks"):
        by_domain.setdefault(r["fcle_domain"], set()).add(r["primary_code"])

    rows = [dict(r) for r in con.execute(
        "SELECT id, benchmark_code, misconception, correction, fcle_domain "
        "FROM misconceptions WHERE benchmark_code = ? ORDER BY id", (PLACEHOLDER,))]
    if limit:
        rows = rows[:limit]
    return rows, codes, by_domain


def group_batches(rows):
    """Batch rows WITHIN a domain.

    Slicing a list of rows ordered by id silently mixes domains, and a batch is told
    which code list to use from its first row - so a domain-4 row in a batch that
    happened to start with a domain-3 row got domain 3's list, the draft passed the
    domain check against the wrong domain, and the row was only rejected later. Group
    by domain first so a batch can only ever see its own domain's codes.
    """
    grouped = {}
    for r in rows:
        grouped.setdefault(r["fcle_domain"], []).append(r)
    out = []
    for domain in sorted(grouped):
        rs = grouped[domain]
        for i in range(0, len(rs), BATCH):
            out.append(rs[i:i + BATCH])
    return out


def code_block(codes, allowed):
    lines = []
    for code in sorted(allowed):
        info = codes.get(code)
        if not info:
            continue
        desc = info["description"] or info["clarifications"]
        lines.append(f"- {code}: {desc[:220]}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# draft + review
# --------------------------------------------------------------------------
DRAFT_SYS = ("You map civics misconceptions to Florida civics benchmark standards. "
             "Return ONLY a JSON array. No prose, no markdown fences.")

DRAFT_TMPL = """Florida has {n} official benchmark standards for this domain of the Civic Literacy exam content.
Pick the ONE standard each misconception below is really about.

STANDARDS:
{standards}

MISCONCEPTIONS:
{items}

Rules:
- Your code MUST be one of the {n} codes printed above. Anything else is rejected automatically.
  Never invent a code. Never answer "FCLE".
- Prefer the standard about the SPECIFIC branch, process, right or case involved over a general
  standard about founding principles, the rule of law, or the Constitution limiting power. Those
  general standards are for misconceptions about the principles themselves, not about how an
  institution actually works.
- Judge by the SUBSTANCE of the misconception and its correction, not by keyword overlap.
- If a misconception spans two standards, choose the one its correction emphasises.

Return ONLY a JSON array, one object per misconception, in the same order:
[{{"id": <id>, "code": "SS.7.CG.1.2", "why": "<12 words max>"}}]"""

REVIEW_SYS = ("You audit civics benchmark mappings. Be skeptical and specific. "
              "Return ONLY a JSON array. No prose, no markdown fences.")

REVIEW_TMPL = """Another reviewer assigned each misconception below to a civics benchmark standard.
Verify each assignment against the standard's own words.

MISCONCEPTIONS AND PROPOSED STANDARDS:
{items}

For each, answer CONFIRM if the standard genuinely covers what the misconception is about,
or DISPUTE if it does not. ALWAYS put the best code from the list below in "code", even when you
CONFIRM, so a confirmed-but-better option is not lost.

Return ONLY a JSON array in the same order:
[{{"id": <id>, "verdict": "CONFIRM", "code": "SS.7.CG.3.8", "reason": "<12 words max>"}}]

CODES AVAILABLE FOR THIS DOMAIN:
{standards}"""


REPAIR_SYS = ("You select civics benchmark codes from a fixed list. "
              "Return ONLY a JSON array. No prose, no markdown fences.")

REPAIR_TMPL = """You must answer using ONLY these codes. Nothing else is accepted.

{codes}

ROWS TO KEY:
{items}

Return ONLY a JSON array in this order:
[{{"id": <id>, "code": "<one code from the list above>", "why": "<10 words max>"}}]"""


def _parse_codes(reply):
    parsed = extract_json(reply)
    out = {}
    if not isinstance(parsed, list):
        return out
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        try:
            rid = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        out[rid] = {"code": (entry.get("code") or "").strip(),
                    "why": clean_text(entry.get("why"))[:90]}
    return out


def draft_batch(rows, codes, by_domain):
    """Assign codes, then force anything out-of-domain through a focused repair pass.

    The drafter has a measured bias: it reaches for the abstract founding-principles
    standards instead of the concrete branch/rights standards. Those codes are real but
    belong to another domain, so they can never match an answer at tier 1. Rather than
    accept them or drop the row, re-ask with nothing but the domain's own list.
    """
    domain = rows[0]["fcle_domain"]
    allowed = by_domain.get(domain, set())
    standards = code_block(codes, allowed)
    items = "\n".join(
        f'{r["id"]}. MISCONCEPTION: {clean_text(r["misconception"])}\n'
        f'   CORRECTION: {clean_text(r["correction"])[:300]}'
        for r in rows)
    reply = ask(DRAFTER, DRAFT_SYS,
                DRAFT_TMPL.format(n=len(allowed), standards=standards, items=items))
    out = _parse_codes(reply)
    for r in rows:
        out.setdefault(r["id"], {"code": None, "why": "missing from reply"})

    bad = [r for r in rows if out[r["id"]]["code"] not in allowed]
    if bad:
        print(f"        [repair] {len(bad)} of {len(rows)} out-of-domain - re-asking "
              f"with the domain list only", flush=True)
        for r in bad:
            out[r["id"]]["proposed"] = out[r["id"]]["code"]
        repair_items = "\n".join(
            f'{r["id"]}. MISCONCEPTION: {clean_text(r["misconception"])[:240]}\n'
            f'   CORRECTION: {clean_text(r["correction"])[:240]}'
            for r in bad)
        try:
            reply2 = ask(DRAFTER, REPAIR_SYS,
                         REPAIR_TMPL.format(codes=standards, items=repair_items),
                         retries=2, max_tokens=1500)
            fixed = _parse_codes(reply2)
        except Exception as exc:                        # noqa: BLE001
            print(f"        [repair] failed: {exc}", flush=True)
            fixed = {}
        for r in bad:
            got = fixed.get(r["id"], {}).get("code")
            if got in allowed:
                out[r["id"]] = {"code": got, "why": fixed[r["id"]]["why"] + " (repaired)",
                                "proposed": out[r["id"]].get("proposed")}
    return out


def review_batch(rows, drafted, codes, by_domain):
    domain = rows[0]["fcle_domain"]
    allowed = by_domain.get(domain, set())
    standards = code_block(codes, allowed)
    items = []
    for r in rows:
        code = drafted.get(r["id"], {}).get("code")
        info = codes.get(code) or {}
        items.append(
            f'{r["id"]}. MISCONCEPTION: {clean_text(r["misconception"])[:240]}\n'
            f'   CORRECTION: {clean_text(r["correction"])[:240]}\n'
            f'   PROPOSED: {code} - {(info.get("description") or info.get("clarifications") or "UNKNOWN CODE")[:200]}')
    reply = ask(REVIEWER, REVIEW_SYS,
                REVIEW_TMPL.format(items="\n\n".join(items), standards=standards))
    parsed = extract_json(reply)
    if not isinstance(parsed, list):
        return {}
    out = {}
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        try:
            rid = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        verdict = str(entry.get("verdict", "")).strip().upper()
        out[rid] = {
            "verdict": "CONFIRM" if verdict.startswith("CONFIRM") else "DISPUTE",
            "code": (entry.get("code") or "").strip() or None,
            "reason": clean_text(entry.get("reason"))[:90],
        }
    return out


def decide(row, drafted, reviewed, codes, by_domain):
    """Fold two model opinions plus the deterministic gate into one decision."""
    domain = row["fcle_domain"]
    allowed = by_domain.get(domain, set())
    proposed = drafted.get("code")
    rev = reviewed or {}
    verdict = rev.get("verdict")
    replacement = rev.get("code")

    if not proposed or proposed not in codes:
        if replacement and replacement in codes and replacement in allowed:
            return replacement, "reviewer-replacement", verdict or "no-draft"
        return None, "no-valid-code", "unmapped"

    if proposed not in allowed:
        if replacement and replacement in allowed:
            return replacement, "reviewer-kept-in-domain", verdict or ""
        return None, "out-of-domain", verdict or ""

    if verdict == "DISPUTE":
        if replacement and replacement in allowed:
            return replacement, "reviewer-accepted", "DISPUTE-then-replacement"
        return proposed, "drafter-kept-reviewer-disputed", "reviewer-dispute-no-alternative"

    if verdict is None:
        return proposed, "drafter-only", "reviewer-silent"
    if replacement and replacement != proposed and replacement in allowed:
        return replacement, "reviewer-preferred", "CONFIRM-with-better-code"
    return proposed, "draft+review-confirmed", "CONFIRM"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--retry-flagged", action="store_true",
                    help="keep the rows already resolved in data/rekey.csv and redo only "
                         "the ones flagged out-of-domain or never reviewed")
    args = ap.parse_args()

    rows, codes, by_domain = load(args.limit or None)

    kept = []
    if args.retry_flagged:
        if not os.path.exists(CSV_OUT):
            raise SystemExit("--retry-flagged needs an existing %s" % CSV_OUT)
        done = {}
        with open(CSV_OUT) as fh:
            for r in csv.DictReader(fh):
                done[int(r["id"])] = r
        REDO = {"out-of-domain", "no-valid-code", "drafter-only"}
        want, keep_ids = [], []
        for r in rows:
            prev = done.get(r["id"])
            if prev and prev.get("source") not in REDO and prev.get("new_code"):
                keep_ids.append(r["id"])
            else:
                want.append(r)
        kept = [done[i] for i in keep_ids]
        print(f"[retry] keeping {len(kept)} resolved rows, redoing {len(want)} flagged rows",
              flush=True)
        rows = want
        if not rows:
            print("[done] nothing flagged; nothing to do", flush=True)
            return
    print(f"[start] placeholder rows={len(rows)} codes={len(codes)}", flush=True)
    for d in sorted(by_domain):
        print(f"        domain {d}: {len(by_domain[d])} codes cover it", flush=True)
    if not rows:
        print("[done] nothing to do", flush=True)
        return

    batches = group_batches(rows)
    print(f"[draft] {len(batches)} batches of <= {BATCH} within one domain each, "
          f"{args.workers} workers", flush=True)

    drafted = {}
    def run_draft(batch):
        domain = batch[0]["fcle_domain"]
        for attempt in range(2):
            try:
                got = draft_batch(batch, codes, by_domain)
                missing = [r["id"] for r in batch if not got.get(r["id"], {}).get("code")]
                if not missing or attempt == 1:
                    return domain, got
            except Exception as exc:                    # noqa: BLE001
                if attempt == 1:
                    return domain, {r["id"]: {"code": None, "why": f"error: {exc}"[:80]}
                                    for r in batch}
        return domain, {}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, (domain, got) in enumerate(pool.map(run_draft, batches), 1):
            drafted.update(got)
            good = sum(1 for v in got.values() if v.get("code"))
            print(f"[draft] batch {i}/{len(batches)} domain {domain} "
                  f"({len(got)} rows, {good} with a code)", flush=True)

    print("[review] starting", flush=True)
    reviewed = {}
    def run_review(batch):
        subset = {r["id"]: drafted.get(r["id"], {}) for r in batch}
        for attempt in range(2):
            try:
                return batch[0]["fcle_domain"], review_batch(batch, subset, codes, by_domain)
            except Exception as exc:                    # noqa: BLE001
                if attempt == 1:
                    print(f"[review] batch failed: {exc}", flush=True)
                    return batch[0]["fcle_domain"], {}
        return batch[0]["fcle_domain"], {}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, (domain, got) in enumerate(pool.map(run_review, batches), 1):
            reviewed.update(got)
            print(f"[review] batch {i}/{len(batches)} domain {domain} ({len(got)} verdicts)", flush=True)

    header = ["id", "domain", "old_code", "proposed_code", "new_code", "source",
              "reviewer_verdict", "drafter_why", "reviewer_reason", "misconception"]
    fresh = []
    stats = {}
    disputes = []
    _merge_and_write(header, kept, fresh, rows, drafted, reviewed, codes, by_domain,
                     stats, disputes)
    print(f"\n[done] resolved={sum(v for k, v in stats.items() if k not in ('no-valid-code', 'out-of-domain'))}"
          f"/{len(rows)} (this pass)", flush=True)
    for k in sorted(stats, key=lambda k: -stats[k]):
        print(f"        {k}: {stats[k]}", flush=True)
    return


def _merge_and_write(header, kept, fresh, rows, drafted, reviewed, codes, by_domain,
                     stats, disputes):
    with open(CSV_OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for prev in kept:
            w.writerow([prev[c] for c in header])
        disputes = []
        for row in rows:
            rid = row["id"]
            code, source, note = decide(row, drafted.get(rid, {}), reviewed.get(rid),
                                        codes, by_domain)
            stats[source] = stats.get(source, 0) + 1
            w.writerow([rid, row["fcle_domain"], row["benchmark_code"],
                        drafted.get(rid, {}).get("proposed") or drafted.get(rid, {}).get("code") or "",
                        code or "", source, note, drafted.get(rid, {}).get("why", ""),
                        (reviewed.get(rid) or {}).get("reason", ""),
                        clean_text(row["misconception"])[:150]])
            if source in ("no-valid-code", "out-of-domain") or code is None:
                disputes.append((rid, row, drafted.get(rid), reviewed.get(rid), source))
            with open(PROGRESS, "a") as pf:
                pf.write(json.dumps({"id": rid, "code": code, "source": source}) + "\n")

    print(f"[pass] resolved={sum(v for k, v in stats.items() if k not in ('no-valid-code', 'out-of-domain'))}"
          f"/{len(rows)} unresolved={len(disputes)}", flush=True)

    with open(DISAGREE_OUT, "w") as fh:
        fh.write("# P0.2 - misconception re-key: rows needing a human decision\n\n")
        fh.write(f"{len(rows)} placeholder rows processed; {len(disputes)} unresolved.\n\n")
        for rid, row, dr, rv, source in disputes:
            fh.write(f"## row {rid} (domain {row['fcle_domain']}) - {source}\n\n")
            fh.write(f"- misconception: {clean_text(row['misconception'])}\n")
            fh.write(f"- correction: {clean_text(row['correction'])[:300]}\n")
            fh.write(f"- drafter: {dr}\n")
            fh.write(f"- reviewer: {rv}\n\n")
    print(f"[out] {CSV_OUT}", flush=True)
    print(f"[out] {DISAGREE_OUT}", flush=True)


if __name__ == "__main__":
    main()
