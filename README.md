# Zulip Make Commands

Small `make` targets for reading, writing, and archiving Zulip messages.
The default workspace is `quantum-info`, mapped to
`configs/quantum-info.zuliprc`.

## Quick Start

```sh
make install
make whoami
make streams
make messages STREAM=general LIMIT=10
make send STREAM=general TOPIC=test MSG='hello from make'
```

`STREAM` and `CHANNEL` are aliases. For multi-line message bodies, use
`MSG_FILE=-` and pipe stdin.

## Targets

| Target | Purpose |
| --- | --- |
| `make install` | Run `uv sync`. |
| `make workspaces` | List `configs/*.zuliprc` workspaces. |
| `make whoami` | Print server URL, account email, and full name. |
| `make help` | List all targets. |
| `make streams` | List subscribed streams. |
| `make topics STREAM=...` | List topics in a stream. |
| `make messages STREAM=... [TOPIC=...] [LIMIT=50] [FORMAT=md]` | Fetch recent messages. |
| `make search QUERY=... [STREAM=...] [LIMIT=20] [FORMAT=md]` | Search Zulip messages. |
| `make send STREAM=... TOPIC=... MSG=...` | Send a stream message. |
| `make dm TO=... MSG=...` | Send a direct message. |
| `make edit ID=... MSG=...` | Edit your own message. |
| `make delete ID=...` | Delete your own message. |
| `make upload FILE=... STREAM=... TOPIC=... [MSG=...]` | Upload a file and post its link. |
| `make pull STREAM=... [TOPIC=...] [IMPORT_HISTORY=0] [ATTACHMENTS=1]` | One-shot archive catchup. |
| `make sync STREAM=... [TOPIC=...] [ATTACHMENTS=1]` | Start background real-time sync. |
| `make sync-fg STREAM=... [TOPIC=...] [ATTACHMENTS=1]` | Run sync in the foreground. |
| `make unsync STREAM=... [TOPIC=...]` | Stop a sync daemon. |
| `make sync-status` | List archive targets and daemon state. |
| `make sync-log STREAM=... [TOPIC=...] [LINES=50]` | Show daemon log tail. |
| `make refresh STREAM=... [TOPIC=...] [SINCE=24h]` | Re-fetch recent archived messages. |
| `make inbox STREAM=... [TOPIC=...] [LIMIT=20]` | Render recent archived messages from disk. |
| `make grep QUERY=... [STREAM=...] [TOPIC=...]` | Search the local archive. |
| `make test` | Run unit tests. |
