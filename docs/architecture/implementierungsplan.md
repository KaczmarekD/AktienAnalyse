# Implementierungsplan

> **Status:** Plan (30.09.2026). Die [Roadmap](roadmap.md) sagt, *was* in welcher Phase passiert
> und was erledigt ist. Dieses Dokument sagt, *wie* jedes Arbeitspaket umgesetzt wird.
> Abgehakt wird nur in der Roadmap.

## Der Zyklus: Test → Implementierung → Grün → Review

Jedes Arbeitspaket durchläuft vier Schritte, keiner wird übersprungen.

| Schritt | Was passiert | Ergebnis |
|---|---|---|
| **1. Test** | Tests beschreiben das gewünschte Verhalten, bevor Produktivcode entsteht. Sie laufen und schlagen aus dem erwarteten Grund fehl. | rote Tests, die das Ziel festhalten |
| **2. Implementierung** | So wenig Code wie nötig, bis die neuen Tests grün sind. Es gelten die Konventionen aus CLAUDE.md und die ADRs. | neue Tests grün |
| **3. Grün** | Die komplette Prüfkette läuft durch, nicht nur die neuen Tests (siehe unten). | alles grün |
| **4. Review** | Review des gesamten Diffs, Befunde beheben, danach wieder Schritt 3. Erst dann kommen deine Abnahme und der Merge. | geprüfter, abgenommener Stand auf `main` |

**Sonderfall Umbau:** Wo sich Verhalten nicht ändern darf (vor allem in Phase 1), sind die
Tests aus Schritt 1 **Sicherungstests**. Sie werden gegen den alten Code geschrieben und sind
dort bereits grün. Der Umbau ist fertig, wenn sie unverändert grün bleiben. Neues Verhalten
innerhalb eines Umbaus folgt wieder dem Weg rot → grün.

**Sonderfall Infrastruktur** (CI, Docker, Tooling): Als „Test“ wird zuerst die Prüfung
eingerichtet, also ein CI-Schritt, ein Smoke-Test oder ein Skript. Ohne die Änderung schlägt sie
fehl.

### Was „Grün“ heißt

Standard für jedes Paket:

1. `make check`: Ruff (Lint und Format), Pyright, Pytest
2. `make test-db-up && make test-db`: alle Tests inklusive der DB-Tests gegen echtes Postgres 18
3. Die Migrationen laufen gegen eine leere Datenbank durch (wie im CI-Job).
4. Die Golden-Files sind unverändert. Oder sie wurden bewusst aktualisiert, und das Review
   begründet es.
5. Die CI auf dem Branch ist grün. Bis P0.2 umgesetzt ist, laufen stattdessen lokal dieselben
   Befehle.

Pakete, die neue Prüfungen einführen (import-linter, Frontend-Tests, Docker-Smoke, `oasdiff`),
nehmen sie ab dann dauerhaft in diesen Standard auf.

### Was „Review“ heißt

1. `/code-review high` auf den Diff `main...HEAD`
2. zusätzlich `/security-review` bei sicherheitsrelevanten Paketen, markiert mit 🔒
3. zusätzlich `/simplify` bei größeren Umbauten
4. Checkliste:
   - Die Tests entstanden vor dem Code und prüfen Verhalten, nicht Implementierungsdetails.
   - CLAUDE.md-Konventionen und ADRs sind eingehalten. Eine Abweichung bekommt ein neues ADR.
   - Neue Dependencies: gepinnt, kein Zwang zu AVX2 bzw. x86-64-v3
     ([ADR-0008](../adr/0008-zielhardware-j4125.md)).
   - Migrationen sind additiv. Jede neue Tabelle bekommt `protect_table()` oder eine
     begründete Ausnahme.
   - Contracts ändern sich nur additiv, sonst gibt es eine neue Version.
   - Die Doku ist aktuell: Roadmap-Haken sowie CLAUDE.md/README, wenn sich Konventionen oder
     Befehle ändern.
5. Befunde beheben, zurück zu „Grün“.
6. **Abnahme durch dich:** kurze Zusammenfassung mit Testnachweis. Nach deinem OK folgen
   Squash-Merge auf `main` und Push.

Bei großen Paketen (Ende von Phase 1 und Phase 4) kannst du zusätzlich `/code-review ultra`
anstoßen. Das ist ein Review mit mehreren Agents in der Cloud, kostenpflichtig und nur durch dich
auslösbar.

### Definition of Done je Paket

- Tests zuerst geschrieben und rot gesehen, bei Umbauten Sicherungstests grün gegen den alten Code
- Implementierung fertig, komplette Prüfkette grün
- Review durchgeführt, Befunde behoben
- Doku aktualisiert, Roadmap-Punkt mit Commit abgehakt
- Abnahme durch dich, Squash-Merge auf `main`, gepusht
- nötige Schritte auf der NAS im Paket beschrieben

## Ablauf je Paket

1. **Vorbereiten:**
   - `git fetch` und `git status`.
   - Prüfen, ob andere Sessions aktiv sind (`ListAgents`).
   - Eigener Worktree unter `.claude/worktrees/<paket>` mit Branch `feat/<paket>`, z. B.
     `feat/p1-3-kennzahlen`. Entwickelt wird nie direkt auf `main`.
2. **Test:** Tests schreiben und gezielt laufen lassen (`pytest tests/… -x`). Bestätigen, dass sie
   aus dem erwarteten Grund rot sind. Commit `test: …` auf dem Branch.
3. **Implementierung:** bis die neuen Tests grün sind. Commit `feat: …` bzw. `refactor: …`.
4. **Grün:** komplette Prüfkette. Erst jetzt wird der Branch gepusht, die CI sieht also nie einen
   roten Stand.
5. **Review:** siehe oben, Korrekturen als eigene Commits.
6. **Abschluss:** Zusammenfassung an dich. Nach deinem OK: Squash-Merge, Push, Roadmap abhaken,
   Worktree entfernen.

**Parallelität:** Die Pakete aus Phase 1 ändern fast alle Dateien und laufen nacheinander. Ab
Phase 3 können Frontend- und Backend-Pakete parallel in getrennten Worktrees laufen, solange sie
keine gemeinsamen Dateien anfassen.

## Voraussetzungen

- **uv** lokal installieren (fehlt noch). Python 3.14 dann per `uv python install 3.14`.
- **Docker** lokal (vorhanden) für die Test-Datenbank und später NATS.
- **Node ≥ 22** für Angular 22. Lokal ist 22.17 vorhanden, das wird bei P3.5 geprüft.
- **GitHub CLI (`gh`)**, optional für PRs und CI-Status (fehlt derzeit).

## Arbeitspakete

### Phase 0 – Fundament

#### P0.1 Golden-Master für die Mail

- **Test:** Golden-File-Tests. Ein fester Eingabedatensatz muss eine HTML-Mail und eine CSV
  erzeugen, die exakt den Dateien in `tests/golden/` entsprechen. Die Tests sind zuerst rot, weil
  `build_report` Uhrzeit und Dateinamen selbst aus der Systemzeit bildet.
- **Implementierung:** Zeitpunkt injizierbar machen (`now`-Parameter). Dazu ein Golden-Helfer
  mit der Option `--update-golden`.
- **Review:** Golden-Dateien stabil und lesbar: feste Sortierung, keine Zufallsanteile.

#### P0.2 CI auf Feature-Branches

- **Test:** Die Workflow-Änderung wird auf einem Test-Branch gepusht. Die CI muss dort anlaufen.
- **Implementierung:** Trigger für `feat/**`, die Concurrency-Regel bleibt. Pfad-Filter
  (Python, Frontend, Images) werden vorbereitet und greifen, sobald es mehrere Workflows gibt
  (ab P0.6).
- **Grün:** Actions-Lauf auf dem Branch grün.

#### P0.3 uv-Workspace statt pip-tools

- **Test:** CI-Schritt `uv sync --frozen` plus `uv run pytest`. Er schlägt ohne `uv.lock` fehl.
- **Implementierung:**
  - Workspace-Root in `pyproject.toml`, Dev-Dependencies als Gruppe, `uv.lock`
  - Make-Targets, CI und Dockerfile auf uv umstellen
  - `requirements*.in/.lock` entfernen
- **Grün:** Standard plus Docker-Build.
- **Review:** Die Paketversionen bleiben gleich (Lockfiles vergleichen), README und Makefile sind
  konsistent.

#### P0.4 Python 3.14

- **Test:** Die CI-Matrix bekommt 3.14. Sie ist rot, solange etwas inkompatibel ist.
- **Implementierung:** `requires-python`, Ruff `target-version`, Pyright `pythonVersion` und das
  Basis-Image `python:3.14-slim` anheben. Danach 3.11/3.12 aus der Matrix entfernen.
- **Review:** Deprecation-Warnungen im Testlauf.

#### P0.5 pandas 3 und yfinance 1.x

- **Test:** Golden-Tests aus P0.1 und die komplette Suite gegen die neuen Versionen. Rote Tests
  zeigen die Inkompatibilitäten.
- **Implementierung:** Pins anheben, betroffene Stellen anpassen (Copy-on-Write, String-Dtype,
  Deprecations in yfinance). pyarrow bleibt, solange der Altdaten-Import Parquet liest.
- **Grün:** Standard, Änderungen an Golden-Files nur mit Begründung.
- **Review:** fachliche Auswirkung jeder Änderung an einem Golden-File.

#### P0.6 Images aus der CI, geprüft für den J4125

- **Test:**
  - Smoke-Schritt im Workflow: `docker run --rm <image> python -c "import numpy, pandas"`.
  - Wenn machbar zusätzlich derselbe Import unter QEMU mit einem CPU-Modell ohne AVX2
    (`qemu-x86_64 -cpu Goldmont-Plus`, entspricht dem J4125).
- **Implementierung:** `images.yml` baut `linux/amd64` und schiebt nach GHCR (Tags: Commit und
  Version). Compose nutzt `image:` statt `build:`.
- **Grün:** Workflow grün, Image liegt in GHCR.
- **Review:** Image-Größe, keine Secrets im Image.
- **NAS (du):** einmalig `docker login ghcr.io`, danach `docker compose pull && docker compose up -d`.

### Phase 1 – Modularer Monolith

Voraussetzung ist P0.1. Die Pakete laufen nacheinander. Grundregel: **Die Golden-Files dürfen
sich in ganz Phase 1 nicht ändern.**

#### P1.1 Workspace-Pakete und Grenzen

- **Test:** import-linter-Verträge (Unabhängigkeit der Services, Schichten innerhalb eines
  Service) als CI-Schritt, zunächst gegen die leeren Gerüste.
- **Implementierung:** Gerüste für `packages/va-contracts`, `packages/va-platform`,
  `services/market-data`, `services/scoring` und `services/notification`. Die Composition Root
  bleibt vorerst beim Batch.
- **Grün:** Standard plus `lint-imports`.
- **Review:** Paketnamen und Abhängigkeiten zwischen den Workspace-Mitgliedern.

#### P1.2 Contracts v1

- **Test:** JSON-Schema-Snapshots und Hin-und-zurück-Tests für `Fundamentals` ↔ `FundamentalsV1`,
  Ranking-Zeilen, Event-Payloads und die Envelope.
- **Implementierung:** Pydantic-Modelle in `va_contracts.events.v1`
  ([events.md](events.md)).
- **Review:** Feldnamen stabil, optionale Felder bewusst gewählt.

#### P1.3 Kennzahlen als reine Funktionen

- **Test:** Kennzahlen-Tests auf Basis gespeicherter Rohdaten echter Titel (JSON-Fixtures, aus
  der Datenbank exportiert oder einmalig aufgezeichnet). Die Erwartungswerte entstehen einmalig
  mit dem heutigen Code. Die Helfer-Tests aus `test_data_fetcher.py` ziehen mit um. yfinance wird
  dabei weiterhin nicht gemockt.
- **Implementierung:** `va_market_data.domain.metrics`. `data_fetcher` ruft die Funktionen auf,
  bis P1.4 den Adapter einführt.
- **Review:** Im Domain-Code gibt es keine Ein-/Ausgabe.

#### P1.4 Adapter für Yahoo und Universum hinter Ports

- **Test:** Tests der Universum-Kette mit Fake-Quellen: Die erste gültige Quelle gewinnt,
  ungültige fallen durch, die CSV kommt zuletzt. Die Parser-Tests der Adapter ziehen mit um.
- **Implementierung:**
  - Ports `UniverseSource` und `FundamentalsProvider`
  - Adapter `ishares`, `deka`, `csv_universe`, `openfigi` sowie `yahoo` (mit `FIELD_MAP`)
- **Review:** Validierungsregeln unverändert (40/50 Aktien, Stichtag höchstens 10 Tage alt).

#### P1.5 Scoring-Modul

- **Test:** `test_scoring.py` zieht mit um. Ein Sicherungstest prüft, dass das Ranking für den
  Golden-Datensatz identisch bleibt.
- **Implementierung:** `va_scoring.domain.scoring`.

#### P1.6 Notification-Modul

- **Test:**
  - Renderer gegen die Golden-Files
  - Versand gegen ein Fake-SMTP
  - Healthcheck-Ping gegen ein Fake-HTTP
- **Implementierung:**
  - Renderer mit Jinja-Template-Datei
  - Ports `ReportSender` und `Heartbeat`
  - Adapter für SMTP und Healthchecks.io
- **Review:** Der Fehlermail-Pfad (`_try_send_error_mail`) ist abgedeckt.

#### P1.7 Datenbankzugriff je Modul

- **Test:** `tests/db/` nach Modulen aufteilen. Der Löschschutz-Test bleibt übergreifend.
- **Implementierung:** Modelle und Repositories ziehen zu ihrem Besitzer-Modul. Engine, Session
  und DDL-Helfer kommen nach `va-platform`. Die Alembic-Historie bleibt vorerst eine einzige.
- **Review:** Keine Fremdschlüssel über Schema-Grenzen.

#### P1.8 Event-Bus im Prozess, Composition Root

- **Test:**
  - Vertragstests für die Bus-Schnittstelle: Zustellung, Fan-out, Verhalten bei Fehlern. Sie
    sind über eine parametrisierte Fixture so geschrieben, dass sie später unverändert auch
    gegen NATS laufen.
  - End-to-End-Test: Die Pipeline über den Bus mit Fakes erzeugt die Golden-Mail.
- **Implementierung:** Schnittstelle `EventBus` und `InProcessBus` in `va-platform`, Handler in
  den Modulen. `main.py` verdrahtet nur noch.
- **Review:** `/simplify` zusätzlich, weil hier der größte Umbau zusammenläuft.

#### P1.9 Aufräumen

- **Test:** keine neuen. Der import-linter läuft ohne Ausnahmen durch.
- **Implementierung:** Die alten Module in `src/` entfernen. CLAUDE.md anpassen (Ort von
  `FIELD_MAP`, Ablauf „Neuer Scoring-Faktor“) und die Projektstruktur im README aktualisieren.

### Phase 2b – Scoring-Profile

#### P2b.1 Profil-Tabellen

- **Test:** DB-Tests:
  - eine Version anlegen und aktivieren, die jüngste Aktivierung gewinnt
  - `UPDATE`/`DELETE` verboten (der Löschschutz-Test greift automatisch)
  - das Profil „Standard“ wird aus ENV angelegt, auch bei wiederholtem Start nur einmal
- **Implementierung:** eine neue Migration (die nächste freie Nummer, `0002` ist durch F1.1
  belegt) mit `protect_table()` sowie ein Repository
  ([scoring-profile.md](scoring-profile.md)).

#### P2b.2 ScoringProfileParams

- **Test:**
  - Validierung: Grenzen, mindestens 2 Faktoren je Gruppe
  - Die Standardwerte entsprechen dem heutigen `ScoringConfig`, die Golden-Files bleiben also
    gleich.
  - Ein abgeschalteter Faktor verändert das Ranking wie erwartet.
- **Implementierung:** Pydantic-Modell und seine Abbildung auf `score()`.

#### P2b.3 Profil-Version im Lauf und in der Mail

- **Test:**
  - DB-Test: `scoring_run` speichert die Profil-Version.
  - Die Golden-Mail zeigt im Footer „Profil Standard v1“. Diese Änderung am Golden-File ist
    beabsichtigt.
- **Implementierung:** Verweis im Lauf, Footer im Template.

### Phase 3 – web-api und Angular

#### P3.1 Gerüst des web-api

- **Test:** Health-Endpoint (TestClient) und OpenAPI-Snapshot.
- **Implementierung:** `services/web-api` mit FastAPI-App, Lifespan und Settings.

#### P3.2 Lese-Endpunkte

- **Test:** API-Tests gegen die Test-Datenbank mit Beispieldaten (Runs, Ranking, Titel,
  gerenderte Mail), Zugriff über die Rolle `va_read`.
- **Implementierung:** Router `runs`, `ranking`, `instruments`, `reports`
  ([web-api-realtime.md](web-api-realtime.md)).

#### P3.3 Profil-Endpunkte und Vorschau

- **Test:**
  - `PUT` mit veraltetem `If-Match` ergibt 409.
  - Die Vorschau mit nur einem Faktor ergibt 422.
  - Aktivieren legt eine neue Aktivierung an.
- **Implementierung:** Router `scoring`, dazu der Port `ScoringPreview`, vorerst im selben Prozess.

#### P3.4 Sicherheitsgrundlagen 🔒

- **Test:**
  - Ein `POST` mit `text/plain` wird abgelehnt.
  - Bei fremdem `Origin` kommen keine CORS-Header.
- **Implementierung:** Mutationen nur mit JSON, CORS bleibt aus
  ([ADR-0007](../adr/0007-lan-only-ohne-login.md)).

#### P3.5 Angular-Gerüst und generierter Client

- **Voraussetzung:** Die UI-Bibliothek ist entschieden.
- **Test:** Vitest-Smoke-Test und ein CI-Job mit `npm ci`, Lint, Test und Build.
- **Implementierung:** Angular-22-Workspace und hey-api-Konfiguration (Angular- und Zod-Plugin)
  auf Basis des OpenAPI-Snapshots.

#### P3.6 frontend-Container 🔒

- **Test:** Container-Smoke in der CI:
  - `nginx -t` läuft durch.
  - `/` und `/runs/1` liefern `index.html`.
  - `/api/v1/health` antwortet über nginx mit 200.
  - Bei unbekanntem Host wird die Verbindung geschlossen (`return 444`).
- **Implementierung:** Dockerfile, `nginx/default.conf` und der Compose-Eintrag
  ([frontend.md](frontend.md)).
- **NAS (du):** Container deployen, Firewall-Regel für Port 8080 auf das eigene Subnetz.

#### P3.7 Ansichten

- **Test:** Komponententests je Ansicht, geschrieben vor der Ansicht selbst: Darstellung,
  Filter, Validierungsmeldungen, Aufruf der Vorschau, Umgang mit 409.
- **Implementierung:** Ranking, Runs, Titel-Detail und der Profil-Editor (Signal Forms mit
  `validateStandardSchema`).

#### P3.8 Schutz der Schnittstelle

- **Test:** CI-Schritt `oasdiff breaking` gegen `main`. Mit einer absichtlich inkompatiblen
  Änderung wird er einmal rot gesehen.
- **Implementierung:** Workflow-Schritt, Referenz ist die OpenAPI von `main`.

### Phase 4 – Events und Echtzeit

#### P4.1 NATS-Infrastruktur

- **Test:** Integrationstest gegen einen NATS-Service-Container: Der Stream `VA_EVENTS` hat die
  Subjects `va.>` und das Deduplizierungsfenster. Die Consumer werden idempotent angelegt.
- **Implementierung:** Compose-Dienst und Provisionierung in `va-platform`
  ([events.md](events.md)).

#### P4.2 Outbox und Inbox

- **Test:** DB-Tests:
  - Ein Event entsteht nur bei Commit, ein Rollback hinterlässt keinen Outbox-Eintrag.
  - Das Relay veröffentlicht offene Einträge und markiert sie.
  - Eine doppelte Event-ID wird nur einmal verarbeitet.
  - `UPDATE` auf der Outbox ist nur für `published_at` erlaubt.
- **Implementierung:** Outbox, Relay und Inbox in `va-platform`.

#### P4.3 NATS als Bus

- **Test:** Die Bus-Vertragstests aus P1.8 laufen zusätzlich gegen NATS und sind dort zunächst rot.
- **Implementierung:** NATS-Implementierung der Bus-Schnittstelle, Umschaltung per Konfiguration.

#### P4.4 Eventmanager und Projektionen

- **Test:**
  - Die Projektion läuft vor dem Broadcast, der Broadcast erst nach dem Commit.
  - Bei einem Fehler gibt es keinen Broadcast, die Exception führt zur Wiederholung.
  - Eine Wiederholung ist idempotent.
- **Implementierung:** Eventmanager, Schema `web` (Migration) und die Projektionen
  ([web-api-realtime.md](web-api-realtime.md)).

#### P4.5 WebSocket-Hub und Protokoll v1 🔒

- **Test:**
  - Ohne Subprotokoll `va.v1` wird die Verbindung abgelehnt, ebenso bei fremdem `Origin`.
  - Abos filtern nach Topic.
  - Eine volle Queue führt zum Schließen mit Code 1013.
  - `resumeFrom` spielt verpasste Events nach bzw. löst `resync` aus.
- **Implementierung:** Hub, Protokoll und Endpunkt `/ws`.

#### P4.6 Echtzeit im Frontend

- **Test:** `RealtimeService` mit Mock-WebSocket:
  - Wiederverbinden mit Backoff
  - `resumeFrom` beim Wiederverbinden
  - Events landen im Store
- **Implementierung:** Service, NgRx-Events und Reducer.

#### P4.7 Runs aus dem UI, Watchdog, Scheduler

- **Test:** mit einer steuerbaren Uhr:
  - Der Watchdog meldet einen Timeout.
  - Derselbe Cron-Termin erzeugt nur einen Run.
  - Ein Start aus dem UI legt einen Run an.
- **Implementierung:** Run-Verwaltung im web-api und Anzeige des Fortschritts im UI.

#### P4.8 Vorschau und Profil-Befehle über NATS

- **Test:** Die API-Tests aus P3.3 laufen unverändert über den RPC-Adapter.
- **Implementierung:** Request/Reply-Adapter für `ScoringPreview` und die Profil-Befehle.

### Phase 5 – Aufteilen in Services

#### P5.1 Images je Service

- **Test:** Smoke-Test je Image (Import, Startbefehl) und die J4125-Prüfung aus P0.6.
- **Implementierung:** Dockerfiles mit `uv sync --package`, CI baut alle Images
  ([betrieb-synology.md](betrieb-synology.md)).

#### P5.2 End-to-End-Test des ganzen Stacks

- **Test:** Die CI startet den kompletten Compose-Stack, löst über die API einen Dry-Run aus und
  vergleicht die Mail mit dem Golden-File.
- **Implementierung:** Compose-Datei für die CI und Warte-Logik auf `notification.report.sent`.

#### P5.3 Eine DB-Rolle je Service 🔒

- **Test:** Rechte-Tests, z. B. die Rolle `va_scoring` kann das Schema `market_data` nicht lesen.
- **Implementierung:** Migration mit den Service-Rollen, `va_app` entfällt.

#### P5.4 Scheduler im web-api

- **Test:** Cron-Termin mit Zeitzone `Europe/Berlin`, derselbe Termin erzeugt nur einen Run.
- **Implementierung:** Scheduler im web-api, der Cron im Container entfällt.

#### P5.5 Tracing

- **Test:** Mit einem In-Memory-Exporter erzeugt ein Run zusammenhängende Spans über Publish und
  Consume hinweg.
- **Implementierung:** OpenTelemetry in FastAPI und FastStream, Weitergabe der run_id.

#### P5.6 Abschluss-Doku

- **Test:** Der Link-Check der Doku läuft durch.
- **Implementierung:** CLAUDE.md auf die Zielarchitektur umschreiben, dazu ein Runbook für die NAS.

### Track F – Fundamentaldaten und Anker (ADR-0010, ADR-0011)

Grundlage ist die [Recherche](../research/fundamentalanalyse-sota/bericht.md). Der Track läuft
neben den Phasen. Die Voraussetzungen stehen bei jedem Paket, Zyklus und Definition of Done gelten
unverändert.

- **F1 (Daten sichern)** ist mit
  [ADR-0010](../adr/0010-stichtagsdaten-konsens-quartale-kurse.md) beschlossen. Das Paket ist
  vorgezogen wie Phase 2, weil sich Konsens- und Quartalsdaten nicht nachholen lassen.
  - F1 speichert nur. Ranking und Mail ändern sich nicht, deshalb kann F1 parallel zu Phase 0
    laufen.
  - Vor Phase 1 entsteht der Code in `src/`, danach im Yahoo-Adapter (P1.4) bzw. in
    `domain/metrics` (P1.3).
  - Ändert ein Phase-0-Paket dieselbe Datei, etwa `data_fetcher.py` in P0.5, wird zuerst das
    Phase-0-Paket gemergt.
- **F2 und F3 (Auswertung)** setzen voraus, dass
  [ADR-0011](../adr/0011-fundamentale-anker-und-belegte-faktoren.md) akzeptiert ist. Es ist derzeit
  nur vorgeschlagen. Bis zur Annahme wird kein F2- oder F3-Paket begonnen, entschieden wird nach
  P1.5 und P2b.2.
  - F2 baut außerdem auf P1.3, P1.5 und P2b.2 auf. Neue Faktoren und Regeln kommen zunächst
    abgeschaltet, die Golden-Files bleiben dabei gleich. Erst F2.5 aktiviert das Standardprofil v2
    und aktualisiert die Golden-Files bewusst.
  - F3.1 folgt nach P2b.2, F3.2 nach P3.7.
- **Tests ohne yfinance-Mocks** (CLAUDE.md): Parser und Kennzahlen werden gegen aufgezeichnete
  Rohdaten als JSON-Fixtures geprüft. Die Abruf-Funktionen selbst gehören nicht zur Test-Suite.

#### F1.1 Konsens-Snapshots

- **Voraussetzung:** Phase 2 ist auf der NAS deployt, sonst wird nichts gespeichert.
- **Test:**
  - Ein Parser-Test mit aufgezeichneten Antworten von `eps_trend`, `eps_revisions`,
    `earnings_estimate`, `revenue_estimate`, `growth_estimates` und `analyst_price_targets`.
  - DB-Tests: Je Titel, Abruf und Art entsteht eine Zeile. Ein zweiter Abruf ergänzt Zeilen und lässt
    die alten stehen. `UPDATE` und `DELETE` sind verboten, das prüft der Löschschutz-Test.
  - Fehlt eine Tabelle oder schlägt ihr Abruf fehl, bleibt der Titel erhalten. Der Fehler steht in
    der Konsens-Zeile (`status = 'error'`, Spalte `error`). Die Snapshot-Spalte `errors` bleibt
    unberührt, weil sonst die CSV ihr Aussehen änderte.
- **Implementierung:**
  - Tabelle `market_data.consensus_snapshot` (`fetch_run_id`, `instrument_id`, `kind`,
    `fetched_at`, `status`, `payload` JSONB, `error`) mit `protect_table()`, Migration `0002`
  - Repository `write_consensus`/`get_consensus`
  - Umwandlung und Fehlertoleranz im neuen Modul `src/consensus.py`, der Abruf
    (`fetch_consensus`) in `data_fetcher`
- **Review:** Gemessen am 30.09.2026 an 8 DAX/MDAX-Titeln: Der Konsens-Abruf kostet im Median
  0,26 s je Titel, also rund 25 s je Lauf. yfinance teilt dabei die Antworten zwischen den Arten.
  Der Basisabruf dauert im Median 0,88 s je Titel.
- **NAS (du):** Nur deployen, die Migration läuft beim Start.

#### F1.2 Quartalsabschlüsse

- **Voraussetzung:** wie F1.1.
- **Test:**
  - Ein Parser-Test mit aufgezeichneten Quartals-Statements.
  - DB-Tests: `statement_value` versioniert mit `frequency = 'quarterly'` genauso wie `annual`,
    also neue Zeile nur bei geändertem Wert.
  - `get_statements_as_of(…, frequency="quarterly")` liefert Quartale getrennt von den
    Jahreswerten.
- **Implementierung:** `quarterly_income_stmt`, `quarterly_balance_sheet` und
  `quarterly_cashflow` abrufen und über `write_statements(..., frequency="quarterly")` speichern.
  Die Spalte `frequency` ist freier Text, eine Migration ist nicht nötig.

#### F1.3 Historie der Aktienanzahl

- **Voraussetzung:** wie F1.1.
- **Test:**
  - Parser-Test: Eine aufgezeichnete `get_shares_full`-Serie wird zu einem Wert je Tag (bei
    mehreren Werten am selben Tag gilt der letzte).
  - DB-Tests: Eine Zeile entsteht nur für ein neues Datum oder einen geänderten Wert.
- **Implementierung:** Tabelle `market_data.share_count` (`instrument_id`, `as_of`, `shares`,
  `first_seen_fetch_run_id`, `first_seen_at`) mit `protect_table()`. Beim ersten Abruf ab
  2000-01-01, danach ab dem letzten gespeicherten Datum.

#### F1.4 Kurshistorie

- **Voraussetzung:** wie F1.1.
- **Test:**
  - Ein Parser-Test mit einer aufgezeichneten Antwort von
    `history(auto_adjust=False, actions=True)`.
  - DB-Tests: die Erstbefüllung, die inkrementelle Ergänzung und der Split-Fall. Ändern sich alte
    Kurse durch einen Split, entstehen neue Versionen, und die alten bleiben erhalten.
- **Implementierung:** Tabelle `market_data.price_bar` (`instrument_id`, `trade_date`, `close`,
  `adj_close`, `dividend`, `split`, `first_seen_fetch_run_id`, `first_seen_at`) mit
  `protect_table()`. Der erste Abruf holt `period="max"`, danach die letzten 40 Handelstage.
- **Review:** Den Speicherbedarf nach der Erstbefüllung messen. Erwartet werden rund 0,7 Mio. Zeilen
  im niedrigen zweistelligen MB-Bereich.
- **NAS (du):** Der erste Lauf nach dem Deployment dauert wegen der Erstbefüllung länger.

#### F2.1 Bilanzqualität: F-Score, Accruals, CFO/Bilanzsumme

- **Voraussetzung:** P1.3, P1.5, P2b.2.
- **Test:**
  - Kennzahlen-Tests mit Fixtures echter Titel und von Hand nachgerechneten Erwartungswerten:
    - jedes der neun F-Score-Signale einzeln
    - fehlende Vorjahreswerte ergeben `None`, nicht 0
    - `operating_accruals` und `cfo_assets` mit Vorzeichen
  - Scoring-Test: Die drei Faktoren stehen im Katalog und sind im Profil v1 abgeschaltet. Die
    Golden-Files bleiben unverändert.
- **Implementierung:**
  - Die Funktionen kommen nach `va_market_data.domain.metrics`, die Felder in `QualityMetrics` und
    in den Snapshot (additive Migration).
  - Die Katalogeinträge kommen nach `va_scoring`.
  - `FIELD_MAP` wird um fehlende Zeilen ergänzt, etwa Umlaufvermögen, kurzfristige
    Verbindlichkeiten, Aktienanzahl und Umsatzkosten.
- **Review:** Die Definitionen sind gegen Piotroski (2000) und Sloan (1996) geprüft und im Code
  als Quelle genannt.

#### F2.2 Netto-Aktienemission

- **Voraussetzung:** F1.3, F1.4 (für die Splits), P2b.2.
- **Test:**
  - Die 12-Monats-Veränderung aus Fixture-Serien: Ein Rückkauf ergibt einen negativen Wert, eine
    Kapitalerhöhung einen positiven. Ein Split zählt nicht als Emission.
  - Scoring-Test: Negative Werte bleiben im Ranking. Der Ausschluss negativer Multiples greift hier
    nicht, weil `net_share_issuance` kein Multiple ist. Im Profil v1 ist der Faktor abgeschaltet.
- **Implementierung:** Die Kennzahl kommt nach `domain.metrics`, dazu der Katalogeintrag. Der
  Katalog bekommt ein Kennzeichen „kein Multiple“, das den Ausschluss negativer Werte je Faktor
  steuert.

#### F2.3 Momentum und Value-Trap-Regel

- **Voraussetzung:** F1.4, F2.1, P2b.2.
- **Test:**
  - Das 12-1-Momentum aus Fixture-Kursen: auf Basis von `adj_close`, der letzte Monat ausgelassen.
    Eine zu kurze Historie ergibt `None`.
  - Flag-Tests: Nur die Kombination aus hohem Value-Score, schwachem Momentum und schwachem F-Score
    setzt die neue Regel. Das Ergebnis nennt den Grund („quality“ oder „momentum“).
  - Mit abgeschalteter Regel (v1) bleiben die Golden-Files unverändert.
- **Implementierung:** Die Kennzahl `momentum_12_1` entsteht in `market-data` aus `price_bar` und
  reist im Snapshot mit. Neue Profil-Parameter: `trap_momentum_rule` (an/aus),
  `trap_momentum_max_rank` und `trap_fscore_max`. Momentum geht nicht in den Composite ein.

#### F2.4 Branchenregeln und Abschnitt „Finanzwerte“

- **Voraussetzung:** P2b.2, F2.1.
- **Test:**
  - Bei Banken und Versicherern werden die ausgeschlossenen Faktoren nicht gerankt. Die Titel
    fallen unter den Mindestanteil und erscheinen in der Liste „Finanzwerte“ mit P/B, P/E, ROE und
    dem gerechtfertigten P/B.
  - Für alle anderen Titel ändern sich die Ränge nur, weil die Finanzwerte aus dem Querschnitt
    fallen.
  - Mit abgeschalteter Regel (v1) bleiben die Golden-Files unverändert.
  - Renderer-Test: Der Abschnitt erscheint nur, wenn Titel betroffen sind.
- **Implementierung:** Die Klassifikation läuft über die Yahoo-`industry` mit einer Präfix-Liste im
  Profil. Dazu kommen der Parameter `industry_rules` (an/aus), die Liste im Ergebnis und ein
  Template-Abschnitt.
- **Immobilien:** Die Präfix-Liste folgt aus der Vorprüfung zu ADR-0011: Enthält das EBIT von
  Vonovia, LEG, TAG und Aroundtown Bewertungsergebnisse nach IAS 40? Ein Test mit deren
  gespeicherten `statement_value`-Zeilen sichert die Einstufung ab.
- **Review:** Es wird kein Rang innerhalb einer Branche berechnet.

#### F2.5 Standardprofil v2 aktivieren

- **Voraussetzung:** F2.1 bis F2.4.
- **Test:**
  - Die Version 2 des Profils „Standard“ enthält die Werte aus ADR-0011.
  - Ein Rescore mit v1 reproduziert das alte Ranking.
  - Die Golden-Files werden bewusst aktualisiert: neues Ranking, Abschnitt „Finanzwerte“, die
    Spalte „Abdeckung“ (vorhandene Faktoren x/y je Titel) und der Footer „Standard v2“.
- **Implementierung:** Seed-Migration für v2 samt Aktivierung, dazu die Spalte „Abdeckung“ im
  Report.
- **Review:** Die Top- und Flop-Listen von v1 und v2 werden auf einem echten Snapshot verglichen und
  die Unterschiede in der Abnahme begründet.
- **Doku:** Den Methodik-Abschnitt in CLAUDE.md auf den neuen Ist-Stand umschreiben.
- **NAS (du):** v2 wirkt ab dem nächsten Lauf. Rollback heißt: v1 aktivieren.

#### F3.1 Ertragskraftwert und implizites Wachstum

- **Voraussetzung:** P1.5, P2b.2.
- **Test:** Die reinen Funktionen werden an Hand-Beispielen geprüft:
  - EPV aus dem Mittelwert der verfügbaren EBIT-Jahre, der effektiven Steuerquote und der
    Nettoverschuldung
  - Preis/EPV
  - Reverse DCF per Bisektion. Bei negativem FCF oder ohne Lösung zwischen −20 % und +40 % gibt es
    kein Ergebnis.
  - Sensitivität bei ±1 Prozentpunkt Kapitalkosten
  - DB-Test: Die Anker je Lauf landen in `scoring.anchor_value` (Long-Format: `scoring_run_id`,
    `instrument_id`, `anchor`, `value`).
- **Implementierung:**
  - `va_scoring.domain.anchors` mit den Profil-Parametern `cost_of_capital` (0,08),
    `terminal_growth` (0,02) und `dcf_years` (10).
  - Die CSV bekommt die Spalten `price_to_epv` und `implied_fcf_growth`. Die Golden-CSV wird
    bewusst aktualisiert.
  - Für Finanzwerte gibt es keine EPV-Anker, dort gilt das gerechtfertigte P/B aus F2.4.
- **Review:** Die Werte von drei bekannten Titeln sind plausibilisiert.

#### F3.2 Titel-Detail: Anker, Wertlinie und Renditezerlegung

- **Voraussetzung:** P3.2, P3.7, F1.2 bis F1.4, F3.1.
- **Test:**
  - API-Tests: Die Wertlinie ist Gewinn bzw. FCF je Aktie mal dem Median-Multiple der eigenen
    Historie, bei Finanzwerten der Buchwert je Aktie. Bei der Renditezerlegung ergibt die Summe der
    Teile die Gesamtrendite, bis auf Rundung.
  - Bei zu kurzer Historie bleibt die Linie leer, statt geschätzt zu werden.
  - Komponententest der Ansicht mit Chart und Sensitivität der Anker.
- **Implementierung:** Endpunkt `GET /api/v1/instruments/{id}/anchors` und Chart im Titel-Detail.
- **Review:** Das UI zeigt an, wie viele Jahre die Wertlinie abdeckt.
