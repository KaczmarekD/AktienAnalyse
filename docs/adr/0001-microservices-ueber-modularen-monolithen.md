# ADR-0001: Microservices, erreicht über einen modularen Monolithen

- **Status:** akzeptiert
- **Datum:** 2026-09-30
- **Hebt auf:** den CLAUDE.md-Ausschluss „Microservices/Message Queues. Single-Container-Batch.“

## Kontext

Der Value-Analyzer ist ein Wochen-Batch in einem Container: Universum laden, Fundamentaldaten von
Yahoo holen, cross-sektional bewerten, Mail verschicken. Er soll um ein Angular-Frontend,
PostgreSQL, Echtzeit-Synchronisation per WebSocket und einen Eventmanager erweitert werden.

Die Last ist klein: 90 Werte pro Woche, ein Nutzer, Betrieb auf einer Synology im LAN.
Skalierung ist also kein Grund für eine Aufteilung. Gründe sind:

- die unzuverlässige externe Datenquelle zu isolieren,
- Teile unabhängig deployen zu können,
- die Grenzen klar zu ziehen,
- UI und Echtzeit sauber auszubauen.

## Entscheidung

- Zielarchitektur mit drei Fach-Services und einem Backend for Frontend:
  - `market-data`: externe Datenquellen (Universum, Yahoo, FX), Kennzahlen
  - `scoring`: Ranking, Scoring-Profile, Vorschau
  - `notification`: Report, Mail, Healthcheck
  - `web-api`: REST, WebSocket, Eventmanager, Runs, Scheduler
- Der Schnitt folgt den Gründen oben: Abhängigkeit nach außen, reine Rechenlogik, Ausgabekanäle,
  UI-Backend.
- Der Weg führt über einen **modularen Monolithen**. Der Code wird zuerst im bestehenden Container
  entlang dieser Grenzen aufgeteilt (Ports & Adapters, ein Event-Bus im Prozess). Danach werden die
  Services herausgelöst. Beim Wechsel des Transports auf NATS ändern sich Handler und Contracts
  nicht.
- Die Samstags-Mail funktioniert nach jeder Phase unverändert.

Details: [Zielarchitektur](../architecture/README.md), [Roadmap](../architecture/roadmap.md).

## Konsequenzen

- ✅ Ein Wechsel des Datenanbieters betrifft nur `market-data`. Scoring ist ohne Netzwerk testbar
  und für die Live-Vorschau schnell genug.
- ✅ Die Aufteilung auf Container ist eine Deployment-Entscheidung. Derselbe Code läuft als ein
  Prozess oder als vier.
- ⚠️ Mehr Betriebsaufwand: Broker, Datenbank, sieben Container, verteilte Fehlerbilder, eventual
  consistency, versionierte Contracts.
- ⚠️ CLAUDE.md beschreibt bis zum Abschluss den Ist-Stand. Für neue Arbeit gelten die ADRs.
- Bewusst **kein** eigener Service für Universum, Scheduler oder API-Gateway.

## Verworfene Alternativen

- **Monolith bleiben:** am einfachsten. UI, Echtzeit und Batch würden aber im selben Prozess
  gekoppelt, und der Ausbau würde mit jedem Schritt schwerer.
- **Feingranulare Microservices (10+):** Overhead ohne Nutzen bei dieser Last.
- **Neu schreiben in einem Schritt:** hohes Risiko, und die Mail fiele während des Umbaus aus.
