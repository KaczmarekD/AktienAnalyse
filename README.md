# Value-Analyzer DAX/MDAX

> Wöchentlicher Fundamentaldaten-Screener für DAX und MDAX. Läuft als Docker-Container auf einer Synology und verschickt jeden Samstag eine HTML-Mail mit den besten und schlechtesten Titeln nach Value- und Quality-Kriterien.

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

---

## Pipeline

```
load_universe()          iShares → Deka → CSV, validiert → Ticker + Quelle
      │
fetch_all()              yfinance → je Titel sofort in PostgreSQL (Rohdaten + Kennzahlen)
      │
score()                  Marktkapitalisierungsfilter → Perzentilränge → Composite Score
      │
build_report()           HTML-Mail-Body + CSV-Vollranking
      │
send_report()            SMTP (Gmail App-Passwort); Report + Versand in PostgreSQL
      │
ping()                   Healthchecks.io (optional)
```

---

## Methodik

### Composite Score = 0.6 × Value + 0.4 × Quality

Alle Faktoren werden als **Perzentilrang** (0–1) über das gefilterte Universum berechnet. Fehlende Werte werden übersprungen, nicht mit 0 bestraft. Der Composite wird nur vergeben, wenn mindestens 50 % der Faktoren je Kategorie vorliegen.

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
| Earnings Stability | `1 − min(σ/μ, 1)` über 5 Jahre Net Income; 1 = konstante Gewinne |

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
nano .env          # SMTP_*, MAIL_TO und die drei DB-Passwörter setzen
docker compose build
docker compose up -d   # startet Postgres (db) und den Batch; Schema wird beim Start migriert
docker compose logs -f
```

**Altdaten übernehmen** (vorhandene `fundamentals_*.parquet` / `value_ranking_*.csv` in `data/`, auch aus Mails gespeicherte CSVs – mehrfach ausführbar, Dateien bleiben liegen):
```bash
make db-import
```

**Dry-Run** (kein Mailversand, erzeugt nur HTML+CSV):
```bash
docker compose run --rm value-analyzer python -m src.main --dry-run
```

**Sofortiger echter Lauf**:
```bash
docker compose run --rm value-analyzer python -m src.main
```

### Datenbank & Auswertungen

PostgreSQL 18 läuft als Container `db`; Daten liegen im Bind-Mount `./pgdata` (sichert Hyper Backup mit, `docker compose down -v` kann ihn nicht löschen).

| Schema | Inhalt |
|---|---|
| `batch` | Läufe (Status, Einstellungen ohne Passwörter, Fehler), Log-Zeilen je Lauf, importierte Altdateien |
| `market_data` | Instrumente (Symbol, ISIN), Abrufe, Index-Zugehörigkeit je Abruf, yfinance-Rohdaten (JSONB), versionierte Abschlusswerte, Wechselkurse, Kennzahlen je Abruf |
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

In Python liefern die Repositories (`src/db/repositories/`) fertige DataFrames, z.B. `get_metric_history`, `get_score_history`, `get_statement_history`, `get_statements_as_of` (Abschlusswerte, wie sie an einem Stichtag bekannt waren).

`make db-backup` schreibt einen Dump nach `backups/`, `make db-shell` öffnet `psql`. Einen Reset gibt es bewusst nicht.

### Lokale Entwicklung

Voraussetzung ist [uv](https://docs.astral.sh/uv/) (Windows: `winget install astral-sh.uv`). uv holt auch die passende Python-Version.

```bash
make install-dev    # alle Abhängigkeiten exakt aus uv.lock (.venv)
cp .env.example .env && nano .env
make dry            # Dry-Run lokal
make check          # ruff + pyright + pytest (DB-Tests werden ohne DB übersprungen)
make test-db-up     # Wegwerf-Postgres auf Port 55432 (Docker)
make test-db        # alle Tests inkl. DB-Tests
make test-cov       # Tests mit Coverage-HTML-Report
make check-j4125    # Image unter QEMU ohne AVX prüfen (CPU der NAS), vor Dependency-Upgrades
```

`make help` zeigt alle verfügbaren Targets.

---

## Konfiguration (`.env`)

| Variable | Default | Beschreibung |
|---|---|---|
| `SMTP_HOST` | `smtp.gmail.com` | SMTP-Server |
| `SMTP_PORT` | `587` | SMTP-Port (STARTTLS) |
| `SMTP_USER` | – **Pflicht** | Gmail-Adresse |
| `SMTP_PASSWORD` | – **Pflicht** | Gmail App-Passwort (16 Zeichen) |
| `MAIL_TO` | – **Pflicht** | Empfänger-Adresse |
| `MAIL_FROM` | `= SMTP_USER` | Absender (überschreibbar) |
| `MAIL_SUBJECT_PREFIX` | `[Value-Screening DAX/MDAX]` | Mail-Betreff-Präfix |
| `UNIVERSE` | `DAX_MDAX` | `DAX_MDAX` oder `DAX_ONLY` |
| `TOP_N` / `BOTTOM_N` | `20` / `10` | Anzahl Top/Bottom-Kandidaten in der Mail |
| `MIN_MARKET_CAP` | `300000000` | Mindest-Marktkapitalisierung in EUR |
| `VALUE_WEIGHT` / `QUALITY_WEIGHT` | `0.6` / `0.4` | Composite-Gewichtung (wird auf Summe 1 normiert) |
| `DEFAULT_TAX_RATE` | `0.27` | Fallback-Steuersatz für ROIC-Berechnung |
| `CRON_SCHEDULE` | `30 7 * * 6` | Cron-Ausdruck (Sa 07:30); Format: `m h dom mon dow` |
| `POSTGRES_PASSWORD` | – **Pflicht** | Passwort der Owner-Rolle `va_owner` (Migrationen) |
| `VA_APP_PASSWORD` | – **Pflicht** | Passwort der App-Rolle `va_app` (kein DELETE); wirkt beim ersten DB-Start |
| `VA_READ_PASSWORD` | – **Pflicht** | Passwort der Lese-Rolle `va_read` für Auswertungen; wirkt beim ersten DB-Start |
| `DB_LAN_BIND` | `127.0.0.1` | IP, an die der Postgres-Port gebunden wird (NAS-IP = im LAN erreichbar) |
| `DATABASE_URL` | von Compose gesetzt | Nur lokal nötig: `postgresql+psycopg://va_app:<pw>@host:5432/value_analyzer` |
| `HEALTHCHECK_URL` | – | Optional: `https://hc-ping.com/<uuid>` |
| `TZ` | `Europe/Berlin` | Container-Zeitzone |

### Gmail App-Passwort einrichten

1. [Zwei-Faktor-Authentifizierung aktivieren](https://myaccount.google.com/security)
2. [App-Passwort generieren](https://myaccount.google.com/apppasswords) → „Value-Analyzer Synology"
3. Die 16 Zeichen in `.env` als `SMTP_PASSWORD` eintragen

---

## Projektstruktur

```
value-analyzer/
├── src/
│   ├── main.py             # Orchestrator: verbindet alle Module
│   ├── config.py           # Pydantic Settings (validiert beim Start)
│   ├── universe.py         # Index-Quellen iShares/Deka/CSV + Validierung
│   ├── fundamentals.py     # Dataclasses: Identity/MarketData/Value/Quality/Growth
│   ├── data_fetcher.py     # yfinance + FIELD_MAP, Rohdaten je Titel
│   ├── scoring.py          # ScoringConfig + Cross-sektionaler Composite Score
│   ├── reporting.py        # HTML-Mail-Body + CSV-Vollranking
│   ├── mailer.py           # SMTP-Versand (Gmail)
│   ├── healthcheck.py      # Healthchecks.io Ping
│   ├── logging_setup.py    # RotatingFileHandler (5 MB × 10)
│   └── db/                 # PostgreSQL: Modelle, Repositories (get/write), Recorder,
│                           #   Migration, Löschschutz (ddl.py), Altdaten-Import
├── migrations/             # Alembic-Migrationen (nur additiv)
├── db/init/01_roles.sh     # Rollen va_app/va_read beim ersten DB-Start
├── tests/                  # pytest-Suite; tests/db/ gegen echtes PostgreSQL
├── data/
│   └── dax_mdax_fallback.csv   # Editierbar ohne Rebuild bei DAX/MDAX-Mutationen
├── pyproject.toml          # Abhängigkeiten + ruff/pytest/pyright-Konfiguration
├── uv.lock                 # Exakt gepinnte Versionen aller Abhängigkeiten (uv)
├── Dockerfile              # Installiert exakt aus uv.lock, uv selbst bleibt draußen
├── docker-compose.yml
├── entrypoint.sh           # Generiert crontab aus CRON_SCHEDULE-Env
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
- Migration gegen leere DB + `alembic check` (Modelle ↔ Migration)
- `pytest` mit Coverage, DB-Tests gegen einen PostgreSQL-18-Service-Container
- Docker-Build als Smoke-Test

---

## Architektur-Entscheidungen

Details zu Faktorwahl, Defaults, bekannten Grenzen und Konventionen: [CLAUDE.md](CLAUDE.md)

Geplanter Umbau zu Microservices mit Angular-Frontend, FastAPI, NATS und PostgreSQL: [Zielarchitektur und Roadmap](docs/architecture/README.md), [Architekturentscheidungen (ADRs)](docs/adr/README.md)

---

## Haftungsausschluss

**Keine Anlageempfehlung.** Dieses Werkzeug liefert eine quantitative Vorauswahl. Jede Position erfordert qualitative Prüfung: Geschäftsmodell, Wettbewerbsposition, Bilanzqualität, Insider-Aktivität. Ein quantitativer Score ersetzt das Lesen des Geschäftsberichts nicht.
