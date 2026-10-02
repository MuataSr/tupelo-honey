"""The session key must be fixed in production, and must fail closed when it is not.

Why this test exists: the old fallback was

    app.secret_key = os.environ.get("FLASK_SECRET", os.urandom(24).hex())

which fails OPEN. A live host that forgot FLASK_SECRET did not crash; it logged
students out at random, because each gunicorn worker signed cookies with a
different key, and worker recycling rotated the key again mid-session. Nothing
in the journal said so, and the progress tables stayed empty while the service
reported healthy.

These tests boot the app in a subprocess because the decision is made at import
time.
"""

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET = "b" * 48


def boot(env_overrides):
    """Import app in a clean child process and return the CompletedProcess."""
    env = {k: v for k, v in os.environ.items() if k not in ("FLASK_SECRET", "FLASK_ENV")}
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", "import app; print(app.app.secret_key)"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )


class TestProductionRequiresASecret(unittest.TestCase):
    def test_production_without_secret_refuses_to_start(self):
        result = boot({"FLASK_ENV": "production"})
        self.assertNotEqual(result.returncode, 0, "production booted without FLASK_SECRET")
        self.assertIn("FLASK_SECRET", result.stderr)

    def test_blank_secret_counts_as_missing(self):
        result = boot({"FLASK_ENV": "production", "FLASK_SECRET": "   "})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FLASK_SECRET", result.stderr)

    def test_production_uses_the_configured_secret(self):
        result = boot({"FLASK_ENV": "production", "FLASK_SECRET": SECRET})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), SECRET)


class TestDevelopmentStillBoots(unittest.TestCase):
    def test_no_secret_and_no_environment_boots_with_a_random_key(self):
        result = boot({})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.strip()), 48, "expected 24 random bytes as hex")


class TestWorkersAgree(unittest.TestCase):
    def test_two_processes_with_the_same_env_share_one_key(self):
        """The property that was broken on the live host: two workers, one key."""
        first = boot({"FLASK_ENV": "production", "FLASK_SECRET": SECRET})
        second = boot({"FLASK_ENV": "production", "FLASK_SECRET": SECRET})
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first.stdout, second.stdout)


if __name__ == "__main__":
    unittest.main()
