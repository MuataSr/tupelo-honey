#!/usr/bin/env python3
"""Phase A — automated QC pass over the FCLE bank (cheap filter before human review).

Read-only with respect to the bank. Writes qc_report.json + qc_summary.md, and
selects the stratified human-validation sample.

Run:  python3 qc_pass.py [--db PATH] [--out DIR] [--sample N] [--seed N]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import random
import re
import sqlite3
import sys

DEFAULT_DB = os.path.expanduser("~/.nanobot/workspace/fcle-study-app/data/fcle.db")
DEFAULT_OUT = os.path.expanduser("~/.nanobot/workspace/fcle-oer-release")
DOMAIN_NAMES = {1: "American Democracy", 2: "US Constitution",
                3: "Founding Documents", 4: "Landmark Impact"}
NEAR_DUP_THRESHOLD = 0.82


def parse_list(value) -> list[str]:
    """wrong_answers / wrong_explanations are JSON arrays, but tolerate other shapes."""
    if value is None:
        return []
    s = str(value).strip()
    if not s:
        return []
    try:
        j = json.loads(s)
        if isinstance(j, list):
            return [str(x).strip() for x in j]
        if isinstance(j, dict):
            return [f"{k}: {v}" for k, v in j.items()]
    except Exception:
        pass
    parts = re.split(r"\n+", s) if "\n" in s else (s.split("|") if "|" in s else [s])
    return [p.strip(" -*\t") for p in parts if p.strip(" -*\t")]


def norm(text) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(text).lower())).strip()


def token_set(text) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", str(text).lower())}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM questions").fetchall()]
    finally:
        conn.close()
    for r in rows:
        r["_wrong"] = parse_list(r.get("wrong_answers"))
        r["_rationales"] = parse_list(r.get("wrong_explanations"))
        r["_options"] = ([str(r.get("correct_answer") or "").strip()] + r["_wrong"])
    return rows


def run_checks(rows: list[dict]) -> tuple[dict, dict[str, list]]:
    counts: collections.Counter = collections.Counter()
    flagged: dict[str, list] = collections.defaultdict(list)

    for r in rows:
        rid = r.get("id")
        key = str(r.get("correct_answer") or "").strip()
        wrongs = r["_wrong"]
        rationales = r["_rationales"]
        options = [o for o in r["_options"] if o]
        exp = str(r.get("explanation") or "")

        # 1. Structural integrity
        if not key:
            counts["missing_key"] += 1
            flagged["missing_key"].append(rid)
        if len(wrongs) != 3:
            counts["distractor_count_not_3"] += 1
            flagged["distractor_count_not_3"].append((rid, len(wrongs)))
        if len(options) >= 2 and len({norm(o) for o in options}) != len(options):
            counts["duplicate_option_within_item"] += 1
            flagged["duplicate_option_within_item"].append(rid)

        # 2. Answer-length bias: is the key uniquely the longest option?
        if len(options) >= 3:
            lens = [len(o) for o in options]
            if len(key) == max(lens) and lens.count(max(lens)) == 1:
                counts["_key_is_longest"] += 1
            counts["_length_checked"] += 1

        # 3. Distractor rationales present for every wrong answer
        if wrongs and len(rationales) != len(wrongs):
            counts["rationale_count_mismatch"] += 1
            flagged["rationale_count_mismatch"].append((rid, len(wrongs), len(rationales)))
        if not rationales:
            counts["no_distractor_rationales"] += 1
            flagged["no_distractor_rationales"].append(rid)
        if exp and len(exp.strip()) < 80:
            counts["short_explanation"] += 1
            flagged["short_explanation"].append((rid, len(exp.strip())))

        # 4. Explanation should engage the keyed answer
        if key and exp and not (token_set(key) & token_set(exp)):
            counts["explanation_no_key_overlap"] += 1
            flagged["explanation_no_key_overlap"].append(rid)

        # 5. Weak item-writing habits
        if any(re.search(r"\b(all|none) of the above\b", o, re.I) for o in options):
            counts["all_none_of_the_above"] += 1
            flagged["all_none_of_the_above"].append(rid)
        if len(str(r.get("question") or "")) < 40:
            counts["very_short_stem"] += 1
            flagged["very_short_stem"].append(rid)
        if any(len(o) > 400 for o in options):
            counts["overlong_option"] += 1
            flagged["overlong_option"].append(rid)
        if not str(r.get("topic") or "").strip():
            counts["missing_topic"] += 1
            flagged["missing_topic"].append(rid)

    # 6. Duplicates
    seen_norm: dict[str, int] = {}
    for r in rows:
        h = norm(r["question"])
        if h in seen_norm:
            counts["exact_duplicate"] += 1
            flagged["exact_duplicate"].append((seen_norm[h], r["id"]))
        else:
            seen_norm[h] = r["id"]

    # 7. Near-duplicates (token Jaccard), bucketed by leading token overlap for speed
    buckets: dict[frozenset, list[dict]] = collections.defaultdict(list)
    near = []
    for r in rows:
        ts = token_set(r["question"])
        if len(ts) < 6:
            continue
        picked = False
        for probe in sorted(ts, key=len, reverse=True)[:4]:
            for cand in buckets.get(frozenset([probe]), [])[:400]:
                if jaccard(ts, cand["_ts"]) >= NEAR_DUP_THRESHOLD:
                    near.append((cand["id"], r["id"], round(jaccard(ts, cand["_ts"]), 3)))
                    counts["near_duplicate"] += 1
                    picked = True
                    break
            if picked:
                break
        if not picked:
            r["_ts"] = ts
            for probe in sorted(ts, key=len, reverse=True)[:4]:
                buckets[frozenset([probe])].append(r)
    flagged["near_duplicate"] = near

    counts["_total"] = len(rows)
    return dict(counts), flagged


def coverage(rows: list[dict], db_path: str) -> dict:
    by_domain = collections.Counter(r.get("fcle_domain") for r in rows)
    by_diff = collections.Counter(str(r.get("difficulty")) for r in rows)
    by_topic = collections.Counter(str(r.get("topic")) for r in rows)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        benches = [dict(r) for r in conn.execute(
            "SELECT * FROM benchmarks").fetchall()]
    except Exception as exc:  # pragma: no cover - defensive
        print(f"WARN: benchmarks coverage unavailable: {exc}", file=sys.stderr)
        benches = []
    finally:
        conn.close()
    return {
        "by_domain": {DOMAIN_NAMES.get(k, str(k)): v for k, v in sorted(by_domain.items(), key=lambda x: str(x[0]))},
        "by_difficulty": dict(by_diff),
        "distinct_topics": len(by_topic),
        "thin_topics_under_8": sorted([(t, n) for t, n in by_topic.items() if n < 8], key=lambda x: x[1]),
        "benchmark_rows": len(benches),
        "with_stimulus": sum(1 for r in rows if str(r.get("stimulus") or "").strip()),
    }


def select_sample(rows: list[dict], n: int, seed: int) -> list[int]:
    """Stratified by domain x difficulty, proportional, deterministic."""
    rng = random.Random(seed)
    strata: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in rows:
        strata[(r.get("fcle_domain"), str(r.get("difficulty")))].append(r)
    total = len(rows)
    picked: list[int] = []
    for key, items in sorted(strata.items(), key=lambda x: str(x[0])):
        want = max(1, round(n * len(items) / total))
        rng.shuffle(items)
        picked.extend(r["id"] for r in items[:want])
    rng.shuffle(picked)
    return picked[:n] if len(picked) > n else picked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--sample", type=int, default=100)
    ap.add_argument("--seed", type=int, default=20260915)
    args = ap.parse_args()

    if not os.path.exists(args.db):
        print(f"ERROR: bank not found: {args.db}", file=sys.stderr)
        return 1
    os.makedirs(args.out, exist_ok=True)

    rows = load(args.db)
    counts, flagged = run_checks(rows)
    cov = coverage(rows, args.db)
    sample_ids = select_sample(rows, args.sample, args.seed)

    len_pct = 100 * counts.get("_key_is_longest", 0) / max(counts.get("_length_checked", 0), 1)
    report = {
        "generated": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "bank": args.db,
        "total_items": len(rows),
        "counts": {k: v for k, v in counts.items() if not k.startswith("_")},
        "key_is_longest_pct": round(len_pct, 1),
        "coverage": cov,
        "flagged": {k: v[:200] for k, v in flagged.items() if v},
        "sample": {"n": len(sample_ids), "seed": args.seed, "ids": sample_ids},
    }
    with open(os.path.join(args.out, "qc_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    lines = [
        "# FCLE OER — Phase A automated QC",
        "",
        f"- Generated: {report['generated']}",
        f"- Bank: `{args.db}`",
        f"- Items: **{len(rows)}**",
        f"- Answer-length bias (key uniquely longest): **{len_pct:.1f}%** "
        f"({counts.get('_key_is_longest', 0)}/{counts.get('_length_checked', 0)}) — target <40%",
        "",
        "## Findings",
        "",
        "| Check | Count |",
        "|---|---|",
    ]
    for k, v in sorted(report["counts"].items(), key=lambda x: -x[1]):
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Coverage", "",
              f"- Domains: {json.dumps(cov['by_domain'])}",
              f"- Difficulty: {json.dumps(cov['by_difficulty'])}",
              f"- Distinct topics: {cov['distinct_topics']} (benchmark rows: {cov['benchmark_rows']})",
              f"- Items with stimulus: {cov['with_stimulus']}",
              f"- Thin topics (<8 items): {len(cov['thin_topics_under_8'])}", ""]
    for t, c in cov["thin_topics_under_8"][:15]:
        lines.append(f"  - {t}: {c}")
    lines += ["", f"## Human-validation sample: {len(sample_ids)} items (seed {args.seed})",
              "", "IDs:", ", ".join(str(i) for i in sample_ids), ""]
    with open(os.path.join(args.out, "qc_summary.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print(f"items={len(rows)} sample={len(sample_ids)} length_bias={len_pct:.1f}%")
    for k, v in sorted(report["counts"].items(), key=lambda x: -x[1]):
        if v:
            print(f"  {k}: {v}")
    print(f"wrote {args.out}/qc_report.json + qc_summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
