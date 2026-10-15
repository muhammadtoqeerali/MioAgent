.PHONY: init start stop status logs test lint
ENV_FILE := $(HOME)/.config/mioagent/.env
init:
	python3 scripts/init_env.py
start:
	docker compose --env-file $(ENV_FILE) up -d --build
stop:
	docker compose --env-file $(ENV_FILE) down
status:
	docker compose --env-file $(ENV_FILE) ps
logs:
	docker compose --env-file $(ENV_FILE) logs -f --tail=80
test:
	python3 -m pytest -q
lint:
	python3 -m ruff check mio tests scripts
