# ADR-0003: PostgreSQL mit einem Schema pro Fachbereich, nichts wird gelöscht

- **Status:** akzeptiert
- **Datum:** 2026-09-30

## Kontext

Bisher gab es nur einen Parquet-Tagescache und Ranking-CSVs, die das Housekeeping nach 90 Tagen
löschte. Gewünscht sind Langzeit-Auswertungen. yfinance liefert nur etwa 4 Geschäftsjahre und
nachträglich korrigierte Zahlen (verifiziert am 29.09.2026). Stichtagsdaten sind deshalb nur
verfügbar, wenn sie zum Abrufzeitpunkt gespeichert werden.

Die Postgres-Persistenz wird seit dem 30.09.2026 auf `feat/postgres-persistence` umgesetzt. Dieses
ADR hält die Grundsätze fest und beschreibt, wie sie in die Zielarchitektur passen.

## Entscheidung

- **PostgreSQL 18** in einem Container, ein Schema pro Fachbereich: `batch`, `market_data`,
  `scoring`, `reporting`. In der Zielarchitektur gehört jedes Schema genau einem Service. Neu kommt
  `web` für die Read-Models des web-api dazu.
- **Nichts wird gelöscht oder überschrieben.** Trigger verbieten `DELETE` und `TRUNCATE`. `UPDATE`
  ist nur für ausdrücklich freigegebene Tabellen erlaubt. Die App-Rolle hat kein `DELETE`-Recht.
- **Rohdaten werden mitgespeichert** (`raw_info`, `statement_value` mit `first_seen_at`).
- **Rollen:** `va_owner` für Migrationen, `va_app` für den Batch, `va_read` für lesende Zugriffe.
  In der Zielarchitektur bekommt jeder Service eine eigene Rolle, die nur auf sein Schema
  zugreift.
- SQLAlchemy mit psycopg 3 und Alembic. Datenbank-Modelle und Pydantic-DTOs bleiben getrennt.
- Neue veränderliche Tabellen (Outbox, Projektionen) sind bewusst gekennzeichnete Ausnahmen.
  Aktivierungen und ähnliche Zustände werden als Anfüge-Log modelliert.

Details: [datenhaltung.md](../architecture/datenhaltung.md).

## Konsequenzen

- ✅ Vollständige Historie, reproduzierbare Rankings, Kennzahlen lassen sich aus Rohdaten neu
  berechnen.
- ✅ Die Schema-Grenzen entsprechen schon heute den späteren Service-Grenzen.
- ⚠️ Datenbankbetrieb gehört jetzt dazu: Backup, Migrationen, Upgrade auf PG 19.
- ⚠️ Der Schreibschutz verlangt Disziplin. Jede neue Tabelle braucht ihn, oder eine begründete
  Ausnahme.
- Das Volume liegt auf `/var/lib/postgresql`. Ab PG 18 ist das nicht mehr `…/data`.

## Verworfene Alternativen

- **Eine Datenbank pro Service:** mehr Container und Betriebsaufwand, ohne Nutzen bei einem Nutzer.
- **Ein gemeinsames Schema:** Die Grenzen verschwimmen, und das spätere Aufteilen wird teuer.
- **Historie als Dateien (Parquet, append-only):** keine Abfragen über Zeiträume, keine
  Transaktionen, kein Schutz vor versehentlichem Löschen.
- **SQLModel:** vermischt Datenbank-Modelle und API-Modelle, was dem Ports-&-Adapters-Ansatz
  widerspricht.
