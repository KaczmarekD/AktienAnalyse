# Value-Analyzer - haeufige Kommandos.
# Nutze 'make help' fuer eine Uebersicht.
.PHONY: help install install-dev lock upgrade run dry force test test-cov test-db test-db-up test-db-down test-nats test-nats-up test-nats-down nats-provision lint format typecheck imports check check-j4125 clean pull build up down logs restart shell docker-dry docker-run db-up db-migrate db-import db-backup db-shell regression regression-export local-up local-run local-dry local-regression local-logs local-down local-ui local-e2e local-check api api-breaking ui-install ui ui-api ui-check ui-e2e-install

# Alle Python-Befehle laufen ueber uv im Projekt-Environment (.venv, aus uv.lock).
# --locked: bricht ab, wenn uv.lock nicht mehr zu pyproject.toml passt (dann: make lock),
# statt still neu zu locken.
UV     ?= uv
RUN    ?= $(UV) run --locked
PYTHON ?= $(RUN) python
# Python-Code fuer Ruff (Pyright: [tool.pyright] include in pyproject.toml)
PY_PATHS = src tests docker packages services migrations

help: ## Zeige verfuegbare Targets
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

# ---------- Dependencies (uv, ADR-0004) ----------------------------------------
install: ## Runtime-Dependencies exakt aus uv.lock installieren
	$(UV) sync --locked --no-dev

install-dev: ## Alle Dependencies inkl. Dev-Tools exakt aus uv.lock installieren
	$(UV) sync --locked

lock: ## uv.lock nach Aenderungen an pyproject.toml aktualisieren (Versionen bleiben)
	$(UV) lock

upgrade: ## Alle Pakete auf die neuesten passenden Versionen heben
	$(UV) lock --upgrade

# ---------- Ausfuehrung -------------------------------------------------------
run: ## Echter Lauf inkl. Mailversand (braucht .env)
	$(PYTHON) -m src.main

dry: ## Dry-Run: erzeugt HTML+CSV ohne Mail
	$(PYTHON) -m src.main --dry-run

force: ## Wie run, aber ignoriert den Abruf von heute in der DB
	$(PYTHON) -m src.main --force-refresh

api: ## web-api aus der .venv mit Reload, Swagger unter http://localhost:8000/api/docs
	$(RUN) uvicorn --factory src.web:create_app --reload --host 127.0.0.1 --port 8000

api-breaking: ## REST-API abwaertskompatibel zu main? (oasdiff breaking, P3.8; braucht Docker)
	git fetch -q origin main
	bash docker/api-breaking.sh origin/main

# ---------- Qualitaetssicherung ----------------------------------------------
test: ## Tests laufen lassen
	$(RUN) pytest

test-cov: ## Tests mit Coverage-Report
	$(RUN) pytest --cov=src --cov=va_contracts --cov=va_platform --cov=va_market_data --cov=va_scoring --cov=va_notification --cov=va_web_api --cov-report=term-missing --cov-report=html

lint: ## Code-Style pruefen (ruff check + Format-Check wie in der CI)
	$(RUN) ruff check $(PY_PATHS)
	$(RUN) ruff format --check $(PY_PATHS)

format: ## Code automatisch formatieren
	$(RUN) ruff format $(PY_PATHS)
	$(RUN) ruff check --fix $(PY_PATHS)

typecheck: ## Statische Typpruefung
	$(RUN) pyright

imports: ## Grenzen zwischen den Workspace-Paketen pruefen (import-linter)
	$(RUN) lint-imports

check: lint typecheck imports test ## Alles in einem: lint + typecheck + imports + test (DB-Tests nur mit TEST_DATABASE_URL)

# DB-Tests laufen gegen ein echtes PostgreSQL (jede Testfunktion bekommt eine eigene DB).
TEST_DATABASE_URL ?= postgresql+psycopg://postgres:test@localhost:55432/postgres

test-db-up: ## Wegwerf-Postgres fuer Tests starten (Port 55432)
	docker run -d --rm --name va-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:18
	until docker exec va-test-pg pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done

test-db: ## Alle Tests inkl. DB-Tests (vorher: make test-db-up)
	TEST_DATABASE_URL=$(TEST_DATABASE_URL) $(RUN) pytest

test-db-down: ## Wegwerf-Postgres stoppen (entfernt nur den Test-Container)
	docker stop va-test-pg

# Wegwerf-NATS mit JetStream fuer die Integrationstests (P4.1); gleiche Version wie im Compose
TEST_NATS_URL ?= nats://127.0.0.1:54222

test-nats-up: ## Wegwerf-NATS mit JetStream fuer Tests starten (Port 54222)
	docker run -d --rm --name va-test-nats -p 54222:4222 nats:2.15.1-alpine -js

test-nats: ## Integrationstests gegen NATS (vorher: make test-nats-up)
	TEST_NATS_URL=$(TEST_NATS_URL) $(RUN) pytest packages/va-platform/tests tests/test_pipeline_bus.py tests/test_main_nats.py

test-nats-down: ## Wegwerf-NATS stoppen (entfernt nur den Test-Container)
	docker stop va-test-nats

nats-provision: ## Stream und Consumer im lokalen NATS anlegen bzw. angleichen (P4.1)
	NATS_URL=nats://127.0.0.1:4222 $(RUN) python -m va_platform.nats

# J4125 der NAS (ADR-0008): kein AVX/AVX2. Die Stufe j4125-check im Dockerfile ist das
# App-Image plus QEMU; Python laeuft dort mit einem CPU-Modell ohne AVX. Braucht ein Paket
# x86-64-v3, bricht der Lauf mit "Illegal instruction" (Exit-Code 132) ab.
check-j4125: ## Nach make lock/upgrade und vor dem Deployment: Image unter QEMU ohne AVX pruefen
	docker build --platform linux/amd64 --target j4125-check -t value-analyzer:j4125-check .
	docker run --rm --platform linux/amd64 value-analyzer:j4125-check

# ---------- Docker auf Synology ---------------------------------------------
# Die NAS baut nicht selbst (ADR-0008): Images kommen aus der CI (GHCR).
# Name wie in docker-compose.yml. Steht VERSION in der .env, nutzt Compose dieses Tag:
# dann lokal z. B. make build VERSION=sha-1234567 (make liest die .env nicht).
REG ?= ghcr.io/kaczmarekd
VERSION ?= latest
IMAGE ?= $(REG)/value-analyzer:$(VERSION)

pull: ## Images aus GHCR laden: App-Image, Services, web-api und frontend (NAS: danach make up)
	docker compose --profile run pull

build: ## Image lokal bauen, unter dem Namen aus docker-compose.yml (nicht auf der NAS)
	docker build --target runtime -t $(IMAGE) .

up: ## Stack starten: Migration, NATS, Services, web-api mit Wochenplan, frontend
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

db-migrate: ## Schema-Migrationen ausfuehren (passiert auch bei jedem make up)
	docker compose run --rm migrate

db-import: ## Altdateien aus data/ importieren (mehrfach ausfuehrbar)
	docker compose run --rm value-analyzer python -m src.db.import_legacy /app/data

db-backup: ## Dump nach backups/ (fuer Hyper Backup; alte Dumps bleiben liegen)
	mkdir -p backups
	docker compose exec -T db pg_dump -U va_owner -Fc value_analyzer > backups/value_analyzer_$$(date +%Y%m%d_%H%M%S).dump

db-shell: ## psql als Owner in der Datenbank
	docker compose exec db psql -U va_owner value_analyzer

# Replay-Regression (P2b.0): bewertet gespeicherte Wochen mit dem Code dieses Images neu und
# vergleicht mit dem Ergebnis von damals. Schreibt nichts in die DB. Nach make pull, vor make up.
regression: ## Gespeicherte Wochen mit diesem Image nachspielen und vergleichen (schreibt nichts)
	docker compose run --rm value-analyzer python -m src.regression

regression-export: ## Wie regression, dazu je Lauf eine Fixture nach data/replay/ (fuer die CI)
	docker compose run --rm value-analyzer python -m src.regression --export /app/data/replay

# ---------- Lokaler Stack (U1, docs/architecture/umgebungen.md) -------------
# Auf dem Entwicklungsrechner: .env aus .env.local.example. Das Image entsteht aus dem
# Arbeitsstand, Mails landen in Mailpit, kein Healthcheck-Ping. Die NAS nutzt diese Targets nicht.
LOCAL = docker compose -f docker-compose.yml -f docker-compose.local.yml

local-up: ## Lokal: DB, NATS, Mailpit (:8025), pgweb (:8081), web-api (:8000) und Worker starten
	$(LOCAL) build value-analyzer
	$(LOCAL) up -d

local-run: ## Lokal: ein Lauf mit dem Arbeitsstand, die Mail landet in Mailpit
	$(LOCAL) run --rm --build value-analyzer python -m src.main

local-dry: ## Lokal: Dry-Run mit dem Arbeitsstand (Vorschau nach data/, keine Mail)
	$(LOCAL) run --rm --build value-analyzer python -m src.main --dry-run

local-regression: ## Lokal: gespeicherte Wochen mit dem Arbeitsstand nachspielen
	$(LOCAL) run --rm --build value-analyzer python -m src.regression

local-logs: ## Lokal: Logs von DB, Mailpit und pgweb verfolgen
	$(LOCAL) logs -f

local-ui: ## Lokal: frontend (nginx) aus dem Arbeitsstand unter http://localhost:8080 (braucht Platz)
	$(LOCAL) --profile ui up -d --build frontend

local-down: ## Lokal: alles stoppen (die Daten in .local/ bleiben)
	$(LOCAL) --profile run --profile ui down

# ---------- E2E-Test (U5, docs/architecture/umgebungen.md) ------------------
# Wegwerf-Stack mit Replay-Daten statt Yahoo: Datenbank auf tmpfs, UI unter :18080, Mailpit
# unter :18025. Laeuft neben dem lokalen Stack. Die CI ruft docker/e2e.sh mit ihren Images auf.
E2E = docker compose --env-file docker/e2e.env -f docker-compose.yml -f docker-compose.local.yml -f docker-compose.e2e.yml

local-e2e: ## Lokal: ganze Kette mit Replay-Daten pruefen (Batch, Mail, API, UI), danach aufraeumen
	cd frontend && npm run build
	$(E2E) build value-analyzer frontend
	bash docker/e2e.sh

local-check: ## Lokal: Mail, API und UI des lokalen Stacks zum letzten Lauf pruefen (braucht make local-ui)
	E2E_BASE_URL=http://127.0.0.1:8080 E2E_MAILPIT_URL=http://127.0.0.1:8025 $(RUN) pytest tests/e2e -p no:cacheprovider
	cd frontend && E2E_BASE_URL=http://127.0.0.1:8080 PLAYWRIGHT_BROWSERS_PATH=../.local/playwright npx playwright test

# ---------- Frontend (P3.5, docs/architecture/frontend.md) ------------------
# Node laeuft nur lokal und in der CI, nie auf der NAS. Das UI holt seine Daten ueber /api vom
# web-api (make api oder make local-up); ng serve leitet /api an 127.0.0.1:8000 weiter.
ui-install: ## Frontend: Abhaengigkeiten exakt aus package-lock.json
	cd frontend && npm ci

ui: ## Frontend mit Reload unter http://localhost:4200 (braucht das web-api auf :8000)
	cd frontend && npm start

ui-api: ## Frontend: API-Client aus tests/golden/openapi/v1.json neu erzeugen
	cd frontend && npm run generate:api

ui-e2e-install: ## Frontend: Chromium fuer die Browser-Tests (U5.3) nach .local/playwright, nicht auf C:
	cd frontend && PLAYWRIGHT_BROWSERS_PATH=../.local/playwright npx playwright install chromium

ui-check: ## Frontend: Format, Lint, Tests und Build wie in der CI
	cd frontend && npm run format:check && npm run lint && npm test -- --watch=false && npm run build

# ---------- Sauberkeit -------------------------------------------------------
clean: ## Cache und Builds entfernen
	rm -rf .pytest_cache .ruff_cache .pyright .coverage htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
