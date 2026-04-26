import json
import unittest
from pathlib import Path

from scripts.format import atomic_write, parse_archive_file, slugify, write_archive_file


def fixture_message() -> dict:
    return json.loads(Path("tests/fixtures/sample_message.json").read_text())


class FormatHelperTests(unittest.TestCase):
    def test_slugify_normalizes_and_sanitizes_names(self):
        self.assertEqual(slugify(" General Discussion / Launch Notes! "), "general-discussion-launch-notes")

    def test_slugify_avoids_reserved_all_literal(self):
        self.assertTrue(slugify("_all").startswith("_all-"))

    def test_write_archive_file_and_parse_archive_file_round_trip(self):
        from tempfile import TemporaryDirectory

        message = fixture_message()
        with TemporaryDirectory() as dirname:
            root = Path(dirname)
            path = write_archive_file(message, root, "quantum-info")

            self.assertEqual(
                path,
                root
                / "quantum-info"
                / "general-discussion"
                / "launch-notes"
                / "2026-04-26T02-30-00_alice-chen_id147641.md",
            )
            self.assertEqual(parse_archive_file(path), message)
            self.assertIn("/user_uploads/1/2/report.pdf", path.read_text())
            self.assertIn("_archive:", path.read_text())

    def test_atomic_write_replaces_content(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as dirname:
            path = Path(dirname) / "nested" / "file.txt"

            atomic_write(path, "first")
            atomic_write(path, "second")

            self.assertEqual(path.read_text(), "second")
            self.assertFalse(list(path.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
