PY = $(if $(wildcard .venv/bin/python),.venv/bin/python,uv run python)
ZLP = $(if $(wildcard .venv/bin/zlp),.venv/bin/zlp,uv run zlp)
RUFF = $(if $(wildcard .venv/bin/ruff),.venv/bin/ruff,uv run --extra dev ruff)
STREAM ?= $(CHANNEL)

require = $(if $($(1)),,$(error $(1) is required))
require_msg = $(if $(or $(MSG),$(MSG_FILE)),,$(error MSG or MSG_FILE is required))

.PHONY: install help fmt fmt-check lint build check clean whoami streams topics messages search send dm edit delete upload pull sync unsync sync-status reconcile test

install:
	uv sync --extra dev

help:
	@printf '%s\n' \
	'install       uv sync --extra dev - create .venv and install dependencies' \
	'fmt           format Python code with ruff' \
	'fmt-check     check Python formatting with ruff' \
	'lint          run ruff lint checks' \
	'build         build sdist and wheel artifacts' \
	'check         run fmt-check, lint, and tests' \
	'whoami        verify auth (uses ZULIP_CONFIG_FILE or ./zuliprc)' \
	'help          list targets' \
	'streams       list subscribed streams' \
	'topics        list topics in STREAM' \
	'messages      fetch recent messages from STREAM[/TOPIC]' \
	'search        full-text search with QUERY' \
	'send          send MSG or MSG_FILE to STREAM > TOPIC' \
	'dm            send MSG or MSG_FILE to TO' \
	'edit          edit message ID with MSG or MSG_FILE' \
	'delete        delete message ID' \
	'upload        upload FILE and post link to STREAM > TOPIC' \
	'pull          one-shot archive catchup' \
	'sync          live event-queue sync (foreground; pass DAEMON=1 for background)' \
	'unsync        stop sync daemon' \
	'sync-status   list sync targets and daemon state' \
	'reconcile     re-fetch recent archived messages to catch edits/deletes' \
	'test          run unit tests'

fmt:
	$(RUFF) format src tests

fmt-check:
	$(RUFF) format --check src tests

lint:
	$(RUFF) check src tests

build:
	uv build

check: fmt-check lint test

clean:
	rm -rf build dist *.egg-info .ruff_cache .pytest_cache

whoami:
	$(ZLP) whoami

streams:
	$(ZLP) streams

topics:
	$(call require,STREAM)
	$(ZLP) topics --stream "$(STREAM)"

messages:
	$(call require,STREAM)
	$(ZLP) messages --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --limit "$(or $(LIMIT),50)" --format "$(or $(FORMAT),md)"

search:
	$(call require,QUERY)
	$(ZLP) search --query "$(QUERY)" $(if $(STREAM),--stream "$(STREAM)") --limit "$(or $(LIMIT),20)" --format "$(or $(FORMAT),md)"

send:
	$(call require,STREAM)
	$(call require,TOPIC)
	$(call require_msg)
	$(ZLP) send --stream "$(STREAM)" --topic "$(TOPIC)" $(if $(MSG),--msg "$(MSG)") $(if $(MSG_FILE),--msg-file "$(MSG_FILE)")

dm:
	$(call require,TO)
	$(call require_msg)
	$(ZLP) dm --to "$(TO)" $(if $(MSG),--msg "$(MSG)") $(if $(MSG_FILE),--msg-file "$(MSG_FILE)")

edit:
	$(call require,ID)
	$(call require_msg)
	$(ZLP) edit --id "$(ID)" $(if $(MSG),--msg "$(MSG)") $(if $(MSG_FILE),--msg-file "$(MSG_FILE)")

delete:
	$(call require,ID)
	$(ZLP) delete --id "$(ID)"

upload:
	$(call require,FILE)
	$(call require,STREAM)
	$(call require,TOPIC)
	$(ZLP) upload --file "$(FILE)" --stream "$(STREAM)" --topic "$(TOPIC)" $(if $(MSG),--msg "$(MSG)") $(if $(MSG_FILE),--msg-file "$(MSG_FILE)")

pull:
	$(ZLP) pull $(if $(STREAM),--stream "$(STREAM)") $(if $(TOPIC),--topic "$(TOPIC)") $(if $(ALL_PUBLIC),--all-public) $(if $(IMPORT_HISTORY),--import-history) $(if $(NO_ATTACHMENTS),--no-attachments) $(if $(SILENT),--silent)

sync:
	$(ZLP) sync $(if $(STREAM),--stream "$(STREAM)") $(if $(TOPIC),--topic "$(TOPIC)") $(if $(ALL_PUBLIC),--all-public) $(if $(NO_ATTACHMENTS),--no-attachments) $(if $(SILENT),--silent) $(if $(DAEMON),--daemon)

unsync:
	$(ZLP) unsync $(if $(STREAM),--stream "$(STREAM)") $(if $(TOPIC),--topic "$(TOPIC)")

sync-status:
	$(ZLP) sync-status

reconcile:
	$(call require,STREAM)
	$(ZLP) reconcile --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --since "$(or $(SINCE),24h)"

test:
	$(PY) -m unittest discover -s tests
