"""Acceptance criterion 5 - no option-letter references, no overclaiming."""

import ast
import os
import re
import unittest

from coach import copy, rules

COPY_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "coach", "copy.py")

# Every form of option-letter reference the live bank was repaired for, plus the
# dangle forms: "(A)" after an option, "B)", "The correct answer is C".
LETTER_REFS = [
    r"\b(?:Distractor|Option|Choice|Answer|letter)\s*[\(\s]*[A-D]\b",
    r"\b[A-D]\)",
    r"(?i)\bthe correct answer is\b",
    r"(?i)\bdistractor\s+[A-D]\b",
]

OVERCLAIMS = [
    r"(?i)\bwill pass\b",
    r"(?i)\bguarantee",
    r"(?i)\bensure you pass\b",
    r"(?i)\byou are ready to pass\b",
    r"(?i)\bpass the exam\b",
]


def _module_docstring_node(tree):
    """The module docstring describes the rules; it is not copy shown to students."""
    body = tree.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[0].value
    return None


def _string_literals(path):
    """Every student-facing string literal in the module."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    doc = _module_docstring_node(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node is doc:
                continue                      # meta-comment, not student copy
            out.append((node.lineno, node.value))
    return out


def _module_docstring_text(path):
    with open(path, encoding="utf-8") as fh:
        return __import__("ast").get_docstring(__import__("ast").parse(fh.read())) or ""


class TestDetectorSanity(unittest.TestCase):
    """A guard that cannot fail is not a guard - prove the detector fires."""

    def test_detector_catches_every_known_form(self):
        positives = [
            "Distractor A is incorrect",
            "Option B is right",
            "The correct answer is C",
            "Choice D fails",
            "answer (A)",
            "this choice is wrong because option (B) says",
        ]
        for sample in positives:
            with self.subTest(sample=sample):
                self.assertTrue(any(re.search(p, sample) for p in LETTER_REFS),
                                f"detector missed: {sample!r}")

    def test_detector_ignores_clean_text(self):
        negatives = [
            "The answer, and why",
            "What is actually true",
            "You were confident and correct.",
            "Read this first",
        ]
        for sample in negatives:
            with self.subTest(sample=sample):
                self.assertFalse(any(re.search(p, sample) for p in LETTER_REFS),
                                 f"false positive: {sample!r}")


class TestLetterFree(unittest.TestCase):
    def test_no_option_letter_reference_anywhere(self):
        bad = []
        for lineno, text in _string_literals(COPY_PATH):
            for pat in LETTER_REFS:
                if re.search(pat, text):
                    bad.append((lineno, pat, text[:70]))
        self.assertEqual(bad, [], f"letter references found: {bad}")


class TestNoOverclaim(unittest.TestCase):
    def test_no_pass_guarantee_language(self):
        bad = []
        for lineno, text in _string_literals(COPY_PATH):
            for pat in OVERCLAIMS:
                if re.search(pat, text):
                    bad.append((lineno, pat, text[:70]))
        self.assertEqual(bad, [], f"overclaiming language found: {bad}")

    def test_overclaim_detector_fires(self):
        for sample in ("you will pass", "guaranteed", "pass the exam"):
            with self.subTest(sample=sample):
                self.assertTrue(any(re.search(p, sample) for p in OVERCLAIMS))

    def test_the_docstring_exclusion_is_honest(self):
        """The only thing skipped is the module docstring, and it really is the rule text."""
        text = _module_docstring_text(COPY_PATH)
        self.assertIn("LETTER-FREE", text)
        self.assertIn("RANGE", text)

    def test_readiness_string_is_a_range_not_a_single_number(self):
        text = copy.readiness_range(44, 53)
        self.assertIn("44", text)
        self.assertIn("53", text)
        self.assertIn("%", text)


class TestCopyCoverage(unittest.TestCase):
    def test_every_phase_has_a_title_and_blurb(self):
        for phase in (rules.PHASE_FOUNDATIONS, rules.PHASE_CLEANUP, rules.PHASE_LAST_MILE,
                      rules.PHASE_TAPER, rules.PHASE_EXAM_EVE):
            with self.subTest(phase=phase):
                self.assertTrue(copy.phase_title(phase).strip())
                self.assertTrue(copy.phase_blurb(phase).strip())

    def test_unknown_phase_degrades_gracefully(self):
        self.assertTrue(copy.phase_title("NOT_A_PHASE"))
        self.assertEqual(copy.phase_blurb("NOT_A_PHASE"), "")

    def test_every_state_has_a_headline(self):
        from coach import diagnosis
        for state in (diagnosis.STATE_MASTERED, diagnosis.STATE_FRAGILE,
                      diagnosis.STATE_MISCONCEPTION, diagnosis.STATE_GAP,
                      diagnosis.STATE_UNSEEN):
            with self.subTest(state=state):
                self.assertTrue(copy.headline(state).strip())

    def test_block_text_agrees_with_the_count(self):
        self.assertIn("3", copy.review_block(3))
        self.assertIn("questions", copy.review_block(3))
        self.assertIn("1", copy.review_block(1))
        self.assertNotIn("questions", copy.review_block(1))
        self.assertIn("questions", copy.new_block(2))


if __name__ == "__main__":
    unittest.main()
