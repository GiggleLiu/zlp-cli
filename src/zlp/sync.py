from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import zulip

from .format import atomic_write, slugify, write_archive_file


UPLOAD_RE = re.compile(r"(?P<url>/user_uploads/[^\s)>\"]+)")
STOP = False
WORKSPACE_STREAM = "*"


def catchup(
    client: zulip.Client,
    archive_root: Path,
    stream: str,
    topic: str | None,
    import_history: bool = False,
    attachments: bool = True,
    silent: bool = False,
) -> int:
    state = load_state(archive_root, stream, topic)
    if not state:
        state = initial_state(client, stream, topic)
        if import_history:
            state["last_message_id"] = 0
        else:
            state["last_message_id"] = newest_message_id(client, stream, topic)
            save_state(archive_root, stream, topic, state)
            return 0

    archived = 0
    while True:
        resp = check(
            client.get_messages(
                {
                    "anchor": state.get("last_message_id", 0),
                    "include_anchor": False,
                    "num_before": 0,
                    "num_after": 5000,
                    "narrow": narrow_for(stream, topic),
                    "apply_markdown": False,
                }
            )
        )
        messages = sorted(resp.get("messages", []), key=lambda item: item.get("id", 0))
        for message in messages:
            path = archive_message(
                client, message, archive_root, stream, topic if topic else "_all", attachments
            )
            report_archive_path(archive_root, path, silent=silent)
            state["last_message_id"] = max(int(state.get("last_message_id", 0)), int(message["id"]))
            archived += 1
        save_state(archive_root, stream, topic, state)
        if resp.get("found_newest", True) or not messages:
            break
    return archived


def catchup_workspace(
    client: zulip.Client,
    archive_root: Path,
    import_history: bool = False,
    attachments: bool = True,
    all_public_streams: bool = False,
    silent: bool = False,
) -> int:
    state = load_workspace_state(archive_root)
    if not state:
        state = initial_workspace_state(client, all_public_streams)
        if import_history:
            state["last_message_id"] = 0
        else:
            state["last_message_id"] = newest_workspace_message_id(client, all_public_streams)
            save_workspace_state(archive_root, state)
            return 0

    archived = 0
    while True:
        resp = check(
            client.get_messages(
                workspace_messages_request(state.get("last_message_id", 0), all_public_streams)
            )
        )
        messages = sorted(resp.get("messages", []), key=lambda item: item.get("id", 0))
        for message in messages:
            if is_stream_message(message):
                path = archive_message(client, message, archive_root, None, None, attachments)
                report_archive_path(archive_root, path, silent=silent)
                archived += 1
            state["last_message_id"] = max(int(state.get("last_message_id", 0)), int(message["id"]))
        save_workspace_state(archive_root, state)
        if resp.get("found_newest", True) or not messages:
            break
    return archived


def start_background(
    config: str,
    archive_root: Path,
    run_root: Path,
    stream: str,
    topic: str | None,
    attachments: bool,
    silent: bool = False,
) -> int:
    pid_path = pid_file(run_root, stream, topic)
    log_path = log_file(run_root, stream, topic)
    run_root.mkdir(parents=True, exist_ok=True)
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            if process_alive(pid):
                print(f"already running pid={pid}")
                return 0
        except ValueError:
            pass
        pid_path.unlink(missing_ok=True)

    first = os.fork()
    if first > 0:
        time.sleep(0.2)
        pid = pid_path.read_text().strip() if pid_path.exists() else ""
        print(f"started pid={pid}")
        return 0
    os.setsid()
    second = os.fork()
    if second > 0:
        os._exit(0)
    with log_path.open("a", buffering=1) as log:
        os.dup2(log.fileno(), sys.stdout.fileno())
        os.dup2(log.fileno(), sys.stderr.fileno())
        pid_path.write_text(str(os.getpid()))
        try:
            raise SystemExit(run_foreground(config, archive_root, stream, topic, attachments, silent=silent))
        finally:
            pid_path.unlink(missing_ok=True)


def start_workspace_background(
    config: str,
    archive_root: Path,
    run_root: Path,
    attachments: bool,
    all_public_streams: bool = False,
    silent: bool = False,
) -> int:
    pid_path = workspace_pid_file(run_root)
    log_path = workspace_log_file(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            if process_alive(pid):
                print(f"already running pid={pid}")
                return 0
        except ValueError:
            pass
        pid_path.unlink(missing_ok=True)

    first = os.fork()
    if first > 0:
        time.sleep(0.2)
        pid = pid_path.read_text().strip() if pid_path.exists() else ""
        print(f"started pid={pid}")
        return 0
    os.setsid()
    second = os.fork()
    if second > 0:
        os._exit(0)
    with log_path.open("a", buffering=1) as log:
        os.dup2(log.fileno(), sys.stdout.fileno())
        os.dup2(log.fileno(), sys.stderr.fileno())
        pid_path.write_text(str(os.getpid()))
        try:
            raise SystemExit(
                run_workspace_foreground(
                    config,
                    archive_root,
                    attachments,
                    all_public_streams,
                    silent=silent,
                )
            )
        finally:
            pid_path.unlink(missing_ok=True)


def run_foreground(
    config: str,
    archive_root: Path,
    stream: str,
    topic: str | None,
    attachments: bool,
    silent: bool = False,
) -> int:
    global STOP

    def handle_term(signum: int, frame: Any) -> None:
        global STOP
        STOP = True

    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)
    client = zulip.Client(config_file=config)

    while not STOP:
        narrow = narrow_for(stream, topic)
        registered = check(
            client.register(narrow=narrow, event_types=["message", "update_message", "delete_message"])
        )
        queue_id = registered["queue_id"]
        last_event_id = registered.get("last_event_id", -1)
        state = load_state(archive_root, stream, topic) or initial_state(client, stream, topic)
        state["last_event_id"] = last_event_id
        save_state(archive_root, stream, topic, state)
        catchup(
            client,
            archive_root,
            stream,
            topic,
            import_history=False,
            attachments=attachments,
            silent=silent,
        )
        while not STOP:
            events_resp = client.get_events(queue_id=queue_id, last_event_id=last_event_id)
            if events_resp.get("code") == "BAD_EVENT_QUEUE_ID":
                break
            check(events_resp)
            events = events_resp.get("events", [])
            for event in events:
                handle_event(client, event, archive_root, stream, topic, attachments, silent=silent)
                last_event_id = event["id"]
            if events:
                state = load_state(archive_root, stream, topic) or initial_state(client, stream, topic)
                state["last_event_id"] = last_event_id
                save_state(archive_root, stream, topic, state)
    return 0


def run_workspace_foreground(
    config: str,
    archive_root: Path,
    attachments: bool,
    all_public_streams: bool = False,
    silent: bool = False,
) -> int:
    global STOP

    def handle_term(signum: int, frame: Any) -> None:
        global STOP
        STOP = True

    signal.signal(signal.SIGTERM, handle_term)
    signal.signal(signal.SIGINT, handle_term)
    client = zulip.Client(config_file=config)

    while not STOP:
        registered = check(
            client.register(
                event_types=["message", "update_message", "delete_message"],
                all_public_streams=all_public_streams,
            )
        )
        queue_id = registered["queue_id"]
        last_event_id = registered.get("last_event_id", -1)
        state = load_workspace_state(archive_root) or initial_workspace_state(client, all_public_streams)
        state["last_event_id"] = last_event_id
        save_workspace_state(archive_root, state)
        catchup_workspace(
            client,
            archive_root,
            import_history=False,
            attachments=attachments,
            all_public_streams=all_public_streams,
            silent=silent,
        )
        while not STOP:
            events_resp = client.get_events(queue_id=queue_id, last_event_id=last_event_id)
            if events_resp.get("code") == "BAD_EVENT_QUEUE_ID":
                break
            check(events_resp)
            events = events_resp.get("events", [])
            for event in events:
                handle_workspace_event(client, event, archive_root, attachments, silent=silent)
                last_event_id = event["id"]
            if events:
                state = load_workspace_state(archive_root) or initial_workspace_state(
                    client, all_public_streams
                )
                state["last_event_id"] = last_event_id
                save_workspace_state(archive_root, state)
    return 0


def handle_event(
    client: zulip.Client,
    event: dict[str, Any],
    archive_root: Path,
    stream: str,
    topic: str | None,
    attachments: bool,
    silent: bool = False,
) -> None:
    event_type = event.get("type")
    if event_type == "message":
        message = event.get("message")
        if message:
            path = archive_message(
                client, message, archive_root, stream, topic if topic else "_all", attachments
            )
            report_archive_path(archive_root, path, silent=silent)
            state = load_state(archive_root, stream, topic) or initial_state(client, stream, topic)
            state["last_message_id"] = max(int(state.get("last_message_id", 0)), int(message["id"]))
            save_state(archive_root, stream, topic, state)
    elif event_type == "update_message":
        for message_id in event_message_ids(event):
            old_path = find_archived_message(archive_root, message_id)
            message = fetch_message_by_id(client, message_id)
            if message is None:
                continue
            new_path = archive_message(client, message, archive_root, None, None, attachments)
            report_archive_path(archive_root, new_path, silent=silent)
            if old_path and old_path != new_path:
                old_path.unlink(missing_ok=True)
    elif event_type == "delete_message":
        for message_id in event_message_ids(event):
            report_archive_path(
                archive_root, mark_deleted(archive_root, message_id), action="deleted", silent=silent
            )


def handle_workspace_event(
    client: zulip.Client,
    event: dict[str, Any],
    archive_root: Path,
    attachments: bool,
    silent: bool = False,
) -> None:
    event_type = event.get("type")
    if event_type == "message":
        message = event.get("message")
        if message:
            if is_stream_message(message):
                path = archive_message(client, message, archive_root, None, None, attachments)
                report_archive_path(archive_root, path, silent=silent)
            state = load_workspace_state(archive_root) or initial_workspace_state(client)
            state["last_message_id"] = max(int(state.get("last_message_id", 0)), int(message["id"]))
            save_workspace_state(archive_root, state)
    elif event_type == "update_message":
        for message_id in event_message_ids(event):
            old_path = find_archived_message(archive_root, message_id)
            message = fetch_message_by_id(client, message_id)
            if message is None or not is_stream_message(message):
                continue
            new_path = archive_message(client, message, archive_root, None, None, attachments)
            report_archive_path(archive_root, new_path, silent=silent)
            if old_path and old_path != new_path:
                old_path.unlink(missing_ok=True)
    elif event_type == "delete_message":
        for message_id in event_message_ids(event):
            report_archive_path(
                archive_root, mark_deleted(archive_root, message_id), action="deleted", silent=silent
            )


def archive_message(
    client: zulip.Client,
    message: dict[str, Any],
    archive_root: Path,
    stream: str | None,
    topic: str | None,
    attachments: bool,
) -> Path:
    archive = {"permalink": permalink(client, message), "attachments": []}
    path = write_archive_file(message, archive_root, stream=stream, topic=topic, archive=archive)
    if attachments:
        files = download_attachments(client, message, path.parent)
        if files:
            archive["attachments"] = files
            path = write_archive_file(message, archive_root, stream=stream, topic=topic, archive=archive)
    return path


def download_attachments(client: zulip.Client, message: dict[str, Any], directory: Path) -> list[str]:
    body = message.get("content", "")
    urls = sorted(set(match.group("url") for match in UPLOAD_RE.finditer(body)))
    if not urls:
        return []
    client.ensure_session()
    assert client.session is not None
    files_dir = directory / "_files"
    files_dir.mkdir(parents=True, exist_ok=True)
    site = client.base_url.removesuffix("/api/")
    downloaded = []
    for url in urls:
        full_url = urljoin(site, url)
        response = client.session.get(full_url, timeout=30)
        response.raise_for_status()
        original = sanitize_filename(Path(urlparse(url).path).name or "attachment")
        digest = hashlib.sha256(response.content).hexdigest()[:12]
        target = files_dir / f"{digest}__{original}"
        target.write_bytes(response.content)
        downloaded.append(str(target.relative_to(directory)))
    return downloaded


def fetch_message_by_id(client: zulip.Client, message_id: int) -> dict[str, Any] | None:
    resp = check(
        client.get_messages(
            {
                "anchor": message_id,
                "include_anchor": True,
                "num_before": 0,
                "num_after": 0,
                "apply_markdown": False,
            }
        )
    )
    for message in resp.get("messages", []):
        if int(message.get("id", -1)) == message_id:
            return message
    return None


def mark_deleted(archive_root: Path, message_id: int) -> Path | None:
    path = find_archived_message(archive_root, message_id)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    _, rest = text.split("---\n", 1)
    frontmatter_text, body = rest.split("\n---\n\n", 1)
    import yaml

    data = yaml.safe_load(frontmatter_text) or {}
    archive = data.setdefault("_archive", {})
    archive["deleted"] = True
    yaml_text = yaml.safe_dump(data, sort_keys=True, allow_unicode=True, default_flow_style=False)
    deleted_path = path.with_suffix(path.suffix + ".deleted")
    atomic_write(deleted_path, f"---\n{yaml_text}---\n\n{body}")
    path.unlink(missing_ok=True)
    return deleted_path


def initial_state(client: zulip.Client, stream: str, topic: str | None) -> dict[str, Any]:
    profile = check(client.get_profile())
    return {
        "site": client.base_url.removesuffix("/api/"),
        "stream": stream,
        "stream_id": stream_id_for_name(client, stream),
        "topic": topic,
        "self_email": profile.get("email") or profile.get("delivery_email") or client.email,
        "last_message_id": 0,
    }


def initial_workspace_state(client: zulip.Client, all_public_streams: bool = False) -> dict[str, Any]:
    profile = check(client.get_profile())
    return {
        "site": client.base_url.removesuffix("/api/"),
        "stream": WORKSPACE_STREAM,
        "topic": None,
        "scope": "all_public_streams" if all_public_streams else "subscribed_streams",
        "self_email": profile.get("email") or profile.get("delivery_email") or client.email,
        "last_message_id": 0,
    }


def newest_message_id(client: zulip.Client, stream: str, topic: str | None) -> int:
    resp = check(
        client.get_messages(
            {
                "anchor": "newest",
                "num_before": 1,
                "num_after": 0,
                "narrow": narrow_for(stream, topic),
                "apply_markdown": False,
            }
        )
    )
    messages = resp.get("messages", [])
    return max((int(message["id"]) for message in messages), default=0)


def newest_workspace_message_id(client: zulip.Client, all_public_streams: bool = False) -> int:
    request = workspace_messages_request("newest", all_public_streams)
    request["num_before"] = 1
    request["num_after"] = 0
    request.pop("include_anchor", None)
    resp = check(client.get_messages(request))
    messages = resp.get("messages", [])
    return max((int(message["id"]) for message in messages), default=0)


def load_state(archive_root: Path, stream: str, topic: str | None) -> dict[str, Any] | None:
    path = state_file(archive_root, stream, topic)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def load_workspace_state(archive_root: Path) -> dict[str, Any] | None:
    path = workspace_state_file(archive_root)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def save_state(archive_root: Path, stream: str, topic: str | None, state: dict[str, Any]) -> None:
    atomic_write(state_file(archive_root, stream, topic), json.dumps(state, indent=2, sort_keys=True) + "\n")


def save_workspace_state(archive_root: Path, state: dict[str, Any]) -> None:
    atomic_write(workspace_state_file(archive_root), json.dumps(state, indent=2, sort_keys=True) + "\n")


def state_file(archive_root: Path, stream: str, topic: str | None) -> Path:
    return target_dir(archive_root, stream, topic) / ".sync-state.json"


def workspace_state_file(archive_root: Path) -> Path:
    return archive_root / ".sync-state.json"


def target_dir(archive_root: Path, stream: str, topic: str | None) -> Path:
    return archive_root / slugify(stream) / (slugify(topic) if topic else "_all")


def pid_file(run_root: Path, stream: str, topic: str | None) -> Path:
    return run_root / f"{slugify(stream)}__{slugify(topic) if topic else '_all'}.pid"


def workspace_pid_file(run_root: Path) -> Path:
    return run_root / "_workspace.pid"


def log_file(run_root: Path, stream: str, topic: str | None) -> Path:
    return run_root / f"{slugify(stream)}__{slugify(topic) if topic else '_all'}.log"


def workspace_log_file(run_root: Path) -> Path:
    return run_root / "_workspace.log"


def stream_id_for_name(client: zulip.Client, stream: str) -> int:
    resp = check(client.get_subscriptions())
    for item in resp.get("subscriptions", []):
        if item.get("name") == stream:
            return int(item["stream_id"])
    resp = check(client.get_streams())
    for item in resp.get("streams", []):
        if item.get("name") == stream:
            return int(item["stream_id"])
    raise SystemExit(f"error: stream not found: {stream}")


def narrow_for(stream: str, topic: str | None = None) -> list[list[str]]:
    narrow = [["stream", stream]]
    if topic:
        narrow.append(["topic", topic])
    return narrow


def is_stream_message(message: dict[str, Any]) -> bool:
    return message.get("type") == "stream" or isinstance(message.get("display_recipient"), str)


def workspace_messages_request(anchor: Any, all_public_streams: bool) -> dict[str, Any]:
    request = {
        "anchor": anchor,
        "include_anchor": False,
        "num_before": 0,
        "num_after": 5000,
        "apply_markdown": False,
    }
    if all_public_streams:
        request["narrow"] = [{"operator": "channels", "operand": "public"}]
    return request


def report_archive_path(
    archive_root: Path,
    path: Path | None,
    action: str = "archived",
    silent: bool = False,
) -> None:
    if silent or path is None:
        return
    try:
        display_path = path.relative_to(archive_root)
    except ValueError:
        display_path = path
    print(f"{action}\t{display_path}", flush=True)


def check(resp: dict[str, Any]) -> dict[str, Any]:
    if resp.get("result") != "success":
        raise SystemExit(f"error: {resp.get('result')}: {resp.get('msg', resp)}")
    return resp


def event_message_ids(event: dict[str, Any]) -> list[int]:
    if "message_ids" in event:
        return [int(item) for item in event["message_ids"]]
    if "message_id" in event:
        return [int(event["message_id"])]
    return []


def find_archived_message(archive_root: Path, message_id: int) -> Path | None:
    candidates = list(archive_root.rglob(f"*_id{message_id}.md")) + list(
        archive_root.rglob(f"*_id{message_id}.md.deleted")
    )
    return candidates[0] if candidates else None


def permalink(client: zulip.Client, message: dict[str, Any]) -> str:
    stream_id = message.get("stream_id") or message.get("recipient_id")
    stream_name = str(message.get("display_recipient", "stream")).replace(" ", "-")
    topic = str(message.get("subject") or message.get("topic") or "")
    site = client.base_url.removesuffix("/api/")
    return f"{site}/#narrow/channel/{stream_id}-{stream_name}/topic/{topic}/near/{message.get('id')}"


def sanitize_filename(name: str) -> str:
    cleaned = "".join("-" if ord(char) < 32 or char in "/\\" else char for char in name)
    cleaned = cleaned.strip(" .")[:80]
    return cleaned or "attachment"


def parse_since(value: str) -> int:
    match = re.fullmatch(r"(\d+)([smhd])", value.strip())
    if not match:
        raise SystemExit("error: SINCE must look like 24h, 30m, 7d")
    number = int(match.group(1))
    unit = match.group(2)
    return number * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False
