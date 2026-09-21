"""Acceptance criteria 10 and 11 - phase, reading and standard routing."""

import unittest

from coach import copy, router, rules
from tests import fixtures


class TestPhaseTotality(unittest.TestCase):
    """AC 11: exactly one phase for every input, never None."""

    def test_every_combination_maps_to_exactly_one_phase(self):
        valid = {rules.PHASE_EXAM_EVE, rules.PHASE_TAPER, rules.PHASE_FOUNDATIONS,
                 rules.PHASE_CLEANUP, rules.PHASE_LAST_MILE}
        steps = 20
        for i in range(steps + 1):
            r = i / float(steps)
            for d in list(range(0, 60)) + [None, 120, 400]:
                ph = router.phase(r, d)
                self.assertIn(ph, valid, f"readiness={r} days={d} -> {ph!r}")

    def test_date_rules_beat_readiness_rules(self):
        """A student testing tomorrow gets TAPER even with terrible readiness."""
        self.assertEqual(router.phase(0.05, 1), rules.PHASE_EXAM_EVE)
        self.assertEqual(router.phase(0.05, 3), rules.PHASE_TAPER)
        self.assertEqual(router.phase(0.95, 2), rules.PHASE_TAPER)

    def test_readiness_bands_when_no_date_is_set(self):
        self.assertEqual(router.phase(0.10, None), rules.PHASE_FOUNDATIONS)
        self.assertEqual(router.phase(0.50, None), rules.PHASE_CLEANUP)
        self.assertEqual(router.phase(0.90, None), rules.PHASE_LAST_MILE)

    def test_boundaries_are_inclusive_where_documented(self):
        self.assertEqual(router.phase(rules.LAST_MILE_ABOVE, None), rules.PHASE_CLEANUP)
        self.assertEqual(router.phase(rules.LAST_MILE_ABOVE + 0.01, None), rules.PHASE_LAST_MILE)
        self.assertEqual(router.phase(0.9, rules.DAYS_TAPER), rules.PHASE_TAPER)
        self.assertEqual(router.phase(0.9, rules.DAYS_TAPER + 1), rules.PHASE_LAST_MILE)

    def test_cold_start_does_not_crash(self):
        self.assertEqual(router.phase(None, None, has_data=False), rules.PHASE_FOUNDATIONS)
        self.assertTrue(router.phase(0.0, None, has_data=False))


class TestReadingRouter(unittest.TestCase):
    """AC 10: a primary section for >= 95% of topics that have one."""

    def setUp(self):
        d = fixtures.real()
        self.sections = d["sections"]
        self.topics = d["topics"]
        self.tbm = {(t["fcle_domain"], t["topic"]): t["primary_code"]
                    for t in d["topic_benchmarks"]}
        self.primary = {}
        for r in d["benchmark_sections"]:
            if r["is_primary"]:
                self.primary.setdefault(r["benchmark_code"], r["section_id"])

    def test_benchmark_path_covers_at_least_95_percent(self):
        hits = total = 0
        for t in self.topics:
            total += 1
            code = self.tbm.get((t["domain"], t["topic"]))
            sec = router.reading_section(t["topic"], self.sections, self.primary.get(code))
            if sec is not None:
                hits += 1
        pct = hits / float(total)
        self.assertGreaterEqual(pct, 0.95, f"reading covered only {hits}/{total} ({pct:.0%})")

    def test_title_matching_alone_is_measured_and_insufficient(self):
        """Documents WHY the benchmark map is the router, not title matching.

        Topic names and chapter titles use different vocabulary ('Federalism
        basics' vs '3.2. Evolution of American Federalism'), so title matching
        alone is a fallback at best. This test records the real number instead
        of pretending otherwise.
        """
        hits = sum(1 for t in self.topics
                   if router.reading_section(t["topic"], self.sections) is not None)
        pct = hits / float(len(self.topics))
        print(f"\n[measurement] title-only reading coverage: {hits}/{len(self.topics)} "
              f"({pct:.0%}) - benchmark map is the production path")
        self.assertLess(pct, 0.95)

    def test_unknown_section_id_falls_back_to_title_matching(self):
        sec = router.reading_section("Federalism", self.sections, primary_section_id=999999)
        self.assertIsNotNone(sec)

    def test_no_topic_returns_none_without_raising(self):
        self.assertIsNone(router.reading_section("", self.sections))
        self.assertIsNone(router.reading_section(None, self.sections))
        self.assertIsNone(router.reading_section("zzzzzz", []))

    def test_display_title_strips_harvest_artifacts(self):
        self.assertEqual(router.display_title({"section_title": "6.2. How Is Public Opinion Measured?*"}),
                         "6.2. How Is Public Opinion Measured?")
        self.assertEqual(router.display_title({"section_title": "1.1. What is Government?**"}),
                         "1.1. What is Government?")
        self.assertEqual(router.display_title({"section_title": "3.1. Division of Powers\u00a0*"}),
                         "3.1. Division of Powers")

    def test_display_title_does_not_mutate_the_row(self):
        row = {"section_title": "2.2. The Articles of Confederation*"}
        router.display_title(row)
        self.assertEqual(row["section_title"], "2.2. The Articles of Confederation*")

    def test_display_title_handles_junk(self):
        for bad in (None, {}, {"section_title": None}, {"section_title": "*"}):
            with self.subTest(row=bad):
                self.assertIsInstance(router.display_title(bad), str)

    def test_real_titles_carry_no_trailing_artifacts(self):
        with open("tests/real_data.json") as fh:
            import json as _json
            secs = _json.load(fh)["sections"]
        dirty = [s["section_title"] for s in secs if router.display_title(s) != s["section_title"]]
        self.assertTrue(dirty, "expected some real titles to carry artifacts")
        for s in secs:
            self.assertFalse(router.display_title(s).endswith("*"))

    def test_read_minutes_are_clamped(self):
        self.assertGreaterEqual(router.reading_minutes({"char_count": 10}),
                                rules.MIN_READING_MINUTES)
        self.assertLessEqual(router.reading_minutes({"char_count": 10 ** 9}),
                             rules.MAX_READING_MINUTES)
        self.assertIsNone(router.reading_minutes(None))


class TestBenchmarkReport(unittest.TestCase):
    def _per_code(self):
        return {"SS.7.CG.1.2": {"attempted": 10, "adjusted_accuracy": 0.4, "label": "Founding"},
                "SS.7.CG.3.9": {"attempted": 8, "adjusted_accuracy": 0.9, "label": "Judicial"}}

    def test_report_is_suppressed_for_domain_4(self):
        for d in rules.BENCHMARK_REPORT_DOMAINS:
            self.assertIsNotNone(router.benchmark_report(self._per_code(), d))
        self.assertIsNone(router.benchmark_report(self._per_code(), 4))

    def test_domain_4_suppression_is_explained_to_the_student(self):
        self.assertTrue(copy.benchmark_report_absent(4).strip())
        self.assertEqual(copy.benchmark_report_absent(2), "")

    def test_rows_are_sorted_by_worst_miss_rate(self):
        rep = router.benchmark_report(self._per_code(), 1)
        self.assertEqual(rep["rows"][0]["code"], "SS.7.CG.1.2")
        self.assertAlmostEqual(rep["rows"][0]["miss_rate"], 0.6, places=4)

    def test_empty_input_returns_none(self):
        self.assertIsNone(router.benchmark_report({}, 1))
        self.assertIsNone(router.benchmark_report(None, 1))

    def test_unattempted_codes_are_omitted(self):
        rep = router.benchmark_report(
            {"SS.7.CG.1.2": {"attempted": 0, "adjusted_accuracy": 0.0}}, 1)
        self.assertIsNone(rep)


if __name__ == "__main__":
    unittest.main()
