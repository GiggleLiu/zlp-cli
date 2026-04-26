import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class MakefileWorkflowTests(unittest.TestCase):
    def test_help_lists_developer_quality_targets(self):
        proc = subprocess.run(
            ["make", "help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for target in (
            "fmt           format Python code with ruff",
            "fmt-check     check Python formatting with ruff",
            "lint          run ruff lint checks",
            "build         build sdist and wheel artifacts",
            "check         run fmt-check, lint, and tests",
        ):
            self.assertIn(target, proc.stdout)

    def test_check_target_runs_format_lint_and_tests(self):
        proc = subprocess.run(
            ["make", "-n", "check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ruff format --check src tests", proc.stdout)
        self.assertIn("ruff check src tests", proc.stdout)
        self.assertIn("python -m unittest discover -s tests", proc.stdout)
        if ".venv/bin/ruff" not in proc.stdout:
            self.assertIn("uv run --extra dev ruff", proc.stdout)
            self.assertNotIn("uv run ruff", proc.stdout)

    def test_build_target_uses_uv_build(self):
        proc = subprocess.run(
            ["make", "-n", "build"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("uv build", proc.stdout)


if __name__ == "__main__":
    unittest.main()
