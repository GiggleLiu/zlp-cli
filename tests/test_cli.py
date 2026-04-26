import io
import os
import sys
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from zlp import cli


@contextmanager
def patched_argv(argv):
    saved = sys.argv
    sys.argv = argv
    try:
        yield
    finally:
        sys.argv = saved


@contextmanager
def patched_env(env):
    saved = {key: os.environ.get(key) for key in env}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class HelpAndUsageTests(unittest.TestCase):
    def test_help_runs_cleanly_and_lists_subcommands(self):
        with patched_argv(["zlp", "--help"]):
            buf = io.StringIO()
            with redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertEqual(ctx.exception.code, 0)
            text = buf.getvalue()
            for cmd in ("whoami", "send", "messages", "pull", "sync", "unsync"):
                self.assertIn(cmd, text)

    def test_missing_subcommand_exits_with_error(self):
        with patched_argv(["zlp"]):
            buf = io.StringIO()
            with redirect_stderr(buf), self.assertRaises(SystemExit) as ctx:
                cli.main()
            self.assertNotEqual(ctx.exception.code, 0)


class ConfigResolutionTests(unittest.TestCase):
    def test_missing_config_file_exits_with_clear_message(self):
        with TemporaryDirectory() as dirname:
            with patched_argv(
                [
                    "zlp",
                    "--config",
                    str(Path(dirname) / "missing.zuliprc"),
                    "--archive-root",
                    dirname,
                    "--run-root",
                    dirname,
                    "whoami",
                ]
            ):
                buf = io.StringIO()
                with redirect_stderr(buf), self.assertRaises(SystemExit) as ctx:
                    cli.main()
                self.assertEqual(ctx.exception.code, 1)
                self.assertIn("zuliprc not found", buf.getvalue())

    def test_env_vars_override_defaults(self):
        with TemporaryDirectory() as dirname:
            env = {
                "ZULIP_CONFIG_FILE": str(Path(dirname) / "absent"),
                "ZLP_ARCHIVE_ROOT": str(Path(dirname) / "mail"),
                "ZLP_RUN_ROOT": str(Path(dirname) / "run"),
            }
            with patched_env(env), patched_argv(["zlp", "whoami"]):
                buf = io.StringIO()
                with redirect_stderr(buf), self.assertRaises(SystemExit):
                    cli.main()
                self.assertIn(str(Path(dirname) / "absent"), buf.getvalue())


class ClientFreeCommandTests(unittest.TestCase):
    def test_sync_status_on_empty_archive_prints_header_only(self):
        with TemporaryDirectory() as dirname:
            with patched_argv(
                [
                    "zlp",
                    "--archive-root",
                    dirname,
                    "--run-root",
                    dirname,
                    "sync-status",
                ]
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cli.main()
                self.assertEqual(rc, 0)
                self.assertIn("stream\ttopic", buf.getvalue())

    def test_pull_without_stream_runs_workspace_catchup(self):
        with TemporaryDirectory() as dirname:
            config = Path(dirname) / "zuliprc"
            config.write_text("[api]\nemail=bot@example.com\nkey=x\nsite=https://example.zulipchat.com\n")
            fake_client = mock.Mock()
            argv = [
                "zlp",
                "--config",
                str(config),
                "--archive-root",
                str(Path(dirname) / "mail"),
                "--run-root",
                str(Path(dirname) / "run"),
                "pull",
            ]
            with (
                patched_argv(argv),
                mock.patch("zlp.cli.zulip.Client", return_value=fake_client) as client_ctor,
                mock.patch("zlp.sync.catchup_workspace", return_value=2) as catchup,
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cli.main()

            self.assertEqual(rc, 0)
            client_ctor.assert_called_once_with(config_file=str(config))
            catchup.assert_called_once_with(
                fake_client,
                (Path(dirname) / "mail").resolve(),
                import_history=False,
                attachments=True,
                all_public_streams=False,
                silent=False,
            )
            self.assertEqual(buf.getvalue(), "ok archived=2\n")

    def test_sync_with_daemon_flag_starts_workspace_daemon(self):
        with TemporaryDirectory() as dirname:
            config = Path(dirname) / "zuliprc"
            config.write_text("[api]\nemail=bot@example.com\nkey=x\nsite=https://example.zulipchat.com\n")
            argv = [
                "zlp",
                "--config",
                str(config),
                "--archive-root",
                str(Path(dirname) / "mail"),
                "--run-root",
                str(Path(dirname) / "run"),
                "sync",
                "--daemon",
            ]
            with (
                patched_argv(argv),
                mock.patch("zlp.cli.zulip.Client") as client_ctor,
                mock.patch("zlp.sync.start_workspace_background", return_value=0) as start,
            ):
                rc = cli.main()

            self.assertEqual(rc, 0)
            client_ctor.assert_not_called()
            start.assert_called_once_with(
                str(config),
                (Path(dirname) / "mail").resolve(),
                (Path(dirname) / "run").resolve(),
                True,
                False,
                False,
            )

    def test_sync_without_daemon_runs_workspace_foreground(self):
        with TemporaryDirectory() as dirname:
            config = Path(dirname) / "zuliprc"
            config.write_text("[api]\nemail=bot@example.com\nkey=x\nsite=https://example.zulipchat.com\n")
            argv = [
                "zlp",
                "--config",
                str(config),
                "--archive-root",
                str(Path(dirname) / "mail"),
                "--run-root",
                str(Path(dirname) / "run"),
                "sync",
            ]
            with (
                patched_argv(argv),
                mock.patch("zlp.cli.zulip.Client") as client_ctor,
                mock.patch("zlp.sync.run_workspace_foreground", return_value=0) as run_ws,
            ):
                rc = cli.main()

            self.assertEqual(rc, 0)
            client_ctor.assert_not_called()
            run_ws.assert_called_once_with(
                str(config),
                (Path(dirname) / "mail").resolve(),
                True,
                False,
                False,
            )

    def test_pull_can_request_all_public_streams_for_workspace_catchup(self):
        with TemporaryDirectory() as dirname:
            config = Path(dirname) / "zuliprc"
            config.write_text("[api]\nemail=bot@example.com\nkey=x\nsite=https://example.zulipchat.com\n")
            fake_client = mock.Mock()
            argv = [
                "zlp",
                "--config",
                str(config),
                "--archive-root",
                str(Path(dirname) / "mail"),
                "--run-root",
                str(Path(dirname) / "run"),
                "pull",
                "--all-public",
            ]
            with (
                patched_argv(argv),
                mock.patch("zlp.cli.zulip.Client", return_value=fake_client),
                mock.patch("zlp.sync.catchup_workspace", return_value=0) as catchup,
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cli.main()

            self.assertEqual(rc, 0)
            catchup.assert_called_once_with(
                fake_client,
                (Path(dirname) / "mail").resolve(),
                import_history=False,
                attachments=True,
                all_public_streams=True,
                silent=False,
            )

    def test_pull_rejects_topic_without_stream(self):
        with TemporaryDirectory() as dirname:
            argv = [
                "zlp",
                "--archive-root",
                str(Path(dirname) / "mail"),
                "--run-root",
                str(Path(dirname) / "run"),
                "pull",
                "--topic",
                "launch",
            ]
            with patched_argv(argv):
                buf = io.StringIO()
                with redirect_stderr(buf):
                    rc = cli.main()

            self.assertEqual(rc, 1)
            self.assertIn("--topic requires --stream", buf.getvalue())

    def test_sync_daemon_silent_suppresses_workspace_archive_path_logging(self):
        with TemporaryDirectory() as dirname:
            config = Path(dirname) / "zuliprc"
            config.write_text("[api]\nemail=bot@example.com\nkey=x\nsite=https://example.zulipchat.com\n")
            argv = [
                "zlp",
                "--config",
                str(config),
                "--archive-root",
                str(Path(dirname) / "mail"),
                "--run-root",
                str(Path(dirname) / "run"),
                "sync",
                "--daemon",
                "--silent",
            ]
            with (
                patched_argv(argv),
                mock.patch("zlp.sync.start_workspace_background", return_value=0) as start,
            ):
                rc = cli.main()

            self.assertEqual(rc, 0)
            start.assert_called_once_with(
                str(config),
                (Path(dirname) / "mail").resolve(),
                (Path(dirname) / "run").resolve(),
                True,
                False,
                True,
            )

    def test_unsync_without_stream_stops_workspace_daemon(self):
        with TemporaryDirectory() as dirname:
            run_root = Path(dirname) / "run"
            run_root.mkdir()
            (run_root / "_workspace.pid").write_text("12345")
            argv = [
                "zlp",
                "--archive-root",
                str(Path(dirname) / "mail"),
                "--run-root",
                str(run_root),
                "unsync",
            ]
            with (
                patched_argv(argv),
                mock.patch("zlp.cli.process_alive", return_value=False),
            ):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cli.main()

            self.assertEqual(rc, 0)
            self.assertEqual(buf.getvalue().strip(), "stale")
            self.assertFalse((run_root / "_workspace.pid").exists())


class WhoamiTests(unittest.TestCase):
    def test_whoami_prints_site_email_name(self):
        fake_client = mock.Mock()
        fake_client.base_url = "https://example.zulipchat.com/api/"
        fake_client.email = "bot@example.com"
        fake_client.get_profile.return_value = {
            "result": "success",
            "email": "bot@example.com",
            "full_name": "Bot Account",
        }
        with TemporaryDirectory() as dirname:
            zuliprc = Path(dirname) / "zuliprc"
            zuliprc.write_text("[api]\nemail=bot@example.com\nkey=x\nsite=https://example.zulipchat.com\n")
            argv = [
                "zlp",
                "--config",
                str(zuliprc),
                "--archive-root",
                dirname,
                "--run-root",
                dirname,
                "whoami",
            ]
            with patched_argv(argv), mock.patch("zlp.cli.zulip.Client", return_value=fake_client):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cli.main()
                self.assertEqual(rc, 0)
                self.assertEqual(
                    buf.getvalue().strip(),
                    "https://example.zulipchat.com bot@example.com Bot Account",
                )


if __name__ == "__main__":
    unittest.main()
