---
name: add-command
description: Use when adding or changing a zlp CLI command
---

# Add Command

Use this when adding a new `zlp` subcommand or changing an existing command's behavior.

## Step 0: Define Behavior

Before editing, identify:
- command name and purpose
- required and optional flags
- whether it needs a live Zulip client
- whether it reads or writes the archive
- output format and exit-code behavior
- README and Makefile impact

If the command can work offline, add it to `NO_CLIENT_COMMANDS`.

## Step 1: Write Tests First

Add or update tests under `tests/`.

Preferred patterns:
- use `TemporaryDirectory` for archive and run roots
- use `unittest.mock` for Zulip client behavior
- patch `sys.argv` rather than shelling out unless testing process-level behavior
- assert stdout, stderr, return code, and filesystem effects

Watch the relevant test fail before implementation.

## Step 2: Implement the CLI Surface

In `src/zlp/cli.py`:
- add the subparser and flags in `main()`
- implement `cmd_<command_name>()`
- reuse helpers such as `check()`, `read_body()`, `narrow_for()`, and format/archive functions
- keep command output stable and easy to parse

Avoid broad refactors while adding a command.

## Step 3: Document and Wrap

Update:
- `README.md` command table and examples when user-facing behavior changes
- `Makefile` only for common ergonomic workflows, not every CLI flag combination

## Step 4: Verify

Run:

```bash
make check
```

For packaging, release, or entry-point changes, also run:

```bash
make build
```

Report any failures with the exact command that failed.

## Common Mistakes

| Mistake | Fix |
| --- | --- |
| Command accidentally requires `zuliprc` | Add client-free commands to `NO_CLIENT_COMMANDS` |
| Tests use real Zulip credentials | Mock the client and use temp dirs |
| Output is hard to parse | Prefer stable Markdown, JSON, or TSV |
| README omitted | Update the command table and examples |
| Archive paths are hardcoded | Use `args.archive_root` and helpers |
