# Roadmap

> Stand: 30.09.2026. Hier steht, *was* in welcher Phase passiert und was erledigt ist. *Wie*
> jedes Arbeitspaket umgesetzt wird (Test → Implementierung → Grün → Review), steht im
> [Implementierungsplan](implementierungsplan.md). Abgehakt wird nur hier, jeweils mit Commit.
> Die Samstags-Mail muss nach jedem Paket unverändert funktionieren.

## Überblick

| Phase | Ziel | Status |
|---|---|---|
| – | Universum aus iShares/Deka statt Wikipedia | ✅ erledigt (`ca85d93`, `c14fa32`) |
| 0 | Fundament: Golden-Master, CI, uv, Python 3.14, aktuelle Dependencies, Images aus CI | offen |
| 1 | Modularer Monolith mit den späteren Service-Grenzen | offen |
| 2 | Postgres als Historien-Schicht | 🚧 im Code erledigt und gepusht (`261dc8f`), Deployment auf der NAS offen |
| 2b | Scoring-Profile in der DB | offen |
| 3 | web-api + Angular (UI im LAN, Profil-Editor) | offen |
| 4 | Events und Echtzeit (NATS, Eventmanager, WebSocket) | offen |
| 5 | Aufteilen in Services (Zielarchitektur) | offen |

**Reihenfolge:**
- Phase 2 wurde vorgezogen, weil jede Woche ohne Stichtagsdaten verloren ist.
- Phase 0 beginnt mit P0.1: Der Golden-Master ist das Sicherungsnetz für alle späteren Umbauten.
- Ab Phase 1 ist die Reihenfolge verbindlich.

## Sofort (du, auf der NAS)

- [ ] `RETENTION_DAYS=0` setzen, bis die Postgres-Persistenz inklusive Altdaten-Import läuft.
      Sonst löscht das alte Housekeeping die Dateien, die importiert werden sollen.

## Phase 0 – Fundament

Details: [Implementierungsplan, Phase 0](implementierungsplan.md#phase-0--fundament)

- [ ] P0.1 Golden-Master für die Mail
- [ ] P0.2 CI auf Feature-Branches
- [ ] P0.3 uv-Workspace statt pip-tools ([ADR-0004](../adr/0004-uv-workspace-monorepo.md))
- [ ] P0.4 Python 3.14
- [ ] P0.5 pandas 3 und yfinance 1.x (lokal lief `score()` bereits mit pandas 3.0.0, die Suite
      selbst noch nicht)
- [ ] P0.6 Images aus der CI, geprüft für den J4125 ([ADR-0008](../adr/0008-zielhardware-j4125.md))
- [ ] NAS (du): Images aus GHCR laden statt auf der NAS zu bauen

**Fertig, wenn:** dieselbe Mail wie vorher kommt (Golden-Master grün), die Images aus der CI
stammen und die Tests auf Python 3.14 grün sind.

## Phase 1 – Modularer Monolith

Details: [Implementierungsplan, Phase 1](implementierungsplan.md#phase-1--modularer-monolith)

- [ ] P1.1 Workspace-Pakete und Grenzen
- [ ] P1.2 Contracts v1
- [ ] P1.3 Kennzahlen als reine Funktionen
- [ ] P1.4 Adapter für Yahoo und Universum hinter Ports
- [ ] P1.5 Scoring-Modul
- [ ] P1.6 Notification-Modul
- [ ] P1.7 Datenbankzugriff je Modul
- [ ] P1.8 Event-Bus im Prozess, Composition Root
- [ ] P1.9 Aufräumen

**Fertig, wenn:** es weiterhin ein Container ist, die Golden-Files unverändert sind und die CI die
Grenzen erzwingt.

## Phase 2 – Postgres (Code fertig, Deployment offen)

Umgesetzt in `261dc8f`. Details in [datenhaltung.md](datenhaltung.md).

- [x] Schemas `batch`, `market_data`, `scoring` und `reporting` mit Alembic (`261dc8f`)
- [x] Rollen `va_owner`, `va_app` und `va_read`, Trigger gegen Löschen und Überschreiben (`261dc8f`)
- [x] Rohdaten (`raw_info`) und Statement-Werte im Long-Format (`statement_value`) (`261dc8f`)
- [x] Import der alten Parquet- und CSV-Dateien, Housekeeping entfernt (`261dc8f`)
- [x] Nach GitHub gepusht (`c584561`)
- [ ] NAS (du): Deployment, danach den Altdaten-Import ausführen (`make db-import`)
- [ ] NAS (du): danach `RETENTION_DAYS` aus der `.env` entfernen
- [ ] NAS (du): Backup per `pg_dump` einrichten (`make db-backup`, Ordner in Hyper Backup
      aufnehmen, siehe [betrieb-synology.md](betrieb-synology.md))

**Fertig, wenn:** jeder Lauf vollständig in der Datenbank steht und die Altdaten importiert sind.

## Phase 2b – Scoring-Profile

Details: [Implementierungsplan, Phase 2b](implementierungsplan.md#phase-2b--scoring-profile)

- [ ] P2b.1 Profil-Tabellen
- [ ] P2b.2 ScoringProfileParams
- [ ] P2b.3 Profil-Version im Lauf und in der Mail

**Fertig, wenn:** jeder Bewertungslauf seine Profil-Version kennt.

## Phase 3 – web-api und Angular

Details: [Implementierungsplan, Phase 3](implementierungsplan.md#phase-3--web-api-und-angular)

- [ ] UI-Bibliothek festlegen (Angular Material oder PrimeNG), vor P3.5
- [ ] P3.1 Gerüst des web-api
- [ ] P3.2 Lese-Endpunkte
- [ ] P3.3 Profil-Endpunkte und Vorschau
- [ ] P3.4 Sicherheitsgrundlagen 🔒
- [ ] P3.5 Angular-Gerüst und generierter Client
- [ ] P3.6 frontend-Container 🔒
- [ ] P3.7 Ansichten
- [ ] P3.8 Schutz der Schnittstelle
- [ ] NAS (du): frontend-Container deployen, Firewall-Regel für Port 8080

**Fertig, wenn:** das UI im LAN nutzbar ist und die Profile editierbar sind.

## Phase 4 – Events und Echtzeit

Details: [Implementierungsplan, Phase 4](implementierungsplan.md#phase-4--events-und-echtzeit)

- [ ] P4.1 NATS-Infrastruktur
- [ ] P4.2 Outbox und Inbox
- [ ] P4.3 NATS als Bus
- [ ] P4.4 Eventmanager und Projektionen
- [ ] P4.5 WebSocket-Hub und Protokoll v1 🔒
- [ ] P4.6 Echtzeit im Frontend
- [ ] P4.7 Runs aus dem UI, Watchdog, Scheduler
- [ ] P4.8 Vorschau und Profil-Befehle über NATS

**Fertig, wenn:** alles über Events läuft und das UI live aktualisiert.

## Phase 5 – Aufteilen in Services

Details: [Implementierungsplan, Phase 5](implementierungsplan.md#phase-5--aufteilen-in-services)

- [ ] P5.1 Images je Service
- [ ] P5.2 End-to-End-Test des ganzen Stacks
- [ ] P5.3 Eine DB-Rolle je Service 🔒
- [ ] P5.4 Scheduler im web-api
- [ ] P5.5 Tracing
- [ ] P5.6 Abschluss-Doku
- [ ] NAS (du): Umstellung auf den kompletten Stack

**Fertig, wenn:** die Zielarchitektur aus [README.md](README.md) läuft.

## Danach (Ideen, nicht beschlossen)

- Watchlists und Diagramme zum Score-Verlauf
- Mehrere Mail-Empfänger. Dann auch einen einfachen Login einführen
  ([ADR-0007](../adr/0007-lan-only-ohne-login.md)).
- Weitere Kanäle in `notification`, z. B. Telegram
- Wechsel des Datenanbieters (FMP/EODHD) als weiterer Adapter in `market-data`
