---
name: dev-check
description: Use before finishing changes to choose and run the right verification commands
---

# Dev Check

Use this before claiming a change is complete.

## Step 1: Pick Verification

Run the smallest command that proves the change:

| Change type | Required command |
| --- | --- |
| Python code, CLI behavior, tests | `make check` |
| README or docs only | inspect the rendered/diffed section and run any touched docs checks |
| Packaging, entry points, version metadata | `make check` and `make build` |
| Makefile workflow | relevant `make -n <target>` plus `make check` if tests changed |

## Step 2: Read Output

Check exit status and output. Do not claim success from partial output.

## Step 3: Report

Report:
- command run
- pass/fail status
- any skipped verification and why

If verification fails, stop and report the failure before moving on.
