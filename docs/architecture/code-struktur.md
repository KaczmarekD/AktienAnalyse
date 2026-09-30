# Code-Struktur

> **Status:** Plan (30.09.2026). Umsetzung vor allem in Phase 1, siehe [Roadmap](roadmap.md).

## Ist-Analyse

**Was bleibt:**

- `scoring.score()` ist bereits rein funktional (DataFrame rein, DataFrame raus) und wird fast
  unverändert der Kern des `scoring`-Service.
- `FIELD_MAP` als Schutzschicht gegen Umbenennungen in yfinance, die Retry-/Fallback-Philosophie
  („lieber einen Ticker verlieren als den ganzen Batch“), Pydantic Settings, die Test-Suite,
  Ruff/Pyright/CI.
- Die Universum-Kette iShares → Deka → Fallback-CSV mit harter Validierung (seit `ca85d93`).
- Die Postgres-Persistenz mit Schemas pro Fachbereich (seit `261dc8f`, siehe
  [datenhaltung.md](datenhaltung.md)).

**Was vor dem Aufteilen entkoppelt werden muss:**

| Stelle | Problem | Lösung |
|---|---|---|
| `data_fetcher.fetch_one()` | mischt yfinance-Abrufe mit Fachlogik (ROIC, FX-Umrechnung, Multiples) | Adapter liefert `RawFinancials`, Kennzahlen werden reine Funktionen |
| `main._run()` | Ablaufsteuerung, Fehlerbehandlung und Verdrahtung in einer Funktion | Composition Root je Service, Ablauf über Events ([events.md](events.md)) |
| `mailer.send_report(settings, …)` | hängt am globalen `Settings` | Port `ReportSender` mit eigener SMTP-Konfiguration |
| `config.Settings` | ein Objekt für SMTP, Scoring, Datenbank und Betrieb | Settings je Service. Die Scoring-Parameter werden versionierte Profile ([scoring-profile.md](scoring-profile.md)). |
| Dependencies | `pandas<3`, `yfinance<0.3`, Python 3.11/3.12, pip-tools | pandas 3, yfinance 1.x, Python 3.14, uv ([ADR-0004](../adr/0004-uv-workspace-monorepo.md)) |

## Monorepo-Layout

```
aktien-analyse/
├── pyproject.toml              # uv-Workspace-Root: Ruff, Pyright, import-linter, Dev-Tools
├── uv.lock                     # ein Lockfile für alle Python-Pakete
├── packages/
│   ├── va-contracts/           # Pydantic: Event-Envelope, Events v1, WebSocket-Nachrichten, DTOs
│   └── va-platform/            # Settings-Basis, Logging, DB-Session, Outbox/Inbox, NATS-Setup
├── services/
│   ├── market-data/            # je Service: pyproject.toml, src/, tests/, migrations/, Dockerfile
│   ├── scoring/
│   ├── notification/
│   └── web-api/
├── frontend/                   # Angular-Workspace, nginx/default.conf, Dockerfile
├── deploy/
│   ├── compose.yaml            # Synology: nur fertige Images aus GHCR
│   └── compose.dev.yaml        # lokal: Postgres + NATS, Services mit Reload
├── data/dax_mdax_fallback.csv  # geprüftes Sicherheitsnetz fürs Universum
├── docs/                       # architecture/, adr/, research/
└── .github/workflows/          # python, frontend, images (mit Pfad-Filtern)
```

`va` steht für value-analyzer. Die Import-Namen sind durchgehend präfixiert (`va_scoring` statt
`scoring`). Im gemeinsamen Workspace-Environment gibt es so keine Kollision mit Paketen von PyPI.
Service-Namen (Container, Verzeichnisse) bleiben kurz: `market-data`, `scoring`,
`notification`, `web-api`.

## Aufbau eines Service (Ports & Adapters)

```
services/market-data/
├── pyproject.toml
├── Dockerfile
├── migrations/                 # Alembic, eigene version_table im Schema market_data
├── src/va_market_data/
│   ├── domain/                 # reine Logik: Kennzahlen, FX-Umrechnung, Snapshot-Regeln
│   ├── application/            # Anwendungsfälle + Ports (typing.Protocol)
│   ├── adapters/               # yahoo.py (FIELD_MAP), ishares.py, deka.py, csv_universe.py,
│   │                           # openfigi.py, postgres.py
│   └── entrypoints/            # worker.py (FastStream), cli.py
└── tests/
```

Regeln:

- `domain/` hat keine Ein- und Ausgabe und keine Framework-Imports. Hier liegen die rechnerischen
  Teile, testbar mit reinen Daten.
- `application/` beschreibt die Anwendungsfälle und definiert die Ports als `typing.Protocol`.
- `adapters/` implementiert die Ports: Yahoo, iShares, Deka, CSV, OpenFIGI, Postgres, SMTP.
- `entrypoints/` verdrahtet alles (Composition Root): FastStream-Worker und CLI, beim web-api
  die FastAPI-App.
- yfinance arbeitet synchron. Im asynchronen Worker läuft der Abruf per `asyncio.to_thread`.

Beispiel-Ports in `market-data`:

```python
class UniverseSource(Protocol):
    def load(self) -> UniverseResult: ...          # Ticker + Quelle + Stichtag

class FundamentalsProvider(Protocol):
    def fetch(self, symbol: str) -> RawFinancials: ...

class SnapshotRepository(Protocol):
    def save(self, snapshot: Snapshot) -> None: ...
    def reusable_for(self, day: date, min_success_share: float) -> Snapshot | None: ...
```

## Wohin die heutigen Module wandern

| Heute | Ziel |
|---|---|
| `universe.py` (iShares → Deka → CSV, Validierung, CSV-Abgleich) | `market-data`: je Quelle ein Adapter hinter dem Port `UniverseSource`, die Kette und die Validierung in `application/` |
| `data_fetcher.py`, Abruf-Teil (`FIELD_MAP`, `_pick`, `_ticker_data`, `_fx_rate`) | `market-data`: `adapters/yahoo.py`, liefert `RawFinancials` |
| `data_fetcher.py`, Rechen-Teil (`_roic`, `_cagr`, `_earnings_stability`, FX, Multiples) | `market-data`: `domain/metrics.py` als reine Funktionen |
| `fundamentals.py` | `va-contracts`: `FundamentalsV1` (Pydantic) für Events. Intern darf `market-data` Dataclasses behalten. |
| `scoring.py` | `scoring`: `domain/scoring.py` fast unverändert, `ScoringConfig` wird `ScoringProfileParams` |
| `reporting.py`, `mailer.py`, `healthcheck.py` | `notification`: Renderer mit Jinja-Template-Datei, Ports `ReportSender` und `Heartbeat` |
| `config.py` | `va-platform`: Basis-Settings (DB, NATS, Logging) + je Service eine eigene Settings-Klasse |
| `logging_setup.py` | `va-platform`: structlog mit JSON auf stdout, Docker rotiert die Logs |
| `main.py` | entfällt. Die Services reagieren auf Events, pro Service gibt es eine `cli.py` für manuelle Läufe. |
| `src/db/` (seit `261dc8f`) | Modelle und Repositories je Schema zum Besitzer-Service: `market_data` → `market-data`, `scoring` → `scoring`, `reporting` → `notification`, `batch` → `web-api`. Der Altdaten-Import bleibt ein einmaliges CLI-Kommando. |

## Grenzen erzwingen (import-linter)

```toml
[tool.importlinter]
root_packages = [
    "va_contracts", "va_platform",
    "va_market_data", "va_scoring", "va_notification", "va_web_api",
]

[[tool.importlinter.contracts]]
name = "Services importieren einander nicht"
type = "independence"
modules = ["va_market_data", "va_scoring", "va_notification", "va_web_api"]

[[tool.importlinter.contracts]]
name = "Schichten innerhalb jedes Service"
type = "layers"
layers = ["entrypoints", "adapters", "application", "domain"]
containers = ["va_market_data", "va_scoring", "va_notification", "va_web_api"]
```

Geteilt wird nur über `va-contracts` (Datenformate) und `va-platform` (Infrastruktur). Fachlogik
wandert nie in diese beiden Pakete.

## Tests

- **Domain:** reine Funktionen mit festen Eingabedaten, darunter als JSON gespeicherte
  Roh-Statements echter Titel. Damit sind die Kennzahlen testbar, ohne yfinance zu mocken.
  Die CLAUDE.md-Regel „yfinance-Calls werden in Tests nicht gemockt“ bleibt bestehen.
- **Event-Handler:** FastStream-`TestNatsBroker` (im Speicher, ohne laufendes NATS).
- **Repositories und Migrationen:** gegen ein echtes Postgres 18, wie seit `261dc8f` in
  `tests/db/` umgesetzt. Jeder Test bekommt eine frische Datenbank aus einer migrierten Vorlage,
  lokal per `make test-db-up`, in der CI als Service-Container. Ein Test prüft den Löschschutz
  jeder Tabelle.
- **Contracts:** JSON-Schema-Snapshots der Pydantic-Modelle. Jede Schema-Änderung ist im Diff
  sichtbar.
- **web-api:** OpenAPI-Snapshot plus `oasdiff breaking` gegen den letzten Release
  ([frontend.md](frontend.md)).
