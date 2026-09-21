#!/usr/bin/env python3
"""
Detect questions where wrong_explanations are mismatched (written for a different question).

Heuristic: For each question, extract significant keywords from the question text,
correct answer, and wrong answers. Then check if those keywords appear in the
wrong explanations. If ALL 3 explanations have zero keyword overlap with the
question, it's likely a mismatch.

Also flags questions where explanations reference topics completely absent from
the question/answer set.
"""

import sqlite3
import json
import re
import string
from collections import Counter

DB_PATH = "data/fcle.db"

# Common stop words to ignore
STOP_WORDS = {
    'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
    'should', 'may', 'might', 'shall', 'can', 'to', 'of', 'in', 'for',
    'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through', 'during',
    'before', 'after', 'above', 'below', 'between', 'out', 'off', 'over',
    'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when',
    'where', 'why', 'how', 'all', 'each', 'every', 'both', 'few', 'more',
    'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own',
    'same', 'so', 'than', 'too', 'very', 'just', 'because', 'but', 'and',
    'or', 'if', 'while', 'about', 'up', 'down', 'this', 'that', 'these',
    'those', 'what', 'which', 'who', 'whom', 'whose', 'it', 'its',
    'they', 'them', 'their', 'we', 'us', 'our', 'you', 'your', 'he',
    'him', 'his', 'she', 'her', 'i', 'me', 'my',
    # Additional generic words
    'also', 'example', 'however', 'therefore', 'thus', 'since',
    'another', 'must', 'does', 'made', 'make', 'making',
    'statement', 'question', 'answer', 'option', 'claim', 'implies',
    'describes', 'refers', 'means', 'suggests',
}


def extract_keywords(text):
    """Extract meaningful keywords from text."""
    if not text:
        return set()
    # Lowercase, remove punctuation
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    words = text.split()
    # Filter stop words and short words, keep meaningful terms
    keywords = set()
    for w in words:
        if len(w) >= 3 and w not in STOP_WORDS:
            keywords.add(w)
    return keywords


def get_bigrams(text):
    """Extract 2-word phrases for more precise matching."""
    if not text:
        return set()
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    words = [w for w in text.split() if len(w) >= 3 and w not in STOP_WORDS]
    bigrams = set()
    for i in range(len(words) - 1):
        bigrams.add(f"{words[i]} {words[i+1]}")
    return bigrams


def check_question(qid, question, correct_answer, wrong_answers, wrong_explanations):
    """
    Check if wrong explanations are mismatched.
    Returns (is_mismatch, score, details)
    """
    # Build keyword set from question + correct answer + wrong answers
    q_keywords = extract_keywords(question)
    ca_keywords = extract_keywords(correct_answer)

    wa_keywords = set()
    for wa in wrong_answers:
        wa_keywords.update(extract_keywords(wa))

    # Combined reference keywords
    ref_keywords = q_keywords | ca_keywords | wa_keywords

    # Build bigrams from question for more precise matching
    q_bigrams = get_bigrams(question) | get_bigrams(correct_answer)

    if not wrong_explanations:
        return True, 0, "NO EXPLANATIONS"

    # Check each explanation
    scores = []
    details = []
    for i, expl in enumerate(wrong_explanations):
        if not expl:
            scores.append(0)
            details.append(f"Expl[{i}]: EMPTY")
            continue

        expl_keywords = extract_keywords(expl)
        expl_bigrams = get_bigrams(expl)

        # Keyword overlap
        keyword_overlap = ref_keywords & expl_keywords
        keyword_count = len(keyword_overlap)

        # Bigram overlap (stronger signal)
        bigram_overlap = q_bigrams & expl_bigrams
        bigram_count = len(bigram_overlap)

        # Check if correct answer text appears anywhere in explanation
        ca_words = set(correct_answer.lower().split())
        ca_in_expl = any(w in expl.lower() for w in ca_words if len(w) >= 3 and w not in STOP_WORDS)

        # Check if any wrong answer key terms appear
        wa_match = False
        for wa in wrong_answers:
            wa_key = extract_keywords(wa)
            if wa_key & expl_keywords:
                wa_match = True
                break

        score = keyword_count + (bigram_count * 3) + (5 if ca_in_expl else 0) + (3 if wa_match else 0)
        scores.append(score)

        top_overlap = sorted(keyword_overlap)[:5] if keyword_overlap else []
        detail = f"Expl[{i}]: score={score} (kw={keyword_count}, bi={bigram_count}, ca={'Y' if ca_in_expl else 'N'}, wa={'Y' if wa_match else 'N'})"
        if top_overlap:
            detail += f" overlap={top_overlap}"
        details.append(detail)

    # A question is flagged if ALL 3 explanations score below threshold
    min_score = min(scores)
    avg_score = sum(scores) / len(scores)

    # Threshold: if average score < 3, very likely mismatched
    # If min score = 0 for all, almost certainly mismatched
    is_mismatch = avg_score < 3

    combined_detail = " | ".join(details)

    return is_mismatch, avg_score, combined_detail


def main():
    db = sqlite3.connect(DB_PATH)
    cur = db.cursor()

    rows = cur.execute("""
        SELECT id, question, correct_answer, wrong_answers, wrong_explanations, fcle_domain
        FROM questions
        ORDER BY fcle_domain, id
    """).fetchall()

    print(f"Scanning {len(rows)} questions for mismatched explanations...\n")

    flagged = []
    clean = 0

    for r in rows:
        qid, question, ca, wa_raw, we_raw, domain = r
        wrong_answers = json.loads(wa_raw) if wa_raw else []
        wrong_explanations = json.loads(we_raw) if we_raw else []

        is_mismatch, score, details = check_question(
            qid, question, ca, wrong_answers, wrong_explanations
        )

        if is_mismatch:
            flagged.append((qid, domain, score, question[:80], details))
        else:
            clean += 1

    print(f"Results: {clean} clean, {len(flagged)} flagged as mismatched\n")

    if flagged:
        print("=" * 80)
        print("FLAGGED QUESTIONS (likely mismatched explanations)")
        print("=" * 80)

        by_domain = {}
        for qid, domain, score, q_text, details in flagged:
            if domain not in by_domain:
                by_domain[domain] = []
            by_domain[domain].append((qid, score, q_text, details))

        for domain in sorted(by_domain.keys()):
            items = by_domain[domain]
            print(f"\n--- Domain {domain} ({len(items)} flagged) ---")
            for qid, score, q_text, details in items:
                print(f"\n  ID {qid} (avg_score={score:.1f})")
                print(f"  Q: {q_text}...")
                print(f"  {details}")

        # Output simple list of IDs for easy processing
        print("\n" + "=" * 80)
        print("ALL FLAGGED IDs (for fix script):")
        print("=" * 80)
        for qid, domain, score, q_text, details in flagged:
            print(f"  D{domain} ID {qid}")

        print(f"\nTotal flagged: {len(flagged)} questions out of {len(rows)} ({100*len(flagged)/len(rows):.1f}%)")

    db.close()


if __name__ == "__main__":
    main()
