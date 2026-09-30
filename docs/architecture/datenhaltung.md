# Datenhaltung

> **Status:** Die Postgres-Persistenz ist seit `261dc8f` auf `main` umgesetzt (Phase 2).
> Maßgeblich für Tabellen und Spalten ist die Alembic-Migration
> `migrations/versions/0001_initial_schema.py`. Dieses Dokument beschreibt das Konzept und wie es
> in die Zielarchitektur wächst. Entscheidung:
> [ADR-0003](../adr/0003-postgresql-schema-pro-service.md).

## Grundsätze

- **Eine Postgres-Instanz, ein Schema pro Fachbereich.** Das hält den Betrieb einfach und die
  Grenzen trotzdem klar.
- **Nichts wird gelöscht oder überschrieben.** Trigger verbieten `DELETE` und `TRUNCATE` auf
  allen Tabellen der Fach-Schemas. `UPDATE` ist nur dort erlaubt, wo es fachlich nötig ist
  (Laufabschluss, ISIN-Nachtrag). Jede neue Tabelle braucht diesen Schutz, ein Test prüft das.
- **Stichtagsdaten sind unersetzlich.** yfinance liefert nur etwa 4 Geschäftsjahre und
  nachträglich korrigierte (restated) Zahlen. Was nicht zum Abrufzeitpunkt gespeichert wird,
  lässt sich später nicht rekonstruieren. Postgres ist damit die Historien-Schicht für
  Langzeit-Auswertungen.
- **Rohdaten mitspeichern.** `raw_info` und `statement_value` halten die Yahoo-Antworten. Ändert
  sich eine Formel, lassen sich die Kennzahlen neu berechnen, ohne Yahoo erneut abzufragen.

## Schemas und Tabellen (Phase 2)

Stand `261dc8f` (Migration `0001_initial_schema`):

| Schema | Tabellen | Zweck |
|---|---|---|
| `batch` | `run`, `run_log`, `import_file` | Läufe (Art `batch`/`rescore`/`import`, Status, Optionen, Zähler), Log-Zeilen je Lauf, SHA-256-Register gegen doppelten Altdaten-Import |
| `market_data` | `fetch_run`, `instrument`, `universe_member`, `fundamental_snapshot`, `raw_info`, `statement_value`, `fx_rate` | Abrufläufe mit Quelle, Stichtag der Indexquelle (`universe_as_of`) und Erfolgsquote; Titel mit Symbol und ISIN (die ISIN wird aus den Universum-Daten nachgetragen, nur leer → Wert); Indexzugehörigkeit; Kennzahlen je Abruf; Rohdaten; Statement-Werte im Long-Format mit `first_seen_at`, das macht Restatements sichtbar; Wechselkurse |
| `scoring` | `scoring_run`, `factor_score`, `score_result` | Bewertungsläufe (Herkunft `live`/`rescore`/`import`) mit Konfiguration und `config_hash`, Faktor-Ränge, Ergebnisse |
| `reporting` | `report`, `delivery` | gerenderte Mail (HTML + CSV), Zustellungen je Kanal (`mail`, `healthcheck`) |

**Rollen:**

| Rolle | Rechte | Verwendung |
|---|---|---|
| `va_owner` (`POSTGRES_USER`) | alles | nur für Migrationen beim Container-Start |
| `va_app` | `SELECT`/`INSERT`, `UPDATE` nur für freigegebene Tabellen, kein `DELETE` | der Batch |
| `va_read` | nur `SELECT` | Auswertungen aus dem LAN; in Phase 3 auch das web-api |

Der Treiber ist psycopg 3 (`postgresql+psycopg://`) mit synchronem SQLAlchemy. Das passt für den
Batch.

## Wie die Schemas in die Zielarchitektur wachsen

| Schema | Besitzer-Service (Phase 5) | Ergänzungen |
|---|---|---|
| `market_data` | `market-data` | `outbox`, `inbox` |
| `scoring` | `scoring` | Profil-Tabellen (unten), lokale Kopie des letzten Snapshots, `outbox`, `inbox` |
| `reporting` | `notification` | `outbox`, `inbox` |
| `batch` | `web-api` | Runs werden vom web-api angelegt (Scheduler/UI); `inbox` |
| `web` (neu) | `web-api` | Read-Models für das UI: aktuelles Ranking, Score-Verlauf je Titel |

Regeln für den Übergang:

- **Eine Rolle pro Service.** Aus `va_app` werden `va_market_data`, `va_scoring`,
  `va_notification` und `va_web_api`. Jede Rolle bekommt Rechte nur auf ihr eigenes Schema.
  Services tauschen Daten ausschließlich über Events und Request/Reply aus.
- **Keine Fremdschlüssel über Schema-Grenzen.** Verweise wie `batch.run.fetch_run_id` bleiben
  lose IDs.
- **Veränderliche Tabellen sind Ausnahmen und bewusst gekennzeichnet.** Die Outbox
  (`published_at`) und die Projektionen im Schema `web` (Read-Models, jederzeit aus Events neu
  aufbaubar) brauchen `UPDATE`. Historien-Tabellen bleiben reine Anfüge-Tabellen.
- **Anfügen statt Ändern, wo immer möglich.** Beispiel: Welches Scoring-Profil aktiv ist, steht
  nicht in einem Flag, sondern ergibt sich aus der jüngsten Zeile einer Aktivierungs-Tabelle.
- **Async erst mit Bedarf.** FastStream und FastAPI laufen asynchron. Ein Service, der beim
  synchronen SQLAlchemy bleibt, kapselt DB-Zugriffe per `asyncio.to_thread`. Die Umstellung auf
  die async-Engine (SQLAlchemy 2.1, `sqlalchemy[asyncio]`) geschieht pro Service, wenn es sich lohnt.

## Scoring-Profile (Phase 2b)

Details zum Konzept stehen in [scoring-profile.md](scoring-profile.md). Das Tabellen-Modell
passt zum Schreibschutz:

| Tabelle | Inhalt | Schreibweise |
|---|---|---|
| `scoring.profile` | id, name, created_at | anfügen |
| `scoring.profile_version` | profile_id, version, params (JSONB), parent_version, comment, created_at | anfügen, Versionen sind unveränderlich |
| `scoring.profile_activation` | profile_id, version, activated_at | anfügen; aktiv ist die jüngste Zeile |

`scoring.scoring_run` bekommt einen Verweis auf die verwendete Profil-Version, zusätzlich zum
vorhandenen `config_hash`.

## Zusätzliche Stichtagsdaten (Track F1)

Die Tabellen sind mit [ADR-0010](../adr/0010-stichtagsdaten-konsens-quartale-kurse.md)
beschlossen. Umgesetzt ist bisher `consensus_snapshot` (F1.1, Migration `0002`). Die Tabellen
speichern nur und fließen noch in keine Auswertung ein.

| Tabelle | Inhalt | Schreibweise |
|---|---|---|
| `market_data.consensus_snapshot` | fetch_run_id, instrument_id, kind (`eps_trend`, `eps_revisions`, `earnings_estimate`, `revenue_estimate`, `growth_estimates`, `analyst_price_targets`), fetched_at, status (`ok`, `empty`, `error`), payload (JSONB, nur bei `ok`), error (nur bei `error`) | anfügen, eine Zeile je Abruf, Titel und Art, auch für leere und gescheiterte Abrufe. DataFrames liegen als `{Zeile: {Spalte: Wert}}` vor, z. B. `payload -> '+1y' ->> 'current'`. |
| `market_data.statement_value` | wie bisher, zusätzlich `frequency = 'quarterly'` | versioniert wie `annual` |
| `market_data.share_count` | instrument_id, as_of, shares, first_seen_fetch_run_id, first_seen_at | anfügen, neue Zeile nur bei neuem Datum oder geändertem Wert |
| `market_data.price_bar` | instrument_id, trade_date, close, adj_close, dividend, split, first_seen_fetch_run_id, first_seen_at | wie `share_count`, beim ersten Abruf die ganze Historie |

## Speicherbedarf

Kennzahlen, Rohdaten und Statement-Werte für 90 Titel ergeben grob wenige MB pro Woche. Postgres
komprimiert große Werte automatisch (TOAST). Selbst über Jahre bleibt das bei einigen hundert MB.
Die Kurshistorie aus F1.4 bringt bei der Erstbefüllung einmalig rund 0,7 Mio. Zeilen, das sind
voraussichtlich einige Dutzend MB. Löschen ist deshalb weder nötig noch vorgesehen.

## Altdaten

Phase 2 bringt einen einmaligen Import der alten Parquet-Caches und Ranking-CSVs mit
(`batch.import_file` verhindert per SHA-256 den doppelten Import). Bis dieser Import auf der NAS
gelaufen ist, muss `RETENTION_DAYS=0` gesetzt bleiben. Sonst löscht das alte Housekeeping genau die
Dateien, die importiert werden sollen.

## Betrieb

- Image `postgres:18-alpine`, Volume auf `/var/lib/postgresql`. Ab PG 18 **nicht** mehr auf
  `…/data`, das Image legt die Daten versionsabhängig unter `18/docker` ab.
- Backup: täglich `pg_dump` in ein Volume, das Hyper Backup sichert
  ([betrieb-synology.md](betrieb-synology.md)).
- Upgrade auf PostgreSQL 19 (GA voraussichtlich Ende Oktober 2026) frühestens nach dem ersten
  Minor-Release, per Dump/Restore oder `pg_upgrade`.
