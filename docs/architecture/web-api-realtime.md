# web-api, Eventmanager und WebSocket

> **Status:** REST seit Phase 3. Seit P4.4 (04.11.2026) gibt es den Eventmanager
> (`va_web_api.events`) mit den Projektionen `web.run_status` und `web.ranking_row`, gespeist aus
> NATS. Seit P4.5 (04.11.2026) meldet der WebSocket-Hub sie unter `/ws` an die offenen Tabs
> (`va_web_api.realtime`, Protokoll v1, Nachspielen mit `resumeFrom`). Seit P4.9 lesen die
> REST-Endpunkte mit NATS aus den Projektionen und per Request/Reply, ohne NATS weiter aus den
> Tabellen des Batches (Port `ReadModel`). Plan (30.09.2026): REST
> ab Phase 3, Eventmanager und WebSocket ab Phase 4, siehe
> [Roadmap](roadmap.md). Entscheidungen:
> [ADR-0006](../adr/0006-websocket-und-eventmanager.md), [ADR-0007](../adr/0007-lan-only-ohne-login.md).

## Aufgaben

Das web-api ist das Backend for Frontend. Es

- stellt die REST-API für das Angular-Frontend bereit,
- verteilt Änderungen per WebSocket an alle offenen Tabs,
- pflegt Read-Models (Projektionen) aus den Events der Fach-Services,
- verwaltet Runs: manueller Start, Scheduler, Watchdog,
- reicht Profil-Befehle und die Live-Vorschau per Request/Reply an `scoring` weiter.

Das web-api hat **keinen Port im LAN**. Erreichbar ist es nur über den `frontend`-Container,
der `/api/*` und `/ws` intern weiterleitet ([frontend.md](frontend.md)).

## Module

```
services/web-api/src/va_web_api/
├── api/            # REST-Router v1: runs, ranking, instruments, scoring
├── realtime/       # WebSocketHub, Protokoll, Origin-Prüfung
├── events/         # EventManager, Broker-Subscriber
├── projections/    # Read-Models: Run-Status, aktuelles Ranking, Score-Verlauf
├── runs/           # Run-Verwaltung, Scheduler, Watchdog
└── main.py         # FastAPI-App; der Lifespan startet DB-Pool, Broker und Scheduler
```

Der `NatsBus` (eigener Adapter mit nats-py, Nachtrag in ADR-0002) wird im Lifespan von
FastAPI gestartet und gestoppt, ebenso der Takt von Scheduler und Watchdog.

## REST-API (v1)

| Methode und Pfad | Zweck | Datenquelle |
|---|---|---|
| `GET /api/v1/runs`, `GET /api/v1/runs/{id}` | Run-Liste und Details | `batch.run` |
| `POST /api/v1/runs` | Run manuell starten (`force_refresh`, `dry_run`, `notify`) | legt den Run an, Event über die Outbox |
| `GET /api/v1/ranking/latest`, `GET /api/v1/ranking/{scoring_run_id}` | Rankings | Projektion im Schema `web` |
| `GET /api/v1/instruments/{symbol}` | Stammdaten, Kennzahlen, Score-Verlauf | Projektion + `rpc.va.marketdata.instrument` |
| `GET /api/v1/reports/{id}` | gerenderte Mail, auch von Dry-Runs | `rpc` an notification bzw. `reporting.report` |
| `GET /api/v1/scoring/factors` | Faktor-Katalog mit Methodik-Hinweisen | `rpc.va.scoring.profiles.get` |
| `GET /api/v1/scoring/profiles`, `GET …/{id}` | Profile und Versionen | `rpc.va.scoring.profiles.*` |
| `PUT /api/v1/scoring/profiles/{id}` | neue Version speichern (mit `If-Match`) | `rpc.va.scoring.profiles.save` |
| `POST /api/v1/scoring/profiles/{id}/activate` | Version aktivieren | `rpc.va.scoring.profiles.activate` |
| `POST /api/v1/scoring/preview` | Live-Vorschau | `rpc.va.scoring.preview` |
| `GET /api/v1/health` | Healthcheck | – |
| `POST /api/v1/auth/login`, `POST /api/v1/auth/logout` | Anmelden (Sitzungs-Cookie), abmelden (seit D1.1) | Schema `identity`, Rolle `va_identity` |
| `GET /api/v1/me` | eigenes Konto (seit D1.1) | Schema `identity` |

Schreibende Endpunkte akzeptieren ausschließlich JSON (siehe Sicherheitsregeln).

**Übergang in Phase 3:** Bevor es Events gibt, liest das web-api über die Rolle `va_read` (seit
Phase 2 vorhanden) direkt aus den Schemas des Batches. Die Profil-Vorschau ruft den
Scoring-Code über einen Port im selben Prozess auf. Ab Phase 4 werden daraus Projektionen und
Request/Reply, ohne dass sich die REST-API ändert.

Seit P3.3 gilt das auch für die Profil-Befehle (Speichern, Aktivieren). Die Ports stehen in
`va_web_api.ports`, umgesetzt sind sie in `src/web.py`, der Composition Root des
web-api-Prozesses. Geschrieben wird mit der Rolle `va_profiles`, die nur in die
Profil-Tabellen anfügen darf, nicht mit der Rolle des Batches. Fehlt
`WEB_API_PROFILES_DATABASE_URL`, antworten die schreibenden Endpunkte mit 503.

**Request/Reply (seit P4.8):** Mit `WEB_API_NATS_URL` gehen Faktor-Katalog, Vorschau, Speichern und
Aktivieren als Request/Reply an scoring (`rpc.va.scoring.*`, Contracts in `va_contracts.rpc.v1`).
`va_web_api.rpc.RemoteScoring` setzt dafür die Ports um, `scoring_handlers` ist die Gegenseite im
Worker. Die REST-API bleibt gleich, die API-Tests aus P3.3 laufen in beiden Varianten. Antwortet
niemand, kommt 503 („Scoring nicht erreichbar“). Nach Speichern und Aktivieren meldet der Worker
`scoring.profile.saved` bzw. `.activated`, die offenen Tabs bekommen das über das Topic `profiles`.

**Lesemodell (seit P4.9):** Die Router fragen den Port `ReadModel`.

- Ohne NATS ist es `TableReadModel` mit den Abfragen aus P3.2 (Rolle `va_read`).
- Mit `WEB_API_NATS_URL` und `WEB_API_PROJECTIONS_DATABASE_URL` ist es `ProjectionReadModel`
  (Rolle `va_web`). Es liest nur `web` und `batch.run`:
  - Ranking und Titelseite aus `snapshot_row`, `ranking_run` und `ranking_row`, seit G3 dazu
    `ranking_profile` und `ranking_factor`;
  - Profile und Reports per Request/Reply von scoring bzw. notification.

Die Historie füllt `src.db.backfill` beim Start der Migration aus den Tabellen nach. Die Antworten
sind in beiden Fällen dieselben.

**Runs aus dem UI (seit P4.7):** `POST /api/v1/runs` antwortet mit 202 und der ID des Runs.
`va_web_api.runs.RunManager` legt ihn mit der Rolle `va_web` in `batch.run` an, dazu
`web.run_request` und das Event in `web.outbox`. Läuft schon ein Run, kommt 409. Ohne
`WEB_API_NATS_URL` und `WEB_API_PROJECTIONS_DATABASE_URL` gibt es keine Run-Verwaltung, dann
kommt 503. Ausgeführt wird der Run von den Services (seit P5.1 je ein Container). Scheduler und Watchdog
laufen im Takt einer Hintergrund-Aufgabe ([events.md](events.md#scheduler-und-watchdog-im-web-api)).

## Eventmanager

Der Eventmanager ist die Drehscheibe im web-api. Er verarbeitet jedes Event in zwei Schritten:

1. **Projektionen aktualisieren:** Die Read-Models werden in einer Transaktion zusammen mit
   der Inbox geschrieben. Schlägt das fehl, wirft der Handler eine Exception, und JetStream
   stellt das Event erneut zu.
2. **Clients benachrichtigen:** Erst nach dem Commit geht die Meldung an den WebSocket-Hub. Wer
   daraufhin per REST nachlädt, sieht also garantiert den neuen Stand.

Ereignisse aus dem UI selbst, etwa ein manueller Run-Start, laufen über dieselben Wege:
REST-Aufruf → Outbox → Event → Eventmanager → alle Clients.

```python
class EventManager:
    """Drehscheibe im web-api: Broker-Event -> Projektionen -> WebSocket-Hub."""

    def __init__(self, uow_factory: UowFactory, hub: WebSocketHub) -> None:
        self._projections: defaultdict[str, list[Projection]] = defaultdict(list)
        self._uow_factory = uow_factory
        self._hub = hub

    def projection(self, event_type: str) -> Callable[[Projection], Projection]:
        def register(fn: Projection) -> Projection:
            self._projections[event_type].append(fn)
            return fn
        return register

    async def dispatch(self, env: Envelope, seq: int) -> None:
        async with self._uow_factory() as uow:
            if await uow.inbox.seen(env.id):             # Redelivery -> idempotent
                return
            for project in self._projections[env.type]:  # Exception -> NAK -> Redelivery
                await project(env, uow)
            await uow.inbox.mark(env.id)
            await uow.commit()
        # Erst nach dem Commit pushen: wer daraufhin per REST nachlaedt, sieht den neuen Stand
        self._hub.publish(topic_for(env), ServerMessage.event(env, seq))


@broker.subscriber("va.>", stream=VA_EVENTS, durable="web-api")
async def on_event(env: Envelope, msg: NatsMessage) -> None:
    await events.dispatch(env, seq=msg.raw_message.metadata.sequence.stream)
```

Flüchtige Fortschrittsmeldungen (`live.va.…`) laufen an den Projektionen vorbei direkt in den
Hub, ohne `seq`.

## WebSocket-Hub

- verwaltet Verbindungen und ihre Topic-Abos,
- gibt jedem Client eine begrenzte Warteschlange (z. B. 256 Nachrichten) mit eigenem
  Schreib-Task. Ist sie voll, wird der Client mit Code `1013` getrennt, verbindet sich neu und
  synchronisiert sich. Ein langsamer Client blockiert nie die anderen.
- Heartbeat: Uvicorn sendet standardmäßig alle 20 s WebSocket-Pings. Der
  `proxy_read_timeout` in nginx muss deutlich länger sein.
- Beim Verbindungsaufbau prüft der Endpunkt den `Origin`-Header: ohne `WEB_API_ALLOWED_ORIGINS`
  (durch Komma getrennt) nur dieselbe Herkunft wie der `Host`, sonst genau die Liste.

```python
class WebSocketHub:
    """Verbindungen, Topic-Abos, pro Client eine begrenzte Queue + Writer-Task."""

    def publish(self, topic: str, message: ServerMessage) -> None:
        for client in self._subscribers.get(topic, ()):
            try:
                client.queue.put_nowait(message)
            except asyncio.QueueFull:
                client.close_soon(code=1013)   # zu langsam: trennen, Client synchronisiert neu
```

## WebSocket-Protokoll v1

Verbindung: `ws://<nas>:8080/ws` mit dem Subprotokoll `va.v1`. Ein Client mit einer
inkompatiblen Protokollversion wird schon beim Handshake abgelehnt.

**Topics**

| Topic | Inhalt |
|---|---|
| `runs` | Run angelegt, Fortschritt, Stufenwechsel, fertig oder fehlgeschlagen |
| `ranking` | neues Ranking (Run oder Rescore) |
| `profiles` | Profil gespeichert oder aktiviert |
| `instrument:<SYMBOL>` | neue Daten zu einem Titel |
| `user:<id>` | seit D1.3: Meldungen nur für diesen Nutzer (später Depots, Berichte). Abonnieren darf nur er selbst, sonst `error` mit Code `forbidden`. |

**Client → Server**

| `op` | Felder | Zweck |
|---|---|---|
| `subscribe` | `topics`, optional `resumeFrom` | Topics abonnieren, verpasste Events ab `seq` nachspielen |
| `unsubscribe` | `topics` | Abo beenden |
| `ping` | – | Heartbeat auf Anwendungsebene |

**Server → Client**

| `op` | Felder | Zweck |
|---|---|---|
| `hello` | `serverTime`, `lastSeq` | nach dem Verbindungsaufbau |
| `event` | `topic`, `type`, `seq` (nur dauerhafte Events), `data` | eine Änderung |
| `resync` | `topic` | Lücke zu groß, der Client lädt per REST neu |
| `pong` | – | Antwort auf `ping` |
| `error` | `code`, `message` | z. B. unbekanntes Topic (`bad_request`), fremdes Topic (`forbidden`) |

**Trennung durch den Server:** `1008` beim Handshake (fremder `Origin`, ohne Subprotokoll, seit
D1.2 ohne Sitzung), `1009` bei zu großer Nachricht, `1013` bei voller Warteschlange, seit D1.3
`4401`, wenn die Sitzung endet: abgemeldet, abgelaufen, widerrufen oder Konto deaktiviert.

```jsonc
// Client → Server
{"op": "subscribe", "topics": ["runs", "ranking"], "resumeFrom": 4711}
// Server → Client
{"op": "event", "topic": "runs", "type": "marketdata.fetch.progressed",
 "data": {"runId": "42", "done": 57, "total": 90}}                  // flüchtig, ohne seq
{"op": "event", "topic": "ranking", "seq": 4712, "type": "scoring.run.completed", "data": {}}
{"op": "resync", "topic": "ranking"}
```

Die Nachrichten sind eigene Modelle des Protokolls (P4.5) mit camelCase-Feldnamen. Die
Event-Payloads aus `va-contracts` bleiben snake_case und werden dort abgebildet
([events.md](events.md)).

## Synchronisation des Frontends

Grundprinzip: **REST liefert den Zustand, WebSocket meldet Änderungen.**

- **Lücken erkennen:** `seq` ist die Sequenznummer aus JetStream. Nach einem
  Verbindungsabbruch meldet der Client mit `resumeFrom`, was er zuletzt gesehen hat. Das web-api
  spielt die fehlenden Events mit einem Ordered Consumer ab dieser Sequenz nach, gefiltert auf die
  Subjects der abonnierten Topics, höchstens 500 Events. Ist die Lücke größer oder älter als der
  Stream, schickt es `resync`.
- **Mehrere Tabs und Geräte:** Änderungen gehen immer per REST rein und kommen als Event an alle
  Clients zurück, auch an den Absender. So gibt es genau einen Synchronisationsweg.
- **Konflikte:** Profil-Speichern nutzt `If-Match` auf die Basisversion. Hat ein anderer Tab
  schneller gespeichert, kommt `409` ([scoring-profile.md](scoring-profile.md)).

## Sicherheitsregeln (LAN, ohne Login)

Nur-LAN heißt nicht schutzlos: Eine fremde Webseite im Browser eines Nutzers kann Anfragen an
Adressen im Heimnetz schicken. Diese Regeln verhindern Missbrauch
([ADR-0007](../adr/0007-lan-only-ohne-login.md)):

1. Schreibende Endpunkte akzeptieren nur JSON, CORS bleibt ausgeschaltet. Fremde Seiten scheitern
   dann an der Vorabprüfung (Preflight) des Browsers. Das gilt auch für Anfragen ohne Body: Ein
   `fetch` ohne Body käme sonst ohne Vorabprüfung durch. Das Frontend schickt Befehle ohne
   Inhalt deshalb als `{}` (`va_web_api.security`, P3.4).
2. Der WebSocket-Hub prüft beim Verbindungsaufbau den `Origin`-Header, denn für WebSockets gibt
   es keinen Preflight.
3. nginx beantwortet nur bekannte Hostnamen: `server_name` plus ein Default-Server mit
   `return 444`. Das schützt vor DNS-Rebinding.
4. Die DSM-Firewall gibt Port 8080 nur für das eigene Subnetz frei.

Secrets (SMTP-Passwort, DB-Passwörter) sind nie über die API lesbar oder änderbar.

**Seit D1.2** ([ADR-0012](../adr/0012-mehrbenutzer-mit-lokalen-konten.md),
[nutzer.md](depot/nutzer.md#sicherheitsregeln)) kommen dazu:

- Jeder Endpunkt außer Health, Anmelden, Abmelden und der API-Beschreibung verlangt eine
  Sitzung. Run-Start, Profil speichern und aktivieren dürfen nur Admins. Übergang bis D1.4/D1.5:
  `WEB_API_AUTH_REQUIRED=false`.
- Jede schreibende Anfrage mit fremdem `Origin` ergibt 403, mit derselben Regel wie am WebSocket.
  Mit dem Sitzungs-Cookie reicht der Preflight allein nicht mehr gegen CSRF.
- Logs enthalten keine Passwörter, Tokens, Sitzungs-IDs oder Mail-Adressen
  (`va_platform.redaction`).

**Seit D1.3:** Der WebSocket kennt Nutzer und Sitzung jeder Verbindung. `user:<id>`-Topics
bekommt nur dieser Nutzer. Abmelden trennt alle Verbindungen der Sitzung sofort (`4401`). Jede
Verbindung prüft ihre Sitzung alle 60 s, ohne sie zu verlängern, und trennt sonst ebenfalls mit
`4401`.

## Warum WebSocket und nicht SSE

SSE (in FastAPI eingebaut seit 0.135) wäre schlanker, weil die Daten fast nur vom Server zum
Client fließen. WebSocket lohnt sich trotzdem: Jede Ansicht abonniert und kündigt Topics über
dieselbe Verbindung, und später können Befehle vom Client dazukommen. Bleibt WebSocket in der
Praxis unnötig komplex, ist SSE der dokumentierte Rückweg
([ADR-0006](../adr/0006-websocket-und-eventmanager.md)).
