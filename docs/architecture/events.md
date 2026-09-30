# Event-Architektur

> **Status:** Plan (30.09.2026). Ab Phase 1 mit einem Bus im Prozess, ab Phase 4 über NATS, siehe
> [Roadmap](roadmap.md). Entscheidung: [ADR-0002](../adr/0002-nats-jetstream-und-faststream.md).

## Grundprinzipien

- **Choreografie statt zentraler Steuerung.** Die Pipeline ist linear und muss nichts
  rückgängig machen. Jeder Service reagiert auf das Event der vorherigen Stufe. Den Überblick
  behält das web-api über den Run-Status.
- **Daten reisen im Event mit (Event-carried State Transfer).** `marketdata.snapshot.completed`
  enthält alle 90 Fundamentaldaten-Datensätze. Das sind grob 80–100 KB, NATS erlaubt
  standardmäßig 1 MB. Kein Service liest die Tabellen eines anderen.
- **Mindestens einmal zugestellt, idempotent verarbeitet.** Beim Sender sorgt eine Outbox dafür,
  beim Empfänger eine Inbox (siehe unten).
- **Eine Transport-Schnittstelle, zwei Implementierungen.** In Phase 1 läuft derselbe Code mit
  einem Bus im Prozess, ab Phase 4 mit NATS. Handler und Contracts ändern sich dabei nicht.

## Ablauf eines Runs

```
Scheduler / UI ─ POST /api/v1/runs ───────────────► web-api
web-api        ─ screening.run.requested ─────────► market-data
market-data    ─ marketdata.fetch.progressed ⁽¹⁾ ─► web-api ─WS─► Browser (57/90)
market-data    ─ marketdata.snapshot.completed ───► scoring, web-api
scoring        ─ scoring.run.completed ───────────► notification, web-api ─WS─► Browser
notification   ─ notification.report.sent ────────► web-api ─WS─► Browser
jede Stufe     ─ screening.run.failed ────────────► notification (Fehlermail, HC /fail), web-api
```

⁽¹⁾ Flüchtig über Core-NATS. Geht eine Fortschrittsmeldung verloren, ist das egal, weil das
web-api den Run-Status ohnehin selbst führt.

## Subjects und Streams

| Präfix | Zweck | Speicherung |
|---|---|---|
| `va.<kontext>.<ereignis>` | dauerhafte Events | Stream `VA_EVENTS` (Subjects `va.>`) |
| `live.va.…` | flüchtige Meldungen (Fortschritt) | keine, bewusst außerhalb des Streams |
| `rpc.va.…` | Request/Reply (Vorschau, Profil-Befehle, Detailabfragen) | keine |

Flüchtige Meldungen dürfen nicht unter `va.` liegen, sonst speichert JetStream sie mit.

Stream `VA_EVENTS`: Speicherung in Dateien, Aufbewahrung 30 Tage, Deduplizierungsfenster
10 Minuten. Die Wahrheit liegt in Postgres, der Stream dient der Zustellung und dem Nachspielen
verpasster Events für WebSocket-Clients.

## Event-Katalog (v1)

| Subject | Sender | Empfänger | Inhalt (Auszug) |
|---|---|---|---|
| `va.screening.run.requested` | web-api | market-data | run_id, trigger (`scheduled`/`manual`), Optionen `force_refresh`, `dry_run`, `notify` |
| `live.va.marketdata.fetch.progressed` | market-data | web-api | run_id, done, total, symbol, ok |
| `va.marketdata.snapshot.completed` | market-data | scoring, web-api | run_id, fetch_run_id, as_of, success_share, universe_source, fundamentals[] |
| `va.scoring.run.completed` | scoring | notification, web-api | run_id (leer bei Rescore), scoring_run_id, trigger, Profil (id, version), ranking[] |
| `va.scoring.profile.saved` | scoring | web-api | profile_id, version |
| `va.scoring.profile.activated` | scoring | web-api | profile_id, version |
| `va.notification.report.sent` | notification | web-api | run_id, report_id, subject, dry_run |
| `va.screening.run.failed` | jede Stufe, Watchdog | notification, web-api | run_id, stage, reason |

Request/Reply über Core-NATS:

| Subject | Anfrage → Antwort |
|---|---|
| `rpc.va.scoring.preview` | Profil-Parameter → Ranking plus Vergleich zum aktiven Profil |
| `rpc.va.scoring.profiles.list` / `.get` | – → Profile bzw. eine Version |
| `rpc.va.scoring.profiles.save` | Parameter + Basisversion → neue Version oder Konflikt |
| `rpc.va.scoring.profiles.activate` | profile_id + version → ok |
| `rpc.va.marketdata.instrument` | Symbol → Stammdaten und Kennzahlen-Verlauf |

## Envelope

Jedes Event steckt in einer Hülle nach CloudEvents 1.0. Die Payload-Modelle liegen versioniert
in `packages/va-contracts`.

```python
class Envelope(BaseModel, Generic[T]):
    specversion: Literal["1.0"] = "1.0"
    id: UUID                       # UUIDv7; zugleich Nats-Msg-Id fuer die Deduplizierung
    type: str                      # z. B. "scoring.run.completed"
    source: str                    # z. B. "va/scoring"
    time: datetime
    dataschema: str                # z. B. "va-contracts/scoring.run.completed/v1"
    correlationid: str | None      # run_id (batch.run.id)
    causationid: UUID | None       # id des ausloesenden Events
    data: T
```

Die Tabellen in Postgres behalten ihre `bigint`-IDs. UUIDv7 gibt es nur für Event-IDs.

Regeln zur Weiterentwicklung:

- Additive Änderungen (neue optionale Felder) sind jederzeit erlaubt.
- Inkompatible Änderungen bekommen ein neues `dataschema` (`…/v2`). Während der Umstellung
  verstehen Empfänger beide Versionen.
- Aus denselben Modellen entstehen die JSON-Schemas für die TypeScript-Typen im Frontend und
  die AsyncAPI-Doku. FastStream erzeugt Letztere automatisch.

## Zuverlässigkeit: Outbox und Inbox

**Outbox (Sender):** Fachdaten und Event werden in einer Transaktion geschrieben. Ein Relay-Task
im selben Service veröffentlicht offene Einträge und setzt `Nats-Msg-Id` gleich der Event-ID.
JetStream verwirft Duplikate innerhalb des Deduplizierungsfensters.

```sql
create table outbox (
    id           uuid primary key,          -- Event-ID (uuidv7)
    subject      text        not null,
    payload      jsonb       not null,
    created_at   timestamptz not null default now(),
    published_at timestamptz
);
create index outbox_pending on outbox (created_at) where published_at is null;
```

**Inbox (Empfänger):** Vor der Verarbeitung prüft der Handler, ob die Event-ID schon verarbeitet
wurde. Verarbeitung und Inbox-Eintrag laufen in einer Transaktion.

```sql
create table inbox (
    message_id   uuid        not null,
    consumer     text        not null,
    processed_at timestamptz not null default now(),
    primary key (message_id, consumer)
);
```

Beide Tabellen gibt es in jedem Service-Schema, die Implementierung liegt einmal in
`va-platform`. Die Outbox braucht `UPDATE` auf `published_at` und damit eine bewusste Ausnahme im
Schreibschutz ([datenhaltung.md](datenhaltung.md)).

## Consumer

| Consumer (durable) | Filter | Besonderheit |
|---|---|---|
| `market-data` | `va.screening.run.requested` | Der Abruf dauert Minuten. Währenddessen In-Progress-Acks senden, sonst stellt JetStream nach `ack_wait` erneut zu. |
| `scoring` | `va.marketdata.snapshot.completed` | speichert den Snapshot zusätzlich lokal, für Vorschau und Rescore |
| `notification` | `va.scoring.run.completed`, `va.screening.run.failed` | ignoriert `trigger=rescore`, bei `dry_run` nur rendern und speichern |
| `web-api` | `va.>` | Projektionen und WebSocket, siehe [web-api-realtime.md](web-api-realtime.md) |

Alle Consumer begrenzen die Wiederholungen (`max_deliver`, z. B. 5). Danach wird die Nachricht
mit Fehler in der Inbox vermerkt, und der Run endet über `va.screening.run.failed`.

## Run-Optionen und Sonderfälle

- `force_refresh`: market-data ignoriert einen wiederverwendbaren Snapshot vom selben Tag.
- `dry_run`: notification rendert die Mail, verschickt sie aber nicht. Sie landet in
  `reporting.report`, das UI kann sie anzeigen.
- `notify=false`: kein Mailversand, z. B. für manuelle Test-Runs.
- **Rescore** nach einer Profil-Aktivierung: scoring bewertet den letzten Snapshot neu
  (`trigger=rescore`, entspricht der Run-Art `rescore` in `batch.run`). Das löst keine Mail und
  keinen Healthcheck-Ping aus.
- Healthchecks.io wird nur bei `trigger=scheduled` gepingt. Manuelle Runs sollen einen
  ausgefallenen Zeitplan nicht verdecken.

## Scheduler und Watchdog (im web-api)

- Der Cron-Ausdruck (heute `CRON_SCHEDULE`, Standard Samstag 07:30) wird mit expliziter Zeitzone
  `Europe/Berlin` ausgewertet, unabhängig von der Zeitzone des Containers.
- **Idempotenz:** Jeder geplante Run wird mit seinem Termin als eindeutigem Schlüssel angelegt.
  Feuert der Scheduler doppelt, entsteht kein zweiter Run.
- **Watchdog:** Hängt ein Run länger als das Zeitlimit seiner Stufe, veröffentlicht das web-api
  `va.screening.run.failed` mit `reason=timeout`. Richtwerte, konfigurierbar: Abruf 45 min,
  Scoring 5 min, Mail 5 min.
