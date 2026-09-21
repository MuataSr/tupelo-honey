"""Prove P0.2a: the generators now carry real codes and refuse the placeholder."""
import os
import sys

os.environ.setdefault("ZAI_API_KEY", "dummy-for-import-test")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))

import misconception_codes as mc  # noqa: E402

print("=== the validator refuses the placeholder ===")
for bad, kw in [("FCLE", {}), ("FCLE", {"domain": 4}), ("SS.7.CG.9.9", {}), ("", {})]:
    try:
        mc.validate(bad, **kw)
        print("  FAIL accepted %r" % bad)
    except ValueError as exc:
        print("  ok refused %-14r -> %s" % (bad, str(exc)[:72]))

print()
print("=== D4 prompt now carries the domain-4 codes ===")
import gen_d4_misconceptions as d4  # noqa: E402
prompt = d4.build_user_prompt(1, ["Mapp v. Ohio", "Miranda warnings"])
codes_in = sorted({t for t in prompt.split() if t.startswith("SS.7.CG.")})
print("  codes present in the prompt:", codes_in)
print("  instructs against FCLE      :", '"FCLE" is NOT a code' in prompt)
print("  example no longer says FCLE :", '"benchmark_code": "SS.7.CG.3.11"' in prompt)
print("  prompt length              :", len(prompt))

print()
print("=== D1 prompt now carries the domain-1 codes ===")
import generate_d1_misconceptions as d1  # noqa: E402
ctx = d1.DOMAIN_CONTEXT
codes_in = sorted({t for t in ctx.split() if t.startswith("SS.7.CG.")})
print("  codes present in DOMAIN_CONTEXT:", codes_in)
print("  no longer says 'always \"FCLE\"':", '(always "FCLE")' not in ctx)

print()
print("=== D3 carries the domain-3 codes ===")
import gen_d3 as d3  # noqa: E402
codes_in = sorted({t for t in d3.SYSTEM.split() if t.startswith("SS.7.CG.")})
print("  codes present in SYSTEM:", codes_in)

print()
print("=== no generator still assigns the literal placeholder ===")
for path in [os.path.join(ROOT, "generate_d1_misconceptions.py"),
             os.path.join(ROOT, "data", "gen_d3.py"),
             os.path.join(ROOT, "data", "gen_d4_misconceptions.py")]:
    body = open(path).read()
    bad = [l for l in body.splitlines()
           if '"FCLE"' in l and "=" in l and not l.strip().startswith(("#", '"', "8."))]
    print("  %-38s %s" % (os.path.basename(path),
                          "CLEAN" if not bad else "STILL STAMPS: %s" % bad))
