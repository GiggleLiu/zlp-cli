# Zulip Make Commands — Design

**Date:** 2026-04-26
**Status:** Approved (pending user spec review)

## Goal

Provide a small, ergonomic `make`-driven toolkit for reading and writing
Zulip stream messages across multiple Zulip workspaces, starting with
`https://quantum-info.zulipchat.com`. Every operation is one make target;
all state lives in version-controllable config files.

## Non-goals

- Admin / management operations (subscribe, mark-as-read, export). Out of v1.
- A full-featured Zulip TUI. Targets are intentionally one-shot CLI calls.
- Reimplementing what the official `zulip` Python client already provides.

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
                                └──>  scripts/format.py  (markdown / json renderers)
```

Three units, each with one responsibility:

| Unit          | Responsibility                                  | Depends on                |
|---------------|-------------------------------------------------|---------------------------|
| `Makefile`    | Argument validation, workspace selection, UX    | `uv`, `scripts/zlp.py`    |
| `scripts/zlp.py` | Dispatch subcommand → call Zulip client → render | `zulip` pkg, `format.py`  |
| `scripts/format.py` | Pure rendering of API responses              | (no I/O, no network)      |

The split keeps `format.py` trivially unit-testable from saved JSON
fixtures, and lets `zlp.py` stay small.

## File layout

```
zulip/
├── Makefile
├── pyproject.toml             # declares "zulip" as the only dep
├── .python-version            # pinned for uv
├── .gitignore                 # configs/*.zuliprc, .venv, __pycache__
├── README.md                  # quick-start + target reference
├── configs/
│   └── quantum-info.zuliprc   # existing zuliprc, moved here
└── scripts/
    ├── zlp.py
    └── format.py
```

The pre-existing `/Users/liujinguo/zulip/zuliprc` is moved to
`configs/quantum-info.zuliprc` during implementation; nothing else in the
repo references the old path.

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
| `format.py` | Pure rendering | Unit tests with 2–3 saved JSON fixtures (one stream message, one DM, one with markdown content). Run via `make test`. |
| `zlp.py` | Command dispatch + API integration | Smoke test target `make test-smoke` that exercises read-only ops (`streams`, `topics`, `messages`) against the real `quantum-info` workspace. Skipped if the config is missing. |
| Write ops | Send / edit / delete | Manual: `make test-smoke-write` sends a message to a designated test topic, then edits and deletes it. Not run by default. |

No mocking of the Zulip client — low value vs. the smoke test.

## Open questions

None blocking implementation. Future-work candidates:

- Add admin operations (subscribe, mark-as-read, export) as a v2.
- Make `LIMIT` paginate transparently for large fetches.
- Add `make export STREAM=… > out.md` convenience that combines several
  fetches with a header.
