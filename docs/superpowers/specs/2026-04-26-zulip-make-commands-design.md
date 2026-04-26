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

## Prior art

`~/rcode/cryochamber` ships a Rust binary `cryo-zulip` that does
incremental sync of one stream into a directory of per-message markdown
files using a `zulip-sync.json` anchor. We adopt its **state-file +
per-message markdown + PID-daemon** patterns; we do *not* adopt its
single-stream-per-directory or chamber-session coupling, because this
project is multi-workspace and multi-stream by design.

**One important upgrade over `cryo-zulip`'s polling loop:** the official
`zulip` Python client provides `Client.call_on_each_event(callback,
narrow=…, event_types=…)`, which uses Zulip's real-time **event queue**
(long-polling). The server pushes events the moment they happen, with
auto-reconnect and `BAD_EVENT_QUEUE_ID` recovery built in. We use this
for the live tail, not periodic polling — sub-second latency, lower
server load, and we transparently get edit/delete/reaction events too.

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
│       ├── <YYYY-MM-DDTHH-MM-SS>_<sender>_id<msgid>.md      # human-readable
│       ├── <YYYY-MM-DDTHH-MM-SS>_<sender>_id<msgid>.json    # full raw API object
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

Conventions for Make variables: `STREAM`, `TOPIC`, `USER`, `MSG`, `FILE`,
`LIMIT`, `FORMAT`, `QUERY`, `ID`, `WORKSPACE`. Defaults are shown.

### Setup / meta
| Target              | Purpose                                                |
|---------------------|--------------------------------------------------------|
| `make install`      | `uv sync` — create `.venv`, install `zulip` package.   |
| `make workspaces`   | List `configs/*.zuliprc` workspaces.                   |
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
| `make send` | `STREAM`, `TOPIC`, `MSG` | `WORKSPACE` | Send `MSG` to `STREAM > TOPIC`. |
| `make dm` | `USER`, `MSG` | `WORKSPACE` | Send a DM. `USER` may be comma-separated for group DM. |
| `make edit` | `ID`, `MSG` | `WORKSPACE` | Edit your own message by id. |
| `make delete` | `ID` | `WORKSPACE` | Delete your own message by id. |
| `make upload` | `FILE`, `STREAM`, `TOPIC` | `MSG`, `WORKSPACE` | Upload a file and post a message containing the resulting link. |

### Local archive + sync
| Target | Required vars | Optional vars | Purpose |
|--------|---------------|---------------|---------|
| `make pull` | `STREAM` | `TOPIC`, `WORKSPACE`, `IMPORT_HISTORY=0`, `ATTACHMENTS=1` | One-shot catchup via `get_messages` (with `apply_markdown=False`) from `last_message_id` into `mail/<ws>/<stream>/<topic\|_all>/`. Writes `.md` + `.json` per message; downloads attachments unless `ATTACHMENTS=0`. Updates `.sync-state.json`. With `IMPORT_HISTORY=1` on first run, fetches all available history; otherwise starts from the newest message. |
| `make sync` | `STREAM` | `TOPIC`, `WORKSPACE`, `ATTACHMENTS=1` | Start a background daemon: catchup once via `pull`, then `client.call_on_each_event(...)` for the live tail. Real-time, no polling interval. PID and log under `run/`. |
| `make unsync` | `STREAM` | `TOPIC`, `WORKSPACE` | Stop the daemon for this sync target. |
| `make sync-status` | — | `WORKSPACE` | List all sync targets, their last-pulled message id, and whether the daemon is alive. |
| `make inbox` | `STREAM` | `TOPIC`, `LIMIT=20`, `WORKSPACE` | Render the most recent archived messages from disk (offline; works without network). |

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

## Sync mechanics (ported from `cryo-zulip`)

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
  `narrow=[…]` + `anchor=last_message_id+1` + `num_before=0` +
  `num_after=5000`, then walks forward in batches if `found_newest=false`.
- On first run with `IMPORT_HISTORY=0` (default): set
  `last_message_id` to the server's current newest message id and store
  no archive (skip backfill). With `IMPORT_HISTORY=1`: set anchor to 0 and
  fetch all available history.

### Per-message storage — side-by-side files for completeness

For each message, the daemon writes **two files** under
`mail/<ws>/<stream>/<topic|_all>/`:

1. `<UTC>_<sender>_id<msgid>.md` — human-readable markdown for grep / browse.
2. `<UTC>_<sender>_id<msgid>.json` — the full raw API message object,
   exactly as returned by the server (reactions, edit_history, flags,
   mentions, topic_links, sender metadata — every field).

The `id<msgid>` suffix makes dedup trivial (re-pull is idempotent — skip
if `.json` already exists). The `.md` file is *derived* from the `.json`
and may be regenerated from it.

**Why both:** the `.md` is what you read; the `.json` is what guarantees
you can fully reconstruct or re-export the message later — including
metadata that doesn't fit cleanly into frontmatter (e.g. reactions,
multi-edit history).

#### `.md` file — body and frontmatter

API messages are fetched with `apply_markdown=False` so `content` is the
original Zulip markdown source, not rendered HTML.

```
---
from: Alice Chen
from_email: alice@example.com
sender_id: 9821
stream: general
topic: hello
timestamp: 2026-04-26T10:30:00Z
zulip_message_id: 147641
type: stream
edited: false                  # true if last_edit_timestamp present
deleted: false                 # set true and renamed to .deleted on delete
reactions: 0                   # count; details in .json
attachments: []                # list of relative paths under _files/
source: zulip
---

hello world, here's a thought…
```

This frontmatter is a superset of `cryo-zulip`'s — anything that already
parses cryo files will parse these too. The richer fields (`sender_id`,
`reactions`, `attachments`, `edited`) are extras; the canonical truth
remains in the sibling `.json`.

On `update_message`: rewrite both `.md` and `.json` (the `.json`'s
`edit_history` already accumulates the chain server-side). On
`delete_message`: rename both files to `*.deleted`.

#### Attachments

When a message body contains `/user_uploads/...` URLs, the daemon
downloads each one to
`mail/<ws>/<stream>/<topic|_all>/_files/<sha1>__<original-filename>`
and rewrites the URL in the `.md` body to the relative `_files/...`
path. The `.json` keeps the original URL untouched. SHA-1 prefix
deduplicates files referenced from multiple messages.

Skip attachment download if `--no-attachments` is passed (or
`ATTACHMENTS=0` from Make).

### Daemon (`scripts/sync_daemon.py`)

- Spawned via `make sync …`; detached via `os.fork()` (POSIX-only — fine
  on macOS/Linux). Writes its PID to `run/<ws>__<stream>__<topic>.pid`.
- Lifecycle:
  1. **Catchup:** call the same code path as `make pull` to drain any
     messages added while the daemon was down (using `get_messages`
     anchored at `last_message_id`). This closes the gap between
     `last_message_id` and the server's current tail.
  2. **Live tail:** call
     `client.call_on_each_event(handle_event, narrow=narrow_for_target(),
     event_types=["message", "update_message", "delete_message"])`.
     This blocks. The SDK long-polls `/events`, auto-reconnects on
     network blips, and re-registers the queue on `BAD_EVENT_QUEUE_ID`.
- `handle_event(event)` per event type:
  - `message` → `format.write_archive_file(...)`, then update
    `last_message_id` in `.sync-state.json`.
  - `update_message` → look up `id<msgid>.md` in the archive, rewrite
    body and add an `edited_at` line to frontmatter (or skip if file is
    not present locally — e.g. message predates archive).
  - `delete_message` → rename `id<msgid>.md` to
    `id<msgid>.md.deleted` (don't hard-delete; leaves a paper trail).
- Liveness check (used by `make sync-status` and `make unsync`): read PID,
  `os.kill(pid, 0)` — alive if no exception or `EPERM`.
- `make unsync` sends SIGTERM and removes the pid file once the process
  exits (5-second wait with poll, then SIGKILL fallback). The SDK loop
  is interruptible because long-poll requests have a `~10 min` timeout.
- One sync target = one daemon. Re-running `make sync` for an already-running
  target is a no-op with a friendly message.

### Why event queue, not polling

`call_on_each_event` is Zulip's native real-time mechanism. Versus a
polling loop:

| Aspect           | Polling (`get_messages` every N s)        | `call_on_each_event` (event queue)     |
|------------------|-------------------------------------------|----------------------------------------|
| Latency          | up to N seconds                           | sub-second (server-pushed)             |
| Server load      | repeated paginated `/messages` calls      | one long-poll connection per target    |
| Edits & deletes  | not detected without extra polling logic  | first-class events                     |
| Reconnect        | hand-rolled                               | built into the SDK                     |
| Server restart   | hand-rolled queue-id recovery             | built-in `BAD_EVENT_QUEUE_ID` retry    |
| Code we maintain | the loop, retry, and dedup                | just the per-event callback            |

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
