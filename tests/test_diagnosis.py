"""Acceptance criteria 8, 9, 12 - the classifier and the misconception matcher."""

import json
import unittest

from coach import diagnosis, rules
from tests import fixtures


class TestQuadrantClassifier(unittest.TestCase):
    """AC 8: all six confidence x correctness cells return the specified state."""

    EXPECTED = {
        (rules.CONFIDENCE_SURE, True): diagnosis.STATE_MASTERED,
        (rules.CONFIDENCE_SURE, False): diagnosis.STATE_MISCONCEPTION,
        (rules.CONFIDENCE_KINDA, True): diagnosis.STATE_FRAGILE,
        (rules.CONFIDENCE_KINDA, False): diagnosis.STATE_GAP,
        (rules.CONFIDENCE_UNSURE, True): diagnosis.STATE_FRAGILE,
        (rules.CONFIDENCE_UNSURE, False): diagnosis.STATE_GAP,
    }

    def test_all_six_cells(self):
        for (conf, correct), state in self.EXPECTED.items():
            with self.subTest(confidence=conf, correct=correct):
                self.assertEqual(diagnosis.classify(conf, correct), state)

    def test_sure_and_wrong_is_the_flagged_case(self):
        self.assertEqual(diagnosis.classify(3, False), diagnosis.STATE_MISCONCEPTION)

    def test_sure_and_wrong_schedules_a_retest_tomorrow(self):
        self.assertEqual(diagnosis.next_review_days(diagnosis.STATE_MISCONCEPTION, 3),
                         rules.MISCONCEPTION_RETEST_DAYS)


class TestConfidenceDegradation(unittest.TestCase):
    """AC 12: unknown or missing confidence degrades to the unsure path, never raises."""

    def test_junk_values_never_raise(self):
        for junk in (None, "", "abc", 0, 99, -1, 2.7, [], {}):
            with self.subTest(value=repr(junk)):
                self.assertEqual(diagnosis.normalise_confidence(junk),
                                 rules.DEFAULT_CONFIDENCE)

    def test_junk_confidence_classifies_as_unsure(self):
        self.assertEqual(diagnosis.classify(None, True), diagnosis.STATE_FRAGILE)
        self.assertEqual(diagnosis.classify("nonsense", False), diagnosis.STATE_GAP)

    def test_normalise_keeps_valid_values(self):
        for v in rules.VALID_CONFIDENCE:
            self.assertEqual(diagnosis.normalise_confidence(v), v)


class TestRefutationAlignment(unittest.TestCase):
    """The per-distractor refutation must follow the exact option chosen."""

    def test_picks_the_matching_refutation(self):
        q = fixtures.question()
        self.assertIn("Divine right", diagnosis.refutation_for(q, "Divine right of kings"))
        self.assertIn("Judicial review concerns",
                      diagnosis.refutation_for(q, "Judicial review"))

    def test_unknown_selection_returns_empty_not_raises(self):
        self.assertEqual(diagnosis.refutation_for(fixtures.question(), "not an option"), "")

    def test_missing_lists_return_empty(self):
        for bad in ({"wrong_answers": None}, {"wrong_explanations": None}, {}):
            with self.subTest(q=bad):
                self.assertEqual(diagnosis.refutation_for(bad, "x"), "")

    def test_misaligned_lists_do_not_overrun(self):
        q = {"wrong_answers": ["a", "b", "c"], "wrong_explanations": ["only one"]}
        self.assertEqual(diagnosis.refutation_for(q, "c"), "")

    def test_accepts_the_raw_json_strings_the_database_stores(self):
        """Regression: the live rows are JSON TEXT, and the refutation silently vanished."""
        q = {
            "wrong_answers": json.dumps(["Divine right of kings", "Judicial review"]),
            "wrong_explanations": json.dumps(["Divine right places authority in a monarch.",
                                              "Judicial review concerns courts assessing laws."]),
        }
        got = diagnosis.refutation_for(q, "Judicial review")
        self.assertIn("Judicial review concerns", got)

    def test_accepts_parsed_lists_too(self):
        q = {"wrong_answers": ["x"], "wrong_explanations": ["because of y"]}
        self.assertEqual(diagnosis.refutation_for(q, "x"), "because of y")

    def test_malformed_json_returns_empty_not_raises(self):
        for bad in ("{not json", "[1,2", "null", "{}"):
            with self.subTest(value=bad):
                self.assertEqual(
                    diagnosis.refutation_for({"wrong_answers": bad,
                                              "wrong_explanations": bad}, "x"), "")


class TestMisconceptionMatcher(unittest.TestCase):
    """AC 9: a row for >= 80% of misses; None without raising otherwise."""

    def setUp(self):
        self.mis = fixtures.real()["misconceptions"]
        self.topics = fixtures.real()["topics"]

    def test_coverage_over_real_topics_is_at_least_80_percent(self):
        hits = 0
        total = 0
        for t in self.topics:
            total += 1
            row, tier = diagnosis.match_misconception(t["domain"], t["topic"], self.mis)
            if row is not None:
                hits += 1
        self.assertGreaterEqual(hits / float(total), 0.80,
                                f"matched {hits}/{total} topics")

    def test_matched_rows_carry_a_correction(self):
        row, _ = diagnosis.match_misconception(3, "Declaration of Independence", self.mis)
        self.assertIsNotNone(row)
        self.assertTrue(str(row.get("correction", "")).strip())

    def test_benchmark_tier_wins_when_a_code_is_supplied(self):
        sample = self.mis[0]
        row, tier = diagnosis.match_misconception(
            sample["fcle_domain"], "an unrelated topic name", self.mis,
            benchmark_code=sample["benchmark_code"])
        self.assertEqual(tier, "benchmark")
        self.assertEqual(row["benchmark_code"], sample["benchmark_code"])

    def test_empty_library_returns_none(self):
        self.assertEqual(diagnosis.match_misconception(1, "x", []), (None, "none"))
        self.assertEqual(diagnosis.match_misconception(1, "x", None), (None, "none"))

    def test_unknown_domain_returns_none(self):
        row, tier = diagnosis.match_misconception(99, "x", self.mis)
        self.assertIsNone(row)
        self.assertEqual(tier, "none")


class TestDirective(unittest.TestCase):
    def test_correct_answer_produces_no_refutation(self):
        a = fixtures.answer(1, 1, "Natural rights and social contract", correct=True, confidence=3)
        d = diagnosis.build_directive(a, fixtures.question(), fixtures.real()["misconceptions"])
        self.assertEqual(d.refutation, "")
        self.assertEqual(d.state, diagnosis.STATE_MASTERED)
        self.assertFalse(d.is_teachable)

    def test_wrong_answer_produces_a_teachable_directive(self):
        a = fixtures.answer(1, 1, "Natural rights and social contract", correct=False,
                            confidence=3, selected="Judicial review")
        d = diagnosis.build_directive(a, fixtures.question(), fixtures.real()["misconceptions"])
        self.assertEqual(d.state, diagnosis.STATE_MISCONCEPTION)
        self.assertTrue(d.is_teachable)
        self.assertIn("Judicial review", d.refutation)
        self.assertTrue(d.correction)


if __name__ == "__main__":
    unittest.main()
