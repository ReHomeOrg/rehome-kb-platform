.PHONY: help decrypt-dev decrypt-staging decrypt-prod encrypt-dev edit-dev edit-staging edit-prod rotate sops-check up down logs

# ADR-0009 SOPS wrappers + docker-compose lifecycle. Все sops-команды требуют
# `SOPS_AGE_KEY_FILE` env (path до `~/.config/sops/age/keys.txt` или similar).
# Без age key targets fail loudly — это by design.

REPO_ROOT := $(shell git rev-parse --show-toplevel 2>/dev/null || echo ..)
SECRETS_DIR := $(REPO_ROOT)/deploy/secrets

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
	@echo "sops + age installed; age key reachable."

# ---------------------------------------------------------------------------
# Decrypt: .enc.yaml → .env.local (gitignored)

# Generic recipe; per-env target ниже зовёт его через `$$ENV`.
# `set -e` явно — Makefile-recipe sh не имеет `pipefail` без shell flags.
define decrypt_env =
	@if [ ! -f $(SECRETS_DIR)/$(1).enc.yaml ]; then \
		echo "ERROR: $(SECRETS_DIR)/$(1).enc.yaml не существует."; \
		echo "       Создайте через `make encrypt-$(1) FILE=plain.yaml`."; \
		exit 1; \
	fi
	@sops decrypt $(SECRETS_DIR)/$(1).enc.yaml > $(REPO_ROOT)/.env.local.tmp
	@mv $(REPO_ROOT)/.env.local.tmp $(REPO_ROOT)/.env.local
	@chmod 600 $(REPO_ROOT)/.env.local
	@echo "✓ Decrypted → $(REPO_ROOT)/.env.local (mode 600, gitignored)."
endef

decrypt-dev: sops-check
	$(call decrypt_env,dev)

decrypt-staging: sops-check
	$(call decrypt_env,staging)

decrypt-prod: sops-check
	$(call decrypt_env,prod)

# ---------------------------------------------------------------------------
# Encrypt: plain yaml → .enc.yaml. Caller передаёт FILE=...

encrypt-dev: sops-check
	@if [ -z "$(FILE)" ]; then echo "Usage: make encrypt-dev FILE=path/to/plain.yaml"; exit 1; fi
	@if [ ! -f "$(FILE)" ]; then echo "ERROR: $(FILE) не существует."; exit 1; fi
	@sops encrypt $(FILE) > $(SECRETS_DIR)/dev.enc.yaml
	@echo "✓ Encrypted → deploy/secrets/dev.enc.yaml. Не забудьте commit + удалить $(FILE)."

encrypt-staging: sops-check
	@if [ -z "$(FILE)" ]; then echo "Usage: make encrypt-staging FILE=path/to/plain.yaml"; exit 1; fi
	@sops encrypt $(FILE) > $(SECRETS_DIR)/staging.enc.yaml
	@echo "✓ Encrypted → deploy/secrets/staging.enc.yaml."

encrypt-prod: sops-check
	@if [ -z "$(FILE)" ]; then echo "Usage: make encrypt-prod FILE=path/to/plain.yaml"; exit 1; fi
	@sops encrypt $(FILE) > $(SECRETS_DIR)/prod.enc.yaml
	@echo "✓ Encrypted → deploy/secrets/prod.enc.yaml."

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
	@for env in dev staging prod; do \
		if [ -f $(SECRETS_DIR)/$$env.enc.yaml ]; then \
			echo "Rotating $$env..."; \
			sops rotate -i $(SECRETS_DIR)/$$env.enc.yaml; \
		fi; \
	done
	@echo "✓ Rotation complete."

# ---------------------------------------------------------------------------
# Docker compose convenience.

up:
	@if [ ! -f $(REPO_ROOT)/.env.local ]; then \
		echo "ERROR: .env.local не существует. Run `make decrypt-dev` сперва."; \
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
