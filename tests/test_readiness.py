"""Acceptance criteria 6 and 7 - the readiness model."""

import unittest

from coach import readiness, rules
from tests import fixtures


class TestCreditWeighting(unittest.TestCase):
    def test_correct_credit_ranks_confidence(self):
        self.assertGreater(readiness.credit(3, True), readiness.credit(2, True))
        self.assertGreater(readiness.credit(2, True), readiness.credit(1, True))

    def test_wrong_answers_earn_nothing_at_any_confidence(self):
        for c in rules.VALID_CONFIDENCE:
            self.assertEqual(readiness.credit(c, False), rules.WRONG_CREDIT)

    def test_unknown_confidence_earns_the_unsure_credit(self):
        self.assertEqual(readiness.credit(99, True),
                         rules.CORRECT_CREDIT[rules.DEFAULT_CONFIDENCE])


class TestDomainReadiness(unittest.TestCase):
    def test_no_answers_is_all_zeros(self):
        dr = readiness.domain_readiness((), 1, fixtures.NOW)
        self.assertEqual((dr.attempted, dr.distinct_answered, dr.readiness), (0, 0, 0.0))

    def test_perfect_answers_reach_full_adjusted_accuracy(self):
        ans = tuple(fixtures.answer(i, 1, "t", correct=True, confidence=3) for i in range(1, 41))
        dr = readiness.domain_readiness(ans, 1, fixtures.NOW)
        self.assertAlmostEqual(dr.adjusted_accuracy, 1.0, places=6)
        self.assertAlmostEqual(dr.coverage, 1.0, places=6)
        self.assertAlmostEqual(dr.readiness, 1.0, places=6)

    def test_coverage_is_capped(self):
        ans = tuple(fixtures.answer(i, 1, "t", True, 3) for i in range(1, 200))
        self.assertEqual(readiness.domain_readiness(ans, 1, fixtures.NOW).coverage, 1.0)

    def test_older_answers_weigh_less(self):
        fresh = tuple(fixtures.answer(i, 1, "t", correct=(i % 2 == 0), confidence=3)
                      for i in range(1, 11))
        stale = tuple(fixtures.answer(100 + i, 1, "t", correct=(i % 2 == 0), confidence=3,
                                      age_days=120) for i in range(1, 11))
        d_fresh = readiness.domain_readiness(fresh, 1, fixtures.NOW)
        d_stale = readiness.domain_readiness(stale, 1, fixtures.NOW)
        self.assertAlmostEqual(d_fresh.adjusted_accuracy, d_stale.adjusted_accuracy, places=3)

    def test_decay_halves_at_the_halflife(self):
        self.assertAlmostEqual(readiness.decay(0.0), 1.0, places=9)
        self.assertAlmostEqual(readiness.decay(rules.RECENCY_HALFLIFE_DAYS), 0.5, places=6)


class TestProjectedRange(unittest.TestCase):
    """AC 6: a range, never a point probability."""

    def test_returns_a_range_object_not_a_scalar(self):
        p = readiness.projected_range(0.6, 0.5)
        self.assertTrue(hasattr(p, "low") and hasattr(p, "high"))
        self.assertIsInstance(p.low, int)
        self.assertIsInstance(p.high, int)

    def test_low_never_exceeds_high(self):
        for r in (0.0, 0.25, 0.5, 0.75, 1.0):
            for c in (0.0, 0.3, 0.7, 1.0):
                with self.subTest(r=r, c=c):
                    p = readiness.projected_range(r, c)
                    self.assertLessEqual(p.low, p.high)

    def test_range_is_never_zero_width(self):
        for r in (0.0, 0.5, 1.0):
            for c in (0.0, 1.0):
                p = readiness.projected_range(r, c)
                self.assertGreaterEqual(p.width, 2,
                                        f"zero-width range at r={r} c={c}: {p.low}-{p.high}")

    def test_bounds_stay_inside_the_exam(self):
        for r in (0.0, 1.0):
            for c in (0.0, 1.0):
                p = readiness.projected_range(r, c)
                self.assertGreaterEqual(p.low, 0)
                self.assertLessEqual(p.high, rules.EXAM_TOTAL_ITEMS)

    def test_perfect_readiness_fully_covered_reports_top_of_scale(self):
        p = readiness.projected_range(1.0, 1.0)
        self.assertGreaterEqual(p.low, rules.PASS_SCORE)


class TestRangeMonotonicity(unittest.TestCase):
    """AC 7: decreasing coverage must not narrow the range."""

    def test_width_is_non_decreasing_as_coverage_falls(self):
        readiness_fixed = 0.6
        coverages = [1.0, 0.9, 0.75, 0.6, 0.5, 0.4, 0.25, 0.1, 0.0]
        widths = [readiness.projected_range(readiness_fixed, c).width for c in coverages]
        for a, b in zip(widths, widths[1:]):
            self.assertLessEqual(a, b, f"range narrowed: {widths}")
        self.assertGreater(widths[-1], widths[0])

    def test_margin_is_monotone_in_coverage(self):
        margins = [readiness.projected_range(0.6, c / 100.0).margin for c in range(100, -1, -1)]
        for a, b in zip(margins, margins[1:]):
            self.assertLessEqual(a, b)


class TestBands(unittest.TestCase):
    def test_every_band_label_is_reachable_and_ordered(self):
        labels = [readiness.band(r) for r in (0.0, 0.5, 0.65, 0.9)]
        self.assertEqual(labels, ["Not yet ready", "Borderline", "Likely ready",
                                  "Ready - protect it with timed sets"])

    def test_band_is_total(self):
        for i in range(0, 101):
            self.assertTrue(readiness.band(i / 100.0))


class TestSummarise(unittest.TestCase):
    def test_empty_input_is_safe_and_reports_no_data(self):
        s = readiness.summarise((), fixtures.NOW)
        self.assertFalse(s["has_data"])
        self.assertEqual(s["readiness"], 0.0)

    def test_realistic_input_produces_a_full_picture(self):
        s = readiness.summarise(fixtures.answers_grid(), fixtures.NOW)
        self.assertTrue(s["has_data"])
        self.assertGreater(s["readiness"], 0.0)
        self.assertLessEqual(s["readiness"], 1.0)
        self.assertTrue(s["band"])
        self.assertEqual(len(s["per_domain"]), len(rules.DOMAIN_WEIGHTS))

    def test_weak_student_bands_below_strong_student(self):
        weak = readiness.summarise(fixtures.answers_grid(correct_rate=0.4), fixtures.NOW)
        strong = readiness.summarise(fixtures.answers_grid(correct_rate=0.95), fixtures.NOW)
        self.assertLess(weak["readiness"], strong["readiness"])


class TestGroupStats(unittest.TestCase):
    def test_topic_stats_are_deterministically_ordered(self):
        a = readiness.topic_stats(fixtures.answers_grid(), fixtures.NOW)
        b = readiness.topic_stats(fixtures.answers_grid(), fixtures.NOW)
        self.assertEqual([x["topic"] for x in a], [x["topic"] for x in b])
        self.assertEqual([x["domain"] for x in a], sorted(x["domain"] for x in a))

    def test_misconception_rate_counts_only_sure_and_wrong(self):
        ans = (fixtures.answer(1, 1, "t", correct=False, confidence=3),
               fixtures.answer(2, 1, "t", correct=False, confidence=1),
               fixtures.answer(3, 1, "t", correct=True, confidence=3))
        s = readiness.topic_stats(ans, fixtures.NOW)[0]
        self.assertAlmostEqual(s["misconception_rate"], 1 / 3.0, places=6)

    def test_code_stats_ignores_untagged_answers(self):
        ans = (fixtures.answer(1, 1, "t", code="SS.7.CG.1.2"),
               fixtures.answer(2, 1, "t", code=None))
        self.assertEqual(tuple(readiness.code_stats(ans, fixtures.NOW)), ("SS.7.CG.1.2",))


if __name__ == "__main__":
    unittest.main()
