# Frontend

> **Status:** Plan (30.09.2026). Umsetzung ab Phase 3, siehe [Roadmap](roadmap.md). Entscheidung:
> [ADR-0005](../adr/0005-angular-frontend-eigener-container.md).

## Stack

| Baustein | Wahl | Hinweis |
|---|---|---|
| Framework | Angular 22 | zoneless und OnPush als Standard, Signal Forms und Resource-API stabil, Tests mit Vitest |
| Build | Node 24 LTS, nur in CI | Angular 22 setzt Node ≥ 22 und TypeScript 6 voraus. Node läuft nie auf der NAS ([ADR-0008](../adr/0008-zielhardware-j4125.md)). |
| State | NgRx SignalStore + Events-Plugin (NgRx ≥ 21) | Server-Events werden zu Store-Events |
| API-Client | @hey-api/openapi-ts: Angular-Plugin (`httpResource`) + Zod-v4-Plugin | aus der OpenAPI-Beschreibung des web-api generiert |
| WebSocket-Typen | aus den Pydantic-Modellen in `va-contracts` (JSON-Schema → TypeScript) | eine Quelle für Python und TypeScript |
| UI-Bibliothek | Angular Material (entschieden am 31.10.2026) | vom Angular-Team, zieht mit jeder Angular-Version mit; die Tabelle mit Sortierung und Filtern reicht für 90 Titel, ein Grid wie AG Grid ist nicht nötig |

## Ansichten

Seit P3.7 (U4) gibt es Ranking, Runs und Titel-Detail ohne Echtzeit: Sie laden beim Öffnen. Live-Updates,
Fortschritt und „Run starten“ kommen mit Phase 4, der Profil-Editor nach Phase 2b.

| Ansicht | Inhalt |
|---|---|
| Ranking | Top/Flop, Filter nach Index und Sektor, Value-Trap-Markierungen, Live-Update bei neuem Ranking |
| Runs | Historie, Live-Fortschritt, Run starten (Optionen: neu laden, Dry-Run, ohne Mail), gerenderte Mail ansehen |
| Titel-Detail | Kennzahlen, Score-Verlauf, Rohdaten-Hinweise (z. B. Restatements) |
| Scoring-Profile | Editor mit Live-Vorschau, Versionen, Aktivieren ([scoring-profile.md](scoring-profile.md)) |

## Datenzugriff und Echtzeit

- **REST:** Die generierten `httpResource`-Funktionen hängen an Signals. Ändern sich Filter oder
  IDs, lädt Angular automatisch nach.
- **RealtimeService:**
  - kapselt `rxjs/webSocket` mit dem Subprotokoll `va.v1`,
  - baut Verbindungen mit wachsender Wartezeit und Zufallsanteil neu auf,
  - stellt den Verbindungsstatus als Signal bereit (Anzeige „offline“ im UI),
  - merkt sich die letzte `seq` und schickt sie beim Wiederverbinden als `resumeFrom`,
  - gibt Servernachrichten als NgRx-Events weiter (`eventGroup({ source: 'Server', … })`).
- **Stores** reagieren mit `withReducer` (z. B. Fortschritt übernehmen) oder laden über
  `withEventHandlers` nach (z. B. bei `resync` oder neuem Ranking).
- Protokoll und Synchronisationsregeln: [web-api-realtime.md](web-api-realtime.md).

## Container

Seit P3.6 gibt es ihn wirklich: [frontend/Dockerfile](../../frontend/Dockerfile) und
[frontend/nginx/default.conf.template](../../frontend/nginx/default.conf.template). Die Skizzen
unten zeigen die Idee, die Dateien den Stand.

- **Hostnamen:** Erlaubt sind die Namen aus `UI_SERVER_NAMES`. nginx setzt sie beim Start ein,
  alle anderen Hostnamen bekommen `return 444`.
- **web-api:** `/api/` geht mit `^~` an das web-api. Es wird erst bei der Anfrage aufgelöst
  (Docker-DNS), nginx startet also auch, wenn das web-api noch fehlt.
- **Sicherheits-Header:** CSP mit `script-src 'self'`, `X-Frame-Options DENY`, `nosniff`,
  `Referrer-Policy same-origin`. Kein Abschnitt setzt ein eigenes `add_header`, sonst gingen
  diese Header dort verloren.
- **Kein Inline-Skript im Build (seit U5.3):** Angular legt das Stylesheet beim Inlining der
  kritischen CSS mit `media="print"` an und schaltet es per Inline-Skript um. Die CSP blockiert
  das Skript, die globalen Styles griffen dann nie. Der Browser-Test hat das gefunden. Deshalb
  steht in `angular.json` `inlineCritical: false`, und `tests/test_nginx_conf.py` prüft das.
- **Cache:** `index.html` wird nie gecacht, Dateien mit Hash im Namen ein Jahr.
- **Swagger:** `/api/docs` geht hinter nginx nicht, weil Swagger sein Skript von einem CDN
  lädt. Lokal bleibt es am web-api auf Port 8000.

Der `frontend`-Container ist der **einzige Einstiegspunkt** im LAN. Er liefert den Angular-Build
aus und leitet `/api/*` und `/ws` intern an das web-api weiter. Für den Browser ist alles eine
einzige Adresse. Deshalb braucht es kein CORS und keine API-URL im Build (nur relative Pfade), und
dasselbe Image läuft lokal wie auf der NAS.

```dockerfile
# frontend/Dockerfile – Skizze (Build nur in CI)
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npx ng build --configuration production

FROM nginxinc/nginx-unprivileged:alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist/va-frontend/browser /usr/share/nginx/html
```

```nginx
# frontend/nginx/default.conf – Skizze
server {
    listen 8080 default_server;
    return 444;                                   # unbekannter Host (DNS-Rebinding): Verbindung zu
}

server {
    listen 8080;
    server_name nas nas.local 192.168.178.10;     # an das eigene Netz anpassen
    root /usr/share/nginx/html;
    server_tokens off;

    location / {
        try_files $uri $uri/ /index.html;         # Routing der Single-Page-App
    }
    location = /index.html {
        add_header Cache-Control "no-cache";
    }
    location ~* \.(?:js|css|woff2?)$ {
        add_header Cache-Control "public, max-age=31536000, immutable";   # Dateinamen mit Hash
    }
    location /api/ {
        proxy_pass http://web-api:8000;
    }
    location /ws {
        proxy_pass http://web-api:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 1h;                    # deutlich laenger als das Ping-Intervall
    }
}
```

Offen für die Umsetzung: eine Content-Security-Policy. `connect-src` muss das WebSocket-Ziel
enthalten.

## Regeln für getrennte Deployments

Frontend und Backend werden unabhängig ausgerollt. Deshalb braucht die Schnittstelle Disziplin:

- Die REST-API bleibt unter `/api/v1` versioniert, Änderungen sind additiv.
- Die CI vergleicht die OpenAPI-Beschreibung mit dem letzten Release (`oasdiff breaking`) und
  bricht bei inkompatiblen Änderungen ab.
- Das WebSocket-Protokoll ist über das Subprotokoll `va.v1` versioniert.
- Reihenfolge beim Update: erst das Backend (abwärtskompatibel), dann das Frontend.

## Lokale Entwicklung

`ng serve` mit einer Proxy-Konfiguration, die `/api` und `/ws` an das lokal laufende web-api
weiterleitet. So ist auch in der Entwicklung alles eine Adresse, genau wie hinter nginx.

Seit P3.5 (Code unter `frontend/`, Befehle in [frontend/README.md](../../frontend/README.md)):

- `make ui-install`, dann `make api` oder `make local-up` für das web-api und `make ui` für das
  UI unter <http://localhost:4200>. `frontend/proxy.conf.json` leitet `/api` an
  `127.0.0.1:8000`.
- Der API-Client unter `frontend/src/app/api/` entsteht mit hey-api aus dem OpenAPI-Snapshot
  `tests/golden/openapi/v1.json` (`make ui-api`). Es gibt `httpResource`-Funktionen wie
  `latestRankingResource` und Zod-4-Schemas. Er wird committet und nie von Hand geändert. Die
  CI erzeugt ihn neu und bricht ab, wenn er nicht zum Snapshot passt.
- Die Operation-IDs der API sind die Funktionsnamen des web-api, daraus entstehen die Namen im
  Client.
- Profil-Editor (seit P3.7, `/profiles`): Signal Forms (`form`, `[formField]`), geprüft mit
  `validateStandardSchema` und dem erzeugten `zProfileParamsV1Input`, Meldungen auf Deutsch. Die
  Live-Vorschau wartet 300 ms (`PREVIEW_DEBOUNCE_MS`). Speichern schickt `If-Match`, eine 409
  bietet „Neu laden“ an.
- Keine Ressourcen aus dem Internet: Systemschrift statt Roboto von Google Fonts, keine Icon-Fonts
  von außen. Das UI läuft im LAN, und jeder Aufruf ginge sonst an Google.
