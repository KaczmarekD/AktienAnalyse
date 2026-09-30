# web-api, Eventmanager und WebSocket

> **Status:** Plan (30.09.2026). REST ab Phase 3, Eventmanager und WebSocket ab Phase 4, siehe
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

Der FastStream-Broker wird im Lifespan von FastAPI gestartet und gestoppt. Die frühere
eingebaute FastAPI-Integration von FastStream ist veraltet und wurde in das Paket
`faststream_fastapi` ausgelagert. Wir brauchen sie nicht.

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

Schreibende Endpunkte akzeptieren ausschließlich JSON (siehe Sicherheitsregeln).

**Übergang in Phase 3:** Bevor es Events gibt, liest das web-api über die Rolle `va_read` (seit
Phase 2 vorhanden) direkt aus den Schemas des Batches. Die Profil-Vorschau ruft den
Scoring-Code über einen Port im selben Prozess auf. Ab Phase 4 werden daraus Projektionen und
Request/Reply, ohne dass sich die REST-API ändert.

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
- Beim Verbindungsaufbau prüft der Hub den `Origin`-Header gegen `WEB_ALLOWED_ORIGINS`.

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
| `error` | `code`, `message` | z. B. unbekanntes Topic |

```jsonc
// Client → Server
{"op": "subscribe", "topics": ["runs", "ranking"], "resumeFrom": 4711}
// Server → Client
{"op": "event", "topic": "runs", "type": "marketdata.fetch.progressed",
 "data": {"runId": "42", "done": 57, "total": 90}}                  // flüchtig, ohne seq
{"op": "event", "topic": "ranking", "seq": 4712, "type": "scoring.run.completed", "data": {}}
{"op": "resync", "topic": "ranking"}
```

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
   dann an der Vorabprüfung (Preflight) des Browsers.
2. Der WebSocket-Hub prüft beim Verbindungsaufbau den `Origin`-Header, denn für WebSockets gibt
   es keinen Preflight.
3. nginx beantwortet nur bekannte Hostnamen: `server_name` plus ein Default-Server mit
   `return 444`. Das schützt vor DNS-Rebinding.
4. Die DSM-Firewall gibt Port 8080 nur für das eigene Subnetz frei.

Secrets (SMTP-Passwort, DB-Passwörter) sind nie über die API lesbar oder änderbar.

## Warum WebSocket und nicht SSE

SSE (in FastAPI eingebaut seit 0.135) wäre schlanker, weil die Daten fast nur vom Server zum
Client fließen. WebSocket lohnt sich trotzdem: Jede Ansicht abonniert und kündigt Topics über
dieselbe Verbindung, und später können Befehle vom Client dazukommen. Bleibt WebSocket in der
Praxis unnötig komplex, ist SSE der dokumentierte Rückweg
([ADR-0006](../adr/0006-websocket-und-eventmanager.md)).
