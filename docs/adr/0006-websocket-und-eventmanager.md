# ADR-0006: WebSocket und Eventmanager im web-api für die Frontend-Synchronisation

- **Status:** akzeptiert
- **Datum:** 2026-09-30

## Kontext

Das Frontend soll ohne Neuladen aktuell bleiben. Beispiele:

- Fortschritt eines laufenden Runs,
- neue Rankings,
- aktivierte Scoring-Profile,
- Änderungen aus einem anderen Tab oder Gerät.

Die Events entstehen in den Fach-Services und laufen über NATS
([ADR-0002](0002-nats-jetstream-und-faststream.md)).

## Entscheidung

- **Eventmanager im web-api:** Er konsumiert alle dauerhaften Events. Zuerst aktualisiert er die
  Read-Models in einer Transaktion zusammen mit der Inbox, und **erst nach dem Commit**
  benachrichtigt er den WebSocket-Hub.
- **WebSocket-Endpunkt `/ws`** mit dem Subprotokoll `va.v1`. Clients abonnieren Topics (`runs`,
  `ranking`, `profiles`, `instrument:<SYMBOL>`).
- **Grundprinzip: REST liefert den Zustand, WebSocket meldet Änderungen.** Jede Änderung geht per
  REST rein und kommt als Event an alle Clients zurück, auch an den Absender.
- **Lücken schließen:** Dauerhafte Events tragen die JetStream-Sequenznummer `seq`. Beim
  Wiederverbinden spielt das web-api ab `resumeFrom` nach, bei zu großer Lücke schickt es `resync`.
- **Rückstau begrenzen:** Jeder Client hat eine begrenzte Warteschlange. Läuft sie voll, wird der
  Client getrennt und synchronisiert sich neu.

Details: [web-api-realtime.md](../architecture/web-api-realtime.md).

## Konsequenzen

- ✅ Alle Tabs und Geräte sehen denselben Stand, und es gibt nur einen Synchronisationsweg.
- ✅ Ein Client, der auf ein Event hin per REST nachlädt, sieht garantiert den neuen Stand.
- ⚠️ Protokoll und Wiederverbindungslogik müssen auf beiden Seiten gepflegt werden.
- ⚠️ Bei mehreren Instanzen des web-api müssten die Projektionen (einmal) und das Verteilen an
  Clients (jede Instanz) getrennt abonniert werden. Bei einer Instanz auf der NAS ist das kein Thema.

## Verworfene Alternativen

- **Server-Sent Events (in FastAPI eingebaut seit 0.135):** schlanker und mit eingebauter
  Wiederverbindung. Die Daten fließen aber nur vom Server zum Client, ein Wechsel der Topics bräuchte
  eine neue Verbindung, und Befehle vom Client wären später nicht möglich. SSE bleibt der
  dokumentierte Rückweg, falls WebSocket in der Praxis unnötig komplex wird.
- **Polling:** einfach, aber träge und ohne echten Live-Fortschritt.
