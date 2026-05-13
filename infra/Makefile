.PHONY: help decrypt-dev decrypt-staging decrypt-prod encrypt-dev edit-dev edit-staging edit-prod rotate sops-check up down logs

# ADR-0009 SOPS wrappers + docker-compose lifecycle. Все sops-команды требуют
# `SOPS_AGE_KEY_FILE` env (path до `~/.config/sops/age/keys.txt` или similar).
# Без age key targets fail loudly — это by design.

REPO_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo ..)
SECRETS_DIR := $(REPO_ROOT)/deploy/secrets

# Один источник истины для списка environments. Используется в `rotate`
# target'е и косвенно: per-env targets ниже именуются `*-dev`, `*-staging`,
# `*-prod`. Если добавляется новый env — также обновить `.sops.yaml`.
ENVS := dev staging prod

help:
	@echo "SOPS targets:"
	@echo "  make decrypt-dev       — deploy/secrets/dev.enc.yaml → .env.local"
	@echo "  make decrypt-staging   — same для staging"
	@echo "  make decrypt-prod      — same для prod"
	@echo "  make encrypt-dev FILE=path/to/plain.yaml — plain → dev.enc.yaml"
	@echo "  make edit-{dev,staging,prod}   — in-place sops edit"
	@echo "  make rotate            — rotate age recipients для всех envs"
	@echo "  make sops-check        — verify sops + age installed"
	@echo ""
	@echo "Docker-compose:"
	@echo "  make up   — docker compose up -d (требует .env.local)"
	@echo "  make down — docker compose down"
	@echo "  make logs SERVICE=... — tail logs"

# ---------------------------------------------------------------------------
# SOPS sanity check

sops-check:
	@command -v sops >/dev/null 2>&1 || { echo "ERROR: sops not installed. См. deploy/secrets/README.md"; exit 1; }
	@command -v age >/dev/null 2>&1 || { echo "ERROR: age not installed. См. deploy/secrets/README.md"; exit 1; }
	@if [ -z "$$SOPS_AGE_KEY_FILE" ] && [ ! -f $$HOME/.config/sops/age/keys.txt ]; then \
		echo "ERROR: SOPS_AGE_KEY_FILE не выставлен и ~/.config/sops/age/keys.txt отсутствует."; \
		echo "       См. ADR-0009 и deploy/secrets/README.md (Использование)."; \
		exit 1; \
	fi
	@echo "sops + age available; age key in expected location."

# ---------------------------------------------------------------------------
# Decrypt: .enc.yaml → .env.local (gitignored)

# Generic recipe; per-env target ниже зовёт через `$(call decrypt_env,<env>)`.
# Atomic chain в одном shell'е: tmp file создаётся под umask 077 (mode 600
# от рождения), затем mv. На любой failure — explicit cleanup tmp'а.
define decrypt_env =
	@if [ ! -f $(SECRETS_DIR)/$(1).enc.yaml ]; then \
		echo "ERROR: $(SECRETS_DIR)/$(1).enc.yaml не существует."; \
		echo "       Создайте через make encrypt-$(1) FILE=plain.yaml"; \
		exit 1; \
	fi
	@(umask 077 && sops decrypt $(SECRETS_DIR)/$(1).enc.yaml > $(REPO_ROOT)/.env.local.tmp) \
		&& mv $(REPO_ROOT)/.env.local.tmp $(REPO_ROOT)/.env.local \
		|| { rm -f $(REPO_ROOT)/.env.local.tmp; exit 1; }
	@echo "Decrypted -> $(REPO_ROOT)/.env.local (mode 600, gitignored)."
endef

decrypt-dev: sops-check
	$(call decrypt_env,dev)

decrypt-staging: sops-check
	$(call decrypt_env,staging)

decrypt-prod: sops-check
	$(call decrypt_env,prod)

# ---------------------------------------------------------------------------
# Encrypt: plain yaml → .enc.yaml. Caller передаёт FILE=...

# Generic recipe — DRY между encrypt-{dev,staging,prod}. Все три ветви
# проверяют FILE существование (раньше только dev делал — inconsistency).
define encrypt_env =
	@if [ -z "$(FILE)" ]; then echo "Usage: make encrypt-$(1) FILE=path/to/plain.yaml"; exit 1; fi
	@if [ ! -f "$(FILE)" ]; then echo "ERROR: $(FILE) не существует."; exit 1; fi
	@sops encrypt $(FILE) > $(SECRETS_DIR)/$(1).enc.yaml
	@echo "Encrypted -> deploy/secrets/$(1).enc.yaml. Не забудьте commit + удалить $(FILE)."
endef

encrypt-dev: sops-check
	$(call encrypt_env,dev)

encrypt-staging: sops-check
	$(call encrypt_env,staging)

encrypt-prod: sops-check
	$(call encrypt_env,prod)

# ---------------------------------------------------------------------------
# In-place edit (decrypt → $$EDITOR → re-encrypt).

edit-dev: sops-check
	@sops $(SECRETS_DIR)/dev.enc.yaml

edit-staging: sops-check
	@sops $(SECRETS_DIR)/staging.enc.yaml

edit-prod: sops-check
	@sops $(SECRETS_DIR)/prod.enc.yaml

# ---------------------------------------------------------------------------
# Rotate: пересhифровать всё под current `.sops.yaml` recipients.
# Используется после `age-keygen` нового key и его добавления в `.sops.yaml`.

rotate: sops-check
	@for env in $(ENVS); do \
		if [ -f $(SECRETS_DIR)/$$env.enc.yaml ]; then \
			echo "Rotating $$env..."; \
			sops rotate -i $(SECRETS_DIR)/$$env.enc.yaml; \
		fi; \
	done
	@echo "Rotation complete."

# ---------------------------------------------------------------------------
# Docker compose convenience.

# NB safety hole (закрывается в item 3 / PR следующий за #119):
# docker-compose.yml сейчас имеет `${POSTGRES_KB_PASSWORD:-kb}` fallback.
# Даже если `.env.local` пустой — `make up` зайдёт с password `kb`. После
# item 3 (compose cleanup) ${VAR:-default} для secrets уйдёт → empty .env.local
# приведёт к compose error на startup.
up:
	@if [ ! -f $(REPO_ROOT)/.env.local ]; then \
		echo "ERROR: .env.local не существует. Run make decrypt-dev сперва."; \
		exit 1; \
	fi
	docker compose --env-file $(REPO_ROOT)/.env.local up -d

down:
	docker compose down

logs:
	@if [ -z "$(SERVICE)" ]; then \
		docker compose logs --tail=100 -f; \
	else \
		docker compose logs --tail=100 -f $(SERVICE); \
	fi
