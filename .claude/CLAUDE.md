# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`zlp` is a single-workspace Zulip CLI for humans and AI agents. It wraps one Zulip account, supports online read/write commands, and maintains a local Markdown archive for offline search and LLM-friendly context.

`AGENTS.md` at the repo root covers the same agent-facing surface for non-Claude tools. When changing agent-facing behavior, update both files so they don't drift.

## Philosophy

- Keep the CLI scriptable: commands should have predictable flags and stable text or JSON output.
- Keep workspace concerns outside this package: one process, one `zuliprc`, one archive root.
- Prefer small, testable command handlers over broad abstractions.
- Treat archive data as durable user data. Be conservative with deletes, migrations, and path changes.

## Skills

Repo-local skills live under `.claude/skills/*/SKILL.md`.

- [add-command](skills/add-command/SKILL.md) -- Use when adding or changing a `zlp` CLI command.
- [dev-check](skills/dev-check/SKILL.md) -- Use before finishing changes to pick and run the right verification commands.

## Commands

Run `make help` for the full list. Common targets: `install`, `fmt`, `fmt-check`, `lint`, `test`, `check` (fmt-check + lint + test), `build`. Zulip-facing wrappers (`make whoami`, `make streams`, `make messages STREAM=...`, `make send STREAM=... TOPIC=... MSG=...`, `make inbox STREAM=...`) are convenience shims over the CLI.

### Running a single test

```bash
uv run python -m unittest tests.test_cli -v
uv run python -m unittest tests.test_cli.TestSendCommand.test_sends_with_topic
```

### Running the CLI from source

```bash
uv run python -m zlp whoami
uv run zlp messages --stream general --limit 5
```

## Architecture

- `src/zlp/cli.py` -- argparse surface and command handlers. Parser subcommand `foo-bar` dispatches to handler `cmd_foo_bar`. Commands that don't need a live Zulip client must be listed in `NO_CLIENT_COMMANDS`.
- `src/zlp/format.py` -- rendering, slugging, archive file parsing/writing. Owns the YAML-frontmatter `.md` format under `mail/<stream>/<topic>/`.
- `src/zlp/sync.py` -- event-queue sync loop and archive reconciliation helpers. Daemons drop pid/log files under `--run-root` (default `./run`).
- `tests/` -- unittest suite; uses `TemporaryDirectory` for filesystem state and `unittest.mock` for Zulip clients. Tests must not require real credentials or network access.
- `.github/workflows/ci.yml` -- test matrix, lint, and distribution build checks.

## CLI Command Conventions

- Commands that read or write the archive should honor `--archive-root` (env: `ZLP_ARCHIVE_ROOT`).
- Daemon commands should honor `--run-root` (env: `ZLP_RUN_ROOT`).
- User-facing output should stay easy to parse: TSV for status tables, Markdown for human message views, and JSON where a command exposes `--format json`.

## Testing Requirements

- New command behavior needs unit tests in `tests/`.
- Tests must not require real Zulip credentials or network access.
- Use `TemporaryDirectory` for filesystem state and `unittest.mock` for Zulip clients.
- Update README command documentation when the CLI surface changes.
- Run `make check` before claiming a change is complete.

## Git Safety

- Do not force push.
- Do not delete user archives, credentials, or daemon state during tests or cleanup.
- Do not commit local `zuliprc`, `mail/`, `run/`, or generated cache files.
