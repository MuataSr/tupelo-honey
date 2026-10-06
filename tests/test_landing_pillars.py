"""The two landing pillar glyphs must stay the decided ones.

Decision (Mister K, 2026-10-06): the pillars row on the landing page carried two
glyphs that did not match their cards.

  Card 1, "The Core Drops" (TEAS & HESI, foundational sciences): it shipped a
  shipping box, whose silhouette is itself a hexagon, so inside the gold hexagon
  frame it read as an empty hexagon and said "logistics" rather than "distilled
  foundations". Replaced with a flask, chosen from a rendered workshop (pick 4).

  Card 2, "The Honeycomb Network" (System Connections): it shipped share-2, the
  universal social-share glyph, which says "post this link" rather than "body
  systems interlock". Replaced with a three-cell honeycomb cluster whose cells
  share edges (pick 1).

Both glyphs are inline SVG in templates/landing.html, each used exactly once, and
each must stay inside its own pillar card. Losing the flask or letting the box
back in is the regression under test.
"""

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LANDING = os.path.join(ROOT, "templates", "landing.html")

# the decided glyphs
FLASK = '<path d="M9 3h6"/>'
FLASK_BODY = '<path d="M10 3v6.5L5.4 18A2 2 0 0 0 7.2 21h9.6a2 2 0 0 0 1.8-3L14 9.5V3"/>'
FLASK_LINE = '<path d="M7.5 15h9"/>'
HONEYCOMB_CELLS = [
    'points="7.67,10.75 12.00,13.25 12.00,18.25 7.67,20.75 3.34,18.25 3.34,13.25"',
    'points="16.33,10.75 20.66,13.25 20.66,18.25 16.33,20.75 12.00,18.25 12.00,13.25"',
    'points="12.00,3.25 16.33,5.75 16.33,10.75 12.00,13.25 7.67,10.75 7.67,5.75"',
]

# the glyphs that were retired
OLD_BOX = 'M21 16V8a2 2 0 0 0-1-1.73l-7-4'
OLD_SHARE = 'circle cx="18" cy="5" r="3"'


class LandingPillarGlyphTests(unittest.TestCase):
    def setUp(self):
        with open(LANDING, encoding="utf-8") as fh:
            self.html = fh.read()
        # bound the slice to the pillars row itself: everything after the row would
        # otherwise drag in the nav and footer glyphs of the rest of the page.
        row = self.html.split('<div class="pillars">', 1)[1].split("</section>", 1)[0]
        self.row = row
        self.pillars = row.split('<div class="pillar">')[1:]

    def test_the_pillars_row_still_has_both_cards(self):
        self.assertEqual(2, len(self.pillars), "pillars row must hold exactly two cards")
        self.assertIn("The Core Drops", self.pillars[0])
        self.assertIn("The Honeycomb Network", self.pillars[1])

    def test_core_drops_carries_the_flask(self):
        self.assertIn(FLASK, self.pillars[0])
        self.assertIn(FLASK_BODY, self.pillars[0])
        self.assertIn(FLASK_LINE, self.pillars[0])
        self.assertEqual(1, self.html.count(FLASK), "the flask belongs to one card only")

    def test_honeycomb_network_carries_the_cell_cluster(self):
        for cell in HONEYCOMB_CELLS:
            self.assertIn(cell, self.pillars[1], "cluster must sit in the Honeycomb card")
            self.assertEqual(1, self.html.count(cell), "each cell is drawn once")
        self.assertEqual(1, self.pillars[1].count("<svg"), "one glyph per card")

    def test_the_retired_box_glyph_is_gone(self):
        self.assertNotIn(OLD_BOX, self.html, "the shipping box read as an empty hexagon")

    def test_the_retired_share_glyph_is_gone(self):
        self.assertNotIn(OLD_SHARE, self.html, "share-2 reads as 'post this link'")

    def test_glyphs_are_inline_svg_not_a_remote_asset(self):
        # the whole pillar row must stay self-contained: no icon font, no <img>,
        # no external svg fetch, which is what keeps it fast and CSP-clean.
        row = self.html.split('<div class="pillars">')[1].split("</section>")[0]
        self.assertNotIn("<img", row)
        self.assertNotIn("icon-font", row)
        self.assertEqual(2, row.count("<svg "))


if __name__ == "__main__":
    unittest.main(verbosity=2)
