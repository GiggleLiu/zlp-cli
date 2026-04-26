from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

import zulip

from .format import parse_archive_file, render_json, render_markdown, slugify


NO_CLIENT_COMMANDS = {"sync-status", "unsync", "sync"}


def main() -> int:
    parser = argparse.ArgumentParser(prog="zlp", description="Single-workspace Zulip CLI")
    parser.add_argument(
        "--config",
        default=os.environ.get("ZULIP_CONFIG_FILE", "zuliprc"),
        help="path to a zuliprc file (default: $ZULIP_CONFIG_FILE or ./zuliprc)",
    )
    parser.add_argument(
        "--archive-root",
        default=os.environ.get("ZLP_ARCHIVE_ROOT", "mail"),
        help="archive output root (default: $ZLP_ARCHIVE_ROOT or ./mail)",
    )
    parser.add_argument(
        "--run-root",
        default=os.environ.get("ZLP_RUN_ROOT", "run"),
        help="daemon pid/log root (default: $ZLP_RUN_ROOT or ./run)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("whoami")
    subparsers.add_parser("streams")

    topics = subparsers.add_parser("topics")
    topics.add_argument("--stream", required=True)

    messages = subparsers.add_parser("messages")
    messages.add_argument("--stream", required=True)
    messages.add_argument("--topic")
    messages.add_argument("--limit", type=int, default=50)
    messages.add_argument("--format", choices=["md", "json"], default="md")

    search = subparsers.add_parser("search")
    search.add_argument("--query", required=True)
    search.add_argument("--stream")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--format", choices=["md", "json"], default="md")

    send = subparsers.add_parser("send")
    send.add_argument("--stream", required=True)
    send.add_argument("--topic", required=True)
    add_body_args(send)

    dm = subparsers.add_parser("dm")
    dm.add_argument("--to", required=True)
    add_body_args(dm)

    edit = subparsers.add_parser("edit")
    edit.add_argument("--id", required=True, type=int)
    add_body_args(edit)

    delete = subparsers.add_parser("delete")
    delete.add_argument("--id", required=True, type=int)

    upload = subparsers.add_parser("upload")
    upload.add_argument("--file", required=True)
    upload.add_argument("--stream", required=True)
    upload.add_argument("--topic", required=True)
    upload.add_argument("--msg")
    upload.add_argument("--msg-file")

    pull = subparsers.add_parser("pull")
    pull.add_argument("--stream")
    pull.add_argument("--topic")
    pull.add_argument("--import-history", action="store_true")
    pull.add_argument("--no-attachments", dest="attachments", action="store_false")
    pull.add_argument("--all-public", action="store_true")
    pull.add_argument("--silent", action="store_true")

    sync = subparsers.add_parser("sync")
    sync.add_argument("--stream")
    sync.add_argument("--topic")
    sync.add_argument("--no-attachments", dest="attachments", action="store_false")
    sync.add_argument("--all-public", action="store_true")
    sync.add_argument("--silent", action="store_true")
    sync.add_argument("--daemon", action="store_true")

    unsync = subparsers.add_parser("unsync")
    unsync.add_argument("--stream")
    unsync.add_argument("--topic")

    subparsers.add_parser("sync-status")

    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--stream", required=True)
    reconcile.add_argument("--topic")
    reconcile.add_argument("--since", default="24h")

    args = parser.parse_args()
    args.archive_root = Path(args.archive_root).resolve()
    args.run_root = Path(args.run_root).resolve()

    validation_error = validate_args(args)
    if validation_error:
        print(f"error: {validation_error}", file=sys.stderr)
        return 1

    client = None
    if args.command not in NO_CLIENT_COMMANDS:
        config = require_config(args.config)
        client = zulip.Client(config_file=str(config))
        args.config = str(config)

    command = args.command.replace("-", "_")
    return globals()[f"cmd_{command}"](client, args)


def add_body_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--msg")
    parser.add_argument("--msg-file")


def require_config(config: str) -> Path:
    path = Path(config)
    if path.exists():
        return path
    print(
        f"error: zuliprc not found at {path}. Set --config or $ZULIP_CONFIG_FILE.",
        file=sys.stderr,
    )
    raise SystemExit(1)


def validate_args(args: argparse.Namespace) -> str | None:
    if args.command in {"pull", "sync", "unsync"} and args.topic and not args.stream:
        return "--topic requires --stream"
    if args.command in {"pull", "sync"} and args.all_public and args.stream:
        return "--all-public cannot be combined with --stream"
    return None


def check(resp: dict[str, Any]) -> dict[str, Any]:
    if resp.get("result") != "success":
        print(f"error: {resp.get('result')}: {resp.get('msg', resp)}", file=sys.stderr)
        raise SystemExit(1)
    return resp


def cmd_whoami(client: zulip.Client, args: argparse.Namespace) -> int:
    profile = check(client.get_profile())
    site = client.base_url.removesuffix("/api/")
    email = profile.get("email") or profile.get("delivery_email") or client.email
    name = profile.get("full_name") or profile.get("short_name") or ""
    print(f"{site} {email} {name}".strip())
    return 0


def cmd_streams(client: zulip.Client, args: argparse.Namespace) -> int:
    resp = check(client.get_subscriptions())
    streams = resp.get("subscriptions") or resp.get("streams") or []
    for stream in sorted(streams, key=lambda item: item.get("name", "")):
        print(stream.get("name"))
    return 0


def cmd_topics(client: zulip.Client, args: argparse.Namespace) -> int:
    stream_id = stream_id_for_name(client, args.stream)
    resp = check(client.get_stream_topics(stream_id))
    for topic in resp.get("topics", []):
        print(topic.get("name"))
    return 0


def cmd_messages(client: zulip.Client, args: argparse.Namespace) -> int:
    narrow = narrow_for(args.stream, args.topic)
    resp = check(
        client.get_messages(
            {
                "anchor": "newest",
                "num_before": args.limit,
                "num_after": 0,
                "narrow": narrow,
                "apply_markdown": False,
            }
        )
    )
    messages = sorted(resp.get("messages", []), key=lambda item: item.get("id", 0))
    print_rendered(messages, args.format, args.stream, args.topic)
    return 0


def cmd_search(client: zulip.Client, args: argparse.Namespace) -> int:
    narrow = []
    if args.stream:
        narrow.append(["stream", args.stream])
    narrow.append(["search", args.query])
    resp = check(
        client.get_messages(
            {
                "anchor": "newest",
                "num_before": args.limit,
                "num_after": 0,
                "narrow": narrow,
                "apply_markdown": False,
            }
        )
    )
    messages = sorted(resp.get("messages", []), key=lambda item: item.get("id", 0))
    print_rendered(messages, args.format, args.stream, None)
    return 0


def cmd_send(client: zulip.Client, args: argparse.Namespace) -> int:
    body = read_body(args)
    resp = check(
        client.send_message({"type": "stream", "to": args.stream, "topic": args.topic, "content": body})
    )
    print(f"ok id={resp.get('id')}")
    return 0


def cmd_dm(client: zulip.Client, args: argparse.Namespace) -> int:
    body = read_body(args)
    resp = check(client.send_message({"type": "private", "to": args.to, "content": body}))
    print(f"ok id={resp.get('id')}")
    return 0


def cmd_edit(client: zulip.Client, args: argparse.Namespace) -> int:
    body = read_body(args)
    check(client.update_message({"message_id": args.id, "content": body}))
    print(f"ok id={args.id}")
    return 0


def cmd_delete(client: zulip.Client, args: argparse.Namespace) -> int:
    check(client.delete_message(args.id))
    print(f"ok id={args.id}")
    return 0


def cmd_upload(client: zulip.Client, args: argparse.Namespace) -> int:
    path = Path(args.file)
    with path.open("rb") as handle:
        resp = check(client.upload_file(handle))
    uri = resp.get("uri")
    content = f"[{path.name}]({uri})"
    body = optional_body(args)
    if body:
        content = f"{body}\n\n{content}"
    sent = check(
        client.send_message({"type": "stream", "to": args.stream, "topic": args.topic, "content": content})
    )
    print(f"ok id={sent.get('id')}")
    return 0


def cmd_pull(client: zulip.Client, args: argparse.Namespace) -> int:
    from .sync import catchup, catchup_workspace

    if not args.stream:
        count = catchup_workspace(
            client,
            args.archive_root,
            import_history=args.import_history,
            attachments=args.attachments,
            all_public_streams=args.all_public,
            silent=args.silent,
        )
    else:
        count = catchup(
            client,
            args.archive_root,
            args.stream,
            args.topic,
            import_history=args.import_history,
            attachments=args.attachments,
            silent=args.silent,
        )
    print(f"ok archived={count}")
    return 0


def cmd_sync(client: zulip.Client, args: argparse.Namespace) -> int:
    from .sync import (
        run_foreground,
        run_workspace_foreground,
        start_background,
        start_workspace_background,
    )

    if args.daemon:
        if not args.stream:
            return start_workspace_background(
                args.config,
                args.archive_root,
                args.run_root,
                args.attachments,
                args.all_public,
                args.silent,
            )
        return start_background(
            args.config,
            args.archive_root,
            args.run_root,
            args.stream,
            args.topic,
            args.attachments,
            args.silent,
        )
    if not args.stream:
        return run_workspace_foreground(
            args.config,
            args.archive_root,
            args.attachments,
            args.all_public,
            args.silent,
        )
    return run_foreground(
        args.config,
        args.archive_root,
        args.stream,
        args.topic,
        args.attachments,
        args.silent,
    )


def cmd_unsync(client: zulip.Client, args: argparse.Namespace) -> int:
    if not args.stream:
        if args.topic:
            print("error: --topic requires --stream", file=sys.stderr)
            return 1
        pid_path = workspace_pid_file(args.run_root)
    else:
        pid_path = pid_file(args.run_root, args.stream, args.topic)
    return stop_daemon(pid_path)


def stop_daemon(pid_path: Path) -> int:
    if not pid_path.exists():
        print("stopped")
        return 0
    try:
        pid = int(pid_path.read_text().strip())
    except ValueError:
        pid_path.unlink(missing_ok=True)
        print("stale")
        return 0
    if not process_alive(pid):
        pid_path.unlink(missing_ok=True)
        print("stale")
        return 0
    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 5
    while time.time() < deadline:
        if not process_alive(pid):
            pid_path.unlink(missing_ok=True)
            print("stopped")
            return 0
        time.sleep(0.2)
    os.kill(pid, signal.SIGKILL)
    pid_path.unlink(missing_ok=True)
    print("killed")
    return 0


def cmd_sync_status(client: zulip.Client, args: argparse.Namespace) -> int:
    print("stream\ttopic\tlast_id\tdaemon\tpulled_files")
    if not args.archive_root.exists():
        return 0
    workspace_state = workspace_state_file(args.archive_root)
    if workspace_state.exists():
        state = json.loads(workspace_state.read_text())
        daemon = daemon_status(workspace_pid_file(args.run_root))
        pulled = len(list(args.archive_root.rglob("*.md"))) + len(
            list(args.archive_root.rglob("*.md.deleted"))
        )
        print(f"{state.get('stream', '*')}\t_all\t{state.get('last_message_id', 0)}\t{daemon}\t{pulled}")
    for state_path in sorted(args.archive_root.glob("*/*/.sync-state.json")):
        state = json.loads(state_path.read_text())
        stream = state.get("stream", "")
        topic = state.get("topic") or "_all"
        pid_path = pid_file(args.run_root, stream, state.get("topic"))
        daemon = daemon_status(pid_path)
        pulled = len(list(state_path.parent.glob("*.md"))) + len(list(state_path.parent.glob("*.md.deleted")))
        print(f"{stream}\t{topic}\t{state.get('last_message_id', 0)}\t{daemon}\t{pulled}")
    return 0


def cmd_reconcile(client: zulip.Client, args: argparse.Namespace) -> int:
    from .sync import archive_message, fetch_message_by_id, parse_since

    cutoff = time.time() - parse_since(args.since)
    target = target_dir(args.archive_root, args.stream, args.topic)
    rewritten = 0
    for path in sorted(target.glob("*.md")):
        try:
            message = parse_archive_file(path)
        except Exception:
            continue
        if int(message.get("timestamp", 0)) < cutoff:
            continue
        fresh = fetch_message_by_id(client, int(message["id"]))
        if fresh is None:
            continue
        archive_message(client, fresh, args.archive_root, args.stream, args.topic, attachments=False)
        rewritten += 1
    print(f"ok reconciled={rewritten}")
    return 0


def read_body(args: argparse.Namespace) -> str:
    body = optional_body(args)
    if body is None:
        print("error: MSG or MSG_FILE is required", file=sys.stderr)
        raise SystemExit(1)
    return body


def optional_body(args: argparse.Namespace) -> str | None:
    if args.msg is not None:
        return args.msg
    if args.msg_file:
        if args.msg_file == "-":
            return sys.stdin.read()
        return Path(args.msg_file).read_text(encoding="utf-8")
    return None


def print_rendered(messages: list[dict[str, Any]], fmt: str, stream: str | None, topic: str | None) -> None:
    if fmt == "json":
        print(render_json(messages))
    else:
        print(render_markdown(messages, stream, topic))


def stream_id_for_name(client: zulip.Client, stream: str) -> int:
    resp = check(client.get_subscriptions())
    for item in resp.get("subscriptions", []):
        if item.get("name") == stream:
            return int(item["stream_id"])
    resp = check(client.get_streams())
    for item in resp.get("streams", []):
        if item.get("name") == stream:
            return int(item["stream_id"])
    print(f"error: stream not found: {stream}", file=sys.stderr)
    raise SystemExit(1)


def narrow_for(stream: str, topic: str | None = None) -> list[list[str]]:
    narrow = [["stream", stream]]
    if topic:
        narrow.append(["topic", topic])
    return narrow


def target_dir(archive_root: Path, stream: str, topic: str | None) -> Path:
    return archive_root / slugify(stream) / (slugify(topic) if topic else "_all")


def pid_file(run_root: Path, stream: str, topic: str | None) -> Path:
    return run_root / f"{slugify(stream)}__{slugify(topic) if topic else '_all'}.pid"


def workspace_state_file(archive_root: Path) -> Path:
    return archive_root / ".sync-state.json"


def workspace_pid_file(run_root: Path) -> Path:
    return run_root / "_workspace.pid"


def daemon_status(pid_path: Path) -> str:
    if not pid_path.exists():
        return "stopped"
    try:
        return "alive" if process_alive(int(pid_path.read_text().strip())) else "stale"
    except ValueError:
        return "stale"


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
