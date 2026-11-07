# Roadmap

> Stand: 04.11.2026. Hier steht, *was* in welcher Phase passiert und was erledigt ist. *Wie*
> jedes Arbeitspaket umgesetzt wird (Test → Implementierung → Grün → Review), steht im
> [Implementierungsplan](implementierungsplan.md). Abgehakt wird nur hier, jeweils mit Commit.
> Die Samstags-Mail muss nach jedem Paket unverändert funktionieren.

## Überblick

| Phase | Ziel | Status |
|---|---|---|
| – | Universum aus iShares/Deka statt Wikipedia | ✅ erledigt (`ca85d93`, `c14fa32`) |
| 0 | Fundament: Golden-Master, CI, uv, Python 3.14, aktuelle Dependencies, Images aus CI | ✅ im Code erledigt (P0.1–P0.8); NAS: mit der Umstellung |
| 1 | Modularer Monolith mit den späteren Service-Grenzen | ✅ im Code erledigt (P1.1–P1.10, M1); NAS: mit der Umstellung |
| 2 | Postgres als Historien-Schicht | ✅ im Code erledigt (`261dc8f`); NAS: mit der Umstellung, inklusive Altdaten-Import |
| 2b | Scoring-Profile in der DB | ✅ im Code erledigt (P2b.0–P2b.3): jeder Lauf rechnet mit dem aktiven Profil und nennt es in der Mail; Editor im UI seit `913ea7c`; NAS: mit der Umstellung |
| 3 | web-api + Angular (UI im LAN, Profil-Editor) | ✅ im Code erledigt (P3.1–P3.8): Analysen, Profil-Editor und Schutz der Schnittstelle; NAS: mit der Umstellung |
| 4 | Events und Echtzeit (NATS, Eventmanager, WebSocket) | ✅ im Code erledigt (P4.1–P4.9): NATS, Outbox/Inbox, idempotente Handler, Eventmanager mit Projektionen, WebSocket-Hub, Echtzeit im UI, Runs aus dem UI mit Scheduler und Watchdog, Request/Reply, REST aus Projektionen |
| 5 | Aufteilen in Services (Zielarchitektur) | ✅ im Code erledigt (P5.1a–P5.6): ein Container je Service, End-to-End-Test des ganzen Stacks, eine DB-Rolle je Service, Scheduler im web-api und NATS als Standard, Tracing, Runbook; NAS: Umstellung offen |
| U | Umgebungen: lokaler Stack und NAS ([umgebungen.md](umgebungen.md)) | 🚧 U1, U4 und U5 (lokaler End-to-End-Test) erledigt, U2 nach dem NAS-Deployment |
| F | Fundamentaldaten: F1 Stichtagsdaten sichern ([ADR-0010](../adr/0010-stichtagsdaten-konsens-quartale-kurse.md)), F2/F3 Auswertung ([ADR-0011](../adr/0011-fundamentale-anker-und-belegte-faktoren.md), angenommen) | 🚧 F1 im Code erledigt (F1.1–F1.6), NAS: mit der Umstellung; ADR-0011 angenommen (06.11.2026), F2.4 im Code erledigt, weiter mit F2.1 |
| G | Gestaltung des UI: klar, ruhig, jeder Begriff erklärt ([Spec](ui-neugestaltung.md)) | ✅ G0 bis G8 umgesetzt und abgenommen (06.11.2026); NAS: mit dem nächsten Deployment |
| D | Depots, mehrere Nutzer, News, Berichte, Bankanbindung ([Spezifikation](depot/README.md), [ADR-0012](../adr/0012-mehrbenutzer-mit-lokalen-konten.md) bis [ADR-0014](../adr/0014-bankanbindung-nur-lesend-ueber-ports.md)) | 🚧 Spezifikation steht, ADR-0012 bis ADR-0014 angenommen (06.11.2026); D1.1 (Konten, Anmeldung, Sitzungen), D1.2 (Sitzungspflicht, Rollen), D1.3 (WebSocket je Nutzer), D1.4 (Anmeldung und Nutzerverwaltung im UI), D1.5 (HTTPS, Proxys, NATS-Nutzer) und D1.6 (Mail-Bestätigung, Export, Löschkommando) im Code erledigt, D1 damit fertig |

**NAS:** Alle offenen NAS-Punkte (unter „Sofort“ und in Phase 0, 2, 3, 5 und F1) erledigt ein
Durchgang nach dem [Runbook](betrieb-synology.md#umstellung-vom-batch-mit-cron-einmalig). Er enthält auch den Altdaten-Import und die Sicherung.

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
      Sonst löscht das alte Housekeeping die Dateien, die importiert werden sollen. Im
      [Runbook](betrieb-synology.md#umstellung-vom-batch-mit-cron-einmalig) der Schritt „Vorab“.

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
- [ ] NAS (du): Backup per `pg_dump` einrichten (`make db-backup` im DSM-Aufgabenplaner, Ordner in
      Hyper Backup aufnehmen, siehe [Runbook, Backup](betrieb-synology.md#backup))

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
- [x] P5.6 Abschluss-Doku, Runbook der NAS, Link-Check (`c9771e0`)
- [ ] NAS (du): Umstellung auf den kompletten Stack, Schritte im
  [Runbook](betrieb-synology.md#umstellung-vom-batch-mit-cron-einmalig)

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
angenommen am 06.11.2026):

- [x] Vorprüfung: Rescore-Vergleich v1/v2 und Prüfung des Immobilien-EBIT
      ([Bericht](../research/adr-0011-vorpruefung/bericht.md), `f6daa2b`)
- [x] Entscheidung (du): ADR-0011 angenommen, dazu Immobilien und „Capital Markets“ in der
      Branchenregel, F2.4 zuerst (06.11.2026)
- [x] F2.4 Branchenregeln und Abschnitt „Finanzwerte“ (vorgezogen, `d2535cb`; abgeschaltet bis F2.5)
- [ ] F2.1 Bilanzqualität: F-Score, Accruals, CFO/Bilanzsumme
- [ ] F2.2 Netto-Aktienemission
- [ ] F2.3 Momentum und Value-Trap-Regel
- [ ] F2.5 Standardprofil v2 aktivieren
- [ ] F3.1 Ertragskraftwert und implizites Wachstum
- [ ] F3.2 Titel-Detail: Anker, Wertlinie und Renditezerlegung

**Fertig, wenn:** über ADR-0011 entschieden ist. Wird es angenommen, außerdem: Das Standardprofil v2
ist aktiv, und das Titel-Detail zeigt die Anker.

## Track G – Gestaltung des UI

Details: [ui-neugestaltung.md](ui-neugestaltung.md)

- [x] Entscheidung (du): E2 Papier-Design, nur Graustufen und Papierfarbe (06.11.2026)
- [x] Entscheidung (du): Spec abnehmen, dazu die Vorschläge E1 und E3 bis E7 (06.11.2026, alle wie vorgeschlagen)
- [x] G0 Designvorlage: klickbarer Entwurf, Abnahme der Optik am 06.11.2026 (`7e13fb8`)
- [x] G1 Fundament und Hülle (`57a0fc5`)
- [x] G2 Begriffe und Tooltips (`bdd9f52`)
- [x] G3 API-Ergänzungen (additiv, `272935c`; Migration `0016`)
- [x] G4 Ranking (`f86fefc`)
- [x] G5 Titel-Detail (`1513f81`)
- [x] G6 Läufe und Lauf-Detail (`f7610b9`)
- [x] G7 Profile und Editor (`63444f7`)
- [x] G8 Abschluss: Barrierefreiheit, hell und dunkel, schmale Bildschirme, Doku (`79a4189`,
      `642ff85`)
- [x] Abnahme über den ganzen Stack (du, 06.11.2026)
- [ ] NAS (du): kommt mit dem nächsten Deployment (`make pull`, `make up`); die Migration `0016`
      und ihr Backfill laufen beim Start

**Fertig, wenn:** jede Ansicht ihre Frage im ersten Bildschirm beantwortet und die Tooltip-Tests
jeden Button, jedes Kürzel und jeden Status abdecken.

## Track D – Depots, mehrere Nutzer und Bankanbindung

Spezifikation: [depot/README.md](depot/README.md). Details:
[Implementierungsplan, Track D](implementierungsplan.md#track-d--depots-mehrere-nutzer-und-bankanbindung)

- [x] D0 Entscheidung (du): ADR-0012, ADR-0013 und ADR-0014 angenommen, offene Fragen 1, 2, 3
      und 6 entschieden (06.11.2026)
- [ ] D0 Entscheidung (du): übrige offene Fragen der Spezifikation (4, 5, 7–13), jeweils
      spätestens vor der Stufe, die sie braucht
- [ ] D0 (du): FinTS-Produktregistrierung als „Privatanwender-Software“ beantragen (kostenlos,
      10–15 Arbeitstage, [Recherche](../research/2026-11-depot-datenquellen-und-bankzugang.md#fints-produktregistrierung))
- [x] D1 Mehrere Nutzer: Login, Sitzungen, Rollen, HTTPS 🔒
  - [x] D1.1 Konten, Anmeldung, Sitzungen, Schema `identity` 🔒 (`0d2d8bd`)
  - [x] D1.2 Rollen und Schutz der bestehenden Endpunkte, Log-Filter 🔒 (`2f21b48`; in Compose
        bis D1.4/D1.5 per `WEB_API_AUTH_REQUIRED=false` abgeschaltet)
  - [x] D1.3 WebSocket mit Sitzung, Topics je Nutzer 🔒 (`253fcda`)
  - [x] D1.4 Frontend: Anmeldung, Nutzerverwaltung, E2E mit Testnutzer (`00d8b62`; lokal und im
        E2E-Stack mit Sitzungspflicht, auf der NAS erst mit D1.5)
  - [x] D1.5 Betrieb: HTTPS über DSM, Vertrauenskette der Proxys, NATS-Nutzer je Dienst 🔒
        (`36e5e86`; NAS: Zertifikat wählen und Reverse-Proxy einrichten, Runbook)
  - [x] D1.6 Mail-Bestätigung, Datenexport, Löschkommando für `identity` (`b753158`; Migration
        0017, Stream `VA_PRIVATE`; NAS: nichts Neues in der `.env`)
- [ ] D2 Wertpapiere über ISIN, Suche, Abdeckung, Tageskurse
- [ ] D3 Dienst portfolio, Depots und Depotstände
- [ ] D4 Analyse: Einordnung ins Referenzuniversum, ETF, Anleihen, Depot
- [ ] D5 Hinweise
- [ ] D6 News
- [ ] D7 Berichte mit eigenem Intervall
- [ ] D8 depot-gateway, Port `DepotSource`, Datei-Adapter 🔒
- [ ] D9 DKB über FinTS 🔒
- [ ] NAS (du): HTTPS einrichten (mit D1), neue Passwörter der Rollen in die `.env` (je Stufe)

**Fertig, wenn:** Nutzer ihre Depots angelegt haben, Analyse, Hinweise, News und Berichte darauf
laufen und der Bestand der DKB nur lesend abrufbar ist.

## Danach (Ideen, nicht beschlossen)

- Diagramme zum Score-Verlauf. Watchlists sind als Beobachtungslisten Teil von Track D (DEP-09).
- Mehrere Mail-Empfänger: mit Track D, Login in D1 ([ADR-0012](../adr/0012-mehrbenutzer-mit-lokalen-konten.md))
  und Berichte je Nutzer in D7.
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
