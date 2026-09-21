"""Acceptance criteria 1, 2, 4 and 15 - the constraints that keep it shippable."""

import ast
import os
import re
import sys
import unittest

COACH_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "coach")

# Values that must live ONLY in rules.py. Distinctive enough that a bounded
# literal search is meaningful; ambiguous small integers are covered by the
# positive "every module reads rules.X" check instead.
THRESHOLDS = ["0.45", "0.60", "0.65", "0.75", "0.10", "0.8", "0.5",
              "14.0", "2.5", "1.3", "180", "1200", "86400"]


def _modules():
    return sorted(f for f in os.listdir(COACH_DIR) if f.endswith(".py"))


def _source(name):
    with open(os.path.join(COACH_DIR, name), encoding="utf-8") as fh:
        return fh.read()


def _imports(name):
    """Top-level module names imported by a module."""
    tree = ast.parse(_source(name))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                out.add(node.module.split(".")[0])
    return out


class TestStdlibOnly(unittest.TestCase):
    """AC 1: no third-party dependencies."""

    def test_every_import_is_stdlib_or_the_package(self):
        allowed_local = {"coach", "__future__"}
        offenders = []
        for name in _modules():
            for mod in _imports(name):
                if mod in allowed_local:
                    continue
                if mod not in sys.stdlib_module_names:
                    offenders.append((name, mod))
        self.assertEqual(offenders, [], f"non-stdlib imports: {offenders}")

    def test_coach_adds_no_dependency_to_the_repo(self):
        """The repo has a requirements.txt for the web app; the coach must add nothing to it.

        Adding a dependency for the coach would make self-hosting harder and break
        the promise that the engine runs on a bare Python install.
        """
        root = os.path.dirname(COACH_DIR)
        req = os.path.join(root, "requirements.txt")
        if not os.path.exists(req):
            return
        with open(req, encoding="utf-8") as fh:
            declared = set()
            for line in fh:
                line = line.split("#")[0].strip()
                if not line:
                    continue
                name = re.split(r"[<>=!\[; ]", line)[0].strip().lower().replace("-", "_")
                if name:
                    declared.add(name)
        coach_imports = set()
        for name in _modules():
            coach_imports |= _imports(name)
        coach_imports -= {"coach"}
        overlap = {m.lower().replace("-", "_") for m in coach_imports} & declared
        self.assertEqual(overlap, set(),
                         f"the coach pulled in declared dependencies: {overlap}")


class TestNoNetworkNoModel(unittest.TestCase):
    """AC 2 and 4: no network, no model server."""

    FORBIDDEN_IMPORTS = {"socket", "urllib", "http", "requests", "httpx", "aiohttp",
                         "ftplib", "smtplib", "telnetlib", "ssl", "xmlrpc", "webbrowser"}

    def test_no_networking_imports(self):
        for name in _modules():
            bad = _imports(name) & self.FORBIDDEN_IMPORTS
            with self.subTest(module=name):
                self.assertEqual(bad, set(), f"{name} imports {bad}")

    def test_no_urls_ports_or_model_references(self):
        patterns = [r"https?://", r"\blocalhost\b", r"\b127\.0\.0\.1\b", r":80\d\d",
                    r"(?i)\bapi[_-]?key\b", r"(?i)\bllama\b", r"(?i)\bopenai\b",
                    r"(?i)\bmodel_name\b", r"(?i)\btemperature\b"]
        for name in _modules():
            src = _source(name)
            for pat in patterns:
                with self.subTest(module=name, pattern=pat):
                    self.assertIsNone(re.search(pat, src),
                                      f"{name} matches {pat} - the coach must not call a model")

    def test_detector_actually_fires(self):
        for sample in ("http://x", "localhost", "127.0.0.1", ":8085", "api_key"):
            with self.subTest(sample=sample):
                self.assertTrue(re.search(r"https?://|localhost|127\.0\.0\.1|:80\d\d|api[_-]?key",
                                          sample, re.I))


class TestThresholdDiscipline(unittest.TestCase):
    """AC 15: thresholds live in rules.py and nowhere else."""

    def test_no_threshold_literals_outside_rules(self):
        offenders = []
        for name in _modules():
            if name == "rules.py":
                continue
            src = _source(name)
            for lit in THRESHOLDS:
                pat = r"(?<![\d.])" + re.escape(lit) + r"(?![\d.])"
                if re.search(pat, src):
                    offenders.append((name, lit))
        self.assertEqual(offenders, [], f"threshold literals leaked: {offenders}")

    def test_rules_module_actually_defines_them(self):
        src = _source("rules.py")
        for lit in THRESHOLDS:
            with self.subTest(literal=lit):
                self.assertIn(lit, src)

    def test_logic_modules_read_the_constants_from_rules(self):
        for name in ("readiness.py", "planner.py", "router.py", "engine.py", "diagnosis.py"):
            with self.subTest(module=name):
                self.assertIn("rules.", _source(name),
                              f"{name} does not read its limits from rules.py")

    def test_boundary_regex_is_not_vacuous(self):
        pat = r"(?<![\d.])" + re.escape("0.45") + r"(?![\d.])"
        self.assertTrue(re.search(pat, "if x < 0.45:"))
        self.assertIsNone(re.search(pat, "if x < 10.452:"))


class TestLayerDiscipline(unittest.TestCase):
    """The DB boundary stays in one module, so the rest stays unit-testable."""

    def test_only_repository_imports_sqlite(self):
        for name in _modules():
            if name == "repository.py":
                continue
            with self.subTest(module=name):
                self.assertNotIn("sqlite3", _imports(name), f"{name} touches a database")

    def test_no_module_opens_or_writes_a_file(self):
        for name in _modules():
            with self.subTest(module=name):
                self.assertNotIn("open(", _source(name),
                                 f"{name} opens a file - reads belong in repository.py")

    def test_repository_reads_are_read_only(self):
        src = _source("repository.py")
        self.assertIn("mode=ro", src)


if __name__ == "__main__":
    unittest.main()
