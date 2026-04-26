import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from zlp.format import (
    archive_path_for_message,
    atomic_write,
    parse_archive_file,
    render_json,
    render_markdown,
    slugify,
    write_archive_file,
)


def fixture_message() -> dict:
    return json.loads((Path(__file__).parent / "fixtures" / "sample_message.json").read_text())


class SlugifyTests(unittest.TestCase):
    def test_normalizes_and_sanitizes_names(self):
        self.assertEqual(slugify(" General Discussion / Launch Notes! "), "general-discussion-launch-notes")

    def test_collapses_repeated_dashes(self):
        self.assertEqual(slugify("a---b"), "a-b")

    def test_truncates_to_80_chars(self):
        self.assertLessEqual(len(slugify("x" * 200)), 80)

    def test_avoids_reserved_all_literal(self):
        self.assertTrue(slugify("_all").startswith("_all-"))

    def test_empty_input_falls_back_to_digest(self):
        self.assertTrue(slugify("").startswith("item-"))
        self.assertTrue(slugify(None).startswith("item-"))

    def test_unicode_is_lowercased(self):
        self.assertNotEqual(slugify("Ümlaut"), "")


class AtomicWriteTests(unittest.TestCase):
    def test_replaces_content_without_leftover_tmp(self):
        with TemporaryDirectory() as dirname:
            path = Path(dirname) / "nested" / "file.txt"

            atomic_write(path, "first")
            atomic_write(path, "second")

            self.assertEqual(path.read_text(), "second")
            self.assertFalse(list(path.parent.glob("*.tmp")))


class ArchivePathTests(unittest.TestCase):
    def test_uses_message_recipients_when_args_missing(self):
        message = fixture_message()
        path = archive_path_for_message(message, Path("/tmp/r"))
        self.assertEqual(
            path,
            Path("/tmp/r/general-discussion/launch-notes/2026-04-26T02-30-00_alice-chen_id147641.md"),
        )

    def test_topic_none_becomes_all_bucket(self):
        message = {**fixture_message(), "subject": ""}
        path = archive_path_for_message(message, Path("/tmp/r"))
        self.assertEqual(path.parent.name, "_all")

    def test_explicit_stream_topic_overrides_message_fields(self):
        message = fixture_message()
        path = archive_path_for_message(message, Path("/tmp/r"), stream="other", topic="bug")
        self.assertEqual(path.parts[-3:-1], ("other", "bug"))


class WriteAndParseArchiveTests(unittest.TestCase):
    def test_round_trip_preserves_message(self):
        message = fixture_message()
        with TemporaryDirectory() as dirname:
            root = Path(dirname)
            path = write_archive_file(message, root)

            self.assertEqual(
                path,
                root / "general-discussion" / "launch-notes" / "2026-04-26T02-30-00_alice-chen_id147641.md",
            )
            self.assertEqual(parse_archive_file(path), message)

    def test_archive_block_is_added_with_metadata(self):
        message = fixture_message()
        with TemporaryDirectory() as dirname:
            path = write_archive_file(
                message,
                Path(dirname),
                archive={"permalink": "https://x/near/1", "attachments": ["_files/a"]},
            )
            text = path.read_text()
            self.assertIn("_archive:", text)
            self.assertIn("permalink: https://x/near/1", text)
            self.assertIn("- _files/a", text)
            self.assertIn("deleted: false", text)

    def test_attachments_url_preserved_in_body(self):
        message = fixture_message()
        with TemporaryDirectory() as dirname:
            path = write_archive_file(message, Path(dirname))
            self.assertIn("/user_uploads/1/2/report.pdf", path.read_text())

    def test_passing_existing_archive_inline_is_preserved(self):
        message = {**fixture_message(), "_archive": {"permalink": "p1", "fetched_at": "2026-01-01T00:00:00Z"}}
        with TemporaryDirectory() as dirname:
            path = write_archive_file(message, Path(dirname), archive={"attachments": ["_files/x"]})
            text = path.read_text()
            self.assertIn("permalink: p1", text)
            self.assertIn("- _files/x", text)


class RenderTests(unittest.TestCase):
    def test_render_markdown_includes_header_and_message_metadata(self):
        message = fixture_message()
        rendered = render_markdown([message], stream="general", topic="launch")
        self.assertIn("## #general > launch", rendered)
        self.assertIn("Alice Chen", rendered)
        self.assertIn("`id:147641`", rendered)
        self.assertIn("Hello **world**", rendered)

    def test_render_markdown_accepts_single_dict(self):
        message = fixture_message()
        rendered = render_markdown(message)
        self.assertIn("Alice Chen", rendered)

    def test_render_markdown_handles_empty_list(self):
        self.assertIn("## #", render_markdown([], stream="x"))

    def test_render_json_is_round_trippable(self):
        messages = [fixture_message()]
        decoded = json.loads(render_json(messages))
        self.assertEqual(decoded, messages)


if __name__ == "__main__":
    unittest.main()
