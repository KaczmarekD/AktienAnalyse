# Value-Analyzer – Projekt-Kontext für Maintainer & Agents

Dieses Dokument hält fest, **warum** der Code so aussieht – die Entscheidungen
hinter den Defaults, die Methodik-Grundlage und die Konventionen. Es ergänzt
den README (der zeigt, **wie** das Projekt betrieben wird).

## Was das Projekt tut

Wöchentlicher Batch-Job auf einer Synology, der DAX/MDAX (90 Werte) nach
einer Value-+-Quality-Methodik durchscoresd und das Ergebnis als E-Mail
versendet (HTML-Top/Flop-Tabellen + CSV-Vollranking).

## Architektur in einem Satz

`load_universe` → `fetch_all` (yfinance) → `score` (Cross-Sektional-Ranking)
→ `build_report` (HTML+CSV) → `send_report` (SMTP), orchestriert von
`src/main.py`, geplant via Cron im Container. Jeder Schritt wird über den
`BatchRecorder` (`src/db/recorder.py`) in PostgreSQL 18 festgehalten.

## Methodik-Entscheidungen

**Composite = 0.6 × Value + 0.4 × Quality** – die Quality-Komponente
existiert primär, um klassische *Value Traps* zu unterdrücken (vgl.
Asness/Frazzini/Pedersen, "Quality Minus Junk"). Reines Value-Investing
kauft die billigsten Aktien – die sind meistens berechtigt billig.

**Value-Faktoren** (alle als Perzentilrang, niedriger Multiple = besser):
EV/EBIT (kapitalstruktur-neutral, Greenblatt-Logik), P/B, P/FCF (FCF ist
schwerer zu manipulieren als E), Shareholder Yield = Div + Buybacks (hoch
= besser). PE bewusst nicht im Composite, weil zu volatil und durch
Einmaleffekte verzerrt.

**Quality-Faktoren**: ROIC, FCF-Marge, Operating Margin, Net Debt/EBITDA
(invertiert), Earnings Stability (1 − min(σ/μ, 1) über 5 Jahre Net Income).
ROIC nutzt die *effektive* Steuerquote pro Unternehmen, wenn Pretax und
Tax Expense vorhanden sind – Fallback ist `DEFAULT_TAX_RATE=0.27`
(deutsche Durchschnittssteuerlast). Begrenzt auf [0, 0.6], um Ausreißer
durch Verlust-Quartale zu kappen.

**Negative Bewertungs-Multiples werden aus dem Value-Ranking
ausgeschlossen**, nicht mit 0 bestraft. Sonst sähen Pleitekandidaten mit
negativem EV/EBIT wie Schnäppchen aus.

**`MIN_MARKET_CAP=300 Mio EUR`** – schließt Micro-Caps aus, in denen
yfinance-Fundamentaldaten oft fehlerhaft oder veraltet sind und die
Liquidität für einen Privatanleger ohnehin grenzwertig ist.

**Value-Trap-Flag** bei oberem Value-Quartil (≥0.70) und unterem
Quality-Quartil (≤0.30). Die Werte sind bewusst weicher als die exakten
0.75/0.25-Quartil-Grenzen, damit auch borderline-Fälle gefangen werden.

## Konventionen

**Datenfluss-Format**: Innerhalb des Codes arbeiten wir mit der
`Fundamentals`-Dataclass (semantisch aufgeteilt in Identity/MarketData/
ValueMetrics/QualityMetrics/Growth). An der Grenze zu pandas (Scoring,
Reporting) wird via `to_flat_dict()` flachgeklopft. Diese Trennung ist
gewollt: Sub-Dataclasses für Lesbarkeit, flat dict für DataFrame-Effizienz.

**yfinance-Feldnamen** stehen ausschließlich in `FIELD_MAP` am Kopf von
`data_fetcher.py`. yfinance benennt Statement-Zeilen unangekündigt um
("Total Revenue" → "TotalRevenue") – wenn das passiert, ist FIELD_MAP die
einzige zu ändernde Stelle.

**Konfiguration kommt aus Pydantic Settings**, niemals aus eingebetteten
Konstanten. Wenn du eine Konstante brauchst und sie könnte sich je nach
Deployment unterscheiden, geh durch `Settings`.

**Magic Numbers in `scoring.py` gehören in `ScoringConfig`**. Wenn du einen
Schwellwert hardcoden willst, frag dich erst, ob `ScoringConfig` die richtige
Heimat ist – meistens ja.

**Universum-Quellen: iShares → Deka → Fallback-CSV** (`src/universe.py`).
Wikipedia wurde ersetzt, weil die englische MDAX-Seite nachweislich veraltet
war und die deutsche keine Ticker hat. Jede Live-Quelle wird hart validiert
(lesbares JSON/XLSX, exakt 40/50 Aktien; iShares zusätzlich Stichtag
plausibel und ≤ 10 Tage – die Deka-Datei enthält kein Datum, der Report
zeigt dann „ohne Stichtag“). Die undokumentierte iShares-API brach im
Sept. 2026 schon einmal still (HTML mit HTTP 200). Abweichungen zur CSV
werden über Symbol + Index + ISIN erkannt, also auch Auf-/Abstiege.
Recherche und Abwägung: `docs/research/dax-mdax-datenquellen/bericht.md` (Rohnotizen unter `notizen/`).

**Fallback-CSV `data/dax_mdax_fallback.csv` (symbol,name,index,isin)** wird
von Hand gepflegt und nie automatisch überschrieben – sie ist das geprüfte
Sicherheitsnetz. Die ISIN ist der Schlüssel für die Deka-Quelle. Weicht die
Live-Quelle ab (Indexreview), zeigt der Mail-Report „Fallback-CSV pflegen“.

**Datenhaltung: PostgreSQL, Daten werden niemals gelöscht.** Die DB ist die
einzige Quelle der Wahrheit (keine Parquet-Caches, kein Housekeeping mehr).
Warum: Snapshots sind nicht rekonstruierbar – yfinance liefert nur den
aktuellen, teils nachträglich korrigierten Stand und maximal 4 Geschäftsjahre.
- Schemas = spätere Services: `batch`, `market_data`, `scoring`, `reporting`.
  Fremdschlüssel nur innerhalb eines Schemas, dazwischen Verweis per ID.
- Die DB erzwingt „niemals löschen“ selbst (`src/db/ddl.py`): Trigger gegen
  DELETE/TRUNCATE auf jeder Tabelle, Faktentabellen zusätzlich gegen UPDATE.
  Einzige UPDATEs: einmaliger Abschluss von `batch.run`/`market_data.fetch_run`
  und das Nachtragen einer ISIN. Rollen: `va_app` ohne DELETE, `va_read` nur
  SELECT (LAN-Auswertungen).
- Neu-Berechnungen erzeugen neue Zeilen (z.B. neuer `scoring_run` auf alten
  Abruf), nie Überschreibungen. Abschlusswerte sind versioniert
  (`statement_value`: neue Zeile nur bei geändertem Wert → Restatements sichtbar,
  Abfrage „Stand zu Datum X“ über `get_statements_as_of`).
- Zugriffe nur über die Repositories in `src/db/repositories/` (`get_*`/`write_*`,
  bewusst ohne delete). Jeder Titel wird sofort nach dem Abruf gespeichert.
- Migrationen (Alembic, `migrations/`) sind nur additiv; jede neue Tabelle
  braucht `protect_table()` – `tests/db/test_protection.py` prüft das.
- Ist die DB nicht erreichbar, bricht der Lauf mit Exit 4 ab: ohne
  Speicherung kein Report; ein manueller Nachlauf am selben Tag reicht.

**Robustheit vor Performance**: yfinance fällt regelmäßig aus, gibt
inkonsistente Daten zurück, ETF-Anbieter bauen Websites um. Jeder externe Call hat
Retry+Fallback. Lieber einen Ticker verlieren als den ganzen Batch.

## Zielarchitektur (beschlossen, in Umsetzung)

Das Projekt wird schrittweise zu ereignisgetriebenen Microservices
umgebaut: `market-data`, `scoring`, `notification` und `web-api` (FastAPI:
REST, WebSocket, Eventmanager), dazu ein Angular-Frontend im eigenen
nginx-Container, NATS JetStream und PostgreSQL. Plan und Roadmap:
`docs/architecture/README.md`, Entscheidungen: `docs/adr/` (ADR-0001 bis
ADR-0009), Recherche: `docs/research/`.

Bis eine Phase umgesetzt ist, beschreibt dieses Dokument den **Ist-Stand**.
Neue Arbeit folgt der Zielrichtung, bei Widersprüchen gelten die ADRs.
Pläne und Recherche-Ergebnisse werden in `docs/` fortgeschrieben, nicht nur
im Chat besprochen.

**Arbeitsweise:** Umgesetzt wird in Arbeitspaketen nach dem Zyklus
Test → Implementierung → Grün → Review
(`docs/architecture/implementierungsplan.md`):
1. Tests zuerst.
2. Code, bis die neuen Tests grün sind.
3. Die komplette Prüfkette läuft durch (`make check` und `make test-db`).
4. Review des Diffs.

Gemergt wird erst nach Abnahme durch den User. Abgehakt wird in
`docs/architecture/roadmap.md`.

**Grenzen der Zielhardware** (Synology mit Celeron J4125, ADR-0008):
- Kein AVX/AVX2: keine Pakete, die x86-64-v3 voraussetzen. Nach
  Dependency-Upgrades im Image auf der NAS `python -c "import numpy, pandas"`
  prüfen.
- DSM-Kernel 4.4: Ziel ist, Images nur für `linux/amd64` in CI zu bauen
  statt auf der NAS (Roadmap Phase 0). Node/Bun laufen nie auf der NAS.

## Was NICHT in dieses Projekt gehört

- Backtesting/Performance-Tracking. Das ist ein **Screener**, kein Backtest.
  Wenn das gewünscht wird, separate Pipeline mit `vectorbt`.
- Sektor-relatives Ranking. Aktuell global. Wäre für Banken/Versicherer
  sauberer, aber bei 90 Werten zu wenig Daten pro Sektor.
- Echtzeit-Daten oder Intraday. Wöchentlicher Batch reicht für
  Fundamentaldaten, die sich quartalsweise ändern. Der geplante WebSocket
  im web-api synchronisiert nur die UI und streamt keine Kurse.
- Ein separates Dependency-Injection-Framework. `Depends` von FastAPI und
  FastStream reicht.

Früher stand hier auch „Microservices/Message Queues“. Das ist durch
ADR-0001 und ADR-0002 aufgehoben.

## Wenn du was änderst

**Neuer Scoring-Faktor**:
1. Feld in passende `*Metrics`-Dataclass in `fundamentals.py`
2. Extraktion in `data_fetcher.fetch_one()` (`FIELD_MAP` erweitern, falls
   yfinance-Roh-Feld nötig)
3. Eintrag in `DEFAULT_VALUE_FACTORS` oder `DEFAULT_QUALITY_FACTORS`
4. Spalte in `FundamentalSnapshot` (`src/db/models/market_data.py`) und
   Migration: `alembic revision --autogenerate -m "..."` (nur additiv) –
   sonst lehnt `write_snapshot` die unbekannte Spalte ab
5. Test in `tests/test_scoring.py`

**Neues Universum (z.B. Stoxx 600)**:
1. Quelle(n) in `src/universe.py` (URL-Konstanten am Dateikopf, Soll-Anzahl
   in `UniverseConfig.expected_counts`)
2. Fallback-CSV in `data/` inkl. ISIN-Spalte
3. ENV `UNIVERSE` in `config.py` um neuen Literal-Wert erweitern
4. Branch in `main.py:_run`

**Neue Mail-Empfänger**: `MAIL_TO` ist heute Single-Recipient. Wenn mehrere,
auf Liste umstellen (`pydantic.EmailStr` → `list[EmailStr]`, `;`-getrennt
parsen) und `mailer.py` anpassen.

## Externe Quellen, von denen wir abhängen

- **yfinance** (Yahoo Finance): kostenlos, kein Vertrag. Kann jederzeit
  rate-limiten oder umbenennen. Wenn das chronisch wird, Wechsel zu FMP
  oder EODHD über ein neues `data_fetcher_*.py`-Modul.
- **iShares-Holdings (EXS1/EXS3)**: undokumentierte Frontend-API von
  BlackRock, liefert Ticker + ISIN. Kann jederzeit umziehen – dann URL/Params
  am Kopf von `universe.py` anpassen.
- **Deka-ETF-XLSX**: Blatt „Indexzusammensetzung“, nur ISIN/WKN.
- **OpenFIGI**: ISIN → Xetra-Ticker für Neuaufnahmen, die noch nicht in der
  CSV stehen; ohne API-Key (10 ISINs pro Request).
- Keine dieser Quellen erlaubt automatisierten Abruf ausdrücklich; robots.txt
  sperrt die genutzten Pfade nicht. Private Nutzung, 1× pro Woche.
- **Gmail SMTP**: kostenlos bis ~500 Mails/Tag; App-Passwort erforderlich.
- **Healthchecks.io** (optional): Free-Tier reicht für einen wöchentlichen
  Check; alternativ Self-Hosted oder gar nicht.

## Qualitätssicherung

`make check` läuft Ruff + Pyright + Pytest. CI auf GitHub Actions macht
dasselbe bei jedem Push auf `main` und `feat/**` sowie bei Pull Requests.
Tests in `tests/` decken Scoring-Logik, CSV-Load,
Reporting-Struktur und Config-Validierung ab. yfinance-Calls werden in
Tests *nicht* gemockt – die Funktionen, die sie aufrufen, sind kein Teil
der Test-Suite (zu viel Mocking-Overhead, zu wenig Wert).

DB-Tests (`tests/db/`) laufen gegen ein echtes PostgreSQL, nicht gegen
SQLite oder Mocks – Trigger, Rollenrechte und `DISTINCT ON` sind der
eigentliche Prüfgegenstand. Jede Testfunktion bekommt eine frische DB aus
einer migrierten Vorlage (Löschen ist ja verboten). Ohne `TEST_DATABASE_URL`
werden sie übersprungen; lokal `make test-db-up && make test-db`, in CI
per Postgres-Service-Container.

**Golden-Master der Mail** (`tests/test_golden_report.py`, Dateien unter
`tests/golden/`): Ein eingefrorener Datensatz
(`golden/input_fundamentals.json`, bewusst nicht die geteilte Fixture) läuft
durch `score()` und `build_report()`. Dabei gilt:
- HTML (je Zweig der Indexquelle) und Metadaten müssen byte-gleich bleiben.
- Die CSV muss inhaltlich gleich bleiben, Gleitkommazahlen mit Toleranz in
  der letzten Stelle.
- Format-Regeln: BOM, `;`, Dezimalkomma, LF.

Das ist das Sicherungsnetz für Umbauten, in Phase 1 dürfen sich die Dateien
nicht ändern. Ist eine Änderung an der Mail gewollt, die Dateien mit
`pytest tests/test_golden_report.py --update-golden` neu schreiben. Geänderte
Dateien melden sich dabei als „übersprungen“, und der Diff wird im Review
begründet. In der CI ist `--update-golden` verboten. `build_report` bekommt
dafür einen festen Zeitpunkt (`now=`), die CSV hat immer LF-Zeilenenden.

## Disclaimer

Dieses Werkzeug liefert eine quantitative Vorauswahl. **Keine
Anlageempfehlung.** Jede Position muss qualitativ überprüft werden:
Geschäftsmodell, Wettbewerbsposition, Insider-Aktivität, Bilanzqualität.
Quantitative Screens identifizieren Kandidaten – sie ersetzen das Lesen
des Geschäftsberichts nicht.
