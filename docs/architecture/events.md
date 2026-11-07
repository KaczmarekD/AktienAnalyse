# Event-Architektur

> **Status:** Umgesetzt: ab Phase 1 mit einem Bus im Prozess, seit Phase 4 über NATS, seit P5.4
> der Standard auf der NAS, siehe [Roadmap](roadmap.md). Entscheidung:
> [ADR-0002](../adr/0002-nats-jetstream-und-faststream.md).
> Seit P4.1 (01.11.2026) gibt es den NATS-Dienst und die Provisionierung von Stream und Consumern
> (`va_platform.nats`), seit P4.2 Outbox und Inbox (`va_platform.messaging`). Seit P4.3 kann der
> Batch die Kette über NATS laufen lassen (`EVENT_BUS=nats`, `va_platform.nats.NatsBus`).
> Standard bleibt der Bus im Prozess. Seit P4.3b hängt jeder Service über einen `ReliableBus` mit
> Inbox und Outbox am Bus (siehe unten).

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

Bis Phase 4 läuft die Kette im Batch-Prozess über `va_platform.bus.InProcessBus` (P1.8):
`src/main.py` übernimmt die Rolle des web-api (Run anlegen, `screening.run.requested`
senden, Ergebnis über den `RunTracker` festhalten), der Trigger ist immer `scheduled`.
Im Prozess gilt `max_deliver=1`. Mit NATS kann ein Event erneut zugestellt werden; spätestens
dann braucht notification die Inbox, sonst ginge die Mail doppelt raus.

## Subjects und Streams

| Präfix | Zweck | Speicherung |
|---|---|---|
| `va.<kontext>.<ereignis>` | dauerhafte Events | Stream `VA_EVENTS` (Subjects `va.>`) |
| `priv.va.<kontext>.<ereignis>` | private Events mit persönlichen Daten (seit D1.6) | Stream `VA_PRIVATE` (Subjects `priv.va.>`) |
| `live.va.…` | flüchtige Meldungen (Fortschritt) | keine, bewusst außerhalb des Streams |
| `rpc.va.…` | Request/Reply (Vorschau, Profil-Befehle, Detailabfragen) | keine |

Flüchtige Meldungen dürfen nicht unter `va.` liegen, sonst speichert JetStream sie mit.

Stream `VA_EVENTS`: Speicherung in Dateien, Aufbewahrung 30 Tage, Deduplizierungsfenster
10 Minuten. Die Wahrheit liegt in Postgres, der Stream dient der Zustellung und dem Nachspielen
verpasster Events für WebSocket-Clients.

Stream `VA_PRIVATE` (seit D1.6, [nutzer.md](depot/nutzer.md#personenbezogene-daten-und-das-löschverbot)):
nur im Speicher, also nicht in `natsdata` und nicht im Backup, Aufbewahrung 24 Stunden. Hier
laufen Events mit Mail-Adressen und Links, später Bestände und Berichte. Im Katalog trägt so ein
Event `private=True` (`EventSpec`), der Publisher wählt den Stream nach dem Subject
(`va_platform.nats.stream_for`). Ein Dienst legt `VA_PRIVATE` nur an, wenn einer seiner Consumer
dort liegt oder er dorthin sendet (`NatsBus(..., streams=…)`, das web-api). Das web-api abonniert
keine privaten Events, sie stehen nie in den Projektionen. Ein Event darf ein eigenes Höchstalter
haben (`EventSpec.max_age`): Der `ReliableBus` überspringt es erst danach, nicht schon nach
`RUN_TIMEOUT_MINUTES`.

## Event-Katalog (v1)

| Subject | Sender | Empfänger | Inhalt (Auszug) |
|---|---|---|---|
| `va.screening.run.requested` | web-api | market-data | run_id, trigger (`scheduled`/`manual`), options (`force_refresh`, `dry_run`, `notify`) |
| `live.va.marketdata.fetch.progressed` | market-data | web-api | run_id, done, total, symbol, ok |
| `va.marketdata.snapshot.completed` | market-data | scoring, web-api | run_id, trigger, options, fetch_run_id, as_of, success_share, universe (Quelle, Stichtag, Größe, Zu-/Abgänge), fundamentals[] |
| `va.scoring.run.completed` | scoring | notification, web-api | run_id (leer genau bei Rescore), trigger, options, scoring_run_id, fetch_run_id, as_of, universe, value_weight, quality_weight, Profil (id, version, Name), seit G3 die Parameter des Laufs (`params`, optional), ranking[] (mindestens eine Zeile, mit Perzentilen je Faktor, seit F2.4 mit `industry_rule` für Titel unter der Branchenregel) |
| `va.scoring.profile.saved` | scoring | web-api | profile_id, version |
| `va.scoring.profile.activated` | scoring | web-api | profile_id, version |
| `va.notification.report.sent` | notification | web-api | run_id, report_id, subject, dry_run |
| `va.screening.run.failed` | jede Stufe, Watchdog | notification, web-api | run_id (leer genau bei Rescore), trigger, options, stage, reason (z. B. `timeout`, `no_data`), scoring_run_id, detail (Traceback für die Fehlermail) |
| `priv.va.identity.email_confirmation.requested` (D1.6, privat, 24 h) | web-api (Outbox im Schema `identity`) | notification (`notification-private`) | user_id, email (die neue Adresse), link (mit Token, aus der geprüften Herkunft der Anfrage), expires_at |

Trigger und Optionen reisen mit jedem Event der Kette mit. So entscheidet jede Stufe allein: scoring
setzt den Trigger fort, notification verschickt bei `dry_run` oder `notify=false` keine Mail und
pingt den Healthcheck nur bei `trigger=scheduled`. `scoring.run.completed` enthält alles, was
Mail und CSV brauchen, auch das Universum (für `partial`/`ok` im Betreff) und die Gewichte.
Ein Test rendert die Golden-Mail allein aus diesem Event (`tests/test_contracts_v1.py`). Keine
bewertbaren Daten sind kein leeres Ranking, sondern `screening.run.failed` mit
`reason=no_data`.

Feldnamen sind snake_case wie in Python und den Tabellen. Das WebSocket-Protokoll zum Browser
(P4.5) hat eigene Nachrichtenmodelle und bildet dort auf camelCase ab.

Request/Reply über Core-NATS. Seit P4.8 umgesetzt sind die vier Befehle für scoring, seit P4.9
die zum Lesen von Profilen und Reports
(`va_contracts.rpc.v1`, Golden-Schemas unter `tests/golden/contracts/rpc/v1/`). Jede Antwort hat
ein optionales `error` (`no_data`, `unknown_profile`, `unknown_version`, `conflict` mit `newest`,
`invalid`, `internal`). Es antwortet der Worker in der Queue-Gruppe des Service (`scoring`,
`notification`).

| Subject | Anfrage → Antwort |
|---|---|
| `rpc.va.scoring.factors` (P4.8) | – → Faktor-Katalog mit Richtung und Methodik-Hinweis |
| `rpc.va.scoring.preview` (P4.8) | Profil-Parameter → Ranking plus Vergleich zum aktiven Profil |
| `rpc.va.scoring.profiles.list` / `.get` (P4.9) | – → Profile bzw. ein Profil mit seinen Versionen (leer: unbekannt) |
| `rpc.va.scoring.profiles.save` (P4.8) | Parameter + Basisversion → neue Version oder Konflikt |
| `rpc.va.scoring.profiles.activate` (P4.8) | profile_id + version → ok |
| `rpc.va.notification.report` / `.report.csv` (P4.9) | report_id → Mail bzw. CSV als Base64 (leer: unbekannt) |
| `rpc.va.marketdata.instrument` | Symbol → Stammdaten und Kennzahlen-Verlauf (nicht nötig: die Titelseite kommt seit P4.9 aus den Projektionen) |
| `rpc.va.marketdata.securities.search` (D2.1) | ISIN, WKN, Name oder Symbol → Treffer (eigene Wertpapiere, OpenFIGI, Yahoo; 24 h im Speicher) |
| `rpc.va.marketdata.securities.resolve` (D2.1) | ISIN, optional ein Listing → Wertpapier mit Stammdaten (ESMA FIRDS) und Listings; speichert sie (leer: unbekannt, `invalid`: falsche Prüfziffer) |

## Envelope

Jedes Event steckt in einer Hülle nach CloudEvents 1.0. Die Payload-Modelle liegen versioniert
in `packages/va-contracts` (seit P1.2: `va_contracts.events.v1`, Hülle `va_contracts.Envelope`,
Katalog `va_contracts.events.v1.EVENTS`). Ihre JSON-Schemas stehen als Golden-Files unter
`tests/golden/contracts/v1/`.

```python
class Envelope[T](Contract):
    specversion: Literal["1.0"] = "1.0"
    id: UUID                       # UUIDv7; zugleich Nats-Msg-Id fuer die Deduplizierung
    type: str                      # z. B. "scoring.run.completed"
    source: str                    # z. B. "va/scoring"
    time: AwareDatetime
    dataschema: str                # z. B. "urn:va-contracts:scoring.run.completed:v1"
    correlationid: str | None      # run_id (batch.run.id) als Text
    causationid: UUID | None       # id des ausloesenden Events
    traceparent: str | None        # W3C Trace Context (P5.5), leer ohne Tracing
    data: T
```

`traceparent` (seit P5.5) ist die CloudEvents-Erweiterung für verteiltes Tracing. Busse und
Outbox setzen es beim Senden aus dem aktuellen Span (`va_platform.tracing.stamp`), Empfänger
öffnen damit ihren Span. So ergibt ein Run einen Trace über alle Services. Ohne Tracing
(`OTEL_TRACES_EXPORTER=none`, Standard) bleibt das Feld leer.

`dataschema` ist eine URN, weil CloudEvents dort eine absolute URI verlangt. Die Hülle prüft,
dass `type` und `dataschema` laut Katalog zur Payload gehören. Sender erzeugen sie mit
`new_envelope(spec, data, source=…)`, Empfänger lesen rohes JSON mit `parse_envelope(raw)`: Das
Dataschema wählt das Modell, ein unbekanntes ergibt `UnknownEventError`.

Die Tabellen in Postgres behalten ihre `bigint`-IDs. UUIDv7 gibt es nur für Event-IDs.

Regeln zur Weiterentwicklung:

- Additive Änderungen (neue optionale Felder) sind jederzeit erlaubt.
- Inkompatible Änderungen bekommen ein neues `dataschema` (`…:v2`). Während der Umstellung
  verstehen Empfänger beide Versionen (beide Einträge in `BY_DATASCHEMA`).
- Aus denselben Modellen entstehen die JSON-Schemas (Golden-Files) und über OpenAPI die
  TypeScript-Typen im Frontend. Eine AsyncAPI-Doku gibt es ohne FastStream nicht, die Tabellen
  hier ersetzen sie.

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

**Umgesetzt seit P4.2 (01.11.2026)**, genutzt ab P4.3:

- **Tabellen** (Migration `0009`): wie oben, in `batch`, `market_data`, `scoring` und
  `reporting`. Die Inbox hat zusätzlich `error`, gesetzt nur bei einem aufgegebenen Event.
  - Die Modelle liegen beim Besitzer des Schemas (`ScoringOutbox`, `ScoringInbox` usw.).
  - Die Spalten kommen aus `OutboxMixin` und `InboxMixin` (`va_platform.messaging`).
- **Senden:**
  - `Outbox(model).add(session, envelope)` schreibt in die Transaktion des Aufrufers. Das
    Subject kommt aus dem Katalog, flüchtige Events lehnt sie ab.
  - `OutboxRelay(engine, outbox, publisher)` veröffentlicht offene Einträge in der Reihenfolge
    ihres Entstehens und setzt danach `published_at`.
    - Scheitert ein Versand, bleiben dieser und alle späteren Einträge offen.
    - `run(stop, interval=…)` versucht es weiter, bis der Dienst stoppt.
  - Publisher für NATS ist `va_platform.nats.JetStreamPublisher` (`Nats-Msg-Id` gleich Event-ID,
    Stream `VA_EVENTS` verlangt).
- **Empfangen:**
  - `Inbox(model).process_once(engine, message_id, consumer, work)` führt `work` nur für ein neues
    Event aus. Inbox-Eintrag, Fachdaten und Folge-Events teilen sich eine Transaktion.
  - `record_dead_letter` vermerkt ein aufgegebenes Event.
- **Schreibschutz:**
  - Der Trigger `va_guard_outbox` lässt nur ein UPDATE zu, das `published_at` einmal setzt.
  - `va_app` hat dafür nur das Spaltenrecht `UPDATE (published_at)`.

**`ReliableBus` (P4.3b, pragmatisch):** So nutzen die Handler Outbox und Inbox, im Prozess wie über
NATS. Er umhüllt den Bus je Service, mit Inbox und Outbox aus dessen Schema.

- **Zustellung:**
  - Ein Event älter als `RUN_TIMEOUT_MINUTES` wird übersprungen, ebenso eines, das der Consumer
    schon verarbeitet hat.
  - Sonst läuft der Handler, und was er veröffentlicht, sammelt der Wrapper.
  - Inbox-Eintrag und Folge-Events kommen dann in einer Transaktion in die Outbox.
  - `drain_outbox` gibt die offenen Einträge danach an den Bus weiter.
- **Fachdaten:** Die schreibt der Handler selbst kurz davor. Stürzt der Prozess genau dazwischen
  ab, läuft er bei erneuter Zustellung noch einmal. Dagegen stehen fachliche Sperren:
  - market-data nutzt den Abruf des Tages wieder.
  - notification verschickt für einen Bewertungslauf höchstens eine Report-Mail.
  - Ein zweiter Bewertungslauf ist harmlos, die Tabellen sind nur zum Anfügen.

## Consumer

| Consumer (durable) | Filter | Besonderheit |
|---|---|---|
| `market-data` | `va.screening.run.requested` | Der Abruf dauert Minuten. Währenddessen In-Progress-Acks senden, sonst stellt JetStream nach `ack_wait` erneut zu. |
| `scoring` | `va.marketdata.snapshot.completed` | speichert den Snapshot zusätzlich lokal, für Vorschau und Rescore |
| `notification` | `va.scoring.run.completed`, `va.screening.run.failed` | ignoriert `trigger=rescore`, bei `dry_run` nur rendern und speichern |
| `web-api` | `va.>` | Projektionen und WebSocket, siehe [web-api-realtime.md](web-api-realtime.md) |
| `batch` | `va.marketdata.snapshot.completed`, `va.scoring.run.completed`, `va.notification.report.sent`, `va.screening.run.failed` | seit P4.3: der `RunTracker` des Batches, Vorläufer der Run-Projektion im web-api |
| `notification-private` | `priv.va.identity.email_confirmation.requested` | seit D1.6, im Stream `VA_PRIVATE`: Bestätigungsmail an die neue Adresse, ohne Versandprotokoll (die Adresse gehört nicht ins Schema `reporting`); ein abgelaufener Link geht nicht mehr raus |

Consumer-Namen sind über beide Streams eindeutig: Der Bus führt seine Consumer nur nach Namen,
den Stream kennt er aus `ConsumerSpec.stream`.

Alle Consumer begrenzen die Wiederholungen (`max_deliver`, z. B. 5). Danach wird die Nachricht
mit Fehler in der Inbox vermerkt, und der Run endet über `va.screening.run.failed`. Ein Event ohne
Run (die Bestätigungsmail) löst dabei kein `va.screening.run.failed` aus.

**`NatsBus` (P4.3):**

- **Consumer:**
  - Einen provisionierten Consumer nutzt der Bus so, wie er ist. Sein Filter muss die
    abonnierten Subjects abdecken.
  - Einen unbekannten Namen (Tests) legt er mit genau diesen Subjects an, nur für neue
    Nachrichten.
  - Je Consumer holt eine Schleife die Nachrichten einzeln ab und verteilt sie nach Event-Typ.
- **Wiederholungen:**
  - Es gilt die Grenze des Busses. Der Batch bleibt bei 1, wie im Prozess.
  - Danach kommt der Dead-Letter-Callback, dann `term()`.
  - Die Grenze des Busses darf höchstens die des Consumers sein.
- **Laufende Handler:** Der Bus sendet In-Progress-Acks alle `ack_wait / 3`.
- **Senden:** Folge-Events stehen im Stream, bevor das auslösende Event bestätigt wird.
- **Batch:** Über NATS wartet `src/main.py`, bis der `RunTracker` ein Ergebnis hat (höchstens
  `RUN_TIMEOUT_MINUTES`). Dann wartet es, bis nichts mehr offen ist, und schließt den Bus geordnet.

## NATS-Nutzer und Rechte (seit D1.5)

NATS verlangt eine Anmeldung ([nutzer.md](depot/nutzer.md#sicherheitsregeln) Regel 11). Die
Nutzer stehen in `docker/nats/nats.conf`, die Passwörter (`NATS_*_PASSWORD`) in der `.env`, der
Nutzername in der `NATS_URL` des Dienstes.

| Nutzer | Sendet | Liest | RPC |
|---|---|---|---|
| `market-data` | `va.marketdata.>`, `live.va.marketdata.>`, `va.screening.run.failed` | Consumer `market-data` | seit D2.1 antwortet auf `rpc.va.marketdata.>` |
| `scoring` | `va.scoring.>`, `va.screening.run.failed` | Consumer `scoring` | antwortet auf `rpc.va.scoring.>` |
| `notification` | `va.notification.>`, `va.screening.run.failed` | Consumer `notification`, seit D1.6 `notification-private` (`VA_PRIVATE`) | antwortet auf `rpc.va.notification.>` |
| `web-api` | `va.screening.run.requested`, `va.screening.run.failed`, seit D1.6 `priv.va.identity.>` | Consumer `web-api`, `live.va.>`, einzelne Nachrichten aus `VA_EVENTS` (Nachspielen); nichts aus `VA_PRIVATE` | fragt `rpc.va.scoring.>`, `rpc.va.notification.>`, seit D2.1 `rpc.va.marketdata.>` |
| `batch` | alles | alles | alles |

- **Inbox:** Antworten (JetStream-API, RPC) gehen an `_INBOX.<nutzer>`; jeder darf nur seine
  lesen (`va_platform.nats.inbox_prefix`).
- **`VA_PRIVATE` (D1.6):** `market-data` und `scoring` sehen den Stream nicht, das web-api sendet
  nur und legt ihn an, notification liest nur über `notification-private`.
- **Provisionierung:** Jeder Dienst legt den Stream und nur seinen eigenen Consumer an. Umstellen
  darf den Stream nur `batch`; weicht er ab, meldet ein Dienst das im Log und läuft weiter. Alle
  Consumer legt `provision()` ohne `consumers` an: der Batch, `src.worker`, `make nats-provision`
  (Nutzer `batch`).
- **Neues Event oder RPC:** Eintrag in `nats.conf` beim Sender (und beim Besitzer des RPC). Fehlt
  er, meldet NATS „Permissions Violation“, und der Dienst bekommt keinen PubAck.
  `tests/test_nats_permissions.py` prüft die Rechte gegen einen NATS mit dieser Datei, der
  E2E-Stack die ganze Kette.

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

Seit P4.7 in `va_web_api.runs`. Beides läuft nur mit NATS und Projektions-Datenbank, in einer
Hintergrund-Aufgabe des web-api (Takt 60 s). Ausgeführt werden die Runs vom Dienste-Prozess
den drei Services (seit P5.1 je ein Container, seit P5.4 ohne Profil; `python -m src.worker` startet
alle drei in einem Prozess).

- **Anlegen:** Ein Run des web-api entsteht in einer Transaktion: `batch.run`, `web.run_request`
  und `screening.run.requested` in `web.outbox`. Danach leert das web-api die Outbox an NATS.
  Ein Start aus dem UI (`POST /api/v1/runs`) wird abgelehnt (409), solange ein Run läuft.
- **Scheduler:** Der Cron-Ausdruck `WEB_API_SCHEDULE` wird mit expliziter Zeitzone ausgewertet
  (`WEB_API_SCHEDULE_TIMEZONE`, Standard `Europe/Berlin`), unabhängig von der Zeitzone des
  Containers. Fällig ist der jüngste Termin, höchstens eine Stunde alt. Leer heißt aus. Auf der NAS
  kommt der Ausdruck seit P5.4 aus `CRON_SCHEDULE` (Standard Samstag 07:30), den Cron im
  Batch-Container gibt es nicht mehr.
- **Idempotenz:** Jeder geplante Run wird mit seinem Termin als eindeutigem Schlüssel angelegt
  (`web.run_request.slot`). Feuert der Scheduler doppelt, entsteht kein zweiter Run.
- **Watchdog:** Hängt ein Run des web-api länger als das Zeitlimit seiner Stufe, veröffentlicht
  das web-api `va.screening.run.failed` mit `stage=watchdog` und `reason=timeout`. Die Grenzen
  sind einstellbar: Abruf 45 min ab der Anfrage (`WEB_API_WATCHDOG_FETCH_MINUTES`), Scoring
  5 min ab `fetched` (`…_SCORING_MINUTES`), Mail 5 min ab `scored` (`…_REPORT_MINUTES`). In
  derselben Transaktion schließt es den Run ab, der nächste Takt meldet ihn nicht noch einmal.
  Abbrechen kann es die Stufe nicht: Liefert sie später doch, kann trotzdem eine Mail rausgehen.
- **Abschluss:** Eine Projektion des Eventmanagers schließt `batch.run` beim ersten Ergebnis ab
  (`notification.report.sent` oder `screening.run.failed`), mit den Regeln des `RunTracker`.
  Runs des Batches schließt weiter der Batch selbst ab.
