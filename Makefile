PY = $(if $(wildcard .venv/bin/python),.venv/bin/python,uv run python)
ZLP = $(if $(wildcard .venv/bin/zlp),.venv/bin/zlp,uv run zlp)
STREAM ?= $(CHANNEL)

require = $(if $($(1)),,$(error $(1) is required))
require_msg = $(if $(or $(MSG),$(MSG_FILE)),,$(error MSG or MSG_FILE is required))

.PHONY: install help whoami streams topics messages search send dm edit delete upload pull sync sync-fg unsync sync-status sync-log refresh inbox grep test

install:
	uv sync

help:
	@printf '%s\n' \
	'install       uv sync - create .venv and install dependencies' \
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
	'sync          start background sync daemon' \
	'sync-fg       run sync daemon in foreground' \
	'unsync        stop sync daemon' \
	'sync-status   list sync targets and daemon state' \
	'sync-log      show daemon log tail' \
	'refresh       reconcile recent archived messages' \
	'inbox         render recent archived messages offline' \
	'grep          search local archive offline' \
	'test          run unit tests'

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
	$(ZLP) upload --file "$(FILE)" --stream "$(STREAM)" --topic "$(TOPIC)" $(if $(MSG),--msg "$(MSG)")

pull:
	$(call require,STREAM)
	$(ZLP) pull --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --import-history "$(or $(IMPORT_HISTORY),0)" --attachments "$(or $(ATTACHMENTS),1)"

sync:
	$(call require,STREAM)
	$(ZLP) sync --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --attachments "$(or $(ATTACHMENTS),1)"

sync-fg:
	$(call require,STREAM)
	$(ZLP) sync-fg --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --attachments "$(or $(ATTACHMENTS),1)"

unsync:
	$(call require,STREAM)
	$(ZLP) unsync --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)")

sync-status:
	$(ZLP) sync-status

sync-log:
	$(call require,STREAM)
	$(ZLP) sync-log --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --lines "$(or $(LINES),50)"

refresh:
	$(call require,STREAM)
	$(ZLP) refresh --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --since "$(or $(SINCE),24h)"

inbox:
	$(call require,STREAM)
	$(ZLP) inbox --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --limit "$(or $(LIMIT),20)"

grep:
	$(call require,QUERY)
	$(ZLP) grep --query "$(QUERY)" $(if $(STREAM),--stream "$(STREAM)") $(if $(TOPIC),--topic "$(TOPIC)")

test:
	$(PY) -m unittest discover -s tests
