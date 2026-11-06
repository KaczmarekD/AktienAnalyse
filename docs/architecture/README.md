# Zielarchitektur Value-Analyzer

> **Status:** Beschlossen am 30.09.2026, umgesetzt in den Phasen 0 bis 5 (bis 04.11.2026), siehe
> [Roadmap](roadmap.md). Abweichung: NATS über einen eigenen Adapter mit nats-py statt
> FastStream (Nachtrag in [ADR-0002](../adr/0002-nats-jetstream-und-faststream.md)). Betrieb:
> [betrieb-synology.md](betrieb-synology.md).
> Im Code erledigt sind:
> - das Universum aus iShares/Deka (`ca85d93`, `c14fa32`)
> - Phase 0, das Fundament: Golden-Master, CI, uv, Python 3.14, Images aus der CI (P0.1–P0.8)
> - Phase 1, der modulare Monolith mit den späteren Service-Grenzen (P1.1–P1.9)
> - Phase 2, die Postgres-Persistenz (`261dc8f`)
> - Track F1, die Stichtagsdaten aus ADR-0010 (F1.1–F1.6)
>
> Deployment und Altdaten-Import auf der NAS stehen noch aus. Es bleibt ein Container mit
> einem Wochen-Batch: `src/` startet die Kette, die Module unter `packages/` und `services/`
> arbeiten über einen Event-Bus im Prozess. [CLAUDE.md](../../CLAUDE.md) beschreibt diesen
> Ist-Stand. Für neue Arbeit gilt die hier beschriebene Richtung. Bei Widersprüchen haben die
> [ADRs](../adr/README.md) Vorrang.

## Kurzfassung

- **Ziel:** ereignisgetriebene Microservices. Drei Fach-Services (`market-data`, `scoring`,
  `notification`) und `web-api` als Backend for Frontend (REST, WebSocket, Eventmanager).
- **Infrastruktur:** NATS JetStream als Event-Bus (eigener Adapter mit nats-py), PostgreSQL 18 mit einem
  Schema pro Service, Angular 22 im eigenen nginx-Container.
- **Weg:** kein Big Bang. Zuerst entsteht ein modularer Monolith mit genau den späteren
  Service-Grenzen, danach werden die Services schrittweise herausgelöst. Die Samstags-Mail
  läuft in jeder Phase weiter.
- **Umgebung:** nur im LAN. Synology mit Intel Celeron J4125 (kein AVX2, DSM-Kernel 4.4) und
  18 GB RAM.

## Warum Microservices?

Für einen Wochen-Batch über 90 Werte (DAX 40 + MDAX 50) bringen Microservices keine
Skalierungsvorteile. Der Nutzen liegt woanders:

1. Die unzuverlässige Datenquelle (yfinance) ist isoliert. Ein Provider-Wechsel betrifft nur
   `market-data`.
2. Teile lassen sich unabhängig deployen und neu starten.
3. Die Grenzen sind klar und werden technisch erzwungen.
4. UI, Echtzeit-Updates und neue Kanäle lassen sich sauber ergänzen.

Deshalb ist der Schnitt bewusst grob: drei Fach-Services plus `web-api`, nicht zehn.
Begründung und verworfene Alternativen stehen in
[ADR-0001](../adr/0001-microservices-ueber-modularen-monolithen.md).

## Zielbild

```
Browser (LAN) ── http://<nas>:8080 ──► frontend (nginx · Angular-Build)
                                         │ /api/* · /ws  (internes Docker-Netz)
┌────────────────────────────────────────▼───────────────────┐
│ web-api  (FastAPI · BFF · kein Port im LAN)                │
│ REST /api/v1 · WebSocket /ws · Profil-API + Vorschau       │
│ EventManager → Projektionen (Read-Models) → WS-Hub         │
│ Run-Verwaltung + Scheduler                                 │
└───────┬─────────────────────────────────────────────▲──────┘
        │ Commands (Outbox)                    Events │ (durable Consumer)
        ▼                                             │
═══════════════ NATS JetStream · Stream VA_EVENTS ════════════════
         ▲▼                     ▲▼                     ▲▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ market-data      │   │ scoring          │   │ notification     │
│ Universum        │   │ Ranking          │   │ HTML/CSV         │
│ Yahoo · FX       │   │ Profil-Versionen │   │ SMTP             │
│ Kennzahlen       │   │ Vorschau (RPC)   │   │ Healthcheck      │
└──────────────────┘   └──────────────────┘   └──────────────────┘
          ▼                      ▼                      ▼
═════════ PostgreSQL 18 · Schemas + DB-Rollen je Service ═════════
    market_data.* · scoring.* · reporting.* · batch.* · web.*
```

Nur der `frontend`-Container hat einen Port im LAN. `web-api`, Postgres und NATS hängen
ausschließlich im internen Docker-Netz.

## Services

| Service | Aufgabe | reagiert auf | sendet |
|---|---|---|---|
| `market-data` | Universum laden, Fundamentaldaten und Wechselkurse von Yahoo holen, Kennzahlen berechnen. Einziger Service mit Zugriff auf externe Datenquellen. | `screening.run.requested` | `marketdata.fetch.progressed` (flüchtig), `marketdata.snapshot.completed` |
| `scoring` | Scoring-Profile (Versionen), Perzentil-Ranking, Value-Trap-Flag, Live-Vorschau per Request/Reply | `marketdata.snapshot.completed` | `scoring.run.completed`, `scoring.profile.saved`, `scoring.profile.activated` |
| `notification` | HTML/CSV-Report, Mail, Fehlermail, Healthchecks-Ping | `scoring.run.completed`, `screening.run.failed` | `notification.report.sent` |
| `web-api` | REST, WebSocket, Eventmanager, Read-Models, Run-Verwaltung, Scheduler, Watchdog | alle Events | `screening.run.requested`, `screening.run.failed` (Watchdog) |
| `frontend` | nginx: liefert den Angular-Build aus und leitet `/api` und `/ws` intern an `web-api` weiter | – | – |

Jedes Postgres-Schema gehört genau einem Service: `market_data` → `market-data`, `scoring` →
`scoring`, `reporting` → `notification`, `batch` und `web` → `web-api`
([datenhaltung.md](datenhaltung.md)).

Bewusst **kein eigener Service** sind das Universum (Teil von `market-data`), der Scheduler
(Modul im `web-api`) und ein API-Gateway (nginx im `frontend`-Container plus BFF genügen).

## Technologie-Stack

Versionen verifiziert am 29. und 30.09.2026, Quellen in den
[Recherche-Notizen](../research/2026-09-zielarchitektur.md).

| Bereich | Wahl | Warum |
|---|---|---|
| Python | 3.14 | Wheels für pandas und NumPy verfügbar. Python 3.15 erscheint am 01.10.2026, Umstieg erst, wenn die Wheels verfügbar sind. |
| Packaging | uv-Workspace (ersetzt pip-tools) | Ein Lockfile für alle Pakete, `uv sync --package` für schlanke Images ([ADR-0004](../adr/0004-uv-workspace-monorepo.md)) |
| Web | FastAPI 0.14x | WebSockets, SSE (ab 0.135) und OpenTelemetry (0.142) eingebaut |
| Contracts und Config | Pydantic 2.13 + pydantic-settings | Events, API-DTOs, Settings und Validierungsregeln aus einem Modell-System |
| Messaging | NATS JetStream 2.15 mit nats-py (geplant war FastStream 0.7) | Persistenz, Replay, Request/Reply, Deduplizierung, geringer Ressourcenbedarf ([ADR-0002](../adr/0002-nats-jetstream-und-faststream.md)) |
| Datenbank | PostgreSQL 18 (19 erscheint voraussichtlich Ende Oktober 2026) | `uuidv7()` eingebaut, ein Schema und eine Rolle je Service ([ADR-0003](../adr/0003-postgresql-schema-pro-service.md)) |
| ORM und Migrationen | SQLAlchemy 2.1 mit psycopg 3 + Alembic | Heute synchron (Batch, Phase 2). Einzelne Services stellen erst bei Bedarf auf die async-Engine um, dafür braucht es das Extra `sqlalchemy[asyncio]` ([datenhaltung.md](datenhaltung.md)). Kein SQLModel, damit Datenbank-Modelle und API-DTOs getrennt bleiben. |
| Datenanalyse | pandas 3, NumPy 2 | pandas steht in `market-data`, `scoring`, `notification` und `va-platform` (`serialization`), NumPy ebenso außer in `notification`. `va-contracts` bleibt ohne (import-linter). pyarrow bleibt nur für den Altdaten-Import (`src/db/import_legacy.py` liest Parquet). |
| Frontend | Angular 22 | zoneless und OnPush als Standard, Signal Forms und Resource-API stabil, Tests mit Vitest ([ADR-0005](../adr/0005-angular-frontend-eigener-container.md)) |
| State | NgRx SignalStore + Events-Plugin (NgRx ≥ 21) | Server-Events werden direkt zu Store-Events |
| API-Client | @hey-api/openapi-ts mit Angular- und Zod-v4-Plugin | typisierter Client und Validierungsschemas aus der OpenAPI-Beschreibung |
| Auslieferung | nginx (`nginxinc/nginx-unprivileged`, alpine) | eigener Container und einziger Einstiegspunkt |
| Grenzen | import-linter in der CI | Services importieren einander nicht, Fachlogik importiert keine Adapter |
| Beobachtbarkeit | structlog (JSON) + OpenTelemetry | Korrelation per run_id und Trace-ID über alle Services |

## Was ausdrücklich draußen bleibt

- Backtesting und Renditeberechnung: Score-Historie ja, Performance-Tracking nein.
- Echtzeit- oder Intraday-Kurse: Der WebSocket synchronisiert nur die UI.
- Sektor-relatives Ranking: zu wenige Werte pro Sektor.
- Ein separates Dependency-Injection-Framework: `Depends` von FastAPI und die Composition
  Roots reichen.

## Dokumente

| Dokument | Inhalt |
|---|---|
| [code-struktur.md](code-struktur.md) | Ist-Analyse nach Phase 1, Monorepo-Layout, Ports & Adapters, wohin die Module des alten Batches gewandert sind |
| [events.md](events.md) | Ablauf eines Runs, Event-Katalog, Envelope, Outbox/Inbox, Streams und Consumer |
| [web-api-realtime.md](web-api-realtime.md) | web-api-Module, REST-API, Eventmanager, WebSocket-Hub und -Protokoll, Sicherheitsregeln |
| [datenhaltung.md](datenhaltung.md) | Postgres-Schemas und Tabellen, Snapshots als Historie, Backup |
| [scoring-profile.md](scoring-profile.md) | Scoring im UI: Versionen, Live-Vorschau, Validierung |
| [frontend.md](frontend.md) | Angular-Stack, Realtime im Client, nginx-Container, Schnittstellenregeln |
| [betrieb-synology.md](betrieb-synology.md) | Regeln für den J4125, Compose, Build und Deployment, Backup, Monitoring |
| [umgebungen.md](umgebungen.md) | Lokaler Stack (Mailpit, pgweb, Läufe auf Knopfdruck) und NAS: was wo läuft |
| [regressionstest.md](regressionstest.md) | Alt gegen Neu auf der NAS, Replay-Regression über gespeicherte Wochen |
| [depot/](depot/README.md) | Spezifikation (ADRs angenommen am 06.11.2026, Umsetzung offen): mehrere Nutzer, Depots mit Aktien, ETFs und Anleihen, Analyse, Hinweise, News, Berichte, nur lesende Bankanbindung (DKB) |
| [roadmap.md](roadmap.md) | Phasen 0–5, Track F (Fundamentaldaten), Track U (Umgebungen), Track G (Gestaltung des UI) und Track D (Depots) mit Arbeitspaketen zum Abhaken und Abschlusskriterien |
| [ui-neugestaltung.md](ui-neugestaltung.md) | Spec für die Neugestaltung des UI: Leitlinien, visuelle Sprache, Tooltips und Begriffe, alle Ansichten, Bausteine, Tests, Pakete G0–G8 |
| [implementierungsplan.md](implementierungsplan.md) | Arbeitsweise Test → Implementierung → Grün → Review und alle Arbeitspakete im Detail |
| [ADRs](../adr/README.md) | Architekturentscheidungen ADR-0001 bis ADR-0014 (ADR-0011 vorgeschlagen, ADR-0007 ersetzt durch ADR-0012) |
| [Recherche](../research/) | Notizen zur Zielarchitektur, zu DAX/MDAX-Datenquellen und zur langfristigen Fundamentalanalyse |
