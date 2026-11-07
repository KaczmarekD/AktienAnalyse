# Wertpapiere: Aktien, ETFs und Anleihen

> **Status:** Spezifikation, Entwurf vom 04.11.2026. Teil der
> [Depot-Spezifikation](README.md), Stufe D2. Grundsatzentscheidung:
> [ADR-0013](../../adr/0013-depots-im-service-portfolio.md) (angenommen am 06.11.2026).
> Datenquellen: [Recherche 11/2026](../../research/2026-11-depot-datenquellen-und-bankzugang.md).
> Umgesetzt: Suche und Auflösung (D2.1, `security`, `security_master`, `listing`), Abdeckung im
> Wochenlauf (D2.2, `coverage_version`, `coverage_item`, `fundamental_snapshot.role`,
> `covered[]`; bis D3 per Kommando gepflegt), Tageskurse (D2.3, `price_run`, `daily_close`,
> `fx_daily`, Scheduler im web-api; Bundesanleihen aus der Bundesbank folgen mit D2.4).

## Ausgangslage

market-data kennt heute nur die 90 Aktien aus DAX und MDAX. Ein Titel ist dort ein Yahoo-Symbol
(`market_data.instrument`, Symbol eindeutig, ISIN wird nachgetragen). Depots brauchen beliebige
Wertpapiere, die meist über ISIN oder WKN bekannt sind, auch solche ohne Yahoo-Symbol.

## Begriffe

| Begriff | Bedeutung |
|---|---|
| **Wertpapier** | über die ISIN eindeutig. Hat eine Anlageklasse. |
| **Listing** | Handel eines Wertpapiers an einem Börsenplatz, mit Symbol und Handelswährung. Ein Wertpapier hat null bis viele Listings. Das heutige `market_data.instrument` ist das Listing für die Fundamentaldaten, seine ISIN ist dort eindeutig. Weitere Listings derselben ISIN (z. B. der Xetra-Kurs einer US-Aktie) stehen in der neuen Tabelle `market_data.listing`. |
| **Anlageklasse** | `equity` (Aktie), `etf` (ETF und andere Fonds), `bond` (Anleihe), `other` (z. B. Zertifikat: nur Bestand und Kurs, keine Analyse) |
| **Abdeckung** | Die Menge der Wertpapiere, für die market-data Daten holt: Referenzuniversum plus alles, was in einem Depot oder einer Beobachtungsliste steht. |

## Anforderungen

| ID | Prio | Anforderung |
|---|---|---|
| WP-01 | Muss | Ein Wertpapier ist über die ISIN eindeutig. WKN und Symbol sind Zusatzangaben. |
| WP-02 | Muss | Suche nach ISIN, WKN, Name oder Symbol. Treffer zeigen Anlageklasse, Börsenplatz und Währung. |
| WP-03 | Muss | Auflösung ISIN → Listing für den Datenabruf. Standard ist Xetra (`.DE`), sonst die Heimatbörse. Der Nutzer kann ein anderes Listing wählen. |
| WP-04 | Muss | Stammdaten je Anlageklasse (Tabelle unten), versioniert und nie überschrieben. |
| WP-05 | Muss | Abdeckung: Der Wochenlauf ruft Fundamentaldaten für alle Aktien in der Abdeckung ab, zusätzlich zum Referenzuniversum. |
| WP-06 | Muss | Schlusskurse an jedem Handelstag für alle Wertpapiere mit Listing, kein Intraday. |
| WP-07 | Muss | Ein Wertpapier ohne Daten blockiert nichts. Es fehlt mit Grund, die anderen laufen weiter (Robustheit vor Vollständigkeit). |
| WP-08 | Muss | Anleihen ohne Listing: Stammdaten und Kurs kommen aus dem Bankabruf oder werden von Hand erfasst. |
| WP-09 | Muss | market-data erfährt nur die Menge der abzudeckenden Wertpapiere, nie Nutzer oder Mengen. |
| WP-10 | Soll | ETF-Bestände für die Durchschau (Look-through), mit Stand und dem Hinweis, ob die Liste vollständig ist. |
| WP-11 | Soll | Fremdwährungen: Kurse und Werte werden mit dem Schlusskurs der Währung in EUR umgerechnet (`market_data.fx_rate`, heute schon für die Kennzahlen). |
| WP-12 | Kann | Weitere Referenzuniversen (z. B. STOXX Europe 600), nach dem Rezept „Neues Universum“ in CLAUDE.md. |
| WP-13 | Muss | Ein neues Wertpapier der Abdeckung wird sofort abgerufen: Stammdaten, letzter Kurs, bei Aktien die Fundamentaldaten. scoring ordnet es gegen den letzten Bewertungslauf ein. Bis dahin zeigt das Depot die Position als „wird geprüft“. |

## Stammdaten je Anlageklasse

| Anlageklasse | Stammdaten | Laufend |
|---|---|---|
| Aktie | Name, Land, Sektor, Branche, Handels- und Berichtswährung, LEI des Emittenten | Fundamentaldaten wie heute (wöchentlich), Schlusskurse |
| ETF | Name, Fondswährung, TER, Fondsvolumen, Ausschüttung, Replikation, Anbieter | Struktur nach Sektor, Land, Anlageklasse; Bestände; Schlusskurse |
| Anleihe | Emittent mit LEI, Land, Währung, Kupon, Kuponfrequenz, Zinsmethode (z. B. ACT/ACT ICMA), erster und letzter Kupontermin, Fälligkeit, Stückelung, Rang, CFI-Code, Sonderform (Floater, inflationsindexiert, ewig, wandelbar, kündbar; erkennbar an der Zinsart im CFI-Code und am Namen) | Kurs in % vom Nennwert |
| Sonstiges | Name, Währung | Kurs, wenn vorhanden |

## Quellen

Stand der [Recherche](../../research/2026-11-depot-datenquellen-und-bankzugang.md) vom 04.11.2026,
live geprüft am 06.11.2026 ([Ergebnisse](../../research/2026-11-depot-datenquellen-und-bankzugang.md#live-prüfung-06112026)).
Jede Quelle ist ein Adapter in market-data.

| Daten | Erste Quelle | Ersatz | Hinweis |
|---|---|---|---|
| ISIN → Listing | OpenFIGI (ohne Schlüssel 25 Anfragen pro Minute, mit kostenlosem Schlüssel 250) | yfinance-Suche, CSV aller Xetra-Instrumente der Deutschen Börse | Live: findet Bund, Unternehmensanleihe, Aktie und ETF. Anfrage mit `exchCode` (Xetra `GY`), sonst bis zu 300 Listings je Aktie. |
| Anlageklasse, Emittent | ESMA FIRDS je ISIN: CFI-Code (E Aktie, D Schuldtitel, C Fonds) und LEI | OpenFIGI `securityType2` (Govt, Corp, Common Stock, Mutual Fund) | Live geprüft für Anleihen, Aktie und ETF |
| Aktien, Fundamentaldaten | yfinance wie heute | – | Ausländische Aktien: Fundamentaldaten vom Heimat-Listing, Kurs von Xetra, falls vorhanden. London notiert in Pence (`GBp`), Regel „/100“. |
| ETF: TER, Sektoren, Anlageklassen | yfinance `funds_data` | Anbieterdateien | Live: TER plausibel (EUNL 0,20 %, EUNH 0,09 %). Länder gibt es dort nicht, das Fondsvolumen ist unzuverlässig, Renten-Kennzahlen unplausibel. |
| ETF: Bestände, Länder, Volumen, Renten-Kennzahlen | Anbieterdateien: iShares (JSON-API, schon im Einsatz), Deka (XLSX) | yfinance, nur die 10 größten Aktien-Positionen | Xtrackers sperrt die Dateien per robots.txt; Swap-ETFs: Index statt Ersatzkorb. Ohne Anbieterdatei keine Länder-Durchschau. |
| Anleihen, Stammdaten | ESMA FIRDS je ISIN: Kupon, Fälligkeit, Stückelung, Rang, Zinsart (CFI) | Bankabruf, Hand | Live geprüft. Die Suche des Registers ist nicht als API dokumentiert, Rückfallweg sind die FIRDS-Dateien. Kupontermine und Zinsmethode fehlen dort. |
| Bundesanleihen, Kurse | Bundesbank, tägliche Kurs- und Renditeliste (XLSX) | Hand | dazu die Zinskurve per SDMX für den Abstand zur Bundkurve |
| andere Anleihen, Kurse | Bankabruf | Hand | keine freie Kursquelle; Yahoo kennt keine Anleihen (live geprüft) |
| Währungen | wie heute yfinance (`EURUSD=X`) | EZB-Referenzkurse | |

## Suche und Auflösung

```
UI ─ GET /api/v1/securities/search?q=DE0007164600 ─► web-api ─ rpc.va.marketdata.securities.search ─► market-data
market-data: eigene Wertpapiere → OpenFIGI (ISIN/WKN → Listings) → yfinance-Suche (Name, Symbol)
          ◄─ Treffer: ISIN, Name, Anlageklasse, Listings (Symbol, Börse, Währung)
```

- OpenFIGI wird heute schon für Neuaufnahmen im Universum genutzt (ohne Schlüssel, 10 ISINs je
  Anfrage, Adapter `openfigi.py`).
- **WKN:** OpenFIGI liefert zur WKN keine ISIN. Deutsche ISINs enthalten die WKN
  (`DE000` + WKN + Prüfziffer), daraus rechnet market-data die ISIN aus. Für ausländische
  Papiere mit WKN findet die Suche so nichts; dann hilft die ISIN oder der Name.
- **Treffer der Yahoo-Suche** haben keine ISIN (Yahoo nennt keine). Sie zeigen Name,
  Anlageklasse und Symbol; übernommen wird ein Wertpapier über seine ISIN.
- Die Suche schreibt nichts. Gespeichert wird ein Wertpapier erst, wenn es in die Abdeckung kommt.
- Ergebnisse werden 24 h im Speicher gehalten, damit Tippen im Suchfeld keine Rate-Limits trifft.
  Das UI sucht erst ab drei Zeichen und wartet 300 ms nach der letzten Taste.

## Abdeckung und Abrufe

| Abruf | Wann | Was | Event |
|---|---|---|---|
| Wochenlauf (heute) | Samstag, Scheduler | Referenzuniversum wie bisher, dazu Fundamentaldaten aller Aktien der Abdeckung | `marketdata.snapshot.completed` mit neuem optionalen Feld `covered[]` |
| Neue Abdeckung (WP-13) | sofort nach `coverage.changed` | Stammdaten, letzter Kurs, Fundamentaldaten der neuen Aktien | `marketdata.securities.updated`, `marketdata.coverage.fetched` |
| Stammdaten | bei neuer Abdeckung sofort, sonst im Wochenlauf | Stammdaten, ETF-Struktur und -Bestände | `marketdata.securities.updated` |
| Tageskurse | Handelstage, 22:30 `Europe/Berlin` (nach Xetra-Schluss), Scheduler | Schlusskurse und Währungskurse für die Abdeckung | `marketdata.prices.completed` |
| News | siehe [news.md](news.md) | | `marketdata.news.collected` |

- **Abdeckung pflegen:** portfolio schickt bei jeder Änderung die vollständige Menge
  (`portfolio.coverage.changed`: ISIN, Anlageklasse, Listing für Fundamentaldaten, Listing für
  Kurse). market-data speichert sie als neue Version. Was nicht mehr gehalten wird, wird nicht mehr
  abgerufen. Seine Historie bleibt.
- **Kein Einfluss auf das Ranking:** Die Aktien der Abdeckung stehen in `covered[]`, nicht in
  `fundamentals[]`. scoring rankt wie bisher nur `fundamentals[]` und ordnet `covered[]` ein
  ([analyse.md](analyse.md#aktien-einordnung)). Die Report-CSV bleibt gleich.
- **Getrennt gespeichert:** Die Snapshots der Abdeckung liegen im selben Abruf, aber mit
  `role = 'coverage'` (neue Spalte in `fundamental_snapshot`, Standard `'universe'`). Alle
  bestehenden Lesewege (`get_snapshots_df`, Backfill der Projektionen, `scoring.input_snapshot`,
  Vorschau, Rescore, Replay-Regression) lesen nur `universe`, sonst stünden Depot-Titel im Ranking.
  `scoring.input_snapshot` hält die Kandidaten getrennt, damit auch der Rescore sie einordnet.
- **ISIN im Event:** Für die Aktien aus `covered[]` füllt market-data die vorhandenen Maps
  `isins` und `instrument_ids` von `SnapshotCompletedV1`. `FundamentalsV1` hat keine ISIN.
- **Größe der Events:** `snapshot.completed` hat heute rund 80–100 KB für 90 Titel. Mit 200
  zusätzlichen Aktien sind es rund 300 KB, unter der Grenze von 1 MB. Bei mehr als 500 Titeln
  in der Abdeckung muss das neu bewertet werden.
- **Laufzeit:** Der Wochenlauf dauert je Titel einige Sekunden. Die Watchdog-Grenze für den Abruf
  (45 min) muss mit der Abdeckung wachsen oder einstellbar bleiben. Das Paket D2 misst das.
- **Tageskurse** kommen über einen Sammelabruf (`yf.download` mit mehreren Symbolen), nicht je
  Titel, dazu Bundesanleihen aus der Liste der Bundesbank. Sie landen in eigenen Tabellen
  (`price_run`, `daily_close`, `fx_daily`), nach ISIN, auch ohne Yahoo-Symbol. `price_bar` und
  `fx_rate` passen nicht: Beide hängen an einem `fetch_run` des Wochenlaufs. `price_bar` bleibt
  die wöchentlich gepflegte Kurshistorie aus F1.4, die Tageskurse ergänzen sie nur für die
  Bewertung der Depots.

## Datenmodell (Schema `market_data`, additiv)

| Tabelle | Inhalt | Schreibweise |
|---|---|---|
| `security` | isin, asset_class, first_seen_at | anfügen, ISIN eindeutig |
| `security_master` | isin, source, payload (JSONB: Stammdaten je Anlageklasse), fetched_at | anfügen, neue Zeile nur bei geändertem Inhalt |
| `etf_composition` | isin, source, as_of, complete (bool), holdings (JSONB), weights (JSONB: Sektor, Land, Anlageklasse), fetched_at | anfügen |
| `coverage_version` | version, created_at, source_event_id | anfügen |
| `coverage_item` | version, isin, asset_class, fundamentals_symbol, price_symbol | anfügen |
| `listing` | isin, symbol (eindeutig), exchange, currency, first_seen_at | anfügen; weitere Listings neben `instrument` |
| `price_run` | id, source (`yahoo`, `bundesbank`), started_at, finished_at, status | anfügen, Abschluss wie `fetch_run` |
| `daily_close` | isin, symbol (kann fehlen), source, trade_date, close, currency, price_run_id, first_seen_at | anfügen, eindeutig (isin, source, trade_date) |
| `fx_daily` | currency, trade_date, rate_to_eur, source, price_run_id | anfügen |
| `instrument` | bestehend: das Listing für die Fundamentaldaten. Verknüpfung zum Wertpapier über die vorhandene, eindeutige Spalte `isin`. | wie bisher |
| `fundamental_snapshot` | bestehend, neue Spalte `role` (`universe`/`coverage`, Standard `universe`) | wie bisher |

`price_run` und `fetch_run` sind getrennte Abrufläufe. Den Abschluss von `price_run` braucht die
Liste der einmaligen UPDATEs in `va_platform.db.ddl` (`UPDATABLE_TABLES`) wie bei `fetch_run`.

## Contracts (additiv)

| Contract | Änderung |
|---|---|
| `SnapshotCompletedV1` | neues optionales Feld `covered: list[FundamentalsV1] = []`; die Maps `isins` und `instrument_ids` decken auch sie ab |
| `ScoringRunCompletedV1` | neues optionales Feld `placements: list[PlacementV1] = []` |
| `PlacementV1` (neu) | symbol, isin, instrument_id, value_score, quality_score, composite, composite_percentile, factor_ranks, value_trap, below_size_filter, reason (leer oder `no_quality`/`no_value`/`no_data`) |
| `CoverageFetchedV1` (neu) | Fundamentaldaten der neu abgedeckten Aktien (WP-13), mit ISIN |
| `PlacementsUpdatedV1` (neu) | scoring_run_id, gegen den eingeordnet wurde, und `placements[]` |
| `SecurityV1` (neu) | isin, asset_class, name, currency, country, listing, Stammdaten je Klasse als Untermodell |
| `SecuritiesUpdatedV1` (neu) | Liste von `SecurityV1` mit Stand |
| `PricesCompletedV1` (neu) | trade_date, Kurse (isin, close, currency), FX-Kurse |
| `CoverageChangedV1` (neu) | version, items (isin, asset_class, fundamentals_symbol, price_symbol). Ein Test prüft, dass es keine Nutzer- oder Mengenfelder gibt. |

`IdentityV1.index` ist heute Pflicht. Für Aktien der Abdeckung steht dort `"-"`, damit das
Contract additiv bleibt. Die Golden-Schemas unter `tests/golden/contracts/v1/` ändern sich mit
Begründung im Review.

## Tests und Abnahme

- Suche: ISIN, WKN, Name, unbekannte ISIN, OpenFIGI nicht erreichbar (dann nur eigene Treffer).
- Auflösung: Xetra bevorzugt, Heimatbörse als Ersatz, vom Nutzer gewähltes Listing.
- Abdeckung: eine neue ISIN führt zu Stammdatenabruf, eine entfallene wird nicht mehr abgerufen.
- Wochenlauf mit `covered[]`: Ranking, CSV und Mail sind byte-gleich zum Lauf ohne Abdeckung
  (Golden-Master, Replay-Fixtures). Backfill der Projektionen, Vorschau und Rescore sehen keine
  Snapshots mit `role = 'coverage'`.
- Neue Abdeckung: Eine neue Aktie hat nach wenigen Minuten Stammdaten, Kurs und Einordnung.
- Mehrere Listings: US-Aktie mit Fundamentaldaten von `AAPL` und Kurs von `APC.DE`.
- Tageskurse: Feiertag ohne neue Kurse, Titel ohne Kurs, Fremdwährung.
- Adapter von yfinance werden wie heute nicht gemockt, die Rechenteile liegen in `domain/`.
