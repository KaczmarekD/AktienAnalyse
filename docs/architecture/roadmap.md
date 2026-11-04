# Roadmap

> Stand: 30.10.2026. Hier steht, *was* in welcher Phase passiert und was erledigt ist. *Wie*
> jedes Arbeitspaket umgesetzt wird (Test → Implementierung → Grün → Review), steht im
> [Implementierungsplan](implementierungsplan.md). Abgehakt wird nur hier, jeweils mit Commit.
> Die Samstags-Mail muss nach jedem Paket unverändert funktionieren.

## Überblick

| Phase | Ziel | Status |
|---|---|---|
| – | Universum aus iShares/Deka statt Wikipedia | ✅ erledigt (`ca85d93`, `c14fa32`) |
| 0 | Fundament: Golden-Master, CI, uv, Python 3.14, aktuelle Dependencies, Images aus CI | ✅ im Code erledigt (P0.1–P0.8), NAS: Images aus GHCR laden |
| 1 | Modularer Monolith mit den späteren Service-Grenzen | ✅ im Code erledigt (P1.1–P1.10, M1), NAS: neues Image laden |
| 2 | Postgres als Historien-Schicht | 🚧 im Code erledigt und gepusht (`261dc8f`), Deployment auf der NAS offen |
| 2b | Scoring-Profile in der DB | ✅ im Code erledigt (P2b.0–P2b.3): jeder Lauf rechnet mit dem aktiven Profil und nennt es in der Mail; API seit P3.3, Editor im UI offen; NAS: Deployment |
| 3 | web-api + Angular (UI im LAN, Profil-Editor) | ✅ im Code erledigt (P3.1–P3.8): Analysen, Profil-Editor und Schutz der Schnittstelle; NAS: Deployment |
| 4 | Events und Echtzeit (NATS, Eventmanager, WebSocket) | 🚧 P4.1–P4.9 erledigt (NATS, Outbox/Inbox, NATS als Bus, idempotente Handler, Eventmanager mit Projektionen, WebSocket-Hub, Echtzeit im UI, Runs aus dem UI mit Worker, Scheduler und Watchdog, Vorschau und Profil-Befehle über NATS, REST aus Projektionen; Standard noch im Prozess). Im Code fertig |
| 5 | Aufteilen in Services (Zielarchitektur) | offen |
| U | Umgebungen: lokaler Stack und NAS ([umgebungen.md](umgebungen.md)) | 🚧 U1, U4 und U5 (lokaler End-to-End-Test) erledigt, U2 nach dem NAS-Deployment |
| F | Fundamentaldaten: F1 Stichtagsdaten sichern ([ADR-0010](../adr/0010-stichtagsdaten-konsens-quartale-kurse.md)), F2/F3 Auswertung ([ADR-0011](../adr/0011-fundamentale-anker-und-belegte-faktoren.md), vorgeschlagen) | 🚧 F1 im Code erledigt (F1.1–F1.6), Deployment offen; F2/F3 warten auf ADR-0011 |

**Reihenfolge:**
- Phase 2 wurde vorgezogen, weil jede Woche ohne Stichtagsdaten verloren ist.
- Phase 0 beginnt mit P0.1: Der Golden-Master ist das Sicherungsnetz für alle späteren Umbauten.
- Ab Phase 1 ist die Reihenfolge verbindlich.
- P1.10 kam vor P2b.1: P2b.1 legt neue Tabellen an und verlässt sich auf den Löschschutz-Test,
  der vor P1.10 den Schutz gegen UPDATE nicht prüfte.
- Track F1 ist aus demselben Grund vorgezogen wie Phase 2 und kann parallel zu Phase 0 laufen.
  F2 und F3 beginnen erst, wenn ADR-0011 angenommen ist, frühestens nach P1.5 und P2b.2.
- U4 (Entscheidung 31.10.2026): Die Lese-Teile von Phase 3 kommen vor Phase 2b, damit die
  Analysen im Browser zu sehen sind. Reihenfolge: P3.1, P3.2, P3.4, P3.5, P3.6, P3.7 ohne den
  Profil-Editor. P3.3 und der Profil-Editor folgen nach Phase 2b.
- U5 (Entscheidung 31.10.2026): Der lokale End-to-End-Test kommt vor P2b.1. Ab Phase 2b lässt
  sich so jedes Paket auf dem Entwicklungsrechner durch die ganze Kette prüfen.

## Sofort (du, auf der NAS)

- [ ] `RETENTION_DAYS=0` setzen, bis die Postgres-Persistenz inklusive Altdaten-Import läuft.
      Sonst löscht das alte Housekeeping die Dateien, die importiert werden sollen.

## Phase 0 – Fundament

Details: [Implementierungsplan, Phase 0](implementierungsplan.md#phase-0--fundament)

- [x] P0.1 Golden-Master für die Mail (`cd21f50`)
- [x] P0.2 CI auf Feature-Branches (`804d4eb`; die CI war seit dem 29.09. rot, ein Test schrieb
      nach `/app`: `d3a0e4d`)
- [x] P0.3 uv-Workspace statt pip-tools ([ADR-0004](../adr/0004-uv-workspace-monorepo.md)) (`a210e20`)
- [x] P0.4 Python 3.14 (`aa49a0b`)
- [x] P0.5 pandas 3 und yfinance 1.7 (`9504dd0`)
- [x] P0.6 J4125-Prüfung in CI und lokal ([ADR-0008](../adr/0008-zielhardware-j4125.md)) (`d4d029c`)
- [x] P0.7 Fix-Paket Perioden und inf (`190a862`)
- [x] P0.6b Images aus der CI nach GHCR (`f9ee183`)
- [x] P0.8 Fix-Paket Infrastruktur (Gesamt-Review) (`d14a859`)
- [ ] NAS (du): Images aus GHCR laden statt auf der NAS zu bauen (nach P0.6b): `git pull`, bei
      privatem Paket `docker login ghcr.io`, `docker compose pull`, Import-Test, `up -d`
      (README, Abschnitt „Update“)

**Fertig, wenn:** dieselbe Mail wie vorher kommt (Golden-Master grün), die Images aus der CI
stammen und die Tests auf Python 3.14 grün sind.

## Phase 1 – Modularer Monolith

Details: [Implementierungsplan, Phase 1](implementierungsplan.md#phase-1--modularer-monolith)

- [x] P1.1 Workspace-Pakete und Grenzen (`eda1b69`)
- [x] P1.2 Contracts v1 (`2f40d43`)
- [x] P1.3 Kennzahlen als reine Funktionen (`b7c1c0a`)
- [x] P1.4 Adapter für Yahoo und Universum hinter Ports (`f7d081f`)
- [x] P1.5 Scoring-Modul (`b7f71a4`)
- [x] P1.6 Notification-Modul (`44ec184`)
- [x] P1.7 Datenbankzugriff je Modul (`5cad2aa`)
- [x] P1.8 Event-Bus im Prozess, Composition Root (`6d6286c`)
- [x] P1.9 Aufräumen (`4f183d6`), Gesamt-Review Phase 1 (`cef8ebb`)
- [x] P1.10 Fix-Paket Spec-Abgleich (Abgleich vom 30.10.2026): Jahresabschlüsse ohne verschluckte
      Abruffehler, Löschschutz-Test mit UPDATE, Trigger für den Abschluss eines Laufs, Doku auf
      den Stand nach Phase 1 (`e338045`)
- [x] Entscheidung (du): Titel ohne Quality-Score bekommen heute den Value-Score als Composite.
      Entschieden am 30.10.2026 für Variante 1, umgesetzt in M1 (siehe unten)

**Fertig, wenn:** es weiterhin ein Container ist, die Golden-Files unverändert sind und die CI die
Grenzen erzwingt.

## Methodik-Korrekturen

Bewusste Änderungen am Ranking außerhalb von ADR-0011. Details:
[Implementierungsplan, Methodik-Korrekturen](implementierungsplan.md#methodik-korrekturen)

- [x] M1 Kein Composite ohne beide Teilscores (`25c260b`)

## Track U – Umgebungen (lokal und NAS)

Details: [umgebungen.md](umgebungen.md),
[Implementierungsplan, Track U](implementierungsplan.md#track-u--umgebungen-lokal-und-nas)

- [x] U1 Lokaler Stack: Mailpit, pgweb, Läufe auf Knopfdruck (`make local-*`), `SMTP_PLAIN`
      (`9ba5ffe`)
- [ ] U2 NAS-Daten lokal einspielen (`make local-restore`), Regression gegen alle Wochen
- [ ] U3 (optional) Test auf der NAS: Branch-Images, zweites Compose-Projekt mit eigener DB
- [x] Entscheidung (du): U4 Analysen im Browser, also P3.1, P3.2 und die Ansichten Ranking,
      Runs und Titel-Detail vor Phase 2b ziehen. Entschieden am 31.10.2026: ja
- [x] U4 Analysen im Browser (Pakete unter Phase 3: P3.1, P3.2, P3.4, P3.5, P3.7, P3.6)
- [x] U5 Lokaler End-to-End-Test (`make local-e2e`, vor P2b.1) (`3dfa605`)
  - [x] U5.1 Replay-Quelle statt Yahoo (`REPLAY_SOURCE`)
  - [x] U5.2 E2E-Stack mit Wegwerf-DB, Prüfungen von Mail, API und UI, auch in der CI
  - [x] U5.3 Browser-Test des UI (Playwright); dabei behoben: Styles des UI hinter nginx

**Fertig, wenn:** jede neue Implementierung lokal mit echten Daten im Browser und in Mailpit
geprüft werden kann, bevor sie auf die NAS geht.

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

- [x] P2b.0 Replay-Regression über gespeicherte Wochen ([Konzept](regressionstest.md),
      Vorschlag B) (`e222564`)
- [x] P2b.1 Profil-Tabellen, Profil „Standard“ beim Start aus ENV (`767263a`)
- [x] P2b.2 ScoringProfileParams (`c230e45`)
- [x] P2b.3 Profil-Version im Lauf und in der Mail (`6baf004`)

**Fertig, wenn:** jeder Bewertungslauf seine Profil-Version kennt.

## Phase 3 – web-api und Angular

Details: [Implementierungsplan, Phase 3](implementierungsplan.md#phase-3--web-api-und-angular)

Mit U4 kommen die Lese-Teile vor Phase 2b. P3.3 und der Profil-Editor aus P3.7 folgen danach.

- [x] UI-Bibliothek festlegen (Angular Material oder PrimeNG), vor P3.5. Entschieden am
      31.10.2026: Angular Material
- [x] P3.1 Gerüst des web-api (U4) (`5c4e9d1`)
- [x] P3.2 Lese-Endpunkte (U4) (`f9ba2a5`)
- [x] P3.3 Profil-Endpunkte und Vorschau, Rolle `va_profiles` (`4792548`)
- [x] P3.4 Sicherheitsgrundlagen 🔒 (U4) (`7736091`)
- [x] P3.5 Angular-Gerüst und generierter Client (U4) (`a342653`)
- [x] P3.6 frontend-Container 🔒 (U4) (`07d234f`)
- [x] P3.7 Ansichten: Ranking, Runs, Titel-Detail (U4) (`c8cf31e`); Profil-Editor (`913ea7c`)
- [x] P3.8 Schutz der Schnittstelle (`oasdiff breaking` gegen `main`) (`a4f4737`)
- [ ] NAS (du): frontend-Container deployen, Firewall-Regel für Port 8080; seit P3.3 gehört
      `VA_PROFILES_PASSWORD` in die `.env`

**Fertig, wenn:** das UI im LAN nutzbar ist und die Profile editierbar sind.

## Phase 4 – Events und Echtzeit

Details: [Implementierungsplan, Phase 4](implementierungsplan.md#phase-4--events-und-echtzeit)

- [x] P4.1 NATS-Infrastruktur (`935dedc`)
- [x] P4.2 Outbox und Inbox (`97d231b`)
- [x] P4.3 NATS als Bus (`b0266c5`)
- [x] P4.3b Idempotente Handler, pragmatisch ueber ReliableBus (`a3c3a0f`)
- [x] P4.4 Eventmanager und Projektionen (`5505365`)
- [x] P4.5 WebSocket-Hub und Protokoll v1 🔒 (`5123c25`)
- [x] P4.6 Echtzeit im Frontend (`4baf52e`)
- [x] P4.7 Runs aus dem UI, Watchdog, Scheduler (`7bc1881`)
- [x] P4.8 Vorschau und Profil-Befehle über NATS (`9a4bb77`)
- [x] P4.9 REST aus Projektionen und Request/Reply (nachgetragen 04.11.2026, `3280951`)

**Fertig, wenn:** alles über Events läuft und das UI live aktualisiert.

## Phase 5 – Aufteilen in Services

Details: [Implementierungsplan, Phase 5](implementierungsplan.md#phase-5--aufteilen-in-services)

- [x] P5.1a Einstiegspunkte je Service (nachgetragen 04.11.2026: eigene Settings, Request/Reply beim Besitzer, `f5d80e0`)
- [x] P5.1 Images je Service (`f7819fe`)
- [x] P5.2 End-to-End-Test des ganzen Stacks (`5833bc2`)
- [x] P5.3 Eine DB-Rolle je Service 🔒 (`5db3abe`)
- [x] P5.4 Scheduler im web-api, NATS als Standard (`da90237`)
- [x] P5.5 Tracing, ein Trace je Run (`4afd3af`)
- [ ] P5.6 Abschluss-Doku
- [ ] NAS (du): Umstellung auf den kompletten Stack

**Fertig, wenn:** die Zielarchitektur aus [README.md](README.md) läuft.

## Track F – Fundamentaldaten und Anker

Details: [Implementierungsplan, Track F](implementierungsplan.md#track-f--fundamentaldaten-und-anker-adr-0010-adr-0011)

**F1 – Stichtagsdaten sichern** ([ADR-0010](../adr/0010-stichtagsdaten-konsens-quartale-kurse.md),
beschlossen, vorgezogen):

- [x] F1.1 Konsens-Snapshots (`65ad20f`)
- [x] F1.2 Quartalsabschlüsse (`d032b7c`)
- [x] F1.3 Historie der Aktienanzahl (`22e5306`)
- [x] F1.4 Kurshistorie (`c2691f3`)
- [x] F1.5 Fix-Paket Zusatzdaten (Review F1.2 bis F1.4) (`b5fb3f6`)
- [x] F1.6 Fix-Paket Gesamt-Review Track F (`27ca2ae`)
- [ ] NAS (du): Deployment. Der erste Lauf danach dauert länger, weil die Kurshistorie erstmals
      gefüllt wird.

**Fertig, wenn:** Konsens, Quartale, Aktienanzahl und Kurse jede Woche gespeichert werden und die
Mail unverändert ist.

**F2/F3 – Auswertung** ([ADR-0011](../adr/0011-fundamentale-anker-und-belegte-faktoren.md),
vorgeschlagen, erst nach Annahme):

- [ ] Entscheidung über ADR-0011 nach P1.5 und P2b.2. Vorher laufen ein Rescore-Vergleich v1/v2 und
      die Prüfung des Immobilien-EBIT.
- [ ] F2.1 Bilanzqualität: F-Score, Accruals, CFO/Bilanzsumme
- [ ] F2.2 Netto-Aktienemission
- [ ] F2.3 Momentum und Value-Trap-Regel
- [ ] F2.4 Branchenregeln und Abschnitt „Finanzwerte“
- [ ] F2.5 Standardprofil v2 aktivieren
- [ ] F3.1 Ertragskraftwert und implizites Wachstum
- [ ] F3.2 Titel-Detail: Anker, Wertlinie und Renditezerlegung

**Fertig, wenn:** über ADR-0011 entschieden ist. Wird es angenommen, außerdem: Das Standardprofil v2
ist aktiv, und das Titel-Detail zeigt die Anker.

## Danach (Ideen, nicht beschlossen)

- Watchlists und Diagramme zum Score-Verlauf
- Mehrere Mail-Empfänger. Dann auch einen einfachen Login einführen
  ([ADR-0007](../adr/0007-lan-only-ohne-login.md)).
- Weitere Kanäle in `notification`, z. B. Telegram
- Wechsel des Datenanbieters (FMP/EODHD) als weiterer Adapter in `market-data`, etwa für eine
  lange Abschlusshistorie der Anker. ESAP (öffentlich ab Juli 2027) als freie Quelle prüfen.
- Revisionsmomentum als Faktor, sobald die Konsens-Snapshots aus F1.1 mindestens ein Jahr
  Historie haben
- LLM-Lesehilfe für die Top-Kandidaten: Geschäfts- und Risikobericht mit Vorjahresvergleich. Braucht
  ein eigenes ADR ([Recherche, Stufe 4](../research/fundamentalanalyse-sota/bericht.md#stufe-4-optional)).
- Directors' Dealings der BaFin sichern (nur 12 Monate online), falls die Nutzungsbedingungen es
  erlauben
- P/B mit aktivierten Forschungsausgaben (Intangibles)
