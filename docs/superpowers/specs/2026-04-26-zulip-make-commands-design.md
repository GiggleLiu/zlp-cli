# Zulip Make Commands — Design

**Date:** 2026-04-26
**Status:** Approved (pending user spec review)

## Goal

Provide a small, ergonomic `make`-driven toolkit for reading, writing,
and **locally archiving with incremental background sync** Zulip stream
messages across multiple Zulip workspaces, starting with
`https://quantum-info.zulipchat.com`. Every operation is one make target;
all state (credentials, sync anchors, archived messages) lives in
version-controllable files on disk.

## Non-goals

- Admin / management operations (subscribe, mark-as-read, export). Out of v1.
- A full-featured Zulip TUI. Targets are intentionally one-shot CLI calls.
- Reimplementing what the official `zulip` Python client already provides.
- Coupling to a session / chamber lifecycle (the way `cryo-zulip` is). Sync
  here is generic per-(workspace, stream, topic).

## Real-time sync mechanism

The official `zulip` Python client supports Zulip's **event queue**
(long-poll) via `register` + `get_events`. We use the lower-level
`register` / `get_events` pair (not the convenience
`call_on_each_event`) so we can interleave catchup and live tail
without a race window.

Strategy ("register-then-catchup-then-drain"):
1. **Register the queue first.** `client.register(narrow=…, event_types=["message", "update_message", "delete_message"])` returns a `queue_id` and the server starts buffering events from that moment.
2. **REST catchup.** `get_messages(anchor=last_message_id, include_anchor=False, num_after=…, apply_markdown=False)` walks forward in batches until `found_newest=True`. Any new message that arrives during this step is also captured by step 3 because the queue is already open.
3. **Live tail.** Loop over `get_events(queue_id, last_event_id)`. On each event, write/update the archive and advance `last_message_id` and `last_event_id` atomically.

This eliminates the race window between catchup and tail and gives us
sub-second latency once the live tail starts. We handle
`BAD_EVENT_QUEUE_ID` (server restart or queue expiry) by re-registering
the queue and re-running the catchup; see *Reconciliation* below for
recovering missed edits/deletes on old messages.

## Stack

- **Make** — user-facing entry point.
- **Python (via `uv`)** — runs the official `zulip` PyPI package.
- **`uv`** — manages a project-local `.venv` and dependency lockfile.
- **`zuliprc` files** (one per workspace) — credentials.

## Architecture

```
Makefile  ──>  uv run scripts/zlp.py <command> [args] --config <zuliprc>
                                │
                                ├──>  zulip.Client (official package) ──>  Zulip REST API
                                ├──>  scripts/format.py     (markdown / json renderers, frontmatter)
                                └──>  scripts/sync_daemon.py (background poller; spawned by `sync`)
```

Four units, each with one responsibility:

| Unit                   | Responsibility                                              | Depends on                          |
|------------------------|-------------------------------------------------------------|-------------------------------------|
| `Makefile`             | Argument validation, workspace selection, UX                | `uv`, `scripts/zlp.py`              |
| `scripts/zlp.py`       | Dispatch subcommand → call Zulip client → render or archive | `zulip` pkg, `format.py`            |
| `scripts/format.py`    | Pure rendering, frontmatter read/write, archive path helpers| (no network)                        |
| `scripts/sync_daemon.py` | Long-running background process: catchup once, then `client.call_on_each_event` for live tail | `zulip` pkg event queue, `zlp.py` for catchup, POSIX signals |

The split keeps `format.py` trivially unit-testable from saved JSON
fixtures, lets `zlp.py` stay small, and isolates daemon-only concerns
(forking, signals, PID files) from the per-call CLI path.

## File layout

```
zulip/
├── Makefile
├── pyproject.toml             # declares "zulip" as the only dep
├── .python-version            # pinned for uv
├── .gitignore                 # configs/*.zuliprc, .venv, mail/, run/
├── README.md                  # quick-start + target reference
├── configs/
│   └── quantum-info.zuliprc   # existing zuliprc, moved here
├── scripts/
│   ├── zlp.py                 # dispatcher
│   ├── sync_daemon.py         # background poller (one process per sync target)
│   └── format.py              # rendering + frontmatter helpers
├── mail/                      # local message archive (gitignored)
│   └── <workspace>/<stream>/<topic|_all>/
│       ├── .sync-state.json   # anchor + stream metadata for this sync target
│       ├── <YYYY-MM-DDTHH-MM-SS>_<sender>_id<msgid>.md      # full message: raw API in YAML frontmatter, markdown body
│       └── _files/<sha1>__<original-name>                   # downloaded attachments
└── run/                       # daemon PID + log files (gitignored)
    └── <workspace>__<stream>__<topic>.{pid,log}
```

The pre-existing `/Users/liujinguo/zulip/zuliprc` is moved to
`configs/quantum-info.zuliprc` during implementation; nothing else in the
repo references the old path.

When `TOPIC` is omitted from a sync target, the topic component of the
path becomes `_all/`, which means "all topics in this stream". Each
`(workspace, stream, topic)` triple is one sync target with its own
state file and its own daemon process.

## Multi-workspace support

- Every target accepts `WORKSPACE=<name>` which maps to `configs/<name>.zuliprc`.
- Default is set in the Makefile: `WORKSPACE ?= quantum-info`. Overridable
  per-call (`make messages WORKSPACE=foo …`) or via shell env (`export WORKSPACE=foo`).
- Adding a workspace = drop a new `<name>.zuliprc` into `configs/`. No code change.
- `make workspaces` lists detected workspace files.
- `zlp.py` accepts `--config <path>` and constructs `zulip.Client(config_file=path)`
  explicitly; the library's `~/.zuliprc` fallback is never used.
- Missing config file → friendly error listing available workspaces, exit 1.

## Make target reference

Conventions for Make variables: `STREAM` (alias `CHANNEL` — Zulip's
modern user-facing term; both resolve to the same arg), `TOPIC`, `TO`
(DM recipient(s) — *not* `USER`, which collides with the shell's
`$USER`), `MSG`, `MSG_FILE` (`-` reads from stdin), `FILE`, `LIMIT`,
`FORMAT`, `QUERY`, `ID`, `WORKSPACE`. Defaults are shown. All
message-fetching paths use `apply_markdown=False` so `content` is the
original markdown source, not rendered HTML.

### Setup / meta
| Target              | Purpose                                                |
|---------------------|--------------------------------------------------------|
| `make install`      | `uv sync` — create `.venv`, install `zulip` + `pyyaml`. |
| `make workspaces`   | List `configs/*.zuliprc` workspaces.                   |
| `make whoami`       | Verify auth: print server URL, account email, and full name. |
| `make help`         | List all targets with one-line descriptions.           |

### Read
| Target | Required vars | Optional vars | Purpose |
|--------|---------------|---------------|---------|
| `make streams` | — | `WORKSPACE` | List streams the user is subscribed to. |
| `make topics` | `STREAM` | `WORKSPACE` | List topics in `STREAM`. |
| `make messages` | `STREAM` | `TOPIC`, `LIMIT=50`, `FORMAT=md`, `WORKSPACE` | Fetch the last `LIMIT` messages from `STREAM`. If `TOPIC` is set, scope to that topic; otherwise across all topics. Output is chronological (oldest → newest). |
| `make search` | `QUERY` | `STREAM`, `LIMIT=20`, `FORMAT=md`, `WORKSPACE` | Full-text search. If `STREAM` is set, scope to that stream; otherwise across all subscribed streams. Output is chronological (oldest → newest). |

### Write
| Target | Required vars | Optional vars | Purpose |
|--------|---------------|---------------|---------|
| `make send` | `STREAM`, `TOPIC`, (`MSG` or `MSG_FILE`) | `WORKSPACE` | Send to `STREAM > TOPIC`. `MSG_FILE=-` reads body from stdin (use this for multi-line / quoted bodies). |
| `make dm` | `TO`, (`MSG` or `MSG_FILE`) | `WORKSPACE` | Send a DM. `TO` may be comma-separated for group DM. |
| `make edit` | `ID`, (`MSG` or `MSG_FILE`) | `WORKSPACE` | Edit your own message by id. |
| `make delete` | `ID` | `WORKSPACE` | Delete your own message by id. |
| `make upload` | `FILE`, `STREAM`, `TOPIC` | `MSG`, `WORKSPACE` | Upload a file and post a message containing the resulting link. |

### Local archive + sync
| Target | Required vars | Optional vars | Purpose |
|--------|---------------|---------------|---------|
| `make pull` | `STREAM` | `TOPIC`, `WORKSPACE`, `IMPORT_HISTORY=0`, `ATTACHMENTS=1` | One-shot catchup via `get_messages` (with `apply_markdown=False`) from `last_message_id` into `mail/<ws>/<stream>/<topic\|_all>/`. Writes one self-contained `.md` per message (full raw API object in frontmatter, markdown body); downloads attachments unless `ATTACHMENTS=0`. Updates `.sync-state.json`. With `IMPORT_HISTORY=1` on first run, fetches all available history; otherwise starts from the newest message. |
| `make sync` | `STREAM` | `TOPIC`, `WORKSPACE`, `ATTACHMENTS=1` | Start a background daemon: register-then-catchup-then-drain (see *Real-time sync mechanism*). Real-time, no polling interval. PID and log under `run/`. |
| `make sync-fg` | `STREAM` | `TOPIC`, `WORKSPACE`, `ATTACHMENTS=1` | Same as `sync` but stays in the foreground for debugging (logs to stderr; SIGINT to stop). |
| `make unsync` | `STREAM` | `TOPIC`, `WORKSPACE` | Stop the daemon for this sync target. Cleans up stale PID files automatically. |
| `make sync-status` | — | `WORKSPACE` | List all sync targets, their last-pulled message id, and whether the daemon is alive. |
| `make sync-log` | `STREAM` | `TOPIC`, `WORKSPACE`, `LINES=50` | Tail the daemon log for this sync target. |
| `make refresh` | `STREAM` | `TOPIC`, `WORKSPACE`, `SINCE=24h` | Reconciliation: re-fetch all known messages newer than `SINCE` and rewrite their `.md`. Recovers edits / deletes / reactions that were missed (e.g. while the daemon was down past queue-expiry). |
| `make inbox` | `STREAM` | `TOPIC`, `LIMIT=20`, `WORKSPACE` | Render the most recent archived messages from disk (offline; works without network). |
| `make grep` | `QUERY` | `STREAM`, `TOPIC`, `WORKSPACE` | Search the local archive (`ripgrep` over `mail/**/*.md`); offline. |

### Argument guards

The Makefile defines:

```make
require = $(if $($(1)),,$(error $(1) is required))
```

…and each target invokes it for its required vars before calling Python,
so missing args fail before any network call.

## Output format

### Markdown (default for `messages`, `search`)

```
## #general > hello   (workspace: quantum-info)

---
**Alice Chen** · 2026-04-26 10:30 · `id:12345`

hello world, here's a thought…

---
**Bob Wu** · 2026-04-26 10:32 · `id:12346`

reply with **markdown** preserved
```

- Server returns `content` already as Zulip markdown — passed through verbatim.
- Header line includes the workspace so piped output is self-identifying.
- Each message has sender · UTC timestamp · `id:` for use with `make edit` / `make delete`.

### JSON (`FORMAT=json`)

The raw `messages` array (or relevant top-level field) from the API is
emitted unchanged so it can be piped to `jq`.

### Other targets

- `streams`, `topics`, `workspaces` — one item per line, plain text.
- `send`, `dm`, `edit`, `delete`, `upload` — print `ok id=<message_id>` on success.

## Sync mechanics

### State file (`mail/<ws>/<stream>/<topic|_all>/.sync-state.json`)

```json
{
  "site": "https://quantum-info.zulipchat.com",
  "workspace": "quantum-info",
  "stream": "general",
  "stream_id": 13,
  "topic": "hello",            // null when topic == _all
  "self_email": "jinguoliu@hkust-gz.edu.cn",
  "last_message_id": 147640
}
```

- `stream_id` and `self_email` are resolved on first `pull` and cached.
- `last_message_id` is the anchor: the next pull uses
  `narrow=[…]` + `anchor=last_message_id` + `include_anchor=False` +
  `num_before=0` + `num_after=5000`, then walks forward in batches
  while `found_newest` is false. The anchor is advanced **only after**
  each batch's archive writes succeed (atomic temp-file + `os.replace`),
  so a crash mid-batch leaves the anchor pointing to the last fully
  archived message — re-run is idempotent.
- The daemon also persists `last_event_id` from `register` /
  `get_events` so a reconnect resumes the event stream without gap.
- On first run with `IMPORT_HISTORY=0` (default): set
  `last_message_id` to the server's current newest message id and store
  no archive (skip backfill). With `IMPORT_HISTORY=1`: set anchor to 0 and
  fetch all available history.

### Per-message storage — single self-contained file

For each message, the daemon writes one file:

```
mail/<ws-slug>/<stream-slug>/<topic-slug|_all>/<UTC>_<sender-slug>_id<msgid>.md
```

Filename example: `2026-04-26T10-30-00_alice_id147641.md`. The
`id<msgid>` suffix makes dedup trivial — re-fetching is idempotent
(skip if the file already exists, unless rewriting due to an edit).

**Path slugging** (applied to `<ws>`, `<stream>`, `<topic>`, `<sender>`):
NFKC-normalize, lowercase, replace any character not in `[a-z0-9._-]`
with `-`, collapse runs of `-`, strip leading/trailing `-`, truncate to
80 chars. If the slug is empty, would equal the reserved literal `_all`,
or collides with an existing slug at that path level, append
`-<8-char-blake2b-hash-of-original>`. The unsanitized originals are
preserved in frontmatter (`subject`, `display_recipient`,
`sender_full_name`).

The file is one Markdown document with **YAML frontmatter holding the
full raw API message object** (every field returned by the server —
`reactions`, `edit_history`, `flags`, `mentions`, `topic_links`,
sender metadata, etc.) and the **markdown body below**. The body comes
from the `content` field, fetched with `apply_markdown=False` so it's
the original markdown source, not rendered HTML. To avoid duplication,
`content` is omitted from the frontmatter — the body *is* the content.

YAML serialization uses `yaml.safe_dump(..., sort_keys=True,
allow_unicode=True, default_flow_style=False)`. Parsing uses
`yaml.safe_load`. Files are written via `tempfile.NamedTemporaryFile`
in the same directory + `os.replace`, so partially-written files never
appear on disk.

Archive-only metadata is namespaced under a single `_archive` key (so
it never collides with future API field additions):

```
---
# Full raw API message object (minus `content`, which is the body):
id: 147641
sender_id: 9821
sender_full_name: Alice Chen
sender_email: alice@example.com
type: stream
display_recipient: general
subject: hello                     # Zulip's term for topic
timestamp: 1745663400              # unix seconds (server's native)
last_edit_timestamp: null
edit_history: null
reactions: []
flags: [read]
mentions: []
topic_links: []
client: website
recipient_id: 4012
avatar_url: https://...
_archive:
  workspace: quantum-info
  fetched_at: 2026-04-26T10:30:01Z
  permalink: https://quantum-info.zulipchat.com/#narrow/channel/13-general/topic/hello/near/147641
  attachments: []                  # relative paths under _files/ (URLs in body remain unchanged)
  deleted: false
---

hello world, here's a thought…
```

**Round-trip guarantee:** `parse_frontmatter(file)` + `body` reconstructs
the original API message object verbatim — re-attach `content = body`,
strip the `_archive` key. The body itself is **never rewritten** (URLs
to `/user_uploads/...` stay verbatim), so round-trip equality holds
even when attachments are downloaded — the local file paths only appear
in `_archive.attachments`. A separate helper `make render ID=<msgid>`
can produce a body with attachment URLs substituted on demand.

**Edits** (`update_message` event): the event may carry one or many
`message_id`s and may also indicate a **topic / channel move** (look
for `subject`/`stream_id` keys in the event). For each affected id:
re-fetch the message via `get_messages`, write the new state, and
**move the file to the new path** if the topic / channel changed (old
path → new slug path). The API's `edit_history` already accumulates the
chain server-side, so previous versions stay in the frontmatter.

**Deletes** (`delete_message` event): the event may carry one or many
`message_id`s. For each id, rename the file to `<...>.md.deleted` and
set `_archive.deleted: true`. Never hard-delete — paper trail is the
point of an archive.

**Reactions are not pushed live.** Reaction state is captured at fetch
time in the `reactions` field; to refresh reaction counts on older
messages, use `make refresh`.

#### Attachments

When a message body contains `/user_uploads/...` URLs, the daemon
downloads each to
`mail/<ws-slug>/<stream-slug>/<topic-slug|_all>/_files/<sha256-12>__<sanitized-original-filename>`
(SHA-256 truncated to 12 hex chars; sanitized filename strips path
separators and control chars, truncates to 80 chars). The body is
**not** rewritten — the original URLs stay verbatim, preserving
round-trip equality. The local paths are listed under
`_archive.attachments` so a renderer can substitute on demand.

Skip attachment download with `ATTACHMENTS=0` (e.g.
`make sync STREAM=general ATTACHMENTS=0`).

Out of v1 scope:
- DM archive / sync (the `_all` and per-topic structure assumes
  channels). DMs can still be fetched ad-hoc with `make dm` (write) and
  `make messages NARROW=is:dm` (future).

### Daemon (`scripts/sync_daemon.py`)

- Spawned via `make sync …`; detached via double-`os.fork()` +
  `os.setsid()` (POSIX-only — fine on macOS/Linux). Writes its PID to
  `run/<ws-slug>__<stream-slug>__<topic-slug>.pid`. `make sync-fg`
  skips the fork and runs in the foreground for debugging.
- Lifecycle (register-then-catchup-then-drain):
  1. `client.register(narrow=…, event_types=["message", "update_message", "delete_message"])` → save `queue_id`, `last_event_id`. Server now buffers events.
  2. **Catchup:** call the same code path as `make pull` (`get_messages` from `last_message_id` forward). Any new messages that arrive during this step are also captured by step 3, so no race.
  3. **Drain loop:** `while True: events = client.get_events(queue_id, last_event_id); for event in events: handle_event(event); last_event_id = event["id"]`. Persist `last_event_id` after each batch.
- `handle_event(event)` per event type:
  - `message` → write `.md` and update `last_message_id` (atomic).
  - `update_message` → for each id in `message_id` / `message_ids`: re-fetch via `get_messages`, write to the (possibly new, on topic/channel move) path, remove the old file if the path changed.
  - `delete_message` → for each id in `message_id` / `message_ids`: rename to `*.md.deleted`, set `_archive.deleted: true`.
  - Other events: ignored.
- On `BAD_EVENT_QUEUE_ID` (server restart / queue expiry past the ~10 min idle window): re-register, re-run catchup, continue drain. Edits / deletes / reactions on already-archived messages that happened during the gap are *not* recovered automatically — run `make refresh` to reconcile.
- Liveness check (used by `make sync-status` and `make unsync`): read PID, `os.kill(pid, 0)` — alive if no exception or `EPERM`. If the PID file exists but the process is dead, `sync-status` flags it as **stale** and `unsync` removes it.
- `make unsync` sends SIGTERM and removes the pid file once the process exits (5-second wait with poll, then SIGKILL fallback). `get_events` returns within ~10 min so SIGTERM is honored promptly between long-polls.
- One sync target = one daemon. Re-running `make sync` for an already-running target is a no-op with a friendly message.

### Reconciliation (`make refresh`)

The event queue closes a known gap: events on already-archived messages
(reactions, edits, deletes) that occur while the daemon is down past
the ~10 min queue-expiry are lost. `make refresh STREAM=…
[TOPIC=…] [SINCE=24h]` re-fetches every message in the archive whose
`timestamp` is within `SINCE` and rewrites the `.md` from the fresh
API object. Run it on a schedule (e.g., daily cron) for full fidelity.

### `make sync-status` output

```
workspace        stream     topic    last_id   daemon  pulled_files
quantum-info     general    hello    147641    alive   42
quantum-info     general    _all     147641    stopped 1284
```

## Error handling

Just enough to make failures debuggable:

- Missing `WORKSPACE` config file → `error: workspace 'foo' not found. Available: quantum-info, …`
- Missing required Make var → caught by the `require` macro before Python runs.
- Zulip API error (`result != "success"`) → print `result` and `msg` from the
  response, exit 1 so Make halts.
- Network/SDK exceptions → traceback to stderr (already useful), exit 1.

No retries, no fancy error classification — these are interactive one-shot commands.

## Testing

| Layer | What | How |
|-------|------|-----|
| `format.py` | Pure rendering + frontmatter helpers | Unit tests with 2–3 saved JSON fixtures (one stream message, one DM, one with markdown content). Round-trip test: render to file → parse back → equal frontmatter. Run via `make test`. |
| `zlp.py` | Command dispatch + API integration | Smoke test target `make test-smoke` that exercises read-only ops (`streams`, `topics`, `messages`) against the real `quantum-info` workspace. Skipped if the config is missing. |
| Sync state logic | Anchor advancement, dedup-by-id | Unit tests on pure functions in `sync_daemon.py` (`next_anchor`, `archive_path_for_message`, `is_already_archived`). |
| Write ops | Send / edit / delete | Manual: `make test-smoke-write` sends a message to a designated test topic, then edits and deletes it. Not run by default. |
| Daemon lifecycle | spawn / status / stop | `make test-smoke-daemon` against a throwaway topic: `sync` → `sync-status` (alive) → `unsync` → `sync-status` (stopped). |

No mocking of the Zulip client — low value vs. the smoke test.

## Open questions

None blocking implementation. Future-work candidates:

- Add admin operations (subscribe, mark-as-read, export) as a v2.
- Make `LIMIT` paginate transparently for large fetches.
- Add `make export STREAM=… > out.md` convenience that combines several
  fetches with a header.
