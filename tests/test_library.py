"""Tests for the per-answer content library and its feedback view."""
import os
import sqlite3
import tempfile
import unittest

from coach import diagnosis, library


def build_db(path):
    """A miniature content DB with the real schema."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE misconceptions (
            id INTEGER PRIMARY KEY, benchmark_code TEXT, misconception TEXT,
            correction TEXT, difficulty TEXT, fcle_domain INTEGER);
        CREATE TABLE content (
            id INTEGER PRIMARY KEY, section_title TEXT, char_count INTEGER,
            fcle_domain INTEGER);
        CREATE TABLE topic_benchmarks (
            fcle_domain INTEGER, topic TEXT, primary_code TEXT);
        CREATE TABLE benchmark_sections (
            benchmark_code TEXT, section_id INTEGER, is_primary INTEGER,
            relevance_score REAL, reviewed INTEGER, review_note TEXT);
        CREATE TABLE benchmarks (
            code TEXT, standard TEXT, description TEXT, clarifications TEXT);
    """)
    con.executemany("INSERT INTO benchmarks VALUES (?,?,?,?)", [
        ("SS.7.CG.3.11", "SS.7.CG.3",
         "Analyze the effects of landmark Supreme Court decisions on law, liberty and "
         "the interpretation of the Constitution.", ""),
        ("SS.7.CG.2.6", "SS.7.CG.2",
         "Examine the election and voting process at the local, state and national levels.", ""),
        ("SS.7.CG.9.9", "SS.7.CG.9", "A standard from another domain entirely.", ""),
    ])
    con.executemany("INSERT INTO misconceptions VALUES (?,?,?,?,?,?)", [
        (1, "SS.7.CG.3.11", "Marbury gave the Court power to strike down laws it dislikes.",
         "Marbury established judicial review of constitutionality, not of policy.", "hard", 4),
        (2, "SS.7.CG.3.11", "The 14th Amendment incorporated the whole Bill of Rights at once.",
         "Incorporation was selective and came case by case.", "hard", 4),
        (3, "SS.7.CG.2.6", "The popular vote decides the presidency.",
         "The Electoral College decides it; five presidents lost the popular vote.", "hard", 1),
        (4, "SS.7.CG.9.9", "A code from another domain that must never be tier-1 matched here.",
         "It belongs elsewhere.", "hard", 2),
    ])
    con.executemany("INSERT INTO content VALUES (?,?,?,?)", [
        (10, "11.1. The Nature of Supreme Court Power" + chr(0xa0) + "*", 24000, 4),
        (11, "6.2. How Is Public Opinion Measured?", 18000, 1),
    ])
    con.executemany("INSERT INTO topic_benchmarks VALUES (?,?,?)", [
        (4, "Landmark Supreme Court cases", "SS.7.CG.3.11"),
        (1, "Political parties and elections", "SS.7.CG.2.6"),
    ])
    con.executemany("INSERT INTO benchmark_sections VALUES (?,?,?,?,?,?)", [
        ("SS.7.CG.3.11", 10, 1, 9.0, 0, None),
        ("SS.7.CG.2.6", 11, 1, 8.0, 1, "judged correct: elections -> public opinion is "
                                           "an offered-by-review case"),
    ])
    con.commit()
    con.close()


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "content.db")
        build_db(self.db)
        library._CACHE.clear()
        self.lib = library.load(self.db)

    def test_shape(self):
        self.assertEqual(len(self.lib["misconceptions"]), 4)
        self.assertEqual(len(self.lib["sections"]), 2)
        self.assertEqual(self.lib["codes"][(4, "Landmark Supreme Court cases")],
                         "SS.7.CG.3.11")

    def test_load_is_cached(self):
        first = library.load(self.db)
        second = library.load(self.db)
        self.assertIs(first, second)

    def test_cache_invalidates_when_the_file_changes(self):
        first = library.load(self.db)
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO misconceptions VALUES (5,'SS.7.CG.3.11','x','y','hard',4)")
        con.commit()
        con.close()
        os.utime(self.db, (os.path.getmtime(self.db) + 10, os.path.getmtime(self.db) + 10))
        second = library.load(self.db)
        self.assertIsNot(first, second)
        self.assertEqual(len(second["misconceptions"]), 5)

    def test_reviewed_link_is_offered_without_a_keyword_match(self):
        # SS.7.CG.2.6 (elections) is linked to "6.2. How Is Public Opinion Measured?", whose
        # title shares no significant word with the benchmark. It is marked reviewed, so the
        # keyword gate must NOT withhold it - that is the whole point of the flag.
        d = self._directive(1, "Political parties and elections", False, 3)
        self.assertEqual(d.read_section_title, "6.2. How Is Public Opinion Measured?")

    def test_external_reading_target_renders_as_a_link(self):
        # An external source has no content row; it must be offered directly and carry a
        # URL that the feedback view turns into a link.
        lib = {
            "sections_by_id": {}, "primary": {}, "reviewed": set(),
            "external": {"SS.7.CG.2.2": {"title": "A Guide to Naturalization",
                                         "url": "https://example.gov/naturalization"}},
            "benchmarks": {"SS.7.CG.2.2": {"description": "Explain the naturalization process"}},
            "codes": {(2, "Citizenship"): "SS.7.CG.2.2"},
            "misconceptions": [], "sections": [],
        }
        question = {"id": 1, "fcle_domain": 2, "topic": "Citizenship", "explanation": "x",
                    "wrong_answers": ["w"], "wrong_explanations": ["y"]}
        answer = {"question_id": 1, "domain": 2, "topic": "Citizenship",
                  "is_correct": False, "confidence": 3, "selected_answer": "w"}
        d = library.directive_for(lib, answer, question)
        self.assertEqual(d.read_section_title, "A Guide to Naturalization")
        self.assertEqual(d.read_section_url, "https://example.gov/naturalization")
        self.assertEqual(library.feedback_view(d)["read_url"],
                         "https://example.gov/naturalization")

    def test_reviewed_set_holds_only_reviewed_codes(self):
        self.assertEqual(self.lib["reviewed"], {"SS.7.CG.2.6"})
        self.assertNotIn("SS.7.CG.3.11", self.lib["reviewed"])

    def test_reference_apparatus_is_never_a_reading_target(self):
        # the back matter was split into its own rows; the Index is small enough to pass
        # the size check, so it needs the title rule or it would become a reading target
        from coach import router
        for title in ("Index", "References", "Answer Key", "index", "References*"):
            with self.subTest(title=title):
                self.assertFalse(router.is_teachable_section(
                    {"section_title": title, "char_count": 27740}))
        self.assertTrue(router.is_teachable_section(
            {"section_title": "Appendix B. The Constitution of the United States",
             "char_count": 47394}))

    def test_the_back_matter_row_is_never_a_reading_target(self):
        from coach import router
        self.assertFalse(router.is_teachable_section({"char_count": 367972}))
        self.assertFalse(router.is_teachable_section({"char_count": 60001}))
        self.assertTrue(router.is_teachable_section({"char_count": 21748}))
        self.assertTrue(router.is_teachable_section({"char_count": 0}))
        self.assertFalse(router.is_teachable_section(None))
        self.assertFalse(router.is_teachable_section({"char_count": "not a number"}))

    def test_implausible_reading_pointer_is_suppressed(self):
        # SS.7.CG.1.8 is the Preamble. Its stored primary link is "17.4. Approaches to
        # Foreign Policy" and its second is "2.5. Constitutional Change" - neither of
        # which mentions the Preamble, so BOTH must be withheld. Withholding the
        # pointer is the honest outcome: the mapping is bad, so there is no good
        # chapter to send the student to.
        from coach import router
        preamble = {"description": "Explain the purpose of the Preamble to the "
                                   "U.S. Constitution."}
        self.assertFalse(router.title_matches_benchmark(
            preamble, "17.4. Approaches to Foreign Policy"))
        self.assertFalse(router.title_matches_benchmark(
            preamble, "2.5. Constitutional Change"))
        self.assertFalse(router.title_matches_benchmark(preamble, ""))
        self.assertFalse(router.title_matches_benchmark(None, "Anything At All"))

    def test_a_genuine_reading_match_still_passes(self):
        from coach import router
        self.assertTrue(router.title_matches_benchmark(
            {"description": "Analyze the effects of landmark Supreme Court decisions "
                            "on law, liberty and the interpretation of the Constitution."},
            "11.1. The Nature of Supreme Court Power"))

    def test_question_domain_reads_every_shape(self):
        self.assertEqual(library.question_domain({"domain_id": 3}), 3)
        self.assertEqual(library.question_domain({"fcle_domain": 2}), 2)
        self.assertEqual(library.question_domain({}, {"domain": 4}), 4)
        self.assertEqual(library.question_domain({"domain_id": 1}, {}, domain=1), 1)

    def test_question_domain_refuses_a_slug(self):
        # the quiz knows its domain as a slug; treating one as an id made the
        # misconception lookup match nothing, so it must resolve to None instead
        self.assertIsNone(library.question_domain({"domain_id": "american-democracy"}))
        self.assertIsNone(library.question_domain({}, {}, domain="us-constitution"))
        self.assertIsNone(library.question_domain({}))

    def test_a_slug_domain_finds_no_benchmark_code(self):
        self.assertIsNone(library.benchmark_code(self.lib, "landmark-impact",
                                                 "Landmark Supreme Court cases"))
        self.assertEqual(library.benchmark_code(self.lib, 4, "Landmark Supreme Court cases"),
                         "SS.7.CG.3.11")

    def test_question_shaped_like_the_apps_still_diagnoses(self):
        # this is the exact shape that silently produced an empty note: a question row
        # with domain_id and an answer carrying only a slug-derived id
        question = {"id": 5, "domain_id": 4, "topic": "Landmark Supreme Court cases",
                    "explanation": "x", "wrong_answers": ["w"], "wrong_explanations": ["y"]}
        answer = {"question_id": 5, "domain": 4, "topic": question["topic"],
                  "is_correct": False, "confidence": 3, "selected_answer": "w"}
        d = library.directive_for(self.lib, answer, question)
        self.assertEqual(d.state, diagnosis.STATE_MISCONCEPTION)
        self.assertTrue(d.misconception_text)
        self.assertTrue(d.correction)
        self.assertEqual(d.read_section_title, "11.1. The Nature of Supreme Court Power")
        self.assertTrue(library.feedback_view(d)["has_diagnosis"])

    def test_benchmark_code_lookup_never_raises(self):
        self.assertEqual(library.benchmark_code(self.lib, 4, "Landmark Supreme Court cases"),
                         "SS.7.CG.3.11")
        self.assertIsNone(library.benchmark_code(self.lib, 4, "nothing like this"))
        for bad in (None, "", "four", 4.5):
            with self.subTest(domain=bad):
                self.assertIsNone(library.benchmark_code(self.lib, bad, "x"))

    def test_read_section_title_is_normalised(self):
        d = self._directive(domain=4, topic="Landmark Supreme Court cases",
                            correct=False, confidence=3)
        self.assertEqual(d.read_section_title, "11.1. The Nature of Supreme Court Power")

    def _directive(self, domain, topic, correct, confidence, selected="a wrong option"):
        question = {"id": 99, "fcle_domain": domain, "topic": topic,
                    "explanation": "the real reasoning",
                    "wrong_answers": [selected], "wrong_explanations": ["because not"]}
        answer = {"question_id": 99, "domain": domain, "topic": topic,
                  "is_correct": correct, "confidence": confidence,
                  "selected_answer": selected}
        return library.directive_for(self.lib, answer, question, domain=domain)

    def test_sure_and_wrong_is_a_misconception(self):
        d = self._directive(4, "Landmark Supreme Court cases", False, 3)
        self.assertEqual(d.state, diagnosis.STATE_MISCONCEPTION)
        self.assertEqual(d.match_tier, "benchmark")
        self.assertIn("Marbury", d.misconception_text)
        self.assertTrue(d.correction)

    def test_unsure_and_wrong_is_a_gap_not_a_misconception(self):
        d = self._directive(4, "Landmark Supreme Court cases", False, 1)
        self.assertEqual(d.state, diagnosis.STATE_GAP)
        self.assertNotEqual(d.state, diagnosis.STATE_MISCONCEPTION)

    def test_sure_and_right_is_mastered(self):
        d = self._directive(4, "Landmark Supreme Court cases", True, 3)
        self.assertEqual(d.state, diagnosis.STATE_MASTERED)

    def test_tier1_never_matches_across_domains(self):
        # the domain-2 misconception exists but must not be reachable from domain 4
        d = self._directive(4, "Landmark Supreme Court cases", False, 3)
        self.assertNotIn("another domain", d.misconception_text)

    def test_view_hides_itself_when_mastered(self):
        v = library.feedback_view(self._directive(4, "Landmark Supreme Court cases", True, 3))
        self.assertFalse(v["show"])
        self.assertEqual(v["headline"], "")

    def test_view_shows_trap_and_correction(self):
        v = library.feedback_view(self._directive(4, "Landmark Supreme Court cases", False, 3))
        self.assertTrue(v["show"])
        self.assertTrue(v["has_diagnosis"])
        self.assertEqual(v["headline"], "This one is a trap for you")
        self.assertTrue(v["trap"] and v["correction"])
        self.assertEqual(v["trap_intro"], "What makes this tempting")
        self.assertEqual(v["correction_intro"], "What is actually true")
        self.assertFalse(v["generic"])

    def test_view_marks_a_domain_tier_match_as_generic(self):
        # no topic mapping -> tier 2/3 fallback, which must be labelled honestly
        question = {"id": 7, "fcle_domain": 4, "topic": "", "explanation": "x"}
        answer = {"question_id": 7, "domain": 4, "topic": "", "is_correct": False,
                  "confidence": 3, "selected_answer": "y"}
        d = library.directive_for(self.lib, answer, question, domain=4)
        v = library.feedback_view(d)
        self.assertEqual(d.match_tier, "domain")
        self.assertTrue(v["generic"])
        self.assertTrue(v["generic_note"])

    def test_view_only_surfaces_strings_from_copy(self):
        from coach import copy
        v = library.feedback_view(self._directive(4, "Landmark Supreme Court cases", False, 3))
        self.assertIn(v["headline"], copy.HEADLINE.values())
        self.assertEqual(v["read_intro"], copy.reading_intro())


if __name__ == "__main__":
    unittest.main()
