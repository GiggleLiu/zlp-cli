import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from zlp.sync import (
    catchup,
    catchup_workspace,
    find_archived_message,
    log_file,
    mark_deleted,
    parse_since,
    pid_file,
    target_dir,
    workspace_state_file,
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


class WorkspaceCatchupTests(unittest.TestCase):
    def test_workspace_catchup_archives_stream_messages_and_advances_past_dms(self):
        class FakeClient:
            base_url = "https://example.zulipchat.com/api/"
            email = "bot@example.com"

            def __init__(self):
                self.calls = []

            def get_profile(self):
                return {"result": "success", "email": "bot@example.com"}

            def get_messages(self, request):
                self.calls.append(request)
                return {
                    "result": "success",
                    "found_newest": True,
                    "messages": [
                        {
                            "id": 10,
                            "timestamp": 1710000000,
                            "sender_full_name": "Ada",
                            "display_recipient": "general",
                            "subject": "launch",
                            "type": "stream",
                            "content": "hello",
                            "stream_id": 1,
                        },
                        {
                            "id": 11,
                            "timestamp": 1710000001,
                            "sender_full_name": "Ada",
                            "display_recipient": [{"email": "bot@example.com"}],
                            "type": "private",
                            "content": "dm",
                        },
                    ],
                }

        with TemporaryDirectory() as dirname:
            root = Path(dirname)
            count = catchup_workspace(FakeClient(), root, import_history=True, attachments=False, silent=True)

            self.assertEqual(count, 1)
            self.assertTrue((root / "general" / "launch").exists())
            self.assertEqual(len(list(root.rglob("*.md"))), 1)
            state = json.loads(workspace_state_file(root).read_text())
            self.assertEqual(state["last_message_id"], 11)
            self.assertEqual(state["stream"], "*")

    def test_workspace_catchup_can_request_all_public_channels(self):
        class FakeClient:
            base_url = "https://example.zulipchat.com/api/"
            email = "bot@example.com"

            def __init__(self):
                self.calls = []

            def get_profile(self):
                return {"result": "success", "email": "bot@example.com"}

            def get_messages(self, request):
                self.calls.append(request)
                return {"result": "success", "found_newest": True, "messages": []}

        with TemporaryDirectory() as dirname:
            client = FakeClient()
            catchup_workspace(
                client,
                Path(dirname),
                import_history=True,
                attachments=False,
                all_public_streams=True,
                silent=True,
            )

            self.assertEqual(client.calls[0]["narrow"], [{"operator": "channels", "operand": "public"}])


class ArchiveOutputTests(unittest.TestCase):
    def test_stream_catchup_prints_archived_paths_by_default(self):
        class FakeClient:
            base_url = "https://example.zulipchat.com/api/"
            email = "bot@example.com"

            def get_profile(self):
                return {"result": "success", "email": "bot@example.com"}

            def get_subscriptions(self):
                return {"result": "success", "subscriptions": [{"name": "general", "stream_id": 1}]}

            def get_messages(self, request):
                return {
                    "result": "success",
                    "found_newest": True,
                    "messages": [
                        {
                            "id": 10,
                            "timestamp": 1710000000,
                            "sender_full_name": "Ada",
                            "display_recipient": "general",
                            "subject": "launch",
                            "type": "stream",
                            "content": "hello",
                            "stream_id": 1,
                        }
                    ],
                }

        with TemporaryDirectory() as dirname:
            buf = StringIO()
            with redirect_stdout(buf):
                count = catchup(
                    FakeClient(),
                    Path(dirname),
                    "general",
                    None,
                    import_history=True,
                    attachments=False,
                )

            self.assertEqual(count, 1)
            self.assertIn("archived\tgeneral/", buf.getvalue())
            self.assertIn("2024-03-09T16-00-00_ada_id10.md", buf.getvalue())

    def test_workspace_catchup_can_suppress_archived_paths(self):
        class FakeClient:
            base_url = "https://example.zulipchat.com/api/"
            email = "bot@example.com"

            def get_profile(self):
                return {"result": "success", "email": "bot@example.com"}

            def get_messages(self, request):
                return {
                    "result": "success",
                    "found_newest": True,
                    "messages": [
                        {
                            "id": 10,
                            "timestamp": 1710000000,
                            "sender_full_name": "Ada",
                            "display_recipient": "general",
                            "subject": "launch",
                            "type": "stream",
                            "content": "hello",
                            "stream_id": 1,
                        }
                    ],
                }

        with TemporaryDirectory() as dirname:
            buf = StringIO()
            with redirect_stdout(buf):
                count = catchup_workspace(
                    FakeClient(),
                    Path(dirname),
                    import_history=True,
                    attachments=False,
                    silent=True,
                )

            self.assertEqual(count, 1)
            self.assertEqual(buf.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
