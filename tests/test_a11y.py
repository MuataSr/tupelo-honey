"""Accessibility regression gate: no route may gain WCAG A/AA findings.

Opt-in because it needs Chrome and takes a couple of minutes: RUN_A11Y=1.

    RUN_A11Y=1 python3 -m unittest tests.test_a11y -v

The baseline in a11y_baseline.json is the frozen debt. When a route gains nodes
the gate fails and names the route plus the rule. Fix the regression, or (after a
deliberate design decision) re-record with:

    python3 <gate> . --signup --write-baseline

The auditor lives outside this repo on purpose: one gate, every Mu2 app.
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE_CANDIDATES = [
    os.environ.get("A11Y_GATE"),
    os.path.expanduser("~/a11y-tools/dogfood_gate.py"),
    os.path.expanduser("~/.hermes/workspace/oer-title-ii-auditor/dogfood_gate.py"),
]


@unittest.skipUnless(os.environ.get("RUN_A11Y"), "set RUN_A11Y=1 to run the browser audit")
class TestAccessibilityGate(unittest.TestCase):
    def test_no_wcag_regressions(self):
        gate = next((g for g in GATE_CANDIDATES if g and os.path.exists(g)), None)
        self.assertIsNotNone(gate, f"gate script not found in {GATE_CANDIDATES}")
        py = os.environ.get("A11Y_PYTHON", sys.executable)
        r = subprocess.run([py, gate, ROOT, "--signup"], capture_output=True, text=True, timeout=900)
        sys.stderr.write(r.stdout[-4000:])
        self.assertEqual(r.returncode, 0, "WCAG regression — see the route/rule table above")


if __name__ == "__main__":
    unittest.main()
