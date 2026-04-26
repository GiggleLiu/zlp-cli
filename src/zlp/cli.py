from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import zulip

from .format import parse_archive_file, render_json, render_markdown, slugify


NO_CLIENT_COMMANDS = {"sync-status", "sync-log", "inbox", "grep", "unsync", "sync", "sync-fg"}


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

    pull = subparsers.add_parser("pull")
    pull.add_argument("--stream", required=True)
    pull.add_argument("--topic")
    pull.add_argument("--import-history", choices=["0", "1"], default="0")
    pull.add_argument("--attachments", choices=["0", "1"], default="1")

    sync = subparsers.add_parser("sync")
    sync.add_argument("--stream", required=True)
    sync.add_argument("--topic")
    sync.add_argument("--attachments", choices=["0", "1"], default="1")

    sync_fg = subparsers.add_parser("sync-fg")
    sync_fg.add_argument("--stream", required=True)
    sync_fg.add_argument("--topic")
    sync_fg.add_argument("--attachments", choices=["0", "1"], default="1")

    unsync = subparsers.add_parser("unsync")
    unsync.add_argument("--stream", required=True)
    unsync.add_argument("--topic")

    subparsers.add_parser("sync-status")

    log = subparsers.add_parser("sync-log")
    log.add_argument("--stream", required=True)
    log.add_argument("--topic")
    log.add_argument("--lines", type=int, default=50)

    refresh = subparsers.add_parser("refresh")
    refresh.add_argument("--stream", required=True)
    refresh.add_argument("--topic")
    refresh.add_argument("--since", default="24h")

    inbox = subparsers.add_parser("inbox")
    inbox.add_argument("--stream", required=True)
    inbox.add_argument("--topic")
    inbox.add_argument("--limit", type=int, default=20)

    grep = subparsers.add_parser("grep")
    grep.add_argument("--query", required=True)
    grep.add_argument("--stream")
    grep.add_argument("--topic")

    args = parser.parse_args()
    args.archive_root = Path(args.archive_root).resolve()
    args.run_root = Path(args.run_root).resolve()

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
    if args.msg:
        content = f"{args.msg}\n\n{content}"
    sent = check(
        client.send_message({"type": "stream", "to": args.stream, "topic": args.topic, "content": content})
    )
    print(f"ok id={sent.get('id')}")
    return 0


def cmd_pull(client: zulip.Client, args: argparse.Namespace) -> int:
    from .sync import catchup

    count = catchup(
        client,
        args.archive_root,
        args.stream,
        args.topic,
        import_history=args.import_history == "1",
        attachments=args.attachments == "1",
    )
    print(f"ok archived={count}")
    return 0


def cmd_sync(client: zulip.Client, args: argparse.Namespace) -> int:
    from .sync import start_background

    return start_background(
        args.config, args.archive_root, args.run_root, args.stream, args.topic, args.attachments == "1"
    )


def cmd_sync_fg(client: zulip.Client, args: argparse.Namespace) -> int:
    from .sync import run_foreground

    return run_foreground(args.config, args.archive_root, args.stream, args.topic, args.attachments == "1")


def cmd_unsync(client: zulip.Client, args: argparse.Namespace) -> int:
    pid_path = pid_file(args.run_root, args.stream, args.topic)
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
    for state_path in sorted(args.archive_root.glob("*/*/.sync-state.json")):
        state = json.loads(state_path.read_text())
        stream = state.get("stream", "")
        topic = state.get("topic") or "_all"
        pid_path = pid_file(args.run_root, stream, state.get("topic"))
        daemon = "stopped"
        if pid_path.exists():
            try:
                daemon = "alive" if process_alive(int(pid_path.read_text().strip())) else "stale"
            except ValueError:
                daemon = "stale"
        pulled = len(list(state_path.parent.glob("*.md"))) + len(list(state_path.parent.glob("*.md.deleted")))
        print(f"{stream}\t{topic}\t{state.get('last_message_id', 0)}\t{daemon}\t{pulled}")
    return 0


def cmd_sync_log(client: zulip.Client, args: argparse.Namespace) -> int:
    path = log_file(args.run_root, args.stream, args.topic)
    if not path.exists():
        print(f"error: no log file at {path}", file=sys.stderr)
        return 1
    lines = path.read_text(errors="replace").splitlines()
    for line in lines[-args.lines :]:
        print(line)
    return 0


def cmd_refresh(client: zulip.Client, args: argparse.Namespace) -> int:
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
    print(f"ok refreshed={rewritten}")
    return 0


def cmd_inbox(client: zulip.Client, args: argparse.Namespace) -> int:
    target = target_dir(args.archive_root, args.stream, args.topic)
    paths = sorted(target.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)[: args.limit]
    messages = [parse_archive_file(path) for path in reversed(paths)]
    print(render_markdown(messages, args.stream, args.topic))
    return 0


def cmd_grep(client: zulip.Client, args: argparse.Namespace) -> int:
    base = args.archive_root
    if args.stream:
        base = base / slugify(args.stream)
    if args.topic:
        base = base / slugify(args.topic)
    if not base.exists():
        return 1
    rg = shutil_which("rg")
    if rg:
        return subprocess.call([rg, args.query, str(base)])
    for path in base.rglob("*.md"):
        text = path.read_text(errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if args.query in line:
                print(f"{path}:{number}:{line}")
    return 0


def read_body(args: argparse.Namespace) -> str:
    if args.msg is not None:
        return args.msg
    if args.msg_file:
        if args.msg_file == "-":
            return sys.stdin.read()
        return Path(args.msg_file).read_text(encoding="utf-8")
    print("error: MSG or MSG_FILE is required", file=sys.stderr)
    raise SystemExit(1)


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


def log_file(run_root: Path, stream: str, topic: str | None) -> Path:
    return run_root / f"{slugify(stream)}__{slugify(topic) if topic else '_all'}.log"


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


def shutil_which(binary: str) -> str | None:
    for item in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(item) / binary
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None
