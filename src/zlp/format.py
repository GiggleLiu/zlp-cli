from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


SLUG_RE = re.compile(r"[^a-z0-9._-]+")
DASH_RE = re.compile(r"-+")


def slugify(s: Any) -> str:
    original = "" if s is None else str(s)
    normalized = unicodedata.normalize("NFKC", original).lower()
    slug = SLUG_RE.sub("-", normalized)
    slug = DASH_RE.sub("-", slug).strip("-")[:80].strip("-")
    if not slug or slug == "_all":
        digest = hashlib.blake2b(original.encode("utf-8"), digest_size=4).hexdigest()
        base = slug or "item"
        slug = f"{base}-{digest}"
    return slug


def atomic_write(path: Path | str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target.parent,
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, target)


def render_markdown(
    messages: list[dict[str, Any]] | dict[str, Any],
    stream: str | None = None,
    topic: str | None = None,
) -> str:
    if isinstance(messages, dict):
        messages = [messages]
    header_stream = stream or _message_stream(messages[0]) if messages else stream or ""
    header_topic = topic or _message_topic(messages[0]) if messages else topic or ""
    header = f"## #{header_stream}"
    if header_topic:
        header += f" > {header_topic}"
    parts = [header]
    for message in messages:
        timestamp = datetime.fromtimestamp(int(message.get("timestamp", 0)), timezone.utc)
        sender = message.get("sender_full_name") or message.get("sender_email") or "unknown"
        parts.append(
            "\n---\n"
            f"**{sender}** · {timestamp:%Y-%m-%d %H:%M} · `id:{message.get('id')}`\n\n"
            f"{message.get('content', '')}"
        )
    return "\n".join(parts)


def render_json(messages: Any) -> str:
    return json.dumps(messages, ensure_ascii=False, indent=2, sort_keys=False)


def archive_path_for_message(
    message: dict[str, Any],
    root: Path | str,
    stream: str | None = None,
    topic: str | None = None,
) -> Path:
    archive_root = Path(root)
    stream_name = stream if stream is not None else _message_stream(message)
    topic_name = topic if topic is not None else _message_topic(message)
    topic_slug = "_all" if topic_name in (None, "") else slugify(topic_name)
    timestamp = datetime.fromtimestamp(int(message.get("timestamp", 0)), timezone.utc)
    sender = message.get("sender_full_name") or message.get("sender_email") or "unknown"
    filename = f"{timestamp:%Y-%m-%dT%H-%M-%S}_{slugify(sender)}_id{message['id']}.md"
    return archive_root / slugify(stream_name) / topic_slug / filename


def write_archive_file(
    message: dict[str, Any],
    root: Path | str,
    stream: str | None = None,
    topic: str | None = None,
    archive: dict[str, Any] | None = None,
) -> Path:
    path = archive_path_for_message(message, root, stream=stream, topic=topic)
    body = message.get("content", "")
    frontmatter = {key: value for key, value in message.items() if key != "content"}
    existing_archive = frontmatter.pop("_archive", {})
    archive_data = {
        "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "permalink": "",
        "attachments": [],
        "deleted": False,
    }
    archive_data.update(existing_archive or {})
    archive_data.update(archive or {})
    frontmatter["_archive"] = archive_data
    yaml_text = yaml.safe_dump(
        frontmatter,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
    )
    atomic_write(path, f"---\n{yaml_text}---\n\n{body}")
    return path


def parse_archive_file(path: Path | str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path} does not start with YAML frontmatter")
    _, rest = text.split("---\n", 1)
    frontmatter_text, body = rest.split("\n---\n\n", 1)
    data = yaml.safe_load(frontmatter_text) or {}
    data.pop("_archive", None)
    data["content"] = body
    return data


def _message_stream(message: dict[str, Any]) -> str:
    display = message.get("display_recipient")
    if isinstance(display, str):
        return display
    if isinstance(display, list):
        return ",".join(str(item.get("email") or item.get("full_name") or item) for item in display)
    return str(message.get("stream") or message.get("stream_name") or "unknown")


def _message_topic(message: dict[str, Any]) -> str:
    return str(message.get("subject") or message.get("topic") or "")
