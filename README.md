# Value-Analyzer DAX/MDAX

> Wöchentlicher Fundamentaldaten-Screener für DAX und MDAX. Läuft als Docker-Container auf einer Synology und verschickt jeden Samstag eine HTML-Mail mit den besten und schlechtesten Titeln nach Value- und Quality-Kriterien.

[![CI](https://github.com/KaczmarekD/AktienAnalyse/actions/workflows/ci.yml/badge.svg)](https://github.com/KaczmarekD/AktienAnalyse/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![Version](https://img.shields.io/badge/version-0.2.0-green)
![License](https://img.shields.io/badge/license-Proprietary-lightgrey)

---

## Was es tut

- Lädt das DAX/MDAX-Universum (~110 Titel) von Wikipedia, Fallback aus `data/dax_mdax_fallback.csv`
- Holt Fundamentaldaten via **yfinance** (kein API-Key nötig) mit lokalem Parquet-Cache
- Berechnet einen **Composite Score** aus Value- und Quality-Faktoren (cross-sektional, Perzentilrang)
- Markiert potenzielle **Value Traps** (billig, aber schlechte Qualität)
- Verschickt jeden **Samstag 07:30 Europe/Berlin** eine HTML-Mail mit Top/Bottom-Tabellen und CSV-Anhang
- Optionaler **Healthchecks.io**-Heartbeat als Dead-Man's-Switch

---

## Pipeline

```
load_universe()          Wikipedia + CSV-Fallback → Liste von Tickern
      │
fetch_all()              yfinance + Parquet-Cache → DataFrame mit Fundamentaldaten
      │
score()                  Marktkapitalisierungsfilter → Perzentilränge → Composite Score
      │
build_report()           HTML-Mail-Body + CSV-Vollranking
      │
send_report()            SMTP (Gmail App-Passwort)
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
nano .env          # SMTP_USER, SMTP_PASSWORD, MAIL_TO setzen
docker compose build
docker compose up -d
docker compose logs -f
```

**Dry-Run** (kein Mailversand, erzeugt nur HTML+CSV):
```bash
docker compose run --rm value-analyzer python -m src.main --dry-run
```

**Sofortiger echter Lauf**:
```bash
docker compose run --rm value-analyzer python -m src.main
```

### Lokale Entwicklung

```bash
make install-dev    # Dev-Abhängigkeiten installieren
cp .env.example .env && nano .env
make dry            # Dry-Run lokal
make check          # ruff + pyright + pytest
make test-cov       # Tests mit Coverage-HTML-Report
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
│   ├── universe.py         # Wikipedia-Parser + CSV-Fallback
│   ├── fundamentals.py     # Dataclasses: Identity/MarketData/Value/Quality/Growth
│   ├── data_fetcher.py     # yfinance + FIELD_MAP + Parquet-Cache
│   ├── scoring.py          # ScoringConfig + Cross-sektionaler Composite Score
│   ├── reporting.py        # HTML-Mail-Body + CSV-Vollranking
│   ├── mailer.py           # SMTP-Versand (Gmail)
│   ├── healthcheck.py      # Healthchecks.io Ping
│   └── logging_setup.py    # RotatingFileHandler (5 MB × 10)
├── tests/                  # pytest-Suite (38 Testdateien)
├── data/
│   └── dax_mdax_fallback.csv   # Editierbar ohne Rebuild bei DAX/MDAX-Mutationen
├── pyproject.toml          # ruff + pytest + pyright Konfiguration
├── requirements.in         # Top-Level-Abhängigkeiten
├── requirements.lock       # Vollständig gepinnte transitive Abhängigkeiten
├── Dockerfile              # Multi-Stage (Builder + schlanke Runtime)
├── docker-compose.yml
├── entrypoint.sh           # Generiert crontab aus CRON_SCHEDULE-Env
├── Makefile                # make help für alle Kommandos
└── .env.example
```

---

## Lockfile-Workflow

Direkte Änderungen in `requirements.lock` sind nicht erlaubt. Abhängigkeiten werden über die `.in`-Dateien verwaltet:

```bash
make lock        # Lockfiles aus *.in regenerieren (Versionen halten)
make upgrade     # Alle Pakete auf neueste kompatible Versionen aktualisieren
```

---

## CI

`.github/workflows/ci.yml` läuft bei jedem Push:

- Python 3.11 und 3.12 Matrix
- `ruff check` + `ruff format --check`
- `pyright` (statische Typprüfung)
- `pytest` mit Coverage
- Docker-Build als Smoke-Test

---

## Architektur-Entscheidungen

Details zu Faktorwahl, Defaults, bekannten Grenzen und Konventionen: [CLAUDE.md](CLAUDE.md)

---

## Haftungsausschluss

**Keine Anlageempfehlung.** Dieses Werkzeug liefert eine quantitative Vorauswahl. Jede Position erfordert qualitative Prüfung: Geschäftsmodell, Wettbewerbsposition, Bilanzqualität, Insider-Aktivität. Ein quantitativer Score ersetzt das Lesen des Geschäftsberichts nicht.
