# Value-Analyzer – Projekt-Kontext für Maintainer & Agents

Dieses Dokument hält fest, **warum** der Code so aussieht – die Entscheidungen
hinter den Defaults, die Methodik-Grundlage und die Konventionen. Es ergänzt
den README (der zeigt, **wie** das Projekt betrieben wird).

## Was das Projekt tut

Wöchentlicher Batch-Job auf einer Synology, der DAX/MDAX (~110 Werte) nach
einer Value-+-Quality-Methodik durchscoresd und das Ergebnis als E-Mail
versendet (HTML-Top/Flop-Tabellen + CSV-Vollranking).

## Architektur in einem Satz

`load_universe` → `fetch_all` (yfinance + Parquet-Cache) → `score`
(Cross-Sektional-Ranking) → `build_report` (HTML+CSV) → `send_report` (SMTP),
orchestriert von `src/main.py`, geplant via Cron im Container.

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

**Fallback-Ticker leben in `data/dax_mdax_fallback.csv`**, nicht im Code.
DAX/MDAX-Mutationen passieren mehrmals pro Jahr – CSV editieren ohne Rebuild.

**Robustheit vor Performance**: yfinance fällt regelmäßig aus, gibt
inkonsistente Daten zurück, Wikipedia ändert HTML. Jeder externe Call hat
Retry+Fallback. Lieber einen Ticker verlieren als den ganzen Batch.

## Was NICHT in dieses Projekt gehört

- Backtesting/Performance-Tracking. Das ist ein **Screener**, kein Backtest.
  Wenn das gewünscht wird, separate Pipeline mit `vectorbt`.
- Sektor-relatives Ranking. Aktuell global. Wäre für Banken/Versicherer
  sauberer, aber bei 110 Werten zu wenig Daten pro Sektor.
- Echtzeit-Daten oder Intraday. Wöchentlicher Batch reicht für
  Fundamentaldaten, die sich quartalsweise ändern.
- Dependency-Injection-Framework. Bei 9 Modulen würde es nur Lesbarkeit
  kosten.
- Microservices/Message Queues. Single-Container-Batch.

## Wenn du was änderst

**Neuer Scoring-Faktor**:
1. Feld in passende `*Metrics`-Dataclass in `fundamentals.py`
2. Extraktion in `data_fetcher.fetch_one()` (`FIELD_MAP` erweitern, falls
   yfinance-Roh-Feld nötig)
3. Eintrag in `DEFAULT_VALUE_FACTORS` oder `DEFAULT_QUALITY_FACTORS`
4. Test in `tests/test_scoring.py`

**Neues Universum (z.B. Stoxx 600)**:
1. Wiki-URL und Parser in `src/universe.py`
2. Fallback-CSV in `data/`
3. ENV `UNIVERSE` in `config.py` um neuen Literal-Wert erweitern
4. Branch in `main.py:_run`

**Neue Mail-Empfänger**: `MAIL_TO` ist heute Single-Recipient. Wenn mehrere,
auf Liste umstellen (`pydantic.EmailStr` → `list[EmailStr]`, `;`-getrennt
parsen) und `mailer.py` anpassen.

## Externe Quellen, von denen wir abhängen

- **yfinance** (Yahoo Finance): kostenlos, kein Vertrag. Kann jederzeit
  rate-limiten oder umbenennen. Wenn das chronisch wird, Wechsel zu FMP
  oder EODHD über ein neues `data_fetcher_*.py`-Modul.
- **Wikipedia DAX/MDAX-Tabellen**: lieferndes HTML kann jederzeit Spalten
  umsortieren. Der Parser ist defensiv, Fallback-CSV deckt den Ausfall ab.
- **Gmail SMTP**: kostenlos bis ~500 Mails/Tag; App-Passwort erforderlich.
- **Healthchecks.io** (optional): Free-Tier reicht für einen wöchentlichen
  Check; alternativ Self-Hosted oder gar nicht.

## Qualitätssicherung

`make check` läuft Ruff + Pyright + Pytest. CI auf GitHub Actions macht
dasselbe bei jedem Push. Tests in `tests/` decken Scoring-Logik, CSV-Load,
Reporting-Struktur und Config-Validierung ab. yfinance-Calls werden in
Tests *nicht* gemockt – die Funktionen, die sie aufrufen, sind kein Teil
der Test-Suite (zu viel Mocking-Overhead, zu wenig Wert).

## Disclaimer

Dieses Werkzeug liefert eine quantitative Vorauswahl. **Keine
Anlageempfehlung.** Jede Position muss qualitativ überprüft werden:
Geschäftsmodell, Wettbewerbsposition, Insider-Aktivität, Bilanzqualität.
Quantitative Screens identifizieren Kandidaten – sie ersetzen das Lesen
des Geschäftsberichts nicht.
