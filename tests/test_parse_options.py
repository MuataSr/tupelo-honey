"""Regression: option lists are parsed, never evaluated.

The practice route used to call eval() on a string read from the database.
Stored rows are JSON arrays; the pipe form is the legacy shape and must keep
working without raising.
"""

import unittest

import app


class ParseOptionsTest(unittest.TestCase):
    def test_json_array(self):
        self.assertEqual(app._parse_options('["a", "b", "c"]'), ["a", "b", "c"])

    def test_legacy_pipe(self):
        self.assertEqual(app._parse_options("a|b|c"), ["a", "b", "c"])

    def test_malformed_bracket_does_not_raise(self):
        self.assertEqual(app._parse_options("[not json"), ["[not json"])

    def test_non_string_is_passed_through(self):
        self.assertEqual(app._parse_options(["a", "b"]), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
