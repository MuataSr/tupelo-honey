"""The /signup bot trap must be INVISIBLE to real users, and must still work.

Regression under test: the `.hp-field` hiding rule lived inside signup.html's
`{% if pilot_full %}` branch. That branch only renders when the pilot cohort is
full, so the ordinary signup form rendered the trap VISIBLY as an empty box
labelled "Leave this field blank". app.py silently drops any signup whose
`website` field is filled (`return redirect("/")`), so a student who typed in
the box they could see was thrown back to the landing page with no account and
no message.

Three properties are locked here:
  1. the hiding rule ships from the shared stylesheet, and it actually hides;
  2. no template scopes that rule to one branch (the root cause);
  3. the trap still drops a filled submission and still lets a clean one through.
"""

import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEMPLATES = os.path.join(ROOT, "templates")
CSS = os.path.join(ROOT, "static", "css", "app.css")


def _templates():
    out = {}
    for name in sorted(os.listdir(TEMPLATES)):
        if name.endswith(".html"):
            with open(os.path.join(TEMPLATES, name), encoding="utf-8") as fh:
                out[name] = fh.read()
    return out


class TestHidingRuleLivesInTheStylesheet(unittest.TestCase):
    def test_stylesheet_defines_the_hp_field_rule(self):
        with open(CSS, encoding="utf-8") as fh:
            css = fh.read()
        match = re.search(r"\.hp-field\s*\{([^}]*)\}", css)
        if match is None:
            self.fail(".hp-field must be defined in static/css/app.css")
        body = match.group(1)
        self.assertIn("position: absolute", body)
        self.assertTrue("-9999px" in body or "display: none" in body,
                        "the trap must be moved off-screen or hidden outright")
        self.assertTrue("opacity: 0" in body or "display: none" in body)
        self.assertIn("pointer-events: none", body)

    def test_no_template_scopes_the_hiding_rule_to_a_branch(self):
        """The root cause: the rule was inside {% if pilot_full %}. Never again."""
        for name, txt in _templates().items():
            self.assertNotIn(".hp-field", txt,
                             "%s carries the .hp-field rule; it belongs in app.css" % name)

    def test_stylesheet_url_is_cache_busted(self):
        """A cached app.css would keep showing the box to returning students."""
        with open(os.path.join(TEMPLATES, "base.html"), encoding="utf-8") as fh:
            base = fh.read()
        self.assertRegex(base, r"css/app\.css'\)\s*\}\}\?v=\d+",
                         "app.css must keep a ?v= cache buster")


class TestBothSignupStatesCarryTheTrap(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.templates = _templates()

    def test_ordinary_signup_branch_has_the_trap(self):
        txt = self.templates["signup.html"]
        self.assertIn('name="website"', txt)
        self.assertIn('class="hp-field"', txt)

    def test_the_trap_renders_on_the_live_signup_page(self):
        import app as app_module
        client = app_module.app.test_client()
        html = client.get("/signup").get_data(as_text=True)
        self.assertIn('class="hp-field"', html)
        self.assertIn('name="website"', html)
        self.assertIn('tabindex="-1"', html)
        self.assertIn('aria-hidden="true"', html)


class TestTrapBehaviour(unittest.TestCase):
    """Behaviour, against a throwaway database. The real runtime DB is never touched."""

    @classmethod
    def setUpClass(cls):
        import app as app_module
        cls.mod = app_module
        cls._orig_db = app_module.db.DB_PATH

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tupelo-honeypot-")
        self.mod.db.DB_PATH = os.path.join(self.tmp, "user_progress.db")
        self.mod.db.init_db()
        self.client = self.mod.app.test_client()
        self._orig_cap = os.environ.pop("PILOT_SIGNUP_CAP", None)

    def tearDown(self):
        if self._orig_cap is not None:
            os.environ["PILOT_SIGNUP_CAP"] = self._orig_cap
        self.mod.db.DB_PATH = self._orig_db
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _email_count(self, email):
        con = self.mod.db._get_conn()
        try:
            row = con.execute("SELECT COUNT(*) FROM users WHERE email = ?", (email,)).fetchone()
            return row[0]
        finally:
            con.close()

    def test_a_filled_trap_is_dropped_and_makes_no_account(self):
        email = "bot@example.com"
        resp = self.client.post("/signup", data={
            "email": email, "display_name": "Bot", "website": "http://spam.example"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "/")
        self.assertEqual(self._email_count(email), 0,
                         "a filled trap must not create an account")

    def test_a_clean_submission_registers(self):
        email = "human@example.com"
        resp = self.client.post("/signup", data={
            "email": email, "display_name": "Human", "website": ""})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "/registered")
        self.assertEqual(self._email_count(email), 1)

    def test_an_absent_trap_field_still_registers(self):
        """Belt and braces: no website key at all must behave like an empty one."""
        email = "human2@example.com"
        resp = self.client.post("/signup", data={"email": email, "display_name": "Human"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "/registered")
        self.assertEqual(self._email_count(email), 1)


if __name__ == "__main__":
    unittest.main()
