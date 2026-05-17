# Value-Analyzer - haeufige Kommandos.
# Nutze 'make help' fuer eine Uebersicht.
.PHONY: help install install-dev lock upgrade run dry test test-cov lint format typecheck check clean build up down logs restart shell

PYTHON ?= python3
PIP    ?= pip

help: ## Zeige verfuegbare Targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------- Dependencies ------------------------------------------------------
install: ## Installiere Runtime-Dependencies aus dem Lockfile
	$(PIP) install --no-deps -r requirements.lock

install-dev: ## Installiere Dev-Dependencies (tests, lint, type-check)
	$(PIP) install -r requirements-dev.lock

lock: ## Regeneriere beide Lockfiles aus den .in Dateien
	pip-compile --resolver=backtracking --strip-extras -o requirements.lock requirements.in
	pip-compile --resolver=backtracking --strip-extras -o requirements-dev.lock requirements-dev.in

upgrade: ## Aktualisiere alle Lockfiles auf die neuesten passenden Versionen
	pip-compile --upgrade --resolver=backtracking --strip-extras -o requirements.lock requirements.in
	pip-compile --upgrade --resolver=backtracking --strip-extras -o requirements-dev.lock requirements-dev.in

# ---------- Ausfuehrung -------------------------------------------------------
run: ## Echter Lauf inkl. Mailversand (braucht .env)
	$(PYTHON) -m src.main

dry: ## Dry-Run: erzeugt HTML+CSV ohne Mail
	$(PYTHON) -m src.main --dry-run

force: ## Wie run, aber ignoriert Cache
	$(PYTHON) -m src.main --force-refresh

# ---------- Qualitaetssicherung ----------------------------------------------
test: ## Tests laufen lassen
	pytest

test-cov: ## Tests mit Coverage-Report
	pytest --cov=src --cov-report=term-missing --cov-report=html

lint: ## Code-Style pruefen (ruff)
	ruff check src tests

format: ## Code automatisch formatieren
	ruff format src tests
	ruff check --fix src tests

typecheck: ## Statische Typpruefung
	pyright

check: lint typecheck test ## Alles in einem: lint + typecheck + test

# ---------- Docker auf Synology ---------------------------------------------
build: ## Docker-Image bauen
	docker compose build

up: ## Container starten (Cron-Mode)
	docker compose up -d

down: ## Container stoppen
	docker compose down

restart: down up ## Container neu starten

logs: ## Live-Logs ansehen
	docker compose logs -f

shell: ## Shell im Container
	docker compose run --rm value-analyzer /bin/bash

docker-dry: ## Dry-Run im Container ohne Mail
	docker compose run --rm value-analyzer python -m src.main --dry-run

docker-run: ## Einmaliger echter Lauf im Container
	docker compose run --rm value-analyzer python -m src.main

# ---------- Sauberkeit -------------------------------------------------------
clean: ## Cache und Builds entfernen
	rm -rf .pytest_cache .ruff_cache .pyright .coverage htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
