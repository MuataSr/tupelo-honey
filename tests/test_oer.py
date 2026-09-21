"""Sabal is OER full stop: one free app, no paid tier, no upselling.

These lock that guarantee. If someone later re-opens a paid surface — a pricing
route, a premium state, an upgrade prompt, an edition flag, or a question cap —
these fail.

The AI tutor is NOT a paid surface: it is an optional "bring your own model"
capability (tutor_engine.py), so it must remain present and un-gated.
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# User-facing paid/upsell copy that must never reach a student.
BANNED = ["Premium", "Upgrade", "pricing", "Unlock", "one-time", "monthly",
          "questions/day", "free questions a day"]

# Structural symbols that must be gone from app.py (and, where noted, templates).
GONE_SYMBOLS = ["APP_EDITION", "FREE_EDITION", "FULL_EDITION", "full_edition_only",
                "_premium_active", "platform_lib", "FCLE_FREE_LAUNCH",
                "_questions_remaining_for", "_questions_left_today",
                "_FREE_LIMIT_MSG", "_limit_redirect", "FREE_DAILY"]


def _app_source():
    with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as fh:
        return fh.read()


def _templates():
    tdir = os.path.join(ROOT, "templates")
    out = {}
    for name in os.listdir(tdir):
        if name.endswith(".html"):
            with open(os.path.join(tdir, name), encoding="utf-8") as fh:
                out[name] = fh.read()
    return out


class TestNoPaidSurfaceInSource(unittest.TestCase):
    def test_paid_symbols_are_gone(self):
        src = _app_source()
        for sym in GONE_SYMBOLS:
            self.assertNotIn(sym, src, "app.py still contains %r" % sym)

    def test_no_pricing_module(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "platform_lib.py")),
                         "platform_lib.py (the paywall helper) must be deleted")

    def test_no_premium_pricing_templates(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "templates", "premium.html")),
                         "premium.html must be deleted")
        self.assertFalse(os.path.exists(os.path.join(ROOT, "templates", "analytics_premium.html")),
                         "analytics_premium.html must be deleted")

    def test_templates_use_no_paywall_vars(self):
        # These context variables no longer exist; a reference would crash render.
        for name, txt in _templates().items():
            for var in ("free_edition", "is_premium", "launch_free", "premium_until",
                        "free_daily", "questions_remaining"):
                self.assertNotIn(var, txt, "%s still references %r" % (name, var))


class TestRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, ROOT)
        import app as app_module
        cls.mod = app_module
        cls.client = app_module.app.test_client()

    def _text(self, path):
        resp = self.client.get(path, follow_redirects=True)
        html = resp.get_data(as_text=True)
        body = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
        return resp.status_code, re.sub(r"\s+", " ", body)

    def test_pricing_route_does_not_exist(self):
        rules = [r.rule for r in self.mod.app.url_map.iter_rules()]
        self.assertNotIn("/pricing", rules, "/pricing must not exist")

    def test_tutor_route_exists_and_is_not_gated(self):
        rules = [r.rule for r in self.mod.app.url_map.iter_rules()]
        self.assertIn("/tutor", rules, "the bring-your-own-model AI tutor must remain")
        self.assertIn("/tutor/chat", rules)

    def test_anon_pages_carry_no_paid_surface(self):
        for path in ("/", "/signup", "/login"):
            _code, text = self._text(path)
            leaked = [b for b in BANNED if b in text]
            self.assertEqual(leaked, [], "%s leaked %s" % (path, leaked))

    def test_account_page_is_free_not_a_quota(self):
        import sqlite3
        db_path = os.path.join(ROOT, "data", "user_progress.db")
        if not os.path.exists(db_path):
            self.skipTest("no user db on this machine")
        con = sqlite3.connect(db_path)
        row = con.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
        con.close()
        if not row:
            self.skipTest("no users on this machine")
        with self.client.session_transaction() as sess:
            sess["user_id"] = row[0]
        _code, text = self._text("/account")
        self.assertIn("Every feature unlocked", text)
        self.assertIn("Unlimited", text)
        self.assertEqual([b for b in BANNED if b in text], [],
                         "account page leaked paid copy")


if __name__ == "__main__":
    unittest.main()
