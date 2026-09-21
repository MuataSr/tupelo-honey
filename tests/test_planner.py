"""Acceptance criterion 14 and the plan composition rules."""

import unittest

from coach import planner, readiness, router, rules
from tests import fixtures


class TestNewMaterialShare(unittest.TestCase):
    def test_share_never_increases_as_the_exam_approaches(self):
        days = [120, 60, 30, 21, 20, 10, 8, 7, 5, 3, 2, 1, 0]
        shares = [planner.new_material_share(d) for d in days]
        for a, b in zip(shares, shares[1:]):
            self.assertLessEqual(b, a, f"share rose: {list(zip(days, shares))}")

    def test_no_date_gets_a_mid_default(self):
        self.assertGreater(planner.new_material_share(None), 0)

    def test_last_three_days_have_no_new_material(self):
        for d in (0, 1, 2, 3):
            self.assertEqual(planner.new_material_share(d),
                             rules.NEW_MATERIAL_SHARE_TAPER)


class TestTaper(unittest.TestCase):
    """AC 14: days_to_exam <= 3 yields a plan with zero new-material sets."""

    def test_taper_phases_carry_no_new_material(self):
        stats = readiness.topic_stats(fixtures.answers_grid(), fixtures.NOW)
        for d in (0, 1, 2, 3):
            ph = router.phase(0.3, d)
            plan = planner.build_plan(ph, d, (1, 2, 3), stats)
            with self.subTest(days=d, phase=ph):
                self.assertEqual(plan.new_count, 0)
                self.assertEqual([b.kind for b in plan.blocks if b.kind == "new"], [])

    def test_exam_eve_has_no_timed_set_either(self):
        stats = readiness.topic_stats(fixtures.answers_grid(), fixtures.NOW)
        plan = planner.build_plan(rules.PHASE_EXAM_EVE, 0, (1, 2, 3), stats)
        self.assertEqual(plan.timed_count, 0)

    def test_taper_keeps_a_short_timed_set(self):
        stats = readiness.topic_stats(fixtures.answers_grid(), fixtures.NOW)
        plan = planner.build_plan(rules.PHASE_TAPER, 2, (1,), stats)
        self.assertGreater(plan.timed_count, 0)
        self.assertLess(plan.timed_count, rules.TIMED_SET_SIZE)


class TestCaps(unittest.TestCase):
    def setUp(self):
        self.stats = readiness.topic_stats(fixtures.answers_grid(), fixtures.NOW)

    def test_review_cap_is_respected(self):
        plan = planner.build_plan(rules.PHASE_LAST_MILE, 30, tuple(range(500)), self.stats)
        self.assertEqual(plan.review_count, rules.REVIEW_CAP)

    def test_new_cap_is_respected(self):
        for d in (5, 10, 30, 120, None):
            plan = planner.build_plan(rules.PHASE_FOUNDATIONS, d, (), self.stats)
            with self.subTest(days=d):
                self.assertLessEqual(plan.new_count, rules.NEW_CAP)

    def test_timed_set_only_in_last_mile(self):
        for ph, expect in ((rules.PHASE_FOUNDATIONS, 0), (rules.PHASE_CLEANUP, 0),
                           (rules.PHASE_LAST_MILE, rules.TIMED_SET_SIZE)):
            plan = planner.build_plan(ph, 30, (), self.stats)
            with self.subTest(phase=ph):
                self.assertEqual(plan.timed_count, expect)


class TestWeakestTopicSelection(unittest.TestCase):
    def test_selection_is_deterministic(self):
        stats = readiness.topic_stats(fixtures.answers_grid(), fixtures.NOW)
        first = [s["topic"] for s in planner.pick_weakest(stats, 3)]
        second = [s["topic"] for s in planner.pick_weakest(stats, 3)]
        self.assertEqual(first, second)

    def test_confident_errors_outrank_mere_weakness(self):
        sure_wrong = {"topic": "a", "domain": 1, "attempted": 5, "adjusted_accuracy": 0.0,
                      "misconception_rate": 1.0, "coverage": 0.1}
        merely_weak = {"topic": "b", "domain": 1, "attempted": 5, "adjusted_accuracy": 0.2,
                       "misconception_rate": 0.0, "coverage": 0.1}
        self.assertEqual(planner.pick_weakest([merely_weak, sure_wrong], 1)[0]["topic"], "a")

    def test_unattempted_topics_are_excluded(self):
        stats = [{"topic": "x", "domain": 1, "attempted": 0, "adjusted_accuracy": 0.0,
                  "misconception_rate": 0.0, "coverage": 0.0}]
        self.assertEqual(planner.pick_weakest(stats, 3), ())

    def test_limit_is_respected(self):
        stats = readiness.topic_stats(fixtures.answers_grid(), fixtures.NOW)
        self.assertLessEqual(len(planner.pick_weakest(stats, 2)), 2)


class TestSpread(unittest.TestCase):
    def test_spread_sums_to_the_count(self):
        for count in range(0, 20):
            for buckets in range(1, 6):
                with self.subTest(count=count, buckets=buckets):
                    self.assertEqual(sum(planner.spread(count, buckets)), count)

    def test_spread_handles_degenerate_input(self):
        self.assertEqual(planner.spread(0, 3), [])
        self.assertEqual(planner.spread(5, 0), [])


if __name__ == "__main__":
    unittest.main()
