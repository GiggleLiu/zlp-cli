WORKSPACE ?= quantum-info
STREAM ?= $(CHANNEL)
CONFIG = configs/$(WORKSPACE).zuliprc
PY = $(if $(wildcard .venv/bin/python),.venv/bin/python,uv run python)

require = $(if $($(1)),,$(error $(1) is required))
require_msg = $(if $(or $(MSG),$(MSG_FILE)),,$(error MSG or MSG_FILE is required))

.PHONY: install workspaces whoami help streams topics messages search send dm edit delete upload pull sync sync-fg unsync sync-status sync-log refresh inbox grep test

install:
	uv sync

workspaces:
	$(PY) scripts/zlp.py --workspace "$(WORKSPACE)" workspaces

whoami:
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" whoami

help:
	@printf '%s\n' \
	'install       uv sync - create .venv and install dependencies' \
	'workspaces    list configs/*.zuliprc workspaces' \
	'whoami        verify auth for WORKSPACE' \
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

streams:
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" streams

topics:
	$(call require,STREAM)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" topics --stream "$(STREAM)"

messages:
	$(call require,STREAM)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" messages --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --limit "$(or $(LIMIT),50)" --format "$(or $(FORMAT),md)"

search:
	$(call require,QUERY)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" search --query "$(QUERY)" $(if $(STREAM),--stream "$(STREAM)") --limit "$(or $(LIMIT),20)" --format "$(or $(FORMAT),md)"

send:
	$(call require,STREAM)
	$(call require,TOPIC)
	$(call require_msg)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" send --stream "$(STREAM)" --topic "$(TOPIC)" $(if $(MSG),--msg "$(MSG)") $(if $(MSG_FILE),--msg-file "$(MSG_FILE)")

dm:
	$(call require,TO)
	$(call require_msg)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" dm --to "$(TO)" $(if $(MSG),--msg "$(MSG)") $(if $(MSG_FILE),--msg-file "$(MSG_FILE)")

edit:
	$(call require,ID)
	$(call require_msg)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" edit --id "$(ID)" $(if $(MSG),--msg "$(MSG)") $(if $(MSG_FILE),--msg-file "$(MSG_FILE)")

delete:
	$(call require,ID)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" delete --id "$(ID)"

upload:
	$(call require,FILE)
	$(call require,STREAM)
	$(call require,TOPIC)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" upload --file "$(FILE)" --stream "$(STREAM)" --topic "$(TOPIC)" $(if $(MSG),--msg "$(MSG)")

pull:
	$(call require,STREAM)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" pull --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --import-history "$(or $(IMPORT_HISTORY),0)" --attachments "$(or $(ATTACHMENTS),1)"

sync:
	$(call require,STREAM)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" sync --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --attachments "$(or $(ATTACHMENTS),1)"

sync-fg:
	$(call require,STREAM)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" sync-fg --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --attachments "$(or $(ATTACHMENTS),1)"

unsync:
	$(call require,STREAM)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" unsync --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)")

sync-status:
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" sync-status

sync-log:
	$(call require,STREAM)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" sync-log --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --lines "$(or $(LINES),50)"

refresh:
	$(call require,STREAM)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" refresh --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --since "$(or $(SINCE),24h)"

inbox:
	$(call require,STREAM)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" inbox --stream "$(STREAM)" $(if $(TOPIC),--topic "$(TOPIC)") --limit "$(or $(LIMIT),20)"

grep:
	$(call require,QUERY)
	$(PY) scripts/zlp.py --config "$(CONFIG)" --workspace "$(WORKSPACE)" grep --query "$(QUERY)" $(if $(STREAM),--stream "$(STREAM)") $(if $(TOPIC),--topic "$(TOPIC)")

test:
	$(PY) -m unittest discover -s tests
