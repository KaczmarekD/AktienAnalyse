# ADR-0013: Depots im neuen Service `portfolio`, bewertet gegen ein Referenzuniversum

- **Status:** akzeptiert (06.11.2026)
- **Datum:** 2026-11-04
- **Ergänzt:** [ADR-0001](0001-microservices-ueber-modularen-monolithen.md) um einen vierten
  Fach-Service

## Kontext

Nutzer sollen Depots mit beliebigen Aktien, ETFs und Anleihen anlegen. Die bisherigen Analysen
(Value, Quality, Value-Trap-Flag, Score-Verlauf) sollen auf diese Depots laufen. Dazu kommen
Analysen auf Depotebene und Hinweise ([Depot-Spezifikation](../architecture/depot/README.md)).

Zwei Fragen sind grundsätzlich:

1. **Wo leben Depots?** Die drei Fach-Services haben klare Aufgaben (externe Daten, Rechnen,
   Ausgabe). Das web-api ist ein Backend for Frontend ohne eigene Fachlogik.
2. **Wogegen wird bewertet?** Das Scoring vergibt Perzentilränge innerhalb eines Universums. Ein
   Depot mit zehn Titeln ist als Vergleichsgruppe zu klein. Der beste von zehn mittelmäßigen
   Titeln bekäme 1,0.

## Entscheidung

- **Neuer Fach-Service `portfolio`** mit Schema `portfolio` und Rolle `va_portfolio`. Er besitzt
  Depots, Depotstände, Zielallokation, die Depot-Analyse, die Hinweise und die Zusammenstellung
  der Depotberichte. Er spricht keine externe Quelle an.
- **Depotstände sind vollständige, unveränderliche Versionen.** Jede Änderung und jeder Bankabruf
  ergibt einen neuen Stand. Das passt zum Löschverbot aus
  [ADR-0003](0003-postgresql-schema-pro-service.md) und macht den Verlauf ohne Rechnen lesbar.
- **DAX/MDAX bleibt das Referenzuniversum.** Aktien eines Depots werden eingeordnet: Sie bekommen
  den Perzentilrang, den sie hätten, wenn man sie allein dem Referenzuniversum hinzufügte. Die
  Ränge der Referenztitel ändern sich nicht. Die Einordnung ist eine reine Funktion `place()` in
  `va_scoring.domain` und läuft im selben Bewertungslauf.
- **market-data bleibt der einzige Service für Marktdaten.** Er kennt Wertpapiere über die ISIN,
  mit Anlageklasse (Aktie, ETF, Anleihe). Die abzurufenden Wertpapiere meldet portfolio als
  Menge ohne Nutzerbezug (`portfolio.coverage.changed`).
- **Ranking und Marktbericht bleiben unverändert.** Zusatzdaten reisen in neuen, optionalen
  Feldern (`covered[]`, `placements[]`), die Contracts ändern sich nur additiv. Die Snapshots der
  Depot-Aktien tragen `role = 'coverage'`, damit Projektionen, Vorschau, Rescore und
  Replay-Regression sie nicht ins Ranking ziehen.
- **Der Marktbericht behält seine Events.** Depotberichte bekommen eigene (`digest.*`), damit
  Run-Verwaltung und `RunTracker` unberührt bleiben.
- **Persönliche Daten bleiben in `portfolio`.** Das web-api liest Depots per Request/Reply, nicht
  aus Projektionen im Schema `web`. Events in `VA_EVENTS` (30 Tage) tragen keine Mengen, Beträge
  oder Mail-Adressen. Wo das nötig ist (Bankbestand, Berichtsdaten), laufen sie mit dem Präfix
  `priv.va.` über einen eigenen Stream `VA_PRIVATE` mit 24 h Aufbewahrung.

Details: [depots.md](../architecture/depot/depots.md), [analyse.md](../architecture/depot/analyse.md),
[wertpapiere.md](../architecture/depot/wertpapiere.md).

## Konsequenzen

- ✅ Ein Score im Depot ist mit dem Ranking vergleichbar (bis auf n zu n+1 Vergleichswerte).
- ✅ Golden-Master, Replay-Fixtures und Samstags-Mail bleiben gültig.
- ✅ portfolio ist ohne Netz testbar: Analyse und Hinweise sind reine Funktionen.
- ⚠️ Ein Container und eine DB-Rolle mehr. Im Worker-Prozess (`python -m src.worker`) darf
  portfolio nur mit eigener Engine und Rolle `va_portfolio` laufen, nicht mit `va_app`.
- ⚠️ Für Titel außerhalb von Deutschland ist DAX/MDAX ein schiefer Vergleich (andere
  Bewertungsniveaus, Rechnungslegung). Hinweis HIN-Q06 sagt das. Weitere Referenzuniversen
  sind möglich, aber noch nicht entschieden.
- ⚠️ ETFs und Anleihen bekommen keinen Score im Sinne des Rankings. ETFs werden über die
  Durchschau auf ihre Bestände beurteilt, Anleihen über Rendite, Laufzeit und Emittent.
- ⚠️ Der Wochenlauf ruft mehr Titel ab. Bei deutlich über 200 Aktien muss die Laufzeit gemessen
  werden.

## Verworfene Alternativen

- **Depots im web-api:** Fachlogik im BFF, und die persönlichen Daten lägen bei den Projektionen.
- **Depots in scoring:** vermischt reines Rechnen mit Nutzerdaten und Berichten.
- **Ranking innerhalb des Depots:** statistisch wertlos bei wenigen Titeln, siehe Kontext.
- **Depot-Titel ins Ranking aufnehmen:** verschiebt die Ränge aller DAX/MDAX-Titel je nach Inhalt
  fremder Depots und ändert die Samstags-Mail.
- **Positionen als Änderungsbuchungen statt ganzer Stände:** spart Zeilen, verlangt aber für
  jede Ansicht ein Nachrechnen. Bei Depots mit unter 200 Positionen lohnt das nicht.
