# zlp

[![PyPI](https://img.shields.io/pypi/v/zlp.svg)](https://pypi.org/project/zlp/)
[![Python](https://img.shields.io/pypi/pyversions/zlp.svg)](https://pypi.org/project/zlp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Single-workspace Zulip CLI for humans and AI agents.** `zlp` is a small,
scriptable command-line toolkit that wraps one Zulip account: read streams,
post and edit messages, upload files, and keep a lossless local Markdown
archive that's easy to `grep` and easy for an LLM to read.

It deliberately knows nothing about *which* Zulip workspace it's talking to —
one process, one `zuliprc`, one archive directory. Driving multiple workspaces
is the job of an outer layer (e.g. a sibling `zulip-workspaces/` repo that
keeps per-workspace credentials and `cd`s into each before invoking `zlp`).

## Why

- **Agent-friendly.** Predictable subcommands, machine-parseable output
  (Markdown with YAML frontmatter, JSON via `--format json`, TSV for status).
  An agent shell can call `zlp messages --stream X` and get usable text back
  without parsing HTML.
- **Local-first archive.** Every message lands as its own `.md` file with
  attachments next to it, making the chat corpus another grep-able knowledge
  base alongside your code repo.
- **Real-time.** A background daemon tails Zulip's event queue (no polling),
  so the local archive stays current automatically.
- **One zuliprc, one job.** No multi-tenant logic, no implicit globals — easy
  to drop into containers, CI, or a per-agent sandbox.

## Install

```sh
pip install zlp        # or: uv pip install zlp
```

This installs the `zlp` console script. You'll also need a `zuliprc` file —
create one at <https://YOUR-ZULIP-SERVER/api/api-keys> and save it.

## Quick start

```sh
export ZULIP_CONFIG_FILE=/path/to/zuliprc

zlp whoami
zlp streams
zlp messages --stream general --limit 10
zlp send --stream general --topic test --msg 'hello from zlp'

# keep a local mirror of one stream
zlp pull --stream general --import-history 1
zlp sync --stream general                  # background daemon
zlp inbox --stream general --limit 20      # offline render
zlp grep --stream general --query "release notes"
```

For multi-line message bodies pipe stdin: `zlp send ... --msg-file -`.

## Configuration

Three settings, with this precedence: **flag > env > default**.

| Setting | Flag | Env var | Default |
| --- | --- | --- | --- |
| zuliprc path | `--config` | `ZULIP_CONFIG_FILE` | `./zuliprc` |
| archive root | `--archive-root` | `ZLP_ARCHIVE_ROOT` | `./mail` |
| daemon pid/log root | `--run-root` | `ZLP_RUN_ROOT` | `./run` |

Defaults are CWD-relative. An outer "workspace manager" can `cd` into a
per-workspace directory or set the env vars to point at workspace-specific
locations — `zlp` itself stays workspace-agnostic.

## Commands

| Command | What it does |
| --- | --- |
| `zlp whoami` | Print server URL, account email, and full name. |
| `zlp streams` | List subscribed streams, one per line. |
| `zlp topics --stream S` | List topics in a stream. |
| `zlp messages --stream S [--topic T] [--limit N] [--format md\|json]` | Fetch recent messages. |
| `zlp search --query Q [--stream S] [--limit N] [--format md\|json]` | Server-side full-text search. |
| `zlp send --stream S --topic T (--msg M \| --msg-file F)` | Send a stream message. |
| `zlp dm --to EMAIL[,EMAIL] (--msg \| --msg-file)` | Send a direct message. |
| `zlp edit --id N (--msg \| --msg-file)` | Edit your own message. |
| `zlp delete --id N` | Delete your own message. |
| `zlp upload --file F --stream S --topic T [--msg M]` | Upload a file and post the link. |
| `zlp pull --stream S [--topic T] [--import-history 0\|1] [--attachments 0\|1]` | One-shot archive catchup. |
| `zlp sync --stream S [--topic T] [--attachments 0\|1]` | Start background sync daemon. |
| `zlp sync-fg --stream S ...` | Run sync in the foreground. |
| `zlp unsync --stream S [--topic T]` | Stop a sync daemon. |
| `zlp sync-status` | TSV of archive targets and daemon state. |
| `zlp sync-log --stream S [--topic T] [--lines N]` | Show daemon log tail. |
| `zlp refresh --stream S [--topic T] [--since 24h]` | Re-fetch recent archived messages. |
| `zlp inbox --stream S [--topic T] [--limit N]` | Render recent archived messages from disk. |
| `zlp grep --query Q [--stream S] [--topic T]` | Search the local archive (uses `rg` if installed). |

A `Makefile` is included for convenience (`make whoami`, `make send STREAM=...`, etc.).

## Archive layout

Under `--archive-root`:

```
mail/
└── <stream-slug>/
    └── <topic-slug | _all>/
        ├── 2026-04-26T02-30-00_alice-chen_id147641.md   # one file per message
        ├── _files/<sha-prefix>__attachment.pdf          # downloaded attachments
        └── .sync-state.json                             # incremental cursor
```

Each `.md` file has YAML frontmatter (sender, ids, timestamp, permalink,
attachments) followed by the message body. Edits rewrite in place; deletions
move the file to `<name>.md.deleted` with `_archive.deleted: true`.

## For agent integrations

The CLI is designed to be the primitive layer below richer integrations:

- **Outer workspace manager.** Keep `zuliprc` files, mail dirs, and run dirs in
  a separate repo (e.g. `zulip-workspaces/<account>/`) and dispatch `zlp` per
  account by setting `ZULIP_CONFIG_FILE`, `ZLP_ARCHIVE_ROOT`, `ZLP_RUN_ROOT`.
- **MCP / function-calling shells.** Subcommands map cleanly onto tool
  schemas; outputs are stable enough to feed back into a model.
- **CI / cron jobs.** `pull` for snapshots, `sync` for live mirrors,
  `refresh` for reconciliation.

## Development

```sh
git clone https://github.com/GiggleLiu/zulip-management
cd zlp
uv sync
make test
```

Source layout uses `src/zlp/`. Build wheels with `uv build` (or `python -m build`).

## License

MIT — see [LICENSE](LICENSE).
