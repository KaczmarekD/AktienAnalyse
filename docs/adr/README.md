# Architecture Decision Records

Jede Grundsatzentscheidung steht hier mit Kontext, Begründung, Konsequenzen und verworfenen
Alternativen. Ein ADR wird nicht nachträglich umgeschrieben. Ändert sich eine Entscheidung, ersetzt
ein neues ADR das alte, und das alte bekommt den Status „ersetzt durch ADR-XXXX“.

| Nr. | Entscheidung | Status | Datum |
|---|---|---|---|
| [0001](0001-microservices-ueber-modularen-monolithen.md) | Microservices, erreicht über einen modularen Monolithen | akzeptiert | 2026-09-30 |
| [0002](0002-nats-jetstream-und-faststream.md) | NATS JetStream mit FastStream als Event-Bus | akzeptiert | 2026-09-30 |
| [0003](0003-postgresql-schema-pro-service.md) | PostgreSQL mit einem Schema pro Fachbereich, nichts wird gelöscht | akzeptiert | 2026-09-30 |
| [0004](0004-uv-workspace-monorepo.md) | Monorepo mit uv-Workspace | akzeptiert | 2026-09-30 |
| [0005](0005-angular-frontend-eigener-container.md) | Angular-Frontend im eigenen nginx-Container als einziger Einstiegspunkt | akzeptiert | 2026-09-30 |
| [0006](0006-websocket-und-eventmanager.md) | WebSocket und Eventmanager im web-api für die Frontend-Synchronisation | akzeptiert | 2026-09-30 |
| [0007](0007-lan-only-ohne-login.md) | Nur im LAN erreichbar, zum Start ohne Login | akzeptiert | 2026-09-30 |
| [0008](0008-zielhardware-j4125.md) | Zielhardware J4125: nur amd64, Build in CI, kein AVX2 | akzeptiert | 2026-09-30 |
| [0009](0009-scoring-profile-in-der-db.md) | Scoring-Profile versioniert in der DB, im UI editierbar | akzeptiert | 2026-09-30 |
| [0010](0010-stichtagsdaten-konsens-quartale-kurse.md) | Zusätzliche Stichtagsdaten sichern: Konsens, Quartale, Aktienanzahl, Kurse | akzeptiert | 2026-09-30 |
| [0011](0011-fundamentale-anker-und-belegte-faktoren.md) | Fundamentale Anker und belegte Faktoren im Scoring | vorgeschlagen | 2026-09-30 |

## Vorlage

```markdown
# ADR-XXXX: Titel als Entscheidung formuliert

- **Status:** vorgeschlagen | akzeptiert | ersetzt durch ADR-YYYY
- **Datum:** JJJJ-MM-TT

## Kontext
Welche Situation und welche Kräfte führen zu der Entscheidung?

## Entscheidung
Was wird gemacht? Aktiv und konkret formuliert.

## Konsequenzen
Was wird leichter, was wird schwerer, was muss beachtet werden?

## Verworfene Alternativen
Welche Optionen gab es, und warum wurden sie nicht gewählt?
```
