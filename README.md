# Value-Analyzer DAX/MDAX

> Wöchentlicher Fundamentaldaten-Screener für DAX und MDAX. Läuft als Docker-Stack auf einer Synology (drei Services an NATS, PostgreSQL, Web-UI) und verschickt jeden Samstag eine HTML-Mail mit den besten und schlechtesten Titeln nach Value- und Quality-Kriterien.

[![CI](https://github.com/KaczmarekD/AktienAnalyse/actions/workflows/ci.yml/badge.svg)](https://github.com/KaczmarekD/AktienAnalyse/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.14-blue)
![Version](https://img.shields.io/badge/version-0.3.0-green)
![License](https://img.shields.io/badge/license-Proprietary-lightgrey)

---

## Was es tut

- Lädt das DAX/MDAX-Universum (40 + 50 Titel) aus den Holdings der iShares-ETFs, Fallback Deka-ETF, dann `data/dax_mdax_fallback.csv`
- Holt Fundamentaldaten via **yfinance** (kein API-Key nötig)
- Speichert **alles dauerhaft in PostgreSQL 18** – Rohdaten, versionierte Abschlüsse, Kennzahlen, Scores, Reports, Versand, Logs. Gelöscht wird nie (von der DB erzwungen)
- Berechnet einen **Composite Score** aus Value- und Quality-Faktoren (cross-sektional, Perzentilrang)
- Markiert potenzielle **Value Traps** (billig, aber schlechte Qualität)
- Verschickt jeden **Samstag 07:30 Europe/Berlin** eine HTML-Mail mit Top/Bottom-Tabellen und CSV-Anhang
- Optionaler **Healthchecks.io**-Heartbeat als Dead-Man's-Switch
- **Web-UI** im LAN: Läufe live verfolgen und starten, Ranking und Historie je Titel, Scoring-Profile mit Vorschau

---

## Pipeline

Das web-api legt den Lauf an, nach Wochenplan oder aus dem UI. Drei Services führen ihn aus,
jeder in seinem Container mit eigenem Schema in PostgreSQL. Sie reagieren auf Events über NATS
JetStream ([events.md](docs/architecture/events.md)):

```
screening.run.requested
      │
market-data              Universum iShares → Deka → CSV, validiert; yfinance → je Titel
      │                  sofort in PostgreSQL (Rohdaten, Abschlüsse, Zusatzdaten, Kennzahlen)
marketdata.snapshot.completed
      │
scoring                  Marktkapitalisierungsfilter → Perzentilränge → Composite Score
      │
scoring.run.completed
      │
notification             HTML-Mail-Body + CSV-Vollranking; Versand über den Port ReportSender
      │                  (SMTP, Gmail App-Passwort), Report + Versand in PostgreSQL;
      │                  Healthchecks.io (optional)
notification.report.sent → web-api schließt batch.run ab, das UI aktualisiert sich (WebSocket)
```

Scheitert eine Stufe, meldet sie `screening.run.failed`. notification pingt dann
Healthchecks.io mit `/fail` (bei geplanten Läufen immer) und schickt eine Fehlermail, außer im
Dry-Run und wenn es nur keine bewertbaren Daten gab. Der Watchdog im web-api meldet einen Run,
der in einer Stufe hängen bleibt, ebenfalls als gescheitert.

Der Batch `src/main.py` führt dieselbe Kette auf Wunsch in einem Prozess aus (`make docker-run`),
verdrahtet in `src/composition.py`.

---

## Methodik

### Composite Score = 0.6 × Value + 0.4 × Quality

Alle Faktoren werden als **Perzentilrang** (0–1) über das gefilterte Universum berechnet. Fehlende Werte werden übersprungen, nicht mit 0 bestraft. Ein Value- oder Quality-Score wird nur vergeben, wenn mindestens 50 % der Faktoren der Kategorie vorliegen (aufgerundet, mindestens 2). Einen Composite gibt es nur mit beiden Teilscores. Titel ohne Composite (heute vor allem Banken, denen Quality-Kennzahlen fehlen) stehen am Ende der CSV, nicht in der Mail, und zählen dort als „fehlgeschlagen“.

**Value-Faktoren** (niedriger Multiple = besser, außer Yield):

| Faktor | Beschreibung |
|---|---|
| EV/EBIT | Kapitalstruktur-neutral (Greenblatt-Logik); negative Werte ausgeschlossen |
| P/B | Kurs-Buchwert-Verhältnis |
| P/FCF | Free-Cashflow-Rendite; schwerer zu manipulieren als KGV |
| Shareholder Yield | Dividende + Buyback-Rendite (hoch = besser) |

> KGV ist bewusst **nicht** enthalten – zu volatil, zu anfällig für Einmaleffekte.

**Quality-Faktoren** (hoch = besser, außer Verschuldung):

| Faktor | Beschreibung |
|---|---|
| ROIC | Mit effektiver Steuerquote; Fallback `DEFAULT_TAX_RATE=0.27`; Obergrenze 0.6 |
| FCF-Marge | Free Cashflow / Umsatz |
| Operating Margin | Betriebliche Rentabilität |
| Net Debt/EBITDA | Verschuldungsgrad (invertiert; niedrig = besser) |
| Earnings Stability | `1 − min(σ/μ, 1)` des Net Income über die letzten 5 Geschäftsjahre (mindestens 4 gültige); σ = Standardabweichung der Grundgesamtheit, μ = Mittelwert der Beträge; 1 = konstante Gewinne |

**Value-Trap-Flag**: Value-Score ≥ 0.70 **und** Quality-Score ≤ 0.30 → der Titel ist billig, aber fundamental schwach.

**Mindest-Marktkapitalisierung**: 300 Mio EUR – schließt Micro-Caps aus, bei denen yfinance-Daten oft unzuverlässig sind.

---

## Quick Start

### Synology (empfohlen)

```bash
cd /volume1/docker/
git clone https://github.com/KaczmarekD/AktienAnalyse.git value-analyzer
cd value-analyzer
cp .env.example .env
nano .env          # SMTP_*, MAIL_TO, die DB-Passwörter, UI_LAN_BIND und UI_SERVER_NAMES setzen
make pull          # fertige Images aus der CI (GHCR); die NAS baut nichts selbst
docker compose run --rm --no-deps --entrypoint python value-analyzer -c "import src.main"
make up            # db, nats, Migration, die drei Services, web-api und frontend
docker compose ps
```

Die Images (`value-analyzer`, `va-market-data`, `va-scoring`, `va-notification`, `va-web-api`,
`va-frontend` unter `ghcr.io/kaczmarekd`) entstehen in GitHub Actions bei jedem Push auf `main`
(`latest`, `sha-<commit>`) und bei Tags `vX.Y.Z` passend zur Version in `pyproject.toml`.
`VERSION` in der `.env` pinnt eine bestimmte Fassung. Der Import-Test prüft das App-Image auf der
echten CPU der NAS (kein AVX, ADR-0008). Ist ein Paket in GHCR privat, vorher einmalig
`docker login ghcr.io` mit einem Token, das nur `read:packages` darf. Lokal baut `make build`
das App-Image.

Betrieb, Updates und die einmalige Umstellung vom Batch mit Cron beschreibt das Runbook
[betrieb-synology.md](docs/architecture/betrieb-synology.md).

**Update** (nach einem Merge auf `main`):
```bash
cd /volume1/docker/value-analyzer
git pull               # Compose-Datei, Fallback-CSV, Doku (die CSV im Image wird von ./data verdeckt)
make pull
docker compose run --rm --no-deps --entrypoint python value-analyzer -c "import src.main"
make regression        # gespeicherte Wochen mit dem neuen Image nachspielen, schreibt nichts
make up
```

**Web-UI** (seit P3.6): `make up` startet das web-api und den `frontend`-Container (nginx).
Damit das UI im LAN unter `http://<nas-ip>:8080` erreichbar ist, in der `.env` `UI_LAN_BIND`
auf die NAS-IP setzen und in `UI_SERVER_NAMES` die Namen eintragen, unter denen du es aufrufst
(z. B. `nas nas.fritz.box 192.168.1.10`). In der DSM-Firewall Port 8080 nur für das eigene
Subnetz freigeben. Ist das Paket `va-frontend` in GHCR privat, gilt dasselbe
wie für die anderen Images (`docker login ghcr.io`).

**Wochenlauf:** Das web-api plant ihn nach `CRON_SCHEDULE` (Standard Samstag 07:30,
Europe/Berlin). Von Hand startet ihn die Seite „Runs“ im UI, wahlweise als Dry-Run.

`make regression` bewertet jede gespeicherte Woche mit dem neuen Code und vergleicht mit dem
Ergebnis von damals. Exit 0 heißt: alles gleich. Abweichungen sind nur dort in Ordnung, wo die
Roadmap eine Methodik-Änderung nennt (z. B. M1). Bei leerer Datenbank meldet es „nichts zu
vergleichen“. Wie jeder Container-Start migriert es vorher das Schema (nur additiv).

**Altdaten übernehmen** (vorhandene `fundamentals_*.parquet` / `value_ranking_*.csv` in `data/`, auch aus Mails gespeicherte CSVs – mehrfach ausführbar, Dateien bleiben liegen):
```bash
make db-import
```

**Batch ohne Services** (Notweg, der Lauf läuft im Batch-Container, ohne NATS):
```bash
make docker-dry    # Dry-Run: kein Mailversand, erzeugt nur HTML+CSV
make docker-run    # echter Lauf
```

### Datenbank & Auswertungen

PostgreSQL 18 läuft als Container `db`; Daten liegen im Bind-Mount `./pgdata` (sichert Hyper Backup mit, `docker compose down -v` kann ihn nicht löschen).

| Schema | Inhalt |
|---|---|
| `batch` | Läufe (Status, Einstellungen ohne Passwörter, Fehler), Log-Zeilen je Lauf, importierte Altdateien |
| `market_data` | Instrumente (Symbol, ISIN), Abrufe, Index-Zugehörigkeit je Abruf, yfinance-Rohdaten (JSONB), versionierte Abschlusswerte (Jahre und Quartale, `statement_value`), Wechselkurse, Kennzahlen je Abruf; seit ADR-0010 Analystenkonsens je Abruf (`consensus_snapshot`), Aktienanzahl (`share_count`) und Tageskurse (`price_bar`), beide versioniert |
| `scoring` | Bewertungsläufe mit Konfiguration, Scores aller Titel, Perzentilrang je Faktor |
| `reporting` | Reports (HTML + CSV), Mail-/Healthcheck-Versand |

**Zugriff aus dem LAN** (DBeaver, Jupyter, Excel): `DB_LAN_BIND` in `.env` auf die NAS-IP setzen, dann mit Rolle `va_read` (nur Lesen) auf Port 5432 verbinden. Die DSM-Firewall sollte den Port auf das Heimnetz beschränken.

```sql
-- EV/EBIT-Verlauf eines Titels über alle Wochen
SELECT f.started_at::date, s.ev_ebit
FROM market_data.fundamental_snapshot s
JOIN market_data.fetch_run f ON f.id = s.fetch_run_id
JOIN market_data.instrument i ON i.id = s.instrument_id
WHERE i.symbol = 'SAP.DE' ORDER BY 1;
```

In Python liefern die Repositories (je Modul unter `adapters/postgres/`) fertige DataFrames, z.B. `get_metric_history`, `get_score_history`, `get_statement_history`, `get_statements_as_of` (Abschlusswerte, wie sie an einem Stichtag bekannt waren).

`make db-backup` schreibt einen Dump nach `backups/`, `make db-shell` öffnet `psql`. Einen Reset gibt es bewusst nicht.

### Lokale Entwicklung

Voraussetzung ist [uv](https://docs.astral.sh/uv/) (Windows: `winget install astral-sh.uv`). uv holt auch die passende Python-Version.

**Lokaler Stack** (Docker): dieselben Container wie auf der NAS, aber das Image entsteht aus dem
Arbeitsstand, die Mail landet im lokalen Postfach Mailpit, und nichts geht nach außen
([umgebungen.md](docs/architecture/umgebungen.md)).

```bash
cp .env.local.example .env
make local-up          # DB, NATS, Mailpit, pgweb, web-api und Worker (Image aus dem Arbeitsstand)
make local-run         # ein Lauf wie am Samstag; die Mail erscheint in Mailpit
make local-regression  # alle gespeicherten Wochen mit dem Arbeitsstand nachspielen
make local-ui          # das UI hinter nginx unter http://localhost:8080
make local-check       # Mail, API und UI zum letzten Lauf prüfen (braucht make local-ui)
make local-down        # stoppen, die Daten in .local/ bleiben
```

**End-to-End-Test** (U5): `make local-e2e` prüft die ganze Kette mit einem Befehl, ohne Yahoo.
Der ganze Stack (NATS, die drei Services, web-api) bewertet eine gespeicherte echte Woche
(`tests/fixtures/replay/`), gestartet über die API. Geprüft werden
die Mail in Mailpit, das web-api hinter nginx und das UI, jeweils gegen die Erwartungswerte der
Woche. Der Stack ist ein Wegwerf-Stack mit eigener Datenbank auf tmpfs, der neben dem lokalen
läuft (UI auf `:18080`, Mailpit auf `:18025`) und danach verschwindet. `E2E_KEEP=1 make
local-e2e` lässt ihn zum Ansehen stehen. Die CI macht dasselbe bei jedem Push.

| Adresse | Was |
|---|---|
| <http://localhost:8025> | Mailpit: die Mails mit CSV-Anhang |
| <http://localhost:8081> | pgweb: alle Tabellen, nur lesend (Rolle `va_read`) |
| <http://localhost:8000/api/docs> | web-api: REST-Schnittstelle mit Swagger |
| `127.0.0.1:5432` | Postgres (`LOCAL_DB_PORT`), z. B. für DBeaver |

Lokal zeigt SMTP immer auf Mailpit und `HEALTHCHECK_URL` ist leer, auch wenn die `.env` echte
Zugangsdaten enthält. Lokal plant das web-api keine Läufe: `make local-run` startet einen im
Batch, die Seite „Runs“ im UI einen über die Services.

**Schneller Weg** ohne Image-Build, aus der `.venv` gegen denselben lokalen Stack:

```bash
make install-dev    # alle Abhängigkeiten exakt aus uv.lock (.venv)
make dry            # Dry-Run lokal
make api            # web-api mit Reload unter localhost:8000 (statt des Containers)
make ui-install     # Frontend: Abhängigkeiten (Node ≥ 22.22, nur lokal und in der CI)
make ui             # Frontend mit Reload unter http://localhost:4200, Daten vom web-api
make check          # ruff + pyright + import-linter + pytest (DB-Tests ohne DB übersprungen)
make test-db-up     # Wegwerf-Postgres auf Port 55432 (Docker)
make test-db        # alle Tests inkl. DB-Tests
make test-nats-up   # Wegwerf-NATS mit JetStream auf Port 54222 (Docker)
make test-nats      # Integrationstests der JetStream-Provisionierung (P4.1)
make test-cov       # Tests mit Coverage-HTML-Report
make check-j4125    # Image unter QEMU ohne AVX prüfen (CPU der NAS), nach Dependency-Upgrades
```

`make help` zeigt alle verfügbaren Targets.

---

## Konfiguration (`.env`)

| Variable | Default | Beschreibung |
|---|---|---|
| `SMTP_HOST` | `smtp.gmail.com` | SMTP-Server |
| `SMTP_PORT` | `587` | SMTP-Port (STARTTLS) |
| `SMTP_PLAIN` | `false` | Nur lokal: ohne TLS und ohne Login an einen Mail-Catcher (Mailpit) |
| `SMTP_USER` | – **Pflicht** | Gmail-Adresse |
| `SMTP_PASSWORD` | – **Pflicht** | Gmail App-Passwort (16 Zeichen) |
| `MAIL_TO` | – **Pflicht** | Empfänger-Adresse |
| `MAIL_FROM` | `= SMTP_USER` | Absender (überschreibbar) |
| `MAIL_SUBJECT_PREFIX` | `[Value-Screening DAX/MDAX]` | Mail-Betreff-Präfix |
| `UNIVERSE` | `DAX_MDAX` | `DAX_MDAX` oder `DAX_ONLY` |
| `TOP_N` / `BOTTOM_N` | `20` / `10` | Anzahl Top/Bottom-Kandidaten in der Mail |
| `MIN_MARKET_CAP` | `300000000` | Mindest-Marktkapitalisierung in EUR, nur Startwert (siehe unten) |
| `VALUE_WEIGHT` / `QUALITY_WEIGHT` | `0.6` / `0.4` | Composite-Gewichtung (wird auf Summe 1 normiert), nur Startwert (siehe unten) |
| `DEFAULT_TAX_RATE` | `0.27` | Fallback-Steuersatz für ROIC-Berechnung |
| `CRON_SCHEDULE` | `30 7 * * 6` | Wochenplan des web-api (Sa 07:30, Europe/Berlin); Format: `m h dom mon dow` |
| `POSTGRES_PASSWORD` | – **Pflicht** | Passwort der Owner-Rolle `va_owner` (Migrationen) |
| `VA_APP_PASSWORD` | – **Pflicht** | Passwort der App-Rolle `va_app` (kein DELETE); wirkt beim ersten DB-Start |
| `VA_READ_PASSWORD` | – **Pflicht** | Passwort der Lese-Rolle `va_read` für Auswertungen; wirkt beim ersten DB-Start |
| `VA_PROFILES_PASSWORD` | – **Pflicht** | Passwort der Rolle `va_profiles` für das web-api ohne NATS (`make api`, P3.3). Fehlt die Rolle in einer bestehenden DB, legt der Dienst `migrate` sie an |
| `VA_WEB_PASSWORD` | – **Pflicht** | Passwort der Rolle `va_web` des web-api: Projektionen, Runs anlegen und abschließen (P4.4, P4.7) |
| `VA_MARKET_DATA_PASSWORD` / `VA_SCORING_PASSWORD` / `VA_NOTIFICATION_PASSWORD` | – **Pflicht** | Je Service eine Rolle nur für das eigene Schema (P5.3); `migrate` legt sie an |
| `DB_LAN_BIND` | `127.0.0.1` | IP, an die der Postgres-Port gebunden wird (NAS-IP = im LAN erreichbar) |
| `LOCAL_DB_PORT` | `5432` | Nur lokaler Stack: Port der lokalen Datenbank, falls 5432 belegt ist |
| `DATABASE_URL` | von Compose gesetzt | Nur lokal nötig: `postgresql+psycopg://va_app:<pw>@host:5432/value_analyzer` |
| `HEALTHCHECK_URL` | – | Optional: `https://hc-ping.com/<uuid>` |
| `UI_LAN_BIND` / `UI_SERVER_NAMES` | `127.0.0.1` / – | IP für Port 8080 des UI und die Hostnamen, unter denen es aufgerufen wird |
| `RUN_TIMEOUT_MINUTES` | `120` | Ältere Events gelten als Reste abgebrochener Läufe; so lange wartet auch der Batch über NATS |
| `OTEL_TRACES_EXPORTER` | `none` | `console`: die Spans jedes Runs als JSON ins Log (OpenTelemetry, P5.5) |
| `TZ` | `Europe/Berlin` | Container-Zeitzone |
| `REG` | `ghcr.io/kaczmarekd` | Registry des Images (Compose) |
| `VERSION` | `latest` | Image-Tag: `latest` folgt `main`, `sha-<commit>` oder `X.Y.Z` pinnt |

**Scoring-Profile** (ADR-0009, seit P2b.3): `MIN_MARKET_CAP`, `VALUE_WEIGHT` und `QUALITY_WEIGHT`
legen beim ersten Lauf das Profil „Standard“ v1 in der Datenbank an. Danach rechnet jeder Lauf mit
dem aktiven Profil, und der Footer der Mail nennt es („Profil Standard v1“). Eine Änderung in der
`.env` wirkt dann nicht mehr. Gewichte ändert eine neue Profil-Version, ab P3.3 im UI.

### Gmail App-Passwort einrichten

1. [Zwei-Faktor-Authentifizierung aktivieren](https://myaccount.google.com/security)
2. [App-Passwort generieren](https://myaccount.google.com/apppasswords) → „Value-Analyzer Synology"
3. Die 16 Zeichen in `.env` als `SMTP_PASSWORD` eintragen

---

## Projektstruktur

```
value-analyzer/
├── src/
│   ├── main.py             # Batch: Lauf anlegen, Event-Kette im Prozess, abschließen
│   ├── composition.py      # Batch: die drei Services an einen Bus hängen
│   ├── worker.py           # die drei Services in einem Prozess über NATS
│   ├── web.py              # web-api ohne NATS (make api): Vorschau und Profile im Prozess
│   ├── run_tracker.py      # Abschluss von batch.run aus den Events
│   ├── config.py           # Pydantic Settings (validiert beim Start)
│   ├── logging_setup.py    # RotatingFileHandler (5 MB × 10)
│   ├── db/                 # PostgreSQL: Schema batch, Recorder, Migration,
│   │                       #   Altdaten-Import (Modelle der Module: adapters/postgres/)
│   └── regression/         # Replay-Regression: gespeicherte Wochen nachspielen
│                           #   und vergleichen (make regression)
├── packages/               # uv-Workspace: va-contracts (Events, RPC), va-platform (Busse,
│                           #   NATS, Outbox/Inbox, Tracing, DB-Basis, Löschschutz)
├── services/               # uv-Workspace, je domain/application/adapters/entrypoints:
│                           #   market-data (Universum, Yahoo, Kennzahlen), scoring,
│                           #   notification (Mail, Healthcheck), web-api (FastAPI)
├── frontend/               # Angular-UI, im Image va-frontend hinter nginx
├── docker/                 # J4125-Prüfung (QEMU), E2E-Test, Image-Tags für GHCR
├── migrations/             # Alembic-Migrationen (nur additiv)
├── db/init/01_roles.sh     # Rollen beim ersten DB-Start (danach legt migrate neue an)
├── tests/                  # pytest-Suite; tests/db/ gegen echtes PostgreSQL,
│                           #   tests/fixtures/replay/ echte Wochen für die Replay-Regression
├── data/
│   └── dax_mdax_fallback.csv   # Editierbar ohne Rebuild bei DAX/MDAX-Mutationen
├── pyproject.toml          # Abhängigkeiten + ruff/pytest/pyright-Konfiguration
├── uv.lock                 # Exakt gepinnte Versionen aller Abhängigkeiten (uv)
├── Dockerfile              # Installiert exakt aus uv.lock, uv selbst bleibt draußen
├── docker-compose.yml
├── entrypoint.sh           # App-Image: migrieren, dann den übergebenen Befehl ausführen
├── Makefile                # make help für alle Kommandos
└── .env.example
```

---

## Lockfile-Workflow

Abhängigkeiten stehen in `pyproject.toml` (`dependencies`, Dev-Tools in der Gruppe `dev`), die exakten Versionen in `uv.lock`. `uv.lock` wird nie von Hand geändert:

```bash
uv add <paket>   # neue Abhängigkeit (Dev-Tool: uv add --dev <paket>)
make lock        # uv.lock nach Änderungen an pyproject.toml aktualisieren (Versionen halten)
make upgrade     # Alle Pakete auf neueste kompatible Versionen aktualisieren
```

---

## CI

`.github/workflows/ci.yml` läuft bei jedem Push auf `main` und auf `feat/**`-Branches sowie bei Pull Requests gegen `main`:

- Python 3.14, Abhängigkeiten per `uv sync` exakt aus `uv.lock`
- `ruff check` + `ruff format --check`
- `pyright` (statische Typprüfung)
- `lint-imports` (Grenzen zwischen den Workspace-Paketen)
- Migration gegen leere DB + `alembic check` (Modelle ↔ Migration)
- `pytest` mit Coverage, DB-Tests gegen einen PostgreSQL-18-Service-Container
- Frontend: Format, Lint, Tests und Build
- Docker-Build aller Images mit Smoke-Test, Compose-Prüfung und J4125-Prüfung (QEMU ohne AVX)
- End-to-End-Test des ganzen Stacks mit einer gespeicherten Woche (Mail, API, UI)
- Push der geprüften Images nach GHCR, nur auf `main` und bei Tags `vX.Y.Z`

---

## Architektur-Entscheidungen

Details zu Faktorwahl, Defaults, bekannten Grenzen und Konventionen: [CLAUDE.md](CLAUDE.md)

Ereignisgetriebene Services mit Angular-Frontend, FastAPI, NATS und PostgreSQL: [Architektur und Roadmap](docs/architecture/README.md), [Architekturentscheidungen (ADRs)](docs/adr/README.md), [Betrieb auf der Synology](docs/architecture/betrieb-synology.md)

---

## Haftungsausschluss

**Keine Anlageempfehlung.** Dieses Werkzeug liefert eine quantitative Vorauswahl. Jede Position erfordert qualitative Prüfung: Geschäftsmodell, Wettbewerbsposition, Bilanzqualität, Insider-Aktivität. Ein quantitativer Score ersetzt das Lesen des Geschäftsberichts nicht.
