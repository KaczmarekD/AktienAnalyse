# Value-Analyzer DAX/MDAX

Batchweise Value-Aktien-Analyse mit wöchentlichem Email-Versand. Läuft als Docker-Container auf Synology DSM 7+.

## Was es tut

- Lädt DAX/MDAX (~110 Werte) von Wikipedia, Fallback aus `data/dax_mdax_fallback.csv`
- Holt Fundamentaldaten via yfinance (kein API-Key nötig)
- Berechnet **Composite Value Score** (EV/EBIT, P/B, P/FCF, Shareholder Yield) und **Quality Score** (ROIC mit effektiver Steuerquote, FCF-Marge, Operating Margin, Net Debt/EBITDA, Earnings-Stabilität)
- Markiert potenzielle Value-Traps
- Versendet jeden **Samstag um 07:30 Europe/Berlin** (konfigurierbar) eine HTML-Mail mit Top/Bottom-Tabellen, CSV-Anhang und Status im Subject (`[ok 110/110]` oder `[partial 80/110]`)
- Optionaler Healthchecks.io-Heartbeat als Dead-Man's-Switch

## Quick Start auf Synology

```bash
# auf der Synology via SSH oder File Station
cd /volume1/docker/
git clone <repo> value-analyzer
cd value-analyzer
cp .env.example .env
nano .env                                  # SMTP_USER/PASSWORD/MAIL_TO setzen
docker compose build
docker compose up -d
docker compose logs -f
```

**Erster Dry-Run** (ohne Mail):
```bash
docker compose run --rm value-analyzer python -m src.main --dry-run
```

**Sofort echter Lauf**:
```bash
docker compose run --rm value-analyzer python -m src.main
```

## Lokale Entwicklung

```bash
make install-dev    # Dev-Dependencies
make dry            # Lokal trockenlaufen lassen
make check          # ruff + pyright + pytest
make test-cov       # Tests mit Coverage-HTML
```

Häufige Befehle siehe `make help`.

## Konfiguration

Alle Einstellungen via `.env` (Pydantic-validiert beim Start):

| Variable | Default | Bedeutung |
|---|---|---|
| `SMTP_HOST/PORT/USER/PASSWORD` | gmail | Gmail-App-Passwort, keine normalen Passwörter |
| `MAIL_TO` | required | Empfänger-Adresse |
| `MAIL_FROM` | = SMTP_USER | Absender (überschreibbar) |
| `UNIVERSE` | `DAX_MDAX` | `DAX_MDAX` oder `DAX_ONLY` |
| `TOP_N` / `BOTTOM_N` | 20 / 10 | Anzahl Top/Bottom-Kandidaten in der Mail |
| `MIN_MARKET_CAP` | 300_000_000 | Mindest-Marktkapitalisierung in EUR |
| `VALUE_WEIGHT` / `QUALITY_WEIGHT` | 0.6 / 0.4 | Composite-Gewichtung (wird auf Summe 1 normiert) |
| `DEFAULT_TAX_RATE` | 0.27 | Fallback wenn effektive Steuerquote nicht ableitbar |
| `CRON_SCHEDULE` | `30 7 * * 6` | Container-internes Cron (Format: m h dom mon dow) |
| `HEALTHCHECK_URL` | – | Optional: https://hc-ping.com/<uuid> für Dead-Man's-Switch |
| `TZ` | `Europe/Berlin` | Zeitzone des Containers |

## Gmail App-Passwort

1. https://myaccount.google.com/security → Zwei-Faktor-Authentifizierung aktivieren
2. https://myaccount.google.com/apppasswords → App-Passwort generieren („Value-Analyzer Synology")
3. Die 16 Zeichen kopieren – wird nur einmal angezeigt

## Projektstruktur

```
value-analyzer/
├── pyproject.toml          # ruff + pytest + pyright Config
├── requirements.in         # Top-Level Dependencies
├── requirements.lock       # Vollständig gepinnt (transitive Deps)
├── requirements-dev.in     # Dev-Tools
├── requirements-dev.lock
├── Makefile                # make help fuer alle Kommandos
├── Dockerfile              # Multi-Stage (builder + slim runtime)
├── docker-compose.yml
├── entrypoint.sh           # Generiert crontab aus CRON_SCHEDULE
├── .env.example
├── README.md
├── CLAUDE.md               # Methodik & Konventionen
├── .github/workflows/ci.yml # GitHub Actions
├── data/
│   ├── dax_mdax_fallback.csv  # Editierbar ohne Code-Aenderung
│   └── (zur Laufzeit: Cache + CSV-Reports)
├── logs/                       # RotatingFileHandler (5MB × 10)
├── src/
│   ├── main.py             # Orchestrator
│   ├── config.py           # Pydantic Settings
│   ├── logging_setup.py    # Rotation
│   ├── universe.py         # Wikipedia + CSV-Fallback
│   ├── fundamentals.py     # Identity/Market/Value/Quality/Growth
│   ├── data_fetcher.py     # yfinance + zentralisiertes FIELD_MAP + Cache
│   ├── scoring.py          # ScoringConfig + Composite Value/Quality
│   ├── reporting.py        # HTML + CSV
│   ├── mailer.py           # SMTP (Gmail)
│   └── healthcheck.py      # Healthchecks.io Ping
└── tests/                  # pytest-Suite (77 Tests)
```

## Methodik im Detail

Siehe [CLAUDE.md](CLAUDE.md) für die Begründung hinter Defaults, Faktorwahl und Architektur-Entscheidungen.

## Lockfile-Workflow

Direkte Edits in `requirements.lock` sind verboten. Stattdessen:

```bash
make lock        # liest *.in, schreibt *.lock (gleiche Versionen sofern möglich)
make upgrade     # liest *.in, schreibt *.lock auf neueste passende Versionen
```

## CI

`.github/workflows/ci.yml` läuft bei jedem Push:
- Python 3.11 + 3.12 Matrix
- ruff check + ruff format --check
- pyright
- pytest mit Coverage
- Docker Build als Smoke-Test

## Haftungsausschluss

**Keine Anlageempfehlung.** Quantitative Vorauswahl ersetzt nicht die Prüfung von Geschäftsmodell, Bilanzqualität und Wettbewerbsposition.
