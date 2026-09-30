# ADR-0010: Zusätzliche Stichtagsdaten sichern: Konsens, Quartale, Aktienanzahl, Kurse

- **Status:** akzeptiert
- **Datum:** 2026-09-30
- **Grundlage:** [Recherche: Langfristige Fundamentalanalyse](../research/fundamentalanalyse-sota/bericht.md)
- **Ergänzt:** [ADR-0003](0003-postgresql-schema-pro-service.md). Die neuen Tabellen folgen denselben
  Regeln: Es wird nichts gelöscht und nichts überschrieben.

## Kontext

- Die Recherche empfiehlt Langfrist-Analysen mit fundamentalen Ankern und Änderungen am Scoring.
  Diese Auswertungen brauchen Daten, die das Projekt heute nicht speichert:
  - Konsensschätzungen und ihre Revisionen
  - Quartalsabschlüsse, etwa für Gewinnüberraschungen und TTM-Kennzahlen
  - die Historie der Aktienanzahl für Netto-Emission, Rückkäufe und Splits
  - Tageskurse für Momentum, Wertlinie und Renditezerlegung
- yfinance liefert das alles (Live-Test vom 30.09.2026):
  - Konsensdaten bei 8 von 8 getesteten DAX/MDAX-Titeln
  - 5 bis 7 Quartale
  - die Aktienanzahl meist ab 2015
  - Kurse ab 1996 bis 2000
- Konsensschätzungen sind Momentaufnahmen, und yfinance zeigt nur die letzten Quartale. **Beides lässt
  sich später nicht nachholen.** Kurse und Aktienanzahl gibt es zwar rückwirkend, aber nur im jeweils
  aktuellen, nachträglich angepassten Stand. Ein alter Lauf wäre damit nicht reproduzierbar.
- Ob und wie das Scoring diese Daten nutzt, ist eine eigene Entscheidung
  ([ADR-0011](0011-fundamentale-anker-und-belegte-faktoren.md), vorgeschlagen). Die Rohdaten werden
  gespeichert, also lässt sich jede spätere Methodik rückwirkend auf alle gespeicherten Abrufe
  anwenden (Rescore). Die Datensammlung darf der Methodik-Entscheidung deshalb vorausgehen.
  Umgekehrt geht das nicht.

## Entscheidung

- **`market-data` speichert bei jedem Abruf zusätzlich:**
  1. **Konsens-Snapshots** unverändert als JSONB in `market_data.consensus_snapshot`:
     `eps_trend`, `eps_revisions`, `earnings_estimate`, `revenue_estimate`, `growth_estimates` und
     `analyst_price_targets`.
  2. **Quartalsabschlüsse** in `statement_value` mit `frequency = 'quarterly'`.
  3. **Aktienanzahl** als Historie in `market_data.share_count`.
  4. **Tageskurse** mit Dividenden und Splits in `market_data.price_bar`. Beim ersten Abruf wird die
     ganze verfügbare Historie gespeichert.
- **Versionierung** wie bei `statement_value`: Eine neue Zeile entsteht nur bei neuem Datum oder
  geändertem Wert. Jede neue Tabelle bekommt `protect_table()`.
- **Nur speichern, nicht auswerten.** Ranking, Mail und CSV bleiben unverändert. Abgeleitete
  Kennzahlen und Signale entstehen erst mit ADR-0011 oder späteren Entscheidungen.
- **Fehlertoleranz:** Scheitert eine Zusatzquelle, bleibt der Titel im Lauf, und der Fehler landet in
  `errors`. „Lieber einen Ticker verlieren als den ganzen Batch“ gilt hier erst recht: Wegen
  Zusatzdaten geht kein Titel verloren.

**Umsetzung:** die Pakete F1.1 bis F1.4 im
[Implementierungsplan](../architecture/implementierungsplan.md). Sie sind vorgezogen wie Phase 2 und
können parallel zu Phase 0 laufen.

## Konsequenzen

- ✅ Ab F1 geht keine Woche Konsens- und Quartalsdaten mehr verloren. Spätere Analysen wie
  Revisionen, Gewinnüberraschungen, Momentum und Anker stützen sich auf echte Stichtagsdaten.
- ✅ Die Samstags-Mail ändert sich nicht, der Golden-Master bleibt gültig.
- ✅ Methodik-Entscheidungen können ohne Zeitdruck fallen, weil gespeicherte Abrufe jederzeit neu
  bewertet werden können.
- ⚠️ Je Titel kommen rund 8 bis 10 Yahoo-Abrufe hinzu. Der Lauf dauert länger, und Rate-Limits
  werden wahrscheinlicher. Retry und Fehlertoleranz gelten wie bisher.
- ⚠️ Die Erstbefüllung der Kurse umfasst rund 0,7 Mio. Zeilen, danach kommen wenige MB pro Woche
  hinzu.
- ⚠️ Mit P1.4 wandern die Abrufe in den Yahoo-Adapter und die Parser nach `domain`. Ab Phase 5
  gehören die Tabellen dem Service `market-data`.

## Verworfene Alternativen

- **Erst sammeln, wenn die Methodik feststeht:** Konsens und Quartale aus der Zwischenzeit wären
  verloren.
- **Nur abgeleitete Kennzahlen speichern:** Spätere Formeln ließen sich nicht auf die Rohdaten
  anwenden. Das widerspricht dem Grundsatz „Rohdaten mitspeichern“ aus
  [datenhaltung.md](../architecture/datenhaltung.md).
- **Kurse nicht speichern, sondern bei Bedarf neu laden:** yfinance passt die Historie nachträglich
  an, etwa bei Splits und Dividenden. Ein Lauf wäre dann nicht reproduzierbar.
- **Sofort eine bezahlte Quelle wie EODHD:** kostet rund 600 € im Jahr. Für die wöchentlichen
  Snapshots reicht yfinance. Eine lange Abschlusshistorie wäre ein eigenes ADR.
