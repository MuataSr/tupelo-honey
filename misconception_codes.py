#!/usr/bin/env python3
"""The real FCLE benchmark codes, and a refusal to emit the old placeholder.

Why this module exists
----------------------
The misconception generators (D1, D3, D4) used to stamp `benchmark_code = "FCLE"`
on every row they produced. "FCLE" is the exam's name, not a standard: it is a
placeholder that no answer can ever carry, so the Study Coach's tier-1 match on
benchmark_code could never fire and every one of those ~350 rows silently fell
back to domain-level matching. That is how a generic domain misconception ended
up quoted against a very specific student error.

Re-keying those rows without fixing the generators just refills the table with
placeholders on the next run. So the generators import this module, put the real
codes in their prompts, and call `validate()` on every item they emit - which
raises rather than writing a placeholder.
"""
import os
import re
import sqlite3

PLACEHOLDER = "FCLE"

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "tupelo.db")


def clean(value):
    """Strip the PDF-harvest artifacts the content rows carry."""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\uf0b7", " ").replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def all_codes(db_path=None):
    """Every real code in the benchmarks table, mapped to its description."""
    con = sqlite3.connect(db_path or DEFAULT_DB)
    con.row_factory = sqlite3.Row
    try:
        return {r["code"]: clean(r["description"] or r["clarifications"])
                for r in con.execute("SELECT code, description, clarifications FROM benchmarks")}
    finally:
        con.close()


def domain_codes(domain, db_path=None):
    """The codes that actually serve one domain, per the topic->benchmark map.

    These are the codes a question in this domain can carry, so they are the only
    ones a misconception in this domain can ever match against at tier 1.
    """
    con = sqlite3.connect(db_path or DEFAULT_DB)
    con.row_factory = sqlite3.Row
    try:
        return sorted({r["primary_code"] for r in con.execute(
            "SELECT DISTINCT primary_code FROM topic_benchmarks WHERE fcle_domain = ?",
            (int(domain),))})
    finally:
        con.close()


def prompt_block(domain, db_path=None):
    """The code list to paste into a generator prompt, one line per standard."""
    codes = all_codes(db_path)
    lines = []
    for code in domain_codes(domain, db_path):
        lines.append("- %s: %s" % (code, codes.get(code, "")[:200]))
    if not lines:
        raise ValueError(
            "no benchmark codes are mapped to domain %r - refusing to build a prompt "
            "that would force a placeholder" % (domain,))
    return "\n".join(lines)


def validate(code, domain=None, db_path=None):
    """Return the code, or raise. Never returns the placeholder."""
    code = (code or "").strip()
    if not code:
        raise ValueError("benchmark_code is empty")
    if code.upper() == PLACEHOLDER:
        raise ValueError(
            'benchmark_code is the placeholder "FCLE". Supply a real SS.7.CG code - '
            "run scripts/rekey_misconceptions.py against the back catalogue if these "
            "rows are already written.")
    known = all_codes(db_path)
    if code not in known:
        raise ValueError("benchmark_code %r is not one of the %d real standards"
                         % (code, len(known)))
    if domain is not None:
        allowed = domain_codes(domain, db_path)
        if allowed and code not in allowed:
            raise ValueError(
                "benchmark_code %r does not serve domain %s (valid there: %s). A code "
                "outside the domain can never match an answer in it at tier 1."
                % (code, domain, ", ".join(allowed)))
    return code


def self_test():
    codes = all_codes()
    assert len(codes) >= 36, "expected the full standards set, got %d" % len(codes)
    for domain in (1, 2, 3, 4):
        block = prompt_block(domain)
        assert "SS.7.CG." in block, "domain %d prompt has no codes" % domain
        assert PLACEHOLDER not in block.split(":", 1)[0]
        for code in domain_codes(domain):
            assert validate(code, domain) == code
    for bad in (PLACEHOLDER, "", None, "SS.7.CG.9.9", "NOPE"):
        try:
            validate(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("validate() accepted %r" % (bad,))
    # a real code that belongs to another domain must be refused for this one
    outsider = sorted(set(all_codes()) - set(domain_codes(1)))[0]
    try:
        validate(outsider, domain=1)
    except ValueError:
        pass
    else:
        raise AssertionError("validate() accepted out-of-domain code %r" % outsider)
    print("self-test ok: %d codes, domains %s"
          % (len(codes), {d: len(domain_codes(d)) for d in (1, 2, 3, 4)}))


if __name__ == "__main__":
    self_test()
