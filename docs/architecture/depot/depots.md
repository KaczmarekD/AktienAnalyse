# Depots und Positionen

> **Status:** Spezifikation, Entwurf vom 04.11.2026. Teil der
> [Depot-Spezifikation](README.md), Stufe D3. Grundsatzentscheidung:
> [ADR-0013](../../adr/0013-depots-im-service-portfolio.md) (vorgeschlagen).

## Begriffe

| Begriff | Bedeutung |
|---|---|
| **Depot** | Sammlung von Positionen eines Nutzers, z. B. „DKB-Depot“ oder „Altersvorsorge“. Basiswährung EUR. |
| **Position** | Ein Wertpapier im Depot mit Menge, optional mit Einstand. |
| **Depotstand** | Der vollständige Bestand eines Depots zu einem Zeitpunkt. Jede Änderung und jeder Abruf von der Bank erzeugt einen neuen Depotstand. |
| **Herkunft** | Woher ein Depotstand kommt: `manual` (im UI erfasst), `import` (Datei), `bank` (Abruf über die [Bankanbindung](bankanbindung.md)). |
| **Beobachtungsliste** | Ein Depot ohne Mengen. Es bekommt Analyse und News, aber keine Gewichte und keine Allokation. |
| **Kasse** | Guthaben auf dem Verrechnungskonto. Es zählt zum Depotwert. |

## Anforderungen

| ID | Prio | Anforderung |
|---|---|---|
| DEP-01 | Muss | Ein Nutzer legt beliebig viele Depots an: Name, optional Beschreibung, Art (`depot` oder `watchlist`). |
| DEP-02 | Muss | Position erfassen: Wertpapier über die [Suche](wertpapiere.md#suche-und-auflösung) (Aktie, ETF, Anleihe), Menge, optional Einstandswert und Kaufdatum. Bruchstücke sind erlaubt (Sparpläne). Bei Anleihen ist die Menge der Nennwert. Ein Wertpapier ohne Stammdaten wird angenommen und als „wird geprüft“ gezeigt, bis market-data es geliefert hat (WP-13). |
| DEP-03 | Muss | Jede Änderung erzeugt einen neuen Depotstand. Der Verlauf ist im UI sichtbar. Zwei gleichzeitige Änderungen erkennt `If-Match` auf die Version des Depotstands (409 wie bei den Profilen). |
| DEP-04 | Muss | Kasse als eigene Zeile mit Betrag in EUR. |
| DEP-05 | Muss | Import einer Datei im eigenen CSV-Format. Fremde Formate kommen über die Adapter der [Bankanbindung](bankanbindung.md). Vor dem Übernehmen zeigt das UI den Abgleich: neu, geändert, entfällt, nicht erkannt. |
| DEP-06 | Muss | Depot archivieren und wiederherstellen. Gelöscht wird nichts. |
| DEP-07 | Muss | Depotwert: Menge mal letzter Schlusskurs, umgerechnet in EUR. Jede Position zeigt ihr Kursdatum und ihre Quelle. Fehlt ein Kurs, fehlt der Wert sichtbar (kein stilles 0). |
| DEP-08 | Muss (ab D8) | Ein Depot mit Bankverbindung bekommt seinen Bestand nur von der Bank. Manuelle Änderungen sind dort gesperrt, das UI zeigt „Stand Bank: <Datum>“. |
| DEP-09 | Soll | Beobachtungsliste (`watchlist`): Wertpapiere ohne Menge, mit Analyse und News. |
| DEP-10 | Soll | Zielallokation je Depot: Anteile je Anlageklasse, optional je Region. Abweichungen werden zu [Hinweisen](analyse.md#hinweise). |
| DEP-11 | Soll | Eine Position bekommt eine Notiz (z. B. „Kaufgrund“). |
| DEP-12 | Kann | Transaktionen (Kauf, Verkauf, Dividende) statt nur Bestände. Das führt zur Renditeberechnung und ist deshalb offen ([README](README.md#offene-fragen)). |
| DEP-13 | Muss | Einstand und Differenz zum aktuellen Wert, je Position und für das Depot, wenn der Einstand erfasst oder von der Bank geliefert ist. Nur Anzeige: keine Rendite pro Jahr, kein Benchmark, keine Wertentwicklung über die Zeit (Frage 6, entschieden am 06.11.2026). |

## Erfassungswege

| Weg | Stufe | Ablauf |
|---|---|---|
| Manuell | D3 | Suche, Menge eingeben, speichern. Jede Speicherung ist ein Depotstand. |
| Datei, eigenes Format | D3 | CSV mit `isin;menge;einstand;notiz`, Trennzeichen `;`, Dezimalkomma (wie die Report-CSV). Abgleich, dann übernehmen. Dasselbe Format liefert der CSV-Export der Positionen. Der Export aller Daten (NUT-12) ist JSON. |
| Datei, fremdes Format | D8 | Ein Datei-Adapter der [Bankanbindung](bankanbindung.md) liest das Format, z. B. den CSV-Export von Portfolio Performance. Sonst wie oben. Die DKB bietet keinen Export des Bestands als Datei ([Recherche](../../research/2026-11-depot-datenquellen-und-bankzugang.md#dkb-zugangswege)). |
| Bank, live | D9 | Abruf über die [Bankanbindung](bankanbindung.md). Jeder Abruf ist ein Depotstand mit Herkunft `bank`. |

Das eigene Format gehört zu portfolio, wie der Export. Fremde Formate und Banken liegen hinter dem
Port der Bankanbindung im Dienst `depot-gateway`.

Datei-Uploads gehen als JSON (`{"filename", "content_base64"}`, höchstens 1 MB), nicht als
`multipart/form-data`. So bleibt die Regel „schreibende Endpunkte nur mit JSON“ bestehen.

## Ablauf: Position ändern

```
UI ─ PUT /api/v1/depots/{id}/holdings (If-Match: 7) ─► web-api
web-api ─ rpc.va.portfolio.holdings.save {user_id, depot_id, base_version: 7, lines} ─► portfolio
portfolio: Besitz prüfen, Version prüfen, Wertpapiere prüfen, Depotstand 8 anlegen,
           Events in die Outbox, Antwort {version: 8}
portfolio ─ va.portfolio.depot.changed ──────► web-api ─WS depot:<id>─► Browser (alle Tabs)
portfolio ─ va.portfolio.coverage.changed ───► market-data (nur wenn sich die Menge aller gehaltenen Wertpapiere ändert)
portfolio: Analyse neu rechnen ─ va.portfolio.analysis.completed ─► web-api ─WS─► Browser
```

Das web-api prüft den Besitz, portfolio prüft ihn noch einmal (Verteidigung in der Tiefe).
`coverage.changed` enthält nur die Menge der Wertpapiere aller Depots, keine Nutzer und keine
Mengen. market-data erfährt also nicht, wer was hält.

## Datenmodell

Neues Schema `portfolio`, Besitzer ist der neue Service `portfolio`, Rolle `va_portfolio`. Alles
wird nur angefügt.

| Tabelle | Inhalt | Schreibweise |
|---|---|---|
| `depot` | id, owner_user_id, kind (`depot`/`watchlist`), created_at | anfügen |
| `depot_version` | depot_id, name, description, created_at | anfügen, gültig ist die jüngste Zeile |
| `depot_status` | depot_id, status (`active`/`archived`), at | anfügen, gültig ist die jüngste Zeile |
| `holding_snapshot` | id, depot_id, version (fortlaufend je Depot), source (`manual`/`import`/`bank`), source_ref (Datei-Hash oder Sync-ID), as_of (Stand laut Herkunft, z. B. der Bank), created_by, created_at | anfügen, eindeutig (depot_id, version) |
| `holding_line` | snapshot_id, isin, quantity (numeric), unit (`pieces`/`nominal`), cost_basis_eur, bank_price, bank_price_currency, bank_price_date, note | anfügen |
| `cash_line` | snapshot_id, currency, amount | anfügen |
| `target_allocation` | depot_id, version, params (JSONB), created_at | anfügen, gültig ist die jüngste Zeile |
| `security_view` | isin, payload (JSONB), received_at | lokale Kopie der Stammdaten aus market-data, anfügen |
| `price_view` | isin, trade_date, close, currency, received_at | lokale Kopie der Kurse, anfügen |
| `score_view` | scoring_run_id, isin, payload (JSONB) | lokale Kopie der Scores und Einordnungen (`PlacementV1`) aus scoring, anfügen |
| `depot_link` | depot_id, connection_id, account_id (aus `bank.account`), at, active | anfügen, gültig ist die jüngste Zeile je Depot (ab D8) || `outbox`, `inbox` | wie in den anderen Schemas | wie dort |

Der aktuelle Bestand ist der Depotstand mit der höchsten Version. Ein Depotstand kopiert alle
Zeilen, auch die unveränderten. Bei Depots mit unter 200 Positionen ist das billig. Dafür ist
jeder Stand ohne Rechnen vollständig lesbar.

Mengen und Beträge sind `numeric` in Postgres und `Decimal` in Python, nie `float`. In den
Contracts stehen sie als Zahl im String, wie Pydantic `Decimal` im JSON-Modus schreibt.

Die `*_view`-Tabellen sind die lokalen Kopien aus Events, wie `scoring.input_snapshot`. Kein
Service liest die Tabellen eines anderen.

## API

Alle Endpunkte verlangen eine Sitzung. Fremde Depots ergeben 404.

| Methode und Pfad | Zweck |
|---|---|
| `GET /api/v1/depots` | eigene Depots mit Wert, Stand und Zahl der Hinweise |
| `POST /api/v1/depots` | Depot anlegen |
| `GET /api/v1/depots/{id}` | Depot mit aktuellem Depotstand, bewertet |
| `PUT /api/v1/depots/{id}` | Name und Beschreibung ändern |
| `POST /api/v1/depots/{id}/archive`, `…/restore` | archivieren, wiederherstellen |
| `GET /api/v1/depots/{id}/holdings?version=` | Depotstand, ohne `version` der aktuelle |
| `PUT /api/v1/depots/{id}/holdings` | neuer Depotstand, `If-Match` mit der Basisversion |
| `GET /api/v1/depots/{id}/history` | Liste der Depotstände mit Herkunft und Änderungen |
| `POST /api/v1/depots/{id}/import/preview` | Datei prüfen, Abgleich zurückgeben, nichts speichern |
| `POST /api/v1/depots/{id}/import` | Abgleich übernehmen (mit `If-Match`) |
| `GET`/`PUT /api/v1/depots/{id}/target-allocation` | Zielallokation |

Das web-api liest Depots per Request/Reply bei portfolio (`rpc.va.portfolio.*`), nicht aus
Projektionen im Schema `web`. So liegen persönliche Daten nur in einem Schema.

## Oberfläche

- **Meine Depots** ist die Startseite nach dem Login: Kacheln mit Name, Wert, Stand,
  Zahl der Hinweise nach Schwere.
- **Depot-Detail** mit Reitern:
  - Übersicht: Wert, Allokation (Anlageklasse, Sektor, Land, Währung), wichtigste Hinweise
  - Positionen: Tabelle mit Menge, Kurs, Wert, Gewicht, Scores, Flags; Bearbeiten-Modus
  - Analyse: siehe [analyse.md](analyse.md)
  - Hinweise
  - News: siehe [news.md](news.md)
  - Verlauf: Depotstände mit Herkunft und Unterschied zum vorherigen
  - Einstellungen: Zielallokation, Schwellen der Hinweise, Bankverbindung, Berichte

Die Bausteine kommen aus dem Designsystem des Frontends, Farben aus `--mat-sys-*`.

## Tests und Abnahme

- Domain: Depotstand anlegen, Abgleich bei Import (neu, geändert, entfällt, unbekannte ISIN),
  Depotwert mit fehlendem Kurs und mit Fremdwährung, Anleihe mit Nennwert und Kurs in Prozent.
- Konflikt: zwei Speicherungen auf dieselbe Basisversion, die zweite ergibt 409.
- Löschschutz: alle neuen Tabellen in `tests/db/test_protection.py`.
- Datentrennung: jeder Endpunkt mit fremdem Depot ergibt 404 (siehe
  [nutzer.md](nutzer.md#tests-und-abnahme)).
- `coverage.changed` enthält keine Nutzer-IDs und keine Mengen (Contract-Test).
