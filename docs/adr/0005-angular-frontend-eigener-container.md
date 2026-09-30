# ADR-0005: Angular-Frontend im eigenen nginx-Container als einziger Einstiegspunkt

- **Status:** akzeptiert
- **Datum:** 2026-09-30

## Kontext

Ein Web-Frontend soll Rankings, Runs, Titel-Details und den Scoring-Profil-Editor zeigen. Es muss
per WebSocket live aktualisieren. Der Nutzer möchte das Frontend als eigenen Container
deployen, getrennt vom Backend.

## Entscheidung

- **Angular 22:** zoneless und OnPush als Standard, Signal Forms, Resource-API.
- **NgRx SignalStore** mit Events-Plugin für den Zustand.
- **@hey-api/openapi-ts** erzeugt den API-Client (`httpResource`) und die Zod-Schemas aus der
  OpenAPI-Beschreibung.
- **Eigener Container** auf Basis von `nginxinc/nginx-unprivileged` (alpine). Er liefert den Build
  aus und leitet `/api/*` und `/ws` intern an das web-api weiter.
- **Einziger Einstiegspunkt:** Nur dieser Container veröffentlicht einen Port im LAN. web-api,
  Postgres und NATS sind von außen nicht erreichbar.
- **Build nur in CI** (Node 24), nie auf der NAS ([ADR-0008](0008-zielhardware-j4125.md)).

Details: [frontend.md](../architecture/frontend.md).

## Konsequenzen

- ✅ Für den Browser ist alles eine einzige Adresse: kein CORS, keine API-URL im Build, dasselbe
  Image lokal und auf der NAS.
- ✅ Frontend und Backend lassen sich unabhängig ausrollen. Die Angriffsfläche im LAN beschränkt
  sich auf nginx.
- ⚠️ Getrennte Deployments brauchen Regeln für die Schnittstelle: `/api/v1`, `oasdiff breaking` in
  der CI, versioniertes WebSocket-Subprotokoll, erst Backend, dann Frontend ausrollen.
- ⚠️ Die nginx-Konfiguration muss gepflegt werden (WebSocket-Header, Hostnamen-Filter, Caching).
- Offen: welche UI-Bibliothek (Angular Material oder PrimeNG). Die Entscheidung fällt zu Beginn
  von Phase 3.

## Verworfene Alternativen

- **Auslieferung durch das web-api per `app.frontend()`** (FastAPI ab 0.138): einfacher, koppelt
  aber UI und Backend in einem Image. Der Nutzer wollte einen eigenen Container.
- **DSM-Reverse-Proxy als Router:** Die Konfiguration steckt in der DSM-Oberfläche statt im Repo
  und lässt sich schlecht versionieren.
- **Getrennte Ports mit CORS:** mehr Angriffsfläche, und die API wäre direkt im LAN erreichbar.
