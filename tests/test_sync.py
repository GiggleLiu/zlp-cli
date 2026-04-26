import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from zlp.sync import (
    find_archived_message,
    log_file,
    mark_deleted,
    parse_since,
    pid_file,
    target_dir,
)
from zlp.format import write_archive_file


def fixture_message() -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / "sample_message.json").read_text())


class PathHelperTests(unittest.TestCase):
    def test_target_dir_uses_topic_when_provided(self):
        self.assertEqual(
            target_dir(Path("/m"), "general", "Launch Notes"),
            Path("/m/general/launch-notes"),
        )

    def test_target_dir_uses_all_when_topic_missing(self):
        self.assertEqual(
            target_dir(Path("/m"), "general", None),
            Path("/m/general/_all"),
        )

    def test_pid_and_log_file_share_naming_convention(self):
        pid = pid_file(Path("/r"), "general", "Launch Notes")
        log = log_file(Path("/r"), "general", "Launch Notes")
        self.assertEqual(pid.name, "general__launch-notes.pid")
        self.assertEqual(log.name, "general__launch-notes.log")

    def test_pid_file_topic_none_uses_all_marker(self):
        self.assertEqual(pid_file(Path("/r"), "general", None).name, "general___all.pid")


class ParseSinceTests(unittest.TestCase):
    def test_parses_each_unit(self):
        self.assertEqual(parse_since("30s"), 30)
        self.assertEqual(parse_since("5m"), 300)
        self.assertEqual(parse_since("2h"), 7200)
        self.assertEqual(parse_since("3d"), 3 * 86400)

    def test_rejects_bad_input(self):
        with self.assertRaises(SystemExit):
            parse_since("forever")
        with self.assertRaises(SystemExit):
            parse_since("10")


class FindAndMarkDeletedTests(unittest.TestCase):
    def test_find_archived_message_locates_by_id(self):
        message = fixture_message()
        with TemporaryDirectory() as dirname:
            root = Path(dirname)
            path = write_archive_file(message, root)

            found = find_archived_message(root, message["id"])
            self.assertEqual(found, path)
            self.assertIsNone(find_archived_message(root, 999999999))

    def test_mark_deleted_renames_and_sets_flag(self):
        message = fixture_message()
        with TemporaryDirectory() as dirname:
            root = Path(dirname)
            path = write_archive_file(message, root)

            mark_deleted(root, message["id"])

            self.assertFalse(path.exists())
            deleted_path = path.with_suffix(path.suffix + ".deleted")
            self.assertTrue(deleted_path.exists())
            self.assertIn("deleted: true", deleted_path.read_text())


if __name__ == "__main__":
    unittest.main()
