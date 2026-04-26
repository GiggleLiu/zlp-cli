# zlp-cli

[![PyPI](https://img.shields.io/pypi/v/zlp-cli.svg)](https://pypi.org/project/zlp-cli/)
[![Build](https://img.shields.io/badge/build-pass-brightgreen)](https://github.com/GiggleLiu/zlp-cli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Single-workspace Zulip CLI for humans and AI agents.** `zlp` is a small,
scriptable command-line toolkit that wraps one Zulip account: read streams,
post and edit messages, upload files, and keep a lossless local Markdown
archive that's easy to `grep` and easy for an LLM to read.

It deliberately knows nothing about *which* Zulip workspace it's talking to —
one process, one `zuliprc`, one archive directory. Driving multiple workspaces
is the job of an outer layer that keeps per-workspace credentials and `cd`s into
each before invoking `zlp`.

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
pip install zlp-cli        # or: uv pip install zlp-cli
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

# run one incremental pass over subscribed workspace stream messages
# prints archived file paths for messages written in this pass
zlp pull

# keep the local mirror current in the foreground (Ctrl-C to stop)
zlp sync

# ...or in the background as a daemon
zlp sync --daemon
tail -f run/_workspace.log                 # daemon log with archived file paths

# or narrow sync to one stream
zlp pull --stream general --import-history
zlp pull --stream general                  # one incremental stream pass
zlp sync --daemon --stream general         # background stream daemon
tail -f run/general__*.log                 # stream daemon log
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
| `zlp upload --file F --stream S --topic T [--msg M \| --msg-file F]` | Upload a file and post the link, with an optional message body. |
| `zlp pull [--stream S [--topic T]] [--all-public] [--import-history] [--no-attachments] [--silent]` | One-shot archive catchup; defaults to subscribed workspace streams, or narrows to one stream. Prints archived file paths unless `--silent` is set. |
| `zlp sync [--daemon] [--stream S [--topic T]] [--all-public] [--no-attachments] [--silent]` | Live event-queue sync. Foreground by default (Ctrl-C to stop); pass `--daemon` to run in the background. Defaults to subscribed workspace streams, or narrows to one stream. Prints archived file paths unless `--silent` is set. |
| `zlp unsync [--stream S [--topic T]]` | Stop the workspace sync daemon, or a stream daemon when `--stream` is set. |
| `zlp sync-status` | TSV of archive targets and daemon state. |
| `zlp reconcile --stream S [--topic T] [--since 24h]` | Re-fetch recent archived messages to catch edits and deletes the daemon may have missed. |

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

Workspace `zlp pull` and `zlp sync --daemon` write a workspace-level
`.sync-state.json` directly under `mail/`; individual messages still land under
their normal stream/topic directories. By default they follow the account's
subscribed stream message feed, including subscribed private streams, and
ignore direct messages. `--all-public` is an advanced mode for public channels
beyond the account's subscriptions.

Each `.md` file has YAML frontmatter (sender, ids, timestamp, permalink,
attachments) followed by the message body. Edits rewrite in place; deletions
move the file to `<name>.md.deleted` with `_archive.deleted: true`.

Archive-writing commands emit stable TSV lines by default:

```
archived	<stream-slug>/<topic-slug>/<message-file>.md
deleted	<stream-slug>/<topic-slug>/<message-file>.md.deleted
```

For background daemons, these lines are written to `run/*.log` (workspace daemon
to `run/_workspace.log`, stream daemons to `run/<stream-slug>__<topic-slug>.log`).
Tail those files directly. Pass `--silent` to suppress them.

For agents, `zlp pull` is the normal "what changed since the last pull?" command:
each `archived\t...` line is a file to read for that pass, followed by
`ok archived=N`. The cursor is the archive's `.sync-state.json`; it tracks last
pulled, not a separate per-agent read receipt. Use `zlp sync --daemon` only when
you want continuous background mirroring; tail `run/_workspace.log` to inspect
that daemon's output.

## For agent integrations

The CLI is designed to be the primitive layer below richer integrations:

- **Outer workspace manager.** Keep `zuliprc` files, mail dirs, and run dirs
  outside this package and dispatch `zlp` per account by setting
  `ZULIP_CONFIG_FILE`, `ZLP_ARCHIVE_ROOT`, `ZLP_RUN_ROOT`.
- **MCP / function-calling shells.** Subcommands map cleanly onto tool
  schemas; outputs are stable enough to feed back into a model.
- **CI / cron jobs.** `pull` for snapshots and one-shot incremental catchup,
  `sync --daemon` for live mirrors, `reconcile` for catching missed edits.

## Development

```sh
git clone https://github.com/GiggleLiu/zlp-cli
cd zlp-cli
uv sync
make test
```

Useful developer targets:

```sh
make fmt        # format Python with ruff
make fmt-check  # check formatting
make lint       # run ruff checks
make check      # fmt-check + lint + tests
make build      # build sdist and wheel artifacts
```

Source layout uses `src/zlp/`. Agent-facing workflow notes live in
`AGENTS.md` and `.claude/CLAUDE.md`.

## License

MIT — see [LICENSE](LICENSE).
