"""Tupelo loads no font from anyone else's server.

The two families were always open source (Libre Baskerville and Source Sans 3, both SIL
OFL 1.1). The defect was never the licence, it was the delivery: `base.html` and
`landing.html` pulled them from fonts.googleapis.com and fonts.gstatic.com, so every
visitor's IP address went to Google to render a page, in an app whose own copy calls itself
a free Open Educational Resource. Self-hosting the same upstream subsets removes the third
party without changing a single glyph.

These tests fail if a third-party font service comes back, if a declared font file goes
missing, if the declarations stop being local, if the attribution disappears, or if the
licence stops being stated on the landing page.
"""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TEMPLATES = os.path.join(ROOT, "templates")
CSS_DIR = os.path.join(ROOT, "static", "css")
FONT_CSS = os.path.join(CSS_DIR, "fonts.css")
FONT_DIR = os.path.join(ROOT, "static", "fonts")
ATTRIBUTION = os.path.join(ROOT, "ATTRIBUTION.md")
LANDING = os.path.join(TEMPLATES, "landing.html")

THIRD_PARTY_FONT_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com", "use.typekit",
                          "fonts.bunny.net", "fonts.cdnfonts.com")

EXPECTED_FILES = (
    "libre-baskerville-latin.woff2",
    "libre-baskerville-latin-ext.woff2",
    "libre-baskerville-italic-latin.woff2",
    "libre-baskerville-italic-latin-ext.woff2",
    "source-sans-3-latin.woff2",
    "source-sans-3-latin-ext.woff2",
)


class TestNoThirdPartyFontService(unittest.TestCase):
    def test_no_template_asks_another_server_for_a_font(self):
        for name in sorted(os.listdir(TEMPLATES)):
            if not name.endswith(".html"):
                continue
            with open(os.path.join(TEMPLATES, name), encoding="utf-8") as fh:
                text = fh.read()
            for host in THIRD_PARTY_FONT_HOSTS:
                self.assertNotIn(host, text, "%s still pulls fonts from %s" % (name, host))

    def test_no_stylesheet_asks_another_server_for_a_font(self):
        for name in sorted(os.listdir(CSS_DIR)):
            if not name.endswith(".css"):
                continue
            with open(os.path.join(CSS_DIR, name), encoding="utf-8") as fh:
                text = fh.read()
            for host in THIRD_PARTY_FONT_HOSTS:
                self.assertNotIn(host, text, "%s references %s" % (name, host))

    def test_the_rendered_landing_page_is_self_contained(self):
        import app as module
        html = module.app.test_client().get("/").get_data(as_text=True)
        for host in THIRD_PARTY_FONT_HOSTS:
            self.assertNotIn(host, html)
        self.assertIn("css/fonts.css", html)

    def test_the_rendered_signup_page_is_self_contained(self):
        """base.html is the other surface that used to load them."""
        import app as module
        html = module.app.test_client().get("/signup").get_data(as_text=True)
        for host in THIRD_PARTY_FONT_HOSTS:
            self.assertNotIn(host, html)
        self.assertIn("css/fonts.css", html)


class TestTheDeclarationsAreLocal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css = open(FONT_CSS, encoding="utf-8").read()

    def test_the_stylesheet_exists_and_declares_both_families(self):
        self.assertIn("'Libre Baskerville'", self.css)
        self.assertIn("'Source Sans 3'", self.css)

    def test_every_url_is_a_local_path(self):
        urls = re.findall(r"url\(([^)]+)\)", self.css)
        self.assertTrue(urls)
        for url in urls:
            self.assertTrue(url.strip().startswith("/static/fonts/"),
                            "%s is not served from this server" % url)
        self.assertNotIn("https://", self.css)

    def test_every_declared_file_exists_and_is_really_woff2(self):
        for url in set(re.findall(r"url\(/static/fonts/([^)]+)\)", self.css)):
            path = os.path.join(FONT_DIR, url)
            self.assertTrue(os.path.exists(path), "%s is declared but missing" % url)
            with open(path, "rb") as fh:
                self.assertEqual(fh.read(4), b"wOF2", "%s is not a WOFF2 file" % url)

    def test_the_weights_the_app_uses_are_covered(self):
        for weight in ("300", "400", "500", "600", "700"):
            self.assertIn("font-weight: %s;" % weight, self.css,
                          "weight %s is used in the UI but not declared" % weight)

    def test_italic_is_declared_for_the_serif(self):
        self.assertRegex(self.css, r"font-family: 'Libre Baskerville';\s*font-style: italic")


class TestTheFilesAreShipped(unittest.TestCase):
    def test_all_six_subsets_are_present_and_not_empty(self):
        for name in EXPECTED_FILES:
            path = os.path.join(FONT_DIR, name)
            self.assertTrue(os.path.exists(path), "%s is not shipped" % name)
            self.assertGreater(os.path.getsize(path), 4096, "%s looks truncated" % name)

    def test_nothing_unreferenced_is_sitting_in_the_font_directory(self):
        declared = set(re.findall(r"url\(/static/fonts/([^)]+)\)",
                                  open(FONT_CSS, encoding="utf-8").read()))
        shipped = {n for n in os.listdir(FONT_DIR) if n.endswith(".woff2")}
        self.assertEqual(declared, shipped,
                         "declared %s but shipped %s" % (sorted(declared), sorted(shipped)))


class TestTheLicenceIsRecorded(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = open(ATTRIBUTION, encoding="utf-8").read()

    def test_both_families_and_their_licence_are_attributed(self):
        self.assertIn("Libre Baskerville", self.text)
        self.assertIn("Source Sans 3", self.text)
        self.assertIn("SIL OFL 1.1", self.text)
        self.assertIn("scripts.sil.org/OFL", self.text)

    def test_the_stylesheet_carries_the_attribution_too(self):
        css = open(FONT_CSS, encoding="utf-8").read()
        self.assertIn("SIL OFL 1.1", css)
        self.assertIn("ATTRIBUTION.md", css)


class TestTheLicenceIsStatedOnTheLandingPage(unittest.TestCase):
    """A reviewer has to be able to read the terms off the page, not the repo.

    Tupelo's licence files were correct while the landing page stated nothing, which is the
    criterion an OER directory checks first.
    """

    @classmethod
    def setUpClass(cls):
        cls.html = open(LANDING, encoding="utf-8").read()

    def test_both_licences_are_named(self):
        self.assertIn("CC BY-NC-SA 4.0", self.html)
        self.assertIn("Apache-2.0", self.html)

    def test_both_licences_link_to_their_deed(self):
        self.assertIn("creativecommons.org/licenses/by-nc-sa/4.0/", self.html)
        self.assertIn("apache.org/licenses/LICENSE-2.0", self.html)

    def test_the_trademark_non_affiliation_line_survives(self):
        self.assertIn("not affiliated with or endorsed by ATI or Elsevier", self.html)


if __name__ == "__main__":
    unittest.main()
