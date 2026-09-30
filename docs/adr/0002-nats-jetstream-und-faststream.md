# ADR-0002: NATS JetStream mit FastStream als Event-Bus

- **Status:** akzeptiert
- **Datum:** 2026-09-30
- **Hebt auf:** den CLAUDE.md-Ausschluss von Message Queues

## Kontext

Die Services aus [ADR-0001](0001-microservices-ueber-modularen-monolithen.md) brauchen einen
Event-Bus. Anforderungen:

- dauerhafte Zustellung der Pipeline-Events (mindestens einmal),
- Verteilung an mehrere Empfänger (Fan-out),
- Request/Reply für die Live-Vorschau und Profil-Befehle,
- Nachspielen ab einer Sequenznummer, damit WebSocket-Clients nach einem Verbindungsabbruch
  aufholen können,
- Deduplizierung,
- geringer Ressourcenbedarf auf einer NAS,
- gute Integration mit Python, Pydantic und FastAPI.

## Entscheidung

- **NATS Server 2.12+ mit JetStream** als Broker, ein Container.
- **FastStream 0.7** als Python-Framework: Handler mit Pydantic-Typen, automatische AsyncAPI-Doku,
  In-Memory-Test-Broker.
- Subject-Konvention:
  - `va.…` für dauerhafte Events (Stream `VA_EVENTS`),
  - `live.va.…` für flüchtige Meldungen,
  - `rpc.va.…` für Request/Reply.
- Zuverlässigkeit über eine Outbox (Sender) und eine Inbox (Empfänger), mit `Nats-Msg-Id` gleich
  der Event-ID.
- Der Broker wird im FastAPI-Lifespan gestartet. Die frühere eingebaute FastAPI-Integration von
  FastStream ist veraltet (ausgelagert nach `faststream_fastapi`) und wird nicht genutzt.

Details: [events.md](../architecture/events.md).

## Konsequenzen

- ✅ Ein Werkzeug deckt dauerhafte Events, flüchtige Meldungen, Request/Reply und Replay ab.
- ✅ Der Ressourcenbedarf ist gering (ein Go-Binary), AVX ist nicht nötig.
- ⚠️ Ein zusätzlicher Container und JetStream-Konzepte (Streams, Consumer, Acks) wollen gelernt
  sein.
- ⚠️ FastStream ist noch vor 1.0: Neue Minor-Versionen können inkompatibel sein. Die Version wird
  gepinnt, Updates bewusst eingespielt.
- ⚠️ Lange Handler (Abruf über mehrere Minuten) müssen In-Progress-Acks senden.

## Verworfene Alternativen

- **Redis Streams:** ähnlich leicht. Request/Reply müsste aber nachgebaut werden, und die
  Persistenz hängt von der AOF-Konfiguration ab.
- **RabbitMQ:** ausgereift, aber schwerer (Erlang-VM), und Replay gibt es nur über das
  Streams-Plugin.
- **Kafka:** für ein paar hundert Events pro Woche überdimensioniert.
- **Nur Postgres (LISTEN/NOTIFY, Queue-Tabellen):** keine zusätzliche Infrastruktur. Die Payload
  von NOTIFY ist aber auf 8 KB begrenzt, es gibt kein Replay und kein sauberes Fan-out an
  WebSocket-Instanzen.
