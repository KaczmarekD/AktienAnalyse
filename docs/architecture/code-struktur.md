# Code-Struktur

> **Status:** Plan vom 30.09.2026, Phase 1 im Code umgesetzt (P1.1–P1.9, 19.10.2026), siehe
> [Roadmap](roadmap.md). Die Ist-Analyse beschreibt den Stand nach Phase 1. Layout und Aufbau
> eines Service zeigen das Ziel. Was dort noch fehlt (`web-api`, FastStream-Worker, CLI,
> Migrationen und Dockerfile je Service), kommt mit Phase 3 bis 5.

## Ist-Analyse (nach Phase 1)

Ein Container mit einem Wochen-Batch, aber schon mit den späteren Service-Grenzen (modularer
Monolith):

- uv-Workspace mit `packages/va-contracts` (Events v1), `packages/va-platform` (Event-Bus,
  DB-Basis mit Löschschutz, Serialisierung) und den Modulen `services/market-data`,
  `services/scoring` und `services/notification`. Jedes Modul hat `domain/`, `application/`,
  `adapters/` und `entrypoints/`.
- Die Module importieren einander nicht und tauschen Events aus. `InProcessBus`
  (`va_platform.bus`) stellt sie im Prozess zu, ab Phase 4 übernimmt NATS. Die Handler liegen in
  `entrypoints/handlers.py`.
- `src/` ist der Batch: `main.py` legt den Lauf an und startet die Kette, `composition.py` baut
  die Adapter und hängt die Handler an den Bus, `run_tracker.py` schließt `batch.run` ab. `db/`
  besitzt das Schema `batch`, die Migration und den Altdaten-Import.
- Jedes Modul speichert selbst in seinem Schema (`adapters/postgres/`). Die Alembic-Historie
  ist noch eine (`migrations/` im Root).

**Geblieben:**

- `score()` (`va_scoring.domain.scoring`) ist unverändert rein funktional (DataFrame rein,
  DataFrame raus).
- Die Tabellen der yfinance-Namen am Kopf von `adapters/yahoo.py` (`FIELD_MAP` und weitere,
  siehe CLAUDE.md), die Retry-/Fallback-Philosophie („lieber einen Ticker verlieren als den
  ganzen Batch“), Pydantic Settings, die Test-Suite mit Golden-Master, Ruff/Pyright/CI.
- Die Universum-Kette iShares → Deka → Fallback-CSV mit harter Validierung (seit `ca85d93`).
- Die Postgres-Persistenz mit Schemas pro Fachbereich (seit `261dc8f`, siehe
  [datenhaltung.md](datenhaltung.md)).

**Erledigt:** Was vor dem Aufteilen entkoppelt werden musste:

| Früher | Heute |
|---|---|
| `data_fetcher.fetch_one()` mischte yfinance-Abrufe mit Fachlogik | Abruf im Adapter `va_market_data.adapters.yahoo` hinter dem Port `FundamentalsProvider`, Kennzahlen als reine Funktionen in `va_market_data.domain.metrics` (P1.3, P1.4) |
| `main._run()`: Ablauf, Fehlerbehandlung und Verdrahtung in einer Funktion | Handler je Modul am Bus, Composition Root `src/composition.py` (P1.8, [events.md](events.md)) |
| `mailer.send_report(settings, …)` hing am globalen `Settings` | Port `ReportSender`, Adapter `va_notification.adapters.smtp` mit eigener `SmtpConfig` (P1.6) |
| `pandas<3`, `yfinance<0.3`, Python 3.11/3.12, pip-tools | pandas 3, yfinance 1.x, Python 3.14, uv ([ADR-0004](../adr/0004-uv-workspace-monorepo.md), Phase 0) |

**Offen:** `src/config.Settings` ist weiter ein Objekt für SMTP, Scoring, Datenbank und Betrieb.
`src/composition.py` gibt jedem Modul daraus nur seine eigene Konfiguration (`FetcherConfig`,
`ScoringConfig`, `SmtpConfig`, `NotificationConfig`). Ziel bleiben Settings je Service. Die
Scoring-Parameter werden versionierte Profile ([scoring-profile.md](scoring-profile.md)).

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

Das ist das Zielbild. Heute fehlen `services/web-api/`, `frontend/` und `deploy/`. `va-platform`
enthält bisher den Event-Bus (`bus`), die DB-Basis mit Löschschutz (`db`) und `serialization`.
`Dockerfile`, `docker-compose.yml`, `migrations/` und der Batch `src/` liegen im Root.

`va` steht für value-analyzer. Die Import-Namen sind durchgehend präfixiert (`va_scoring` statt
`scoring`). Im gemeinsamen Workspace-Environment gibt es so keine Kollision mit Paketen von PyPI.
Service-Namen (Container, Verzeichnisse) bleiben kurz: `market-data`, `scoring`,
`notification`, `web-api`.

## Aufbau eines Service (Ports & Adapters)

```
services/market-data/
├── pyproject.toml
├── Dockerfile                  # Ziel (P5.1), heute ein Image im Root
├── migrations/                 # Ziel: Alembic, eigene version_table im Schema market_data;
│                               # heute eine Historie unter migrations/ im Root
├── src/va_market_data/
│   ├── domain/                 # reine Logik: Kennzahlen inkl. FX-Umrechnung, Universum-Regeln,
│   │                           # Perioden, Konsens, Zeitreihen
│   ├── application/            # Anwendungsfälle + Ports (typing.Protocol)
│   ├── adapters/               # yahoo.py (Tabellen der yfinance-Namen), ishares.py, deka.py,
│   │                           # csv_universe.py, openfigi.py, http.py, postgres/ (Paket:
│   │                           # Modelle, Repository, Store)
│   └── entrypoints/            # heute handlers.py (Bus); Ziel: worker.py (FastStream), cli.py
└── tests/
```

Regeln:

- `domain/` hat keine Ein- und Ausgabe und keine Framework-Imports. Hier liegen die rechnerischen
  Teile, testbar mit reinen Daten.
- `application/` beschreibt die Anwendungsfälle und definiert die Ports als `typing.Protocol`.
- `adapters/` implementiert die Ports: Yahoo, iShares, Deka, CSV, OpenFIGI, Postgres, SMTP.
- `entrypoints/` verdrahtet alles (Composition Root): FastStream-Worker und CLI, beim web-api
  die FastAPI-App. Bis Phase 5 liegt die Composition Root beim Batch (`src/composition.py`),
  `entrypoints/handlers.py` enthält nur die Handler am Bus.
- yfinance arbeitet synchron. Im asynchronen Worker läuft der Abruf per `asyncio.to_thread`.

Die Ports von `market-data` (`application/ports.py`, gekürzt):

```python
class UniverseSource(Protocol):  # iShares, Deka; wirft bei jedem Fehler
    name: str

    def load(self, fallback: list[Ticker], cfg: UniverseConfig, today: date) -> LiveUniverse: ...

class FundamentalsProvider(Protocol):  # Yahoo; wirft nie, Fehler stehen in errors
    def fetch(self, ticker: Ticker, history: HistoryState | None = None) -> Fundamentals: ...

class SnapshotStore(Protocol):  # Schema market_data
    def find_reusable_fetch(self, day: date, symbols: Collection[str]) -> int | None: ...
    def load_snapshots(self, fetch_run_id: int, symbols: Collection[str]) -> pd.DataFrame: ...
    def start_fetch(
        self, tickers: Sequence[Ticker], source: str, as_of: date | None = None
    ) -> int: ...
    def history_state(self, symbols: Collection[str]) -> Mapping[str, HistoryState]: ...
    def record_fundamentals(self, fetch_run_id: int, fund: Fundamentals) -> None: ...
    def finish_fetch(self, fetch_run_id: int, df: pd.DataFrame) -> None: ...
```

`LiveUniverse` enthält die Titel und den Stichtag (Deka kennt keinen). Dazu kommt `Fetch`, die
Abrufschleife mit fertig verdrahtetem Provider. Die Kette der Quellen steht in
`application/universe.py`. Die Regeln liegen in `domain/universe.py`: Soll-Anzahl je Index
(`check_count`, `UniverseConfig`), Dubletten (`dedupe`) und Abgleich mit der CSV (`diff`). Die
Adapter rufen `check_count` auf und prüfen selbst das Format, iShares auch den Stichtag.

## Wohin die Module des alten Batches wandern

Die Tabelle stammt aus der Planung vom 30.09.2026. Die Module der linken Spalte lagen in `src/`.
Bis auf `config.py`, `logging_setup.py`, `main.py` und `db/` gibt es sie seit Phase 1 nicht mehr.
Die Spalte „Stand nach Phase 1“ zeigt, wo sie heute liegen.

| Vor Phase 1 (`src/`) | Ziel | Stand nach Phase 1 |
|---|---|---|
| `universe.py` (iShares → Deka → CSV, Validierung, CSV-Abgleich) | `market-data`: je Quelle ein Adapter hinter dem Port `UniverseSource`, die Kette und die Validierung in `application/` | erledigt: Adapter `ishares`, `deka`, `csv_universe`, `openfigi`, Kette in `application/universe.py`, Regeln in `domain/universe.py` |
| `data_fetcher.py`, Abruf-Teil (`FIELD_MAP`, `_pick`, `_ticker_data`, `_fx_rate`) | `market-data`: `adapters/yahoo.py`, liefert `RawFinancials` | erledigt: `adapters/yahoo.py` liefert `Fundamentals`, die Rohdaten hängen als `Fundamentals.raw` daran |
| `data_fetcher.py`, Rechen-Teil (`_roic`, `_cagr`, `_earnings_stability`, FX, Multiples) | `market-data`: `domain/metrics.py` als reine Funktionen | erledigt (P1.3) |
| `fundamentals.py` | `va-contracts`: `FundamentalsV1` (Pydantic) für Events. Intern darf `market-data` Dataclasses behalten. | erledigt: `FundamentalsV1` (P1.2), Dataclasses in `va_market_data.domain.fundamentals` |
| `scoring.py` | `scoring`: `domain/scoring.py` fast unverändert, `ScoringConfig` wird `ScoringProfileParams` | verschoben (P1.5), `ScoringProfileParams` offen (P2b.2) |
| `reporting.py`, `mailer.py`, `healthcheck.py` | `notification`: Renderer mit Jinja-Template-Datei, Ports `ReportSender` und `Heartbeat` | erledigt (P1.6): `domain/report.py` mit `templates/report.html.j2`, Adapter `smtp` und `healthchecks` |
| `config.py` | `va-platform`: Basis-Settings (DB, NATS, Logging) + je Service eine eigene Settings-Klasse | offen: weiter `src/config.py` |
| `logging_setup.py` | `va-platform`: structlog mit JSON auf stdout, Docker rotiert die Logs | offen: weiter `src/logging_setup.py` |
| `main.py` | entfällt. Die Services reagieren auf Events, pro Service gibt es eine `cli.py` für manuelle Läufe. | Zwischenstand: `src/main.py` startet nur noch die Kette am Bus (P1.8) |
| `src/db/` (seit `261dc8f`) | Modelle und Repositories je Schema zum Besitzer-Service: `market_data` → `market-data`, `scoring` → `scoring`, `reporting` → `notification`, `batch` → `web-api`. Der Altdaten-Import bleibt ein einmaliges CLI-Kommando. | teilweise (P1.7): `market_data`, `scoring` und `reporting` liegen beim Modul unter `adapters/postgres/`; `batch`, Migration und Altdaten-Import bleiben in `src/db/` |

## Grenzen erzwingen (import-linter)

Umgesetzt mit P1.1 in `pyproject.toml` (`make imports`, CI-Schritt „Import-Grenzen“). Heute
sind es sieben Verträge:

1. Services importieren einander nicht.
2. Schichten innerhalb jedes Service: `entrypoints` → `adapters` → `application` → `domain`.
3. Die geteilten Pakete kennen keine Services.
4. `va_contracts` kennt `va_platform` nicht.
5. `va_contracts` importiert weder pandas, numpy, SQLAlchemy, psycopg noch yfinance.
6. Die `domain` der Services importiert weder yfinance, requests, SQLAlchemy, psycopg noch
   Alembic.
7. Kein Paket und kein Service importiert den Batch `src`.

`src` steht in `root_packages` und heißt dort „Batch“ (Einstieg, Konfiguration, Composition
Root, Schema `batch`). `va_web_api` kommt mit P3.1 dazu. Die ersten beiden Verträge im Zielbild:

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
- **Event-Handler:** FastStream-`TestNatsBroker` (im Speicher, ohne laufendes NATS). Bis Phase 4
  laufen sie gegen `InProcessBus`, die Bus-Verträge in `packages/va-platform/tests/` sind schon
  für beide Umsetzungen geschrieben.
- **Repositories und Migrationen:** gegen ein echtes Postgres 18, wie seit `261dc8f` in
  `tests/db/` umgesetzt. Jeder Test bekommt eine frische Datenbank aus einer migrierten Vorlage,
  lokal per `make test-db-up`, in der CI als Service-Container. Ein Test prüft den Löschschutz
  jeder Tabelle.
- **Contracts:** JSON-Schema-Snapshots der Pydantic-Modelle (`tests/golden/contracts/v1/`,
  seit P1.2). Jede Schema-Änderung ist im Diff sichtbar.
- **web-api:** OpenAPI-Snapshot plus `oasdiff breaking` gegen den letzten Release
  ([frontend.md](frontend.md)).
