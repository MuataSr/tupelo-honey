"""Accessibility regression gate: no route may gain WCAG A/AA findings.

Opt-in because it needs Chrome and takes a couple of minutes: RUN_A11Y=1.

    RUN_A11Y=1 python -m unittest tests.test_a11y -v

The baseline in a11y_baseline.json is the frozen debt. When a route gains nodes
the gate fails and names the route plus the rule. Fix the regression, or (after a
deliberate design decision) re-record with:

    python ~/.hermes/workspace/oer-title-ii-auditor/dogfood_gate.py . --signup --write-baseline

The auditor lives outside this repo on purpose: one gate, every Mu2 app.
"""

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GATE = os.environ.get("A11Y_GATE",
                      os.path.expanduser("~/.hermes/workspace/oer-title-ii-auditor/dogfood_gate.py"))


@unittest.skipUnless(os.environ.get("RUN_A11Y"), "set RUN_A11Y=1 to run the browser audit")
class TestAccessibilityGate(unittest.TestCase):
    def test_no_wcag_regressions(self):
        self.assertTrue(os.path.exists(GATE), f"gate script not found: {GATE}")
        venv = os.environ.get("A11Y_PYTHON", os.path.expanduser("~/.hermes/workspace/oer-title-ii-auditor/venv/bin/python"))
        r = subprocess.run([venv, GATE, ROOT, "--signup"], capture_output=True, text=True, timeout=900)
        sys.stderr.write(r.stdout[-4000:])
        self.assertEqual(r.returncode, 0, "WCAG regression — see the route/rule table above")


if __name__ == "__main__":
    unittest.main()