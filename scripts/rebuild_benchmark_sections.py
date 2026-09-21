#!/usr/bin/env python3
"""Rebuild benchmark -> section links on evidence instead of a migration heuristic.

The problem
-----------
`benchmark_sections` came out of scripts/migrate_civics_to_fcle.py, whose relevance
score plainly misfired: SS.7.CG.1.8 (the Preamble) resolves to "17.4. Approaches to
Foreign Policy", and that same section is the top link for a dozen unrelated codes.
66 of the primary links share no significant word with their own benchmark, so the
"read this first" pointer was mostly wrong.

Why this design
---------------
Retrieval is deterministic and judgement is a model's, because that is the split that
works: models are unreliable at ranking 82 documents but good at reading two passages
and saying whether they are about the same thing. So:

  stage 1  BM25 over the section BODY text (2.2M chars), not the titles. The titles
           were the reason a foreign-policy chapter won for the Preamble; the bodies
           say what a section is actually about. Deterministic, no model.
  stage 2  drafter (Qwen3.5-9B) picks the best 1-3 from the top candidates, seeing the
           benchmark's official text and the most relevant excerpt of each candidate.
  stage 3  reviewer (Gemma 4 26B) - a different family - sees the same evidence plus
           the drafter's pick and must CONFIRM or name a better candidate.
  stage 4  a deterministic gate: the write must be a candidate that exists in
           `content`. A code with no accepted pick gets NO link, because a pointer
           that sends a student to the wrong chapter is worse than no pointer.

Nothing is written unless --apply is passed, and a backup is taken first.

Usage:
    python3 scripts/rebuild_benchmark_sections.py --limit 4
    python3 scripts/rebuild_benchmark_sections.py --apply
"""
import argparse
import collections
import csv
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from coach import rules as coach_rules  # noqa: E402  one source of truth for exclusions

DB = os.path.join(ROOT, "data", "tupelo.db")
OUT = os.path.join(ROOT, "data", "benchmark-sections.csv")
DISAGREE = os.path.join(ROOT, "data", "benchmark-sections-disagreements.md")

DRAFTER = ("http://127.0.0.1:8085/v1/chat/completions", "Qwen3.5-9B")
REVIEWER = ("http://127.0.0.1:8083/v1/chat/completions", "gemma-4-26B-vision")

TOP_N = 10          # candidates handed to the models
MAX_SECTION_CHARS = 60000   # a bigger row is back matter, not a section
EXCERPT = 700       # chars of evidence per candidate
K1, B = 1.2, 0.75   # BM25

STOP = set("""the and for are but not you all any can had her was one our out day get has him his how
man new now old see two way who boy did its let put say she too use that with this from they have
will your what when make like time just know take people into year good some could them than then
look only come over think also back after work first well even want because these give most shall
upon about which their there been other more such must does between both during under while where
its it's such being each same than those through""".split())


# --------------------------------------------------------------------------
# stage 1: deterministic retrieval over the section bodies
# --------------------------------------------------------------------------
def clean(value):
    """Strip the PDF-harvest artifacts (bullet glyphs, NBSPs) and collapse space."""
    text = str(value or "")
    text = text.replace("\uf0b7", " ").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def tokens(text):
    return [w for w in re.findall(r"[a-z]{3,}", str(text or "").lower()) if w not in STOP]


def build_index(sections):
    """BM25 over the section bodies."""
    docs = {s["id"]: tokens(s["text"]) for s in sections}
    lengths = {i: len(t) for i, t in docs.items()}
    avgdl = (sum(lengths.values()) / len(lengths)) if lengths else 1.0
    tf = {}
    df = collections.Counter()
    for sid, toks in docs.items():
        counts = collections.Counter(toks)
        tf[sid] = counts
        for term in counts:
            df[term] += 1
    n = len(docs) or 1
    idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
    return {"tf": tf, "idf": idf, "lengths": lengths, "avgdl": avgdl, "n": n}


def bm25(index, query_terms):
    scores = {}
    for sid, counts in index["tf"].items():
        dl = index["lengths"][sid] or 1
        total = 0.0
        for term in set(query_terms):
            f = counts.get(term)
            if not f:
                continue
            denom = f + K1 * (1 - B + B * dl / index["avgdl"])
            total += index["idf"].get(term, 0.0) * (f * (K1 + 1)) / denom
        scores[sid] = total
    return scores


OBJECTIVES_MARKER = "learning objectives"
OBJECTIVES_CHARS = 800
OPENING_CHARS = 500


def learning_objectives(text):
    """A section's own statement of what it teaches.

    76 of the 81 usable sections open with "By the end of this section, you will be
    able to: ...". That IS the evidence for whether a section teaches a standard, far
    better than any keyword score or a sampled passage. The first pass asked the
    reviewer to judge teaching quality from a 700-character excerpt alone, and it
    disputed most picks for lack of evidence, which produced no link at all.

    A plain marker search, not a regex: an earlier version tried to stop at
    "Introduction" and silently returned nothing for 76 of 81 sections.
    """
    body = clean(text)
    idx = body.lower().find(OBJECTIVES_MARKER)
    if idx != -1:
        start = idx + len(OBJECTIVES_MARKER)
        return body[start:start + OBJECTIVES_CHARS].strip()
    # No stated objectives (5 sections): the opening is the next best statement of scope.
    return body[:OPENING_CHARS].strip()


def best_excerpt(text, query_terms, width=EXCERPT):
    """The densest window of the section for this query - the evidence a model needs.

    Sections run to tens of thousands of characters; handing the model all of it would
    bury the relevant passage. Find the window with the most distinct query terms.
    """
    body = clean(text)
    if len(body) <= width:
        return body
    terms = set(query_terms)
    best, best_score, best_at = body[:width], -1, 0
    step = max(1, width // 2)
    for start in range(0, len(body) - width + 1, step):
        window = body[start:start + width]
        score = len(terms & set(tokens(window)))
        if score > best_score:
            best, best_score, best_at = window, score, start
    if best_at:
        cut = best.find(" ")
        if 0 < cut < 120:
            best = best[cut + 1:]
    return best.strip()


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------
def extract_json(text):
    if not text:
        return None
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    for candidate in (text,):
        try:
            return json.loads(candidate)
        except Exception:
            pass
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    if m:
        blob = re.sub(r",\s*([\]}])", r"\1", m.group(0))
        try:
            return json.loads(blob)
        except Exception:
            return None
    return None


def ask(endpoint, system, user, retries=3, max_tokens=1800):
    payload = {"model": endpoint[1],
               "messages": [{"role": "system", "content": system},
                            {"role": "user", "content": user}],
               "temperature": 0.0, "max_tokens": max_tokens, "stream": False}
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(endpoint[0], data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read().decode())["choices"][0]["message"]["content"]
        except Exception as exc:            # noqa: BLE001 - report and retry
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{endpoint[1]} failed: {last}")


DRAFT_SYS = ("You match Florida civics standards to textbook sections. "
             "Return ONLY JSON. No prose, no markdown fences.")
DRAFT_TMPL = """Which textbook section best teaches this Florida civics standard?

STANDARD {code}
Official text: {official}

Candidate sections, each with the passage most related to the standard:
{candidates}

Pick the 1 to 3 sections that genuinely TEACH this standard - where a student who
studied that section would know it. Judge by the section's OWN STATED OBJECTIVES
first and the passage second, not by whether the words look similar.

Return ONLY JSON:
{{"picks": [{{"section_id": <id>, "why": "<15 words max>"}}]}}
Put the best first. If NO candidate teaches it, return {{"picks": []}}."""

REVIEW_SYS = ("You audit civics standard-to-textbook mappings. Be skeptical. "
              "Return ONLY JSON. No prose, no markdown fences.")
REVIEW_TMPL = """A reviewer chose a textbook section for this Florida civics standard.
Check the choice against the passage.

STANDARD {code}
Official text: {official}

CHOSEN: section {chosen_id}
Passage: {chosen_excerpt}

All candidates that were available:
{others}

Is this section a sound place for a student to study this standard? Weigh the
section's own stated objectives most heavily - if its objectives match the standard,
that is teaching, even when the sampled passage happens to be about something else.

Return ONLY JSON:
{{"verdict": "CONFIRM" or "DISPUTE",
  "better_section_id": <id from the list>, "reason": "<15 words max>"}}

If you DISPUTE you MUST name the best alternative from the list. Only use null when
NO candidate is a sound place to study it, and say why."""


def candidate_block(entries):
    lines = []
    for rank, (sid, score, title, excerpt, objectives) in enumerate(entries, 1):
        lines.append(f"{rank}. section_id={sid}  \"{title}\"  (retrieval score {score:.1f})\n"
                     f"   ITS STATED OBJECTIVES: {objectives or '(none stated)'}\n"
                     f"   PASSAGE: {excerpt}")
    return "\n".join(lines)


REPAIR_TMPL = """Choose using ONLY these exact section ids. No other id is valid.

{codes}

STANDARD {code}
Official text: {official}

Return ONLY JSON: {{"picks": [{{"section_id": <id from the list above>, "why": "<12 words>"}}]}}
If none of them teaches it, return {{"picks": []}}."""


def draft(code, official, entries):
    """Assign sections, then re-ask once for any id that is not a real candidate.

    The drafter returns ids outside the offered list often enough to matter (about a
    third of codes on the first clean run), which is a formatting failure, not a
    judgement failure - it usually meant the right section. Re-asking with nothing but
    the valid ids recovers those instead of discarding a good pick.
    """
    valid = [e[0] for e in entries]
    reply = ask(DRAFTER, DRAFT_SYS, DRAFT_TMPL.format(
        code=code, official=official, candidates=candidate_block(entries)))
    parsed = extract_json(reply)
    picks = []
    if isinstance(parsed, dict):
        for p in parsed.get("picks") or []:
            try:
                picks.append({"section_id": int(p["section_id"]),
                              "why": clean(p.get("why"))[:120]})
            except (KeyError, TypeError, ValueError):
                continue

    if picks and all(p["section_id"] in valid for p in picks):
        return picks
    if not picks:
        return picks

    listed = "\n".join(f"- section_id={sid}  \"{title}\"" for sid, _s, title, _e, _o in entries)
    try:
        reply2 = ask(DRAFTER, DRAFT_SYS, REPAIR_TMPL.format(
            codes=listed, code=code, official=official), retries=2, max_tokens=900)
    except Exception:                                   # noqa: BLE001
        return picks
    fixed = extract_json(reply2)
    out = []
    if isinstance(fixed, dict):
        for p in fixed.get("picks") or []:
            try:
                sid = int(p["section_id"])
            except (KeyError, TypeError, ValueError):
                continue
            if sid in valid:
                out.append({"section_id": sid, "why": clean(p.get("why"))[:120]})
    for p in picks:                      # keep any original that was already valid
        if p["section_id"] in valid and all(o["section_id"] != p["section_id"] for o in out):
            out.append(p)
    return out


def review(code, official, chosen, entries):
    others = "\n".join(f"   section_id={sid}  \"{title}\"" for sid, _s, title, _e, _o in entries)
    reply = ask(REVIEWER, REVIEW_SYS, REVIEW_TMPL.format(
        code=code, official=official, chosen_id=chosen["section_id"],
        chosen_excerpt=(f"its objectives: {chosen.get('objectives') or '(none)'}\n"
                        f"passage: {chosen['excerpt']}"), others=others))
    parsed = extract_json(reply)
    if not isinstance(parsed, dict):
        return {}
    verdict = str(parsed.get("verdict", "")).strip().upper()
    try:
        better = int(parsed["better_section_id"]) if parsed.get("better_section_id") else None
    except (TypeError, ValueError):
        better = None
    return {"verdict": "CONFIRM" if verdict.startswith("CONFIRM") else "DISPUTE",
            "better": better, "reason": clean(parsed.get("reason"))[:120]}


def decide(picks, entries, review_result, valid_ids):
    """Fold draft + review + the deterministic gate into one accepted link."""
    allowed = {sid for sid, _s, _t, _e, _o in entries}
    if not picks:
        return None, "no-pick", "drafter found nothing"
    chosen = picks[0]
    if chosen["section_id"] not in allowed or chosen["section_id"] not in valid_ids:
        return None, "invalid-id", "pick is not a candidate"
    if review_result.get("verdict") == "DISPUTE":
        better = review_result.get("better")
        if better in allowed and better in valid_ids and better != chosen["section_id"]:
            return better, "reviewer-accepted", "reviewer named a better section"
        if better is None:
            return None, "reviewer-disputed-none-better", "reviewer rejected the pick"
        return chosen["section_id"], "drafter-kept-reviewer-disputed", \
            "reviewer alternative unusable"
    if not review_result:
        return chosen["section_id"], "drafter-only", "reviewer silent"
    return chosen["section_id"], "draft+review-confirmed", "CONFIRM"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--codes", default="",
                    help="comma-separated codes to process, for smoke testing")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    sections = [dict(r) for r in con.execute(
        "SELECT id, section_title, text, char_count, fcle_domain FROM content")]
    # Section 77 is 367,972 characters of 17.4 plus the book's appendices, references
    # and index. It matches 27 of 36 standards and poisoned every ranking; a section
    # that size is not a teachable target, so it is not a candidate.
    over = [s for s in sections if (s["char_count"] or 0) > MAX_SECTION_CHARS]
    if over:
        print("[exclude] oversized rows never offered as readings: %s"
              % [(s["id"], s["char_count"]) for s in over], flush=True)
    sections = [s for s in sections if (s["char_count"] or 0) <= MAX_SECTION_CHARS]
    apparatus = [s for s in sections
                 if str(s["section_title"] or "").strip().rstrip("*").strip().lower()
                 in coach_rules.NON_SECTION_TITLES]
    if apparatus:
        print("[exclude] reference apparatus is not reading: %s"
              % [(s["id"], s["section_title"]) for s in apparatus], flush=True)
    sections = [s for s in sections if s not in apparatus]
    benchmarks = {r["code"]: dict(r) for r in con.execute(
        "SELECT code, standard, description, clarifications FROM benchmarks")}
    existing = collections.defaultdict(list)
    for r in con.execute("SELECT benchmark_code, section_id, relevance_score, is_primary "
                         "FROM benchmark_sections"):
        existing[r["benchmark_code"]].append(dict(r))

    if not sections or not benchmarks:
        raise SystemExit("content or benchmarks table is empty - nothing to work from")

    index = build_index(sections)
    by_id = {s["id"]: s for s in sections}
    valid_ids = set(by_id)
    codes = sorted(benchmarks)
    if args.codes:
        wanted = [c.strip() for c in args.codes.split(",") if c.strip()]
        missing = [c for c in wanted if c not in benchmarks]
        if missing:
            raise SystemExit("not in benchmarks: %s" % ", ".join(missing))
        codes = wanted
    elif args.limit:
        codes = codes[:args.limit]
    print(f"[start] codes={len(codes)} sections={len(sections)} "
          f"existing links={sum(len(v) for v in existing.values())}", flush=True)

    stale = [r["section_id"] for v in existing.values() for r in v if r["section_id"] not in valid_ids]
    if stale:
        print(f"[warn] {len(stale)} existing links point at a section that does not exist", flush=True)

    def work(code):
        info = benchmarks[code]
        # description + clarifications only. The `standard` field is boilerplate shared
        # by every code in the strand ("Demonstrate an understanding of the origins and
        # purposes of government...") and concatenating it drowned the distinctive words:
        # it is what made a foreign-policy chapter win for the Preamble.
        official = clean(" | ".join(x for x in (info.get("description"),
                                                info.get("clarifications")) if x))
        q = tokens(official)
        scores = bm25(index, q)
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:TOP_N]
        entries = [(sid, sc, clean(by_id[sid]["section_title"]),
                    best_excerpt(by_id[sid]["text"], q),
                    learning_objectives(by_id[sid]["text"])) for sid, sc in ranked]
        try:
            picks = draft(code, official, entries)
        except Exception as exc:                    # noqa: BLE001
            print(f"  [draft] {code} failed: {exc}", flush=True)
            picks = []
        chosen = None
        if picks:
            chosen = dict(picks[0])
            match = next((e for e in entries if e[0] == chosen["section_id"]), None)
            chosen["excerpt"] = match[3] if match else ""
            chosen["objectives"] = match[4] if match else ""
        result = {}
        if chosen:
            try:
                result = review(code, official, chosen, entries)
            except Exception as exc:                # noqa: BLE001
                print(f"  [review] {code} failed: {exc}", flush=True)
                result = {}
        accepted, source, note = decide(picks, entries, result, valid_ids)
        return {"code": code, "accepted": accepted, "source": source, "note": note,
                "draft": picks, "review": result,
                "entries": [(sid, round(sc, 2), t) for sid, sc, t, _e, _o in entries]}

    out = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, res in enumerate(pool.map(work, codes), 1):
            out.append(res)
            got = res["accepted"]
            print(f"  [{i}/{len(codes)}] {res['code']:<14} -> "
                  f"{('section ' + str(got)) if got else '(no link)':<14} {res['source']}",
                  flush=True)

    with open(OUT, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["code", "accepted_section_id", "accepted_title", "source", "note",
                    "drafted_ids", "review_verdict", "review_reason"])
        for r in out:
            title = clean(by_id[r["accepted"]]["section_title"]) if r["accepted"] else ""
            w.writerow([r["code"], r["accepted"] or "", title, r["source"], r["note"],
                        " ".join(str(p["section_id"]) for p in r["draft"]),
                        r["review"].get("verdict", ""), r["review"].get("reason", "")])

    stats = collections.Counter(r["source"] for r in out)
    print()
    print("[pass] accepted=%d/%d" % (sum(1 for r in out if r["accepted"]), len(out)), flush=True)
    for k in sorted(stats, key=lambda k: -stats[k]):
        print(f"        {k}: {stats[k]}", flush=True)

    unresolved = [r for r in out if not r["accepted"]]
    with open(DISAGREE, "w") as fh:
        fh.write("# benchmark -> section rebuild: codes left with NO link\n\n")
        fh.write(f"{len(unresolved)} of {len(out)} codes. No link is written for these: a\n")
        fh.write("pointer to the wrong chapter is worse than no pointer.\n\n")
        for r in unresolved:
            fh.write(f"## {r['code']} - {r['source']}\n\n")
            fh.write(f"- {r['note']}\n")
            fh.write(f"- drafter picks: {r['draft']}\n")
            fh.write(f"- reviewer: {r['review']}\n")
            fh.write(f"- top retrieval candidates: {r['entries'][:5]}\n\n")

    print(f"[out] {OUT}", flush=True)
    print(f"[out] {DISAGREE}", flush=True)

    if not args.apply:
        print("\n[dry] not written to the database. Re-run with --apply.", flush=True)
        con.close()
        return

    accepted = [r for r in out if r["accepted"]]
    if not accepted:
        print("[apply] nothing accepted; refusing to write", flush=True)
        con.close()
        return
    backup = "%s.pre-sections-%s" % (DB, time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(DB, backup)
    print(f"\nbackup written: {backup}", flush=True)

    cur = con.cursor()
    before = con.total_changes
    for r in accepted:
        # replace this code's links outright, so stale misfires cannot linger
        cur.execute("DELETE FROM benchmark_sections WHERE benchmark_code = ?", (r["code"],))
        cur.execute("INSERT INTO benchmark_sections "
                    "(benchmark_code, section_id, relevance_score, is_primary) "
                    "VALUES (?,?,?,?)", (r["code"], r["accepted"], 100.0, 1))
        for sid, score, _t in r["entries"]:
            if sid == r["accepted"]:
                continue
            cur.execute("INSERT INTO benchmark_sections "
                        "(benchmark_code, section_id, relevance_score, is_primary) "
                        "VALUES (?,?,?,?)", (r["code"], sid, score, 0))
            if sum(1 for e in r["entries"] if e[0] != r["accepted"]) > 2:
                break
    con.commit()
    print("rows written: %d" % (con.total_changes - before), flush=True)
    print("codes now with a primary link: %d" % con.execute(
        "SELECT COUNT(DISTINCT benchmark_code) FROM benchmark_sections "
        "WHERE is_primary = 1").fetchone()[0], flush=True)
    print("integrity_check: %s" % con.execute("PRAGMA integrity_check").fetchone()[0], flush=True)
    con.close()


if __name__ == "__main__":
    main()
