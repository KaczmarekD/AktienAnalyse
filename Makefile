# Value-Analyzer - haeufige Kommandos.
# Nutze 'make help' fuer eine Uebersicht.
.PHONY: help install install-dev lock upgrade run dry force test test-cov test-db test-db-up test-db-down lint format typecheck check clean build up down logs restart shell docker-dry docker-run db-up db-migrate db-import db-backup db-shell

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

force: ## Wie run, aber ignoriert den Abruf von heute in der DB
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

check: lint typecheck test ## Alles in einem: lint + typecheck + test (DB-Tests nur mit TEST_DATABASE_URL)

# DB-Tests laufen gegen ein echtes PostgreSQL (jede Testfunktion bekommt eine eigene DB).
TEST_DATABASE_URL ?= postgresql+psycopg://postgres:test@localhost:55432/postgres

test-db-up: ## Wegwerf-Postgres fuer Tests starten (Port 55432)
	docker run -d --rm --name va-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:18
	until docker exec va-test-pg pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done

test-db: ## Alle Tests inkl. DB-Tests (vorher: make test-db-up)
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) pytest

test-db-down: ## Wegwerf-Postgres stoppen (entfernt nur den Test-Container)
	docker stop va-test-pg

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

# ---------- Datenbank (niemals loeschen: es gibt bewusst kein db-reset) -------
db-up: ## Nur die Datenbank starten
	docker compose up -d db

db-migrate: ## Schema-Migrationen ausfuehren (passiert auch bei jedem App-Start)
	docker compose run --rm value-analyzer true

db-import: ## Altdateien aus data/ importieren (mehrfach ausfuehrbar)
	docker compose run --rm value-analyzer python -m src.db.import_legacy /app/data

db-backup: ## Dump nach backups/ (fuer Hyper Backup; alte Dumps bleiben liegen)
	mkdir -p backups
	docker compose exec -T db pg_dump -U va_owner -Fc value_analyzer > backups/value_analyzer_$$(date +%Y%m%d_%H%M%S).dump

db-shell: ## psql als Owner in der Datenbank
	docker compose exec db psql -U va_owner value_analyzer

# ---------- Sauberkeit -------------------------------------------------------
clean: ## Cache und Builds entfernen
	rm -rf .pytest_cache .ruff_cache .pyright .coverage htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
