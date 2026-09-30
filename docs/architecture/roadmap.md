# Roadmap

> Stand: 30.09.2026. Erledigtes abhaken und mit Commit oder Branch belegen. Die Samstags-Mail muss
> nach jeder Phase unverändert funktionieren.

## Überblick

| Phase | Ziel | Status |
|---|---|---|
| – | Universum aus iShares/Deka statt Wikipedia | ✅ erledigt (`ca85d93`, `c14fa32`) |
| 0 | Fundament: uv, Python 3.14, aktuelle Dependencies, Images aus CI | offen |
| 1 | Modularer Monolith mit den späteren Service-Grenzen | offen |
| 2 | Postgres als Historien-Schicht | 🚧 im Code erledigt (`261dc8f`), Deployment auf der NAS offen |
| 2b | Scoring-Profile in der DB | offen, nach Phase 2 |
| 3 | web-api + Angular (UI im LAN, Profil-Editor) | offen |
| 4 | Events und Echtzeit (NATS, Eventmanager, WebSocket) | offen |
| 5 | Aufteilen in Services (Zielarchitektur) | offen |

**Reihenfolge:** Phase 2 wurde vorgezogen, weil jede Woche ohne Stichtagsdaten verloren ist.
Phase 0 und 1 bauen auf ihr auf. Ab Phase 3 ist die Reihenfolge verbindlich.

## Sofort

- [ ] `RETENTION_DAYS=0` auf der NAS setzen, bis die Postgres-Persistenz inklusive
      Altdaten-Import läuft. Sonst löscht das alte Housekeeping die Dateien, die importiert werden
      sollen.

## Phase 0 – Fundament

- [ ] uv-Workspace-Root anlegen, pip-tools-Lockfiles durch `uv.lock` ersetzen
      ([ADR-0004](../adr/0004-uv-workspace-monorepo.md))
- [ ] Python 3.14 in Dockerfile, CI, `requires-python`, Ruff und Pyright
- [ ] pandas 3.x und yfinance 1.x; die komplette Test-Suite grün (lokal lief `score()` bereits mit
      pandas 3.0.0, die Suite selbst noch nicht)
- [ ] CI baut die Images für `linux/amd64` und schiebt sie nach GHCR
      ([ADR-0008](../adr/0008-zielhardware-j4125.md))
- [ ] NAS: `docker compose pull` statt Build auf der NAS, Import-Test nach Upgrades
- [ ] CI mit Pfad-Filtern vorbereiten (Python, Frontend, Images)

**Fertig, wenn:** dieselbe Mail wie vorher kommt, die Images aus der CI stammen und die Tests auf
Python 3.14 grün sind.

## Phase 1 – Modularer Monolith

- [ ] Pakete `va-contracts` und `va-platform` anlegen
- [ ] `src/` in `va_market_data`, `va_scoring` und `va_notification` aufteilen, jeweils mit Ports &
      Adapters ([code-struktur.md](code-struktur.md))
- [ ] `data_fetcher.fetch_one` aufteilen: Yahoo-Adapter (`RawFinancials`) und `domain/metrics.py`
- [ ] Universum-Kette (iShares → Deka → CSV) als Adapter hinter dem Port `UniverseSource`
- [ ] Event-Contracts v1 (Pydantic) und ein Bus im Prozess mit derselben Schnittstelle wie später
      NATS ([events.md](events.md))
- [ ] `main.py` wird zur Composition Root, die die drei Module über den Bus verbindet
- [ ] import-linter-Regeln in der CI
- [ ] Tests umziehen, Kennzahlen-Tests mit gespeicherten JSON-Rohdaten

**Fertig, wenn:** es weiterhin ein Container ist, die Mail identisch bleibt und die CI die Grenzen
erzwingt.

## Phase 2 – Postgres (Code fertig, Deployment offen)

Umgesetzt in `261dc8f`. Details in [datenhaltung.md](datenhaltung.md).

- [x] Schemas `batch`, `market_data`, `scoring` und `reporting` mit Alembic (`261dc8f`)
- [x] Rollen `va_owner`, `va_app` und `va_read`, Trigger gegen Löschen und Überschreiben (`261dc8f`)
- [x] Rohdaten (`raw_info`) und Statement-Werte im Long-Format (`statement_value`) (`261dc8f`)
- [x] Import der alten Parquet- und CSV-Dateien, Housekeeping entfernt (`261dc8f`)
- [ ] Nach GitHub pushen, Deployment auf der NAS, Altdaten-Import auf der NAS ausführen
- [ ] Danach `RETENTION_DAYS` aus der `.env` entfernen
- [ ] Backup per `pg_dump` einrichten ([betrieb-synology.md](betrieb-synology.md))

**Fertig, wenn:** jeder Lauf vollständig in der Datenbank steht und die Altdaten importiert sind.

## Phase 2b – Scoring-Profile

- [ ] Tabellen `scoring.profile`, `profile_version`, `profile_activation`
      ([scoring-profile.md](scoring-profile.md))
- [ ] Profil „Standard“ einmalig aus den ENV-Werten anlegen
- [ ] `scoring_run` speichert die verwendete Profil-Version, die Mail nennt sie im Footer

**Fertig, wenn:** jeder Bewertungslauf seine Profil-Version kennt.

## Phase 3 – web-api und Angular

- [ ] web-api (FastAPI) mit REST v1 für Runs, Ranking, Titel, Profile und Vorschau
      ([web-api-realtime.md](web-api-realtime.md))
- [ ] Lesen über die Rolle `va_read` direkt aus den Batch-Schemas. Projektionen kommen erst in
      Phase 4.
- [ ] Profil-Vorschau zunächst im selben Prozess über einen Port, in Phase 4 über NATS
- [ ] UI-Bibliothek festlegen (Angular Material oder PrimeNG)
- [ ] Angular-22-App: Ranking, Titel-Detail, Run-Historie, Profil-Editor mit Vorschau
      ([frontend.md](frontend.md))
- [ ] Generierter Client (hey-api) mit Zod; `oasdiff breaking` in der CI
- [ ] `frontend`-Container (nginx) als einziger Port, Sicherheitsregeln für den LAN-Betrieb umsetzen

**Fertig, wenn:** das UI im LAN nutzbar ist und die Profile editierbar sind.

## Phase 4 – Events und Echtzeit

- [ ] NATS JetStream und FastStream, Stream `VA_EVENTS`, ein Consumer pro Modul
      ([events.md](events.md))
- [ ] Outbox und Inbox in `va-platform`, als bewusste Ausnahmen im Schreibschutz
- [ ] Eventmanager, WebSocket-Hub und Protokoll `va.v1`; `RealtimeService` im Frontend
- [ ] Projektionen im Schema `web`
- [ ] Run-Start aus dem UI, Live-Fortschritt, Abgleich zwischen Tabs, Watchdog
- [ ] Vorschau und Profil-Befehle per Request/Reply

**Fertig, wenn:** alles über Events läuft und das UI live aktualisiert.

## Phase 5 – Aufteilen in Services

- [ ] eigene Images und Container je Service ([betrieb-synology.md](betrieb-synology.md))
- [ ] eine DB-Rolle pro Service, jeweils nur auf das eigene Schema
- [ ] Scheduler im web-api (Cron-Termin als eindeutiger Schlüssel), Cron im Container entfällt
- [ ] OpenTelemetry-Tracing (FastAPI eingebaut, FastStream-Middleware), optional Grafana-Stack
- [ ] CLAUDE.md auf die Zielarchitektur umschreiben (dann gilt: Ist = Ziel)

**Fertig, wenn:** die Zielarchitektur aus [README.md](README.md) läuft.

## Danach (Ideen, nicht beschlossen)

- Watchlists und Diagramme zum Score-Verlauf
- Mehrere Mail-Empfänger. Dann auch einen einfachen Login einführen
  ([ADR-0007](../adr/0007-lan-only-ohne-login.md)).
- Weitere Kanäle in `notification`, z. B. Telegram
- Wechsel des Datenanbieters (FMP/EODHD) als weiterer Adapter in `market-data`
