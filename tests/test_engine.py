"""Acceptance criteria 3 and 13 - determinism and the cold start."""

import unittest

from coach import copy, diagnosis, engine, readiness, router, rules
from tests import fixtures


def _state(**kw):
    d = fixtures.real()
    base = dict(
        user={"id": 1, "exam_date": "2026-10-15"},
        answers=fixtures.answers_grid(),
        due_review_ids=tuple(range(1, 6)),
        misconceptions=tuple(d["misconceptions"]),
        sections=tuple(d["sections"]),
        benchmark_map={(t["fcle_domain"], t["topic"]): t["primary_code"]
                       for t in d["topic_benchmarks"]},
        benchmark_primary_section={},
        now=fixtures.NOW,
    )
    base.update(kw)
    return engine.State(**base)


class TestDeterminism(unittest.TestCase):
    """AC 3: identical inputs produce identical output."""

    def test_two_builds_are_byte_identical(self):
        a = engine.build(_state())
        b = engine.build(_state())
        self.assertEqual(repr(a), repr(b))

    def test_plan_for_is_an_alias_for_build(self):
        s = _state()
        self.assertEqual(repr(engine.plan_for(s)), repr(engine.build(s)))

    def test_answer_order_does_not_change_readiness(self):
        ans = list(fixtures.answers_grid())
        s1 = _state(answers=tuple(ans))
        s2 = _state(answers=tuple(reversed(ans)))
        self.assertAlmostEqual(engine.build(s1).readiness, engine.build(s2).readiness, places=9)


class TestColdStart(unittest.TestCase):
    """AC 13: a brand-new user gets a diagnostic-first plan, never a crash."""

    def test_no_answers_and_no_exam_date(self):
        s = _state(user={}, answers=(), due_review_ids=(), now=fixtures.NOW)
        plan = engine.build(s)
        self.assertFalse(plan.has_data)
        self.assertEqual(plan.phase, rules.PHASE_FOUNDATIONS)
        self.assertEqual(plan.projected_range_text, copy.readiness_unknown())
        self.assertTrue(plan.title and plan.blurb)

    def test_empty_everything(self):
        plan = engine.build(engine.State(now=fixtures.NOW))
        self.assertFalse(plan.has_data)
        self.assertEqual(plan.blocks, ())

    def test_no_misconception_library_still_builds(self):
        plan = engine.build(_state(misconceptions=()))
        self.assertTrue(plan.has_data)

    def test_no_sections_still_builds(self):
        plan = engine.build(_state(sections=()))
        self.assertIsNone(plan.reading)

    def test_garbage_exam_date_is_ignored_not_fatal(self):
        for bad in ("not-a-date", "", None, "2026", 12345):
            with self.subTest(exam_date=repr(bad)):
                plan = engine.build(_state(user={"id": 1, "exam_date": bad}))
                self.assertTrue(plan.phase)


class TestDaysToExam(unittest.TestCase):
    def test_counts_forward_days(self):
        self.assertEqual(engine.days_to_exam({"exam_date": "2026-09-20"}, fixtures.NOW), 7)

    def test_missing_or_bad_dates_return_none(self):
        for v in ({}, {"exam_date": None}, {"exam_date": "nope"}):
            with self.subTest(user=v):
                self.assertIsNone(engine.days_to_exam(v, fixtures.NOW))

    def test_past_exam_date_is_negative_not_an_error(self):
        self.assertLess(engine.days_to_exam({"exam_date": "2026-09-01"}, fixtures.NOW), 0)


class TestFullBuild(unittest.TestCase):
    def test_plan_carries_every_render_field(self):
        plan = engine.build(_state())
        for field in ("phase", "title", "blurb", "band", "projected_range_text",
                      "pass_line_text", "blocks"):
            with self.subTest(field=field):
                self.assertTrue(getattr(plan, field) is not None)
        self.assertTrue(all(b.text for b in plan.blocks))

    def test_taper_state_produces_no_new_blocks(self):
        plan = engine.build(_state(user={"id": 1, "exam_date": "2026-09-15"}))
        self.assertEqual(plan.phase, rules.PHASE_TAPER)
        self.assertEqual([b for b in plan.blocks if b.kind == "new"], [])

    def test_reading_is_resolved_through_the_benchmark_map(self):
        d = fixtures.real()
        primary = {}
        for r in d["benchmark_sections"]:
            if r["is_primary"]:
                primary.setdefault(r["benchmark_code"], r["section_id"])
        plan = engine.build(_state(benchmark_primary_section=primary))
        self.assertIsNotNone(plan.reading)
        self.assertTrue(plan.reading["title"])

    def test_focus_domain_tracks_the_weakest_topic(self):
        plan = engine.build(_state())
        self.assertIn(plan.focus_domain, (1, 2, 3, 4))
        if plan.reading:
            self.assertEqual(plan.reading.get("domain"), plan.focus_domain)

    def test_focus_domain_is_none_with_no_data(self):
        self.assertIsNone(engine.build(engine.State(user={}, now=fixtures.NOW)).focus_domain)

    def test_benchmark_code_lookup(self):
        s = _state()
        self.assertTrue(engine.benchmark_code_for(s, 4, "Marbury v Madison"))
        self.assertIsNone(engine.benchmark_code_for(s, 4, "no such topic"))


class TestDirectiveIntegration(unittest.TestCase):
    def test_wrong_answer_flow_end_to_end(self):
        q = fixtures.question(qid=1, domain=1, topic="Natural rights and social contract")
        a = fixtures.answer(1, 1, q["topic"], correct=False, confidence=3,
                            selected="Judicial review")
        d = diagnosis.build_directive(a, q, fixtures.real()["misconceptions"])
        self.assertEqual(d.state, diagnosis.STATE_MISCONCEPTION)
        self.assertTrue(d.refutation and d.correction)
        self.assertEqual(d.next_review_days, rules.MISCONCEPTION_RETEST_DAYS)

    def test_group_stats_feed_the_planner(self):
        stats = readiness.topic_stats(fixtures.answers_grid(correct_rate=0.2), fixtures.NOW)
        self.assertTrue(stats)
        self.assertTrue(all(s["attempted"] > 0 for s in stats))


if __name__ == "__main__":
    unittest.main()
