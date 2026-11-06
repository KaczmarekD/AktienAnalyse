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

1. `make check`: Ruff (Lint und Format), Pyright, import-linter (seit P1.1), Pytest
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

#### P0.6 J4125-Prüfung

- **Test:** J4125-Prüfung (`make check-j4125` und CI-Schritt): Stufe `j4125-check` im
  Dockerfile, Python unter `qemu-x86_64 -cpu Denverton` (Goldmont, ohne AVX; ein
  Goldmont-Plus-Modell hat QEMU nicht). Gegenprobe mit einer AVX2-Instruktion, die mit SIGILL
  enden muss. Details in [Betrieb auf der Synology](betrieb-synology.md).
- **Grün:** CI-Job „Docker Build + J4125-Pruefung“ grün.

#### P0.6b Images aus der CI nach GHCR

Eigenes Paket nach P0.6. F1 wartet nicht darauf.

- **Test:** zwei CI-Schritte, beide rot ohne die Änderung:
  - Smoke-Test `docker run --rm --entrypoint python value-analyzer:ci -c "import src.main"`. Das
    Image wurde bisher gebaut, aber nicht geladen.
  - `docker compose config --images` muss `ghcr.io/kaczmarekd/value-analyzer:latest` liefern.
- **Implementierung:**
  - Statt einer eigenen `images.yml` schiebt der Job „Docker Build + J4125-Pruefung“ in `ci.yml`
    das geprüfte Image nach GHCR. Er läuft nach `quality` (`needs`), also bekommen nur getestete
    Commits ein Image. Ein paralleler zweiter Workflow könnte ein Image eines roten Commits
    veröffentlichen. Getrennte Workflows mit Pfadfiltern kommen mit mehreren Images (P5.1).
  - Gepusht wird nur auf `main` und bei Tags `v*`. Tags: `sha-<commit>` immer, `latest` von
    `main`, `<version>` bei einem Git-Tag `v<version>`. Eine Versionsnummer wird so nicht von
    jedem Merge überschrieben.
  - Compose nutzt `image: ${REG:-ghcr.io/kaczmarekd}/value-analyzer:${VERSION:-latest}` ohne
    `build:`. `make build` baut lokal unter demselben Namen, `make pull` lädt aus GHCR.
- **Grün:** Workflow grün, Image liegt in GHCR. Der Push läuft erst nach dem Merge auf `main`.
- **Review:** Gemessen am 19.10.2026: Das Image ist 818 MB groß. Größter Posten ist pyarrow mit
  156 MB von 460 MB Paketen, es wird nur für den Altdaten-Import gebraucht. Keine Secrets im
  Image: `.env` ist per `.dockerignore` ausgeschlossen, in `data/` liegt nur die Fallback-CSV.
- **NAS (du):** `git pull` (neue Compose-Datei), bei privatem Paket einmalig
  `docker login ghcr.io`, dann `docker compose pull`, Import-Test, `docker compose up -d`
  (Ablauf im README unter „Update“).

#### P0.7 Fix-Paket Perioden und inf

Aus dem Review von Phase 0 entstanden.

- **Test:** Spalten ohne gültiges Periodenende (NaT, `None`, Zahlen-Labels) und ein Überlauf in
  `_safe_div` (rot).
- **Implementierung:** Eine Periodenregel für Kennzahlen und `statement_value`, gerechnet wird nur
  mit datierten Spalten, `inf` wird zentral zu `None`.

#### P0.8 Fix-Paket Infrastruktur

Aus dem Gesamt-Review am 19.10.2026 entstanden (P0.6b, P1.1).

- **Test:** `tests/test_image_tags.py` für die Image-Tags (rot). Gegenprobe zum Docker-Cache:
  zwei Builds, dazwischen eine Code-Änderung in `packages/`.
- **Implementierung:**
  - `docker/image_tags.py`: `latest` nur, wenn der Commit noch der Kopf von `main` ist; ein
    Versions-Tag muss `vX.Y.Z` sein und zu `pyproject.toml` passen, sonst kein Push.
  - Dockerfile bindet beim `uv sync` nur die `pyproject.toml` der Mitglieder ein: Code-Änderungen
    in `packages/` und `services/` lassen die Abhängigkeitsschicht im Cache (gemessen).
    `.dockerignore` schließt `__pycache__` in allen Ebenen aus.
  - CI: Workflow-Standard `contents: read`, Actions auf aktuelle Major-Versionen (Node 24),
    `migrations/` in Ruff und Pyright, Coverage auch für `va_contracts`.
  - Ruff kennt die Workspace-Pakete als first-party, `make help` zeigt auch Targets mit Ziffern,
    `make build` taggt mit `REG`/`VERSION`.
  - Doku: Update-Ablauf für die NAS (README), CI-Abschnitt, Projektbaum, Rezept für ein neues
    Workspace-Mitglied (CLAUDE.md).

### Phase 1 – Modularer Monolith

Voraussetzung ist P0.1. Die Pakete laufen nacheinander. Grundregel: **Die Golden-Files dürfen
sich in ganz Phase 1 nicht ändern.**

#### P1.1 Workspace-Pakete und Grenzen

- **Test:** import-linter-Verträge (Unabhängigkeit der Services, Schichten innerhalb eines
  Service) als CI-Schritt, zunächst gegen die leeren Gerüste.
- **Implementierung:** Gerüste für `packages/va-contracts`, `packages/va-platform`,
  `services/market-data`, `services/scoring` und `services/notification`. Die Composition Root
  bleibt vorerst beim Batch.
  - Paketnamen `va-<name>`, Import-Namen `va_<name>`, Build-Backend `uv_build`. Die Services
    hängen von `va-contracts` und `va-platform` ab, `va-platform` von `va-contracts`.
  - Die Mitglieder stehen in der Dev-Gruppe des Root-Projekts: Tests, Pyright und import-linter
    sehen sie, ins Image kommen sie noch nicht. Ab P1.3, wenn der Batch sie nutzt, werden sie
    normale Abhängigkeiten.
  - Der Docker-Build bindet `packages/` und `services/` ein. Ohne die Verzeichnisse bricht
    `uv sync --locked` ab, weil das Lockfile Workspace-Mitglieder nennt.
  - Neben den beiden Verträgen aus [code-struktur.md](code-struktur.md) gibt es drei weitere:
    Die geteilten Pakete kennen keine Services, `va_contracts` kennt `va_platform` nicht, und
    kein neues Paket importiert den Altbestand `src`. `va_web_api` kommt mit P3.1 dazu.
- **Grün:** Standard plus `lint-imports` (`make imports`, CI-Schritt „Import-Grenzen“).
- **Review:** Paketnamen und Abhängigkeiten zwischen den Workspace-Mitgliedern. Gegenprobe am
  19.10.2026: Je ein eingebauter Verstoß gegen jeden der fünf Verträge wurde erkannt.

#### P1.2 Contracts v1

- **Test:** JSON-Schema-Snapshots und Hin-und-zurück-Tests für `Fundamentals` ↔ `FundamentalsV1`,
  Ranking-Zeilen, Event-Payloads und die Envelope.
- **Implementierung:** Pydantic-Modelle in `va_contracts.events.v1`
  ([events.md](events.md)).
  - `FundamentalsV1` hat dieselben Gruppen und Feldnamen wie die Dataclasses, ohne Rohdaten.
    `to_flat()` ergibt die Spalten von DataFrame und CSV. `RankingRowV1` enthält
    Fundamentaldaten plus Scores, flach entspricht es der Ausgabe von `score()`.
  - Der Katalog (`EVENTS`, je Event ein `EventSpec`) legt Typ, Subject, Payload-Modell und
    Dataschema fest. `new_envelope(spec, data, source=…)` erzeugt die Hülle mit UUIDv7
    (`uuid.uuid7()` aus Python 3.14).
  - Alle Modelle erben von `Contract`: unveränderlich, unbekannte Felder werden ignoriert
    (additive Weiterentwicklung), NaN und inf werden abgelehnt.
  - Die Tests liegen in `tests/test_contracts_v1.py`, die JSON-Schemas als Golden-Files unter
    `tests/golden/contracts/v1/`. `va_contracts` darf `src` nicht kennen, deshalb prüfen die
    Tests die Passung zu `src.fundamentals` und `score()` von außen, mit dem Golden-Datensatz.
- **Review:** Feldnamen stabil, optionale Felder bewusst gewählt.
  - In `FundamentalsV1` sind nur Symbol, Name und Index Pflicht. Die Event-Payloads haben mehr
    Pflichtfelder: die IDs (ab 1) und je nach Event etwa `trigger`, `options`, `stage`,
    `reason`, `as_of` oder `universe`. `run_id` ist genau bei einem Rescore leer, ein Validator
    prüft das. `profile` bleibt bis Phase 2b leer.
  - Nachgeschärft nach dem Gesamt-Review (19.10.2026), solange noch kein Event gespeichert
    wird: Trigger und Run-Optionen reisen mit, `scoring.run.completed` enthält Universum,
    Gewichte, `fetch_run_id` und `as_of`, das Ranking ist nie leer, `composite_score` hat keine
    Obergrenze (Gewichte werden erst ab 1 % Abweichung normiert), `dataschema` ist eine URN,
    `parse_envelope` wählt auf der Empfängerseite das Modell, `from_flat` macht aus NaN wieder
    `None`. Ein Test rendert die Golden-Mail allein aus `scoring.run.completed`. Ein weiterer
    import-linter-Vertrag hält pandas, numpy, SQLAlchemy, psycopg und yfinance aus
    `va_contracts` heraus.
  - `ERRORS_SEPARATOR` steht wegen der Import-Grenze zweimal (`src.fundamentals` und
    `va_contracts`). Der Flat-Test bemerkt, wenn beide auseinanderlaufen. Mit P1.9 entfällt die
    Kopie in `src`.

#### P1.3 Kennzahlen als reine Funktionen

- **Test:** Kennzahlen-Tests auf Basis gespeicherter Rohdaten echter Titel (JSON-Fixtures, aus
  der Datenbank exportiert oder einmalig aufgezeichnet). Die Erwartungswerte entstehen einmalig
  mit dem heutigen Code. Die Helfer-Tests aus `test_data_fetcher.py` ziehen mit um. yfinance wird
  dabei weiterhin nicht gemockt.
- **Implementierung:** `va_market_data.domain.metrics`. `data_fetcher` ruft die Funktionen auf,
  bis P1.4 den Adapter einführt.
  - `compute_metrics(StatementFigures, MarketFigures, fx=…)` rechnet alle Kennzahlen inklusive
    FX-Umrechnung und Free-Cash-Flow-Ersatz. `data_fetcher` liest nur noch aus (`FIELD_MAP`,
    `info`, Periodenregel, FX-Abruf) und übernimmt das Ergebnis in die `Fundamentals`.
  - Sicherungstests: Rohdaten von sieben echten Titeln (`tests/fixtures/metrics/`, darunter Bank,
    Versicherer, Immobilien und Qiagen mit USD-Abschluss), Erwartungswerte als Golden-Files aus
    dem Code vor dem Umbau (`tests/golden/metrics/`). Sie blieben unverändert grün, ebenso die
    Golden-Mail.
  - Service-Tests liegen unter `services/market-data/tests/` (in `testpaths`).
  - `va-market-data` ist seit P1.3 eine Laufzeitabhängigkeit. Das Dockerfile installiert erst
    die Fremdpakete ohne Workspace (`--no-install-workspace`, große Schicht, bleibt im Cache),
    dann die Mitglieder nicht-editierbar (`--no-editable`, kleine Schicht).
- **Review:** Im Domain-Code gibt es keine Ein-/Ausgabe. Ein import-linter-Vertrag verbietet
  yfinance, requests, SQLAlchemy, psycopg und Alembic in allen `domain`-Schichten.
  - Verhaltensgleichheit am 19.10.2026 belegt: 4.000 Zufallsfälle gegen den alten `fetch_one`
    ohne Abweichung, dazu eine Golden-Variante „Qiagen ohne Wechselkurs“ aus dem alten Code.
  - Nachgeschärft: Die Domain bekommt die Reihen roh (mit Lücken) und wendet „4 von 5 Jahren“
    selbst an. Die Prozent-Eigenheit der Dividendenrendite und das Parsen von Zahlen bleiben
    beim Abruf. `default_tax_rate` ist Pflicht (Wert aus den Settings). Lokale Builds holen
    geänderten Code der Mitglieder per `--refresh-package` ins Image.
  - Bekannt und bewusst unverändert (Golden-Files): Fehlt ein Jahr in der Mitte, rechnet die
    CAGR über die vorhandenen Werte, als lägen sie direkt hintereinander (Beispiel
    100, –, 80, 70, 60 ergibt 18,6 % statt 13,6 %). Betrifft nur die Wachstumswerte, die nicht
    in den Composite eingehen. Eine Korrektur wäre eine bewusste Änderung der Golden-Files.

#### P1.4 Adapter für Yahoo und Universum hinter Ports

- **Test:** Tests der Universum-Kette mit Fake-Quellen: Die erste gültige Quelle gewinnt,
  ungültige fallen durch, die CSV kommt zuletzt. Die Parser-Tests der Adapter ziehen mit um.
- **Implementierung:**
  - Ports `UniverseSource` und `FundamentalsProvider`
  - Adapter `ishares`, `deka`, `csv_universe`, `openfigi` sowie `yahoo` (mit `FIELD_MAP`)
- **Review:** Validierungsregeln unverändert (40/50 Aktien, Stichtag höchstens 10 Tage alt).
- **Umgesetzt (19.10.2026):**
  - `domain`: `fundamentals`, `consensus`, `history`, `periods` (Periodenregel), `universe`
    (Ticker, Validierung, Abgleich mit der CSV). `va_platform.serialization`: `json_safe`,
    `to_python`.
  - `application`: Ports `UniverseSource`, `FundamentalsProvider`; Kette `load_universe`,
    Abrufschleife `fetch_all`.
  - `adapters`: `yahoo` (`YahooFundamentals`, `FIELD_MAP`), `ishares`, `deka`, `openfigi`,
    `csv_universe`, `http`.
  - `src/universe.py` und `src/data_fetcher.py` verdrahten bis P1.8 mit unveränderter
    Schnittstelle; der Pfad der Fallback-CSV kommt von dort, weil das Paket im Image in
    site-packages liegt. `src/db/serialization.py` reicht bis P1.7 weiter.
  - Tests: Kette und Schleife mit Fakes (neu, rot zuerst), Parser- und Adaptertests unter
    `services/market-data/tests/`; `consensus`/`history` bleiben vorerst unter `tests/`, weil
    sie Fixtures mit den DB-Tests teilen. Live geprüft: iShares liefert 90 Titel.

#### P1.5 Scoring-Modul

- **Test:** `test_scoring.py` zieht mit um. Ein Sicherungstest prüft, dass das Ranking für den
  Golden-Datensatz identisch bleibt.
- **Implementierung:** `va_scoring.domain.scoring`.
- **Umgesetzt (19.10.2026):** `src/scoring.py` unverändert verschoben, `va-scoring` ist
  Laufzeitabhängigkeit (Image: `--refresh-package va-scoring`). Tests unter
  `services/scoring/tests/`. Golden-Mail mit `ranking.csv` und Kennzahlen unverändert.

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
- **Umgesetzt (19.10.2026):** `va_notification.domain.report` (Template als Paketdatei
  `templates/report.html.j2`, im Image geprüft), Ports `ReportSender`/`Heartbeat`, Adapter
  `smtp` (eigene `SmtpConfig` statt der Settings) und `healthchecks`. `src/mailer.py`
  verdrahtet bis P1.8. Der Name der Fallback-Quelle steht in notification eigens, ein Test
  vergleicht ihn mit market-data. Golden-Mail unverändert.

#### P1.7 Datenbankzugriff je Modul

- **Test:** `tests/db/` nach Modulen aufteilen. Der Löschschutz-Test bleibt übergreifend.
- **Implementierung:** Modelle und Repositories ziehen zu ihrem Besitzer-Modul. Engine, Session
  und DDL-Helfer kommen nach `va-platform`. Die Alembic-Historie bleibt vorerst eine einzige.
- **Review:** Keine Fremdschlüssel über Schema-Grenzen.
- **Umgesetzt (19.10.2026):**
  - `va_platform.db`: Basis (`Base`, `APP_SCHEMAS`, `in_values`), Engine/Session, `ddl`
    (Migrationen importieren von dort).
  - `adapters/postgres` je Modul mit Modellen und Repository: `va_market_data` (dazu
    `snapshot_row`/`snapshot_values`), `va_scoring`, `va_notification` (`reporting`).
    `batch` und `RunRepository` bleiben bis P1.8 in `src/db`, ebenso Recorder und
    Altdaten-Import. `src/db/models/__init__.py` sammelt alle Modelle für Alembic.
  - scoring liest das Symbol aus `market_data.instrument` über eine schlanke
    Tabellenreferenz (`sqlalchemy.table`), nicht über das Modell: kein Import über die
    Service-Grenze, kein Fremdschlüssel. Übergang, bis die Symbole mit den Events kommen.
  - Die Services deklarieren ihre Laufzeitabhängigkeiten selbst (u. a. `sqlalchemy`;
    market-data zusätzlich pandas, yfinance, requests, tenacity, openpyxl, die seit P1.4
    nur über das Root-Projekt kamen).
  - Tests: `tests/db/{market_data,scoring,notification,batch}/`, Löschschutz,
    Pipeline und Altdaten-Import übergreifend. Neu `test_schema_boundaries.py`: jedes
    Schema hat genau ein Besitzer-Modul, keine Fremdschlüssel über Schema-Grenzen (Modelle
    und migrierte DB). `alembic check` meldet keine Abweichung der Modelle.

#### P1.8 Event-Bus im Prozess, Composition Root

- **Test:**
  - Vertragstests für die Bus-Schnittstelle: Zustellung, Fan-out, Verhalten bei Fehlern. Sie
    sind über eine parametrisierte Fixture so geschrieben, dass sie später unverändert auch
    gegen NATS laufen.
  - End-to-End-Test: Die Pipeline über den Bus mit Fakes erzeugt die Golden-Mail.
- **Implementierung:** Schnittstelle `EventBus` und `InProcessBus` in `va-platform`, Handler in
  den Modulen. `main.py` verdrahtet nur noch.
- **Review:** `/simplify` zusätzlich, weil hier der größte Umbau zusammenläuft.
- **Umgesetzt (19.10.2026):**
  - `va_platform.bus`: `EventBus`, `InProcessBus` (jede Zustellung als JSON-Kopie,
    Fan-out, Wiederholung bis `max_deliver`, danach `DeadLetter`), `follow_up` für
    Folge-Events (Korrelation = Run, Ursache = auslösendes Event).
  - Handler: market-data `RunRequestedHandler` (Anwendungsfall `take_snapshot`), scoring
    `SnapshotCompletedHandler`, notification `NotificationHandler`. Jeder Handler fängt
    seine Fehler und meldet `screening.run.failed`. Speicher je Modul in
    `adapters/postgres/store.py`; scoring liest Instrument-IDs nur noch (kein Anlegen).
  - `src/composition.py` (`Adapters`, `build_adapters`, `wire`), `src/run_tracker.py`
    (Vorläufer der Run-Projektion im web-api), `src/main.py` startet nur die Kette.
    Im Batch `max_deliver=1`: Die Handler wiederholen nichts selbst, ein zweiter Abruf
    kostete Minuten. Ein Dead Letter beendet den Lauf über `screening.run.failed`.
  - Fällt trotzdem etwas aus dem Bus heraus oder endet die Kette ohne Ergebnis, schließt
    `main.py` den Lauf als `failed` ab und alarmiert (Ping `/fail`, Fehlermail).
  - Contracts: `RunFailedV1.detail` (Traceback für die Fehlermail) additiv, Konstante
    `REASON_NO_DATA`.
    `parse_envelope` parametrisiert mit dem Payload-Modell; vorher verlor ein
    weitergereichtes Event beim Serialisieren seine Payload.
  - Bewusste Unterschiede zum alten Ablauf: Scheitert der Mailversand, bleibt
    `batch.run.report_id` leer (der Report verweist über `run_id` auf den Lauf); scheitert
    der Abruf, bleibt `universe_size` leer. Scheitert market-data nach `start_fetch`, bleibt
    auch `batch.run.fetch_run_id` leer, obwohl der Abruf in `market_data.fetch_run` steht:
    `RunFailedV1` trägt keine `fetch_run_id`. Der Abschluss von `batch.run` ist immer
    „sicher“ (ein DB-Fehler dort ändert den Exit-Code nicht mehr, auch nicht im Dry-Run).
  - Tests: Bus-Verträge (`packages/va-platform/tests`), Handler je Modul, RunTracker,
    Golden-Mail über den Bus (`tests/test_pipeline_bus.py`, HTML byte-gleich).
    `test_main`/`test_pipeline_db` bekommen die Adapter injiziert.

#### P1.9 Aufräumen

- **Test:** keine neuen. Der import-linter läuft ohne Ausnahmen durch.
- **Implementierung:** Die alten Module in `src/` entfernen. CLAUDE.md anpassen (Ort von
  `FIELD_MAP`, Ablauf „Neuer Scoring-Faktor“) und die Projektstruktur im README aktualisieren.
- **Umgesetzt (19.10.2026):** `src/universe.py`, `src/data_fetcher.py` und `src/mailer.py` sind
  in `src/composition.py` aufgegangen (`load_universe`, `DEFAULT_FALLBACK_CSV`, Abruf über
  `YahooFundamentals`, `smtp_config`). In `src/` bleiben der Batch-Einstieg (`main`,
  `composition`, `run_tracker`, `config`, `logging_setup`) und `db` (Schema `batch`,
  Migration, Altdaten-Import). Der import-linter hält alle Verträge ohne Ausnahmen ein,
  `src` heißt dort jetzt „Batch“ statt „Altbestand“. CLAUDE.md (Architektur, Rezepte) und
  README (Projektstruktur) beschreiben den neuen Stand.
- **Gesamt-Review Phase 1 (19.10.2026):**
  - Ein unendlicher Wert (`inf`) wird beim Einlesen in den Contract zu `None` und kostet
    nur dieses Feld, nicht mehr den Lauf (`missing_to_none`).
  - Ein Fehler beim Melden des Fortschritts bricht den Abruf nicht mehr ab.
  - `ERRORS_SEPARATOR` gibt es nur noch im Contract.
  - va-platform deklariert numpy und pandas, der Batch va-contracts und va-platform als
    Laufzeitabhängigkeit.
  - Coverage schließt va_platform ein (pyproject, Makefile, CI).
  - `mock_universe_df` hat eine Quelle (`services/scoring/tests/fixtures/mock_universe.json`).
  - Veraltete Verweise in Docstrings und CLAUDE.md sind korrigiert.

#### P1.10 Fix-Paket Spec-Abgleich

Aus dem Abgleich von Code und Specs am 30.10.2026 entstanden (Stand `8580e7d`, CI grün). Keiner
der Befunde stammt aus dem Umbau in Phase 1, alle sind älter. Ranking und Mail ändern sich nicht,
die Golden-Files der Mail, der Kennzahlen und der Contracts bleiben unverändert. Das Paket kommt
vor P2b.1, weil P2b.1 neue Tabellen anlegt und sich auf den Löschschutz-Test verlässt.

- **Test:**
  - **Jahresabschlüsse:** Ein Netzfehler oder Rate-Limit beim Abruf von `income_stmt`,
    `balance_sheet` oder `cashflow` löst den Retry von `_ticker_data` aus. Nach dem letzten Versuch
    gilt der Titel als nicht abrufbar (`fetch failed`), rot.
    - Heute schluckt yfinance den Fehler (`hide_exceptions`) und liefert eine leere Tabelle. Der
      Retry greift nie, der Titel zählt als Erfolg mit leeren Kennzahlen, und in `errors` steht
      nichts. F1.5 hat das nur für die Zusatzabrufe behoben.
    - Getestet wie in F1.5 mit gepatchter HTTP-Schicht (`YfData.get`) oder einem Fake nach dem
      Muster von `_SwallowingTicker`.
    - Ein leerer Abschluss ohne Fehler bleibt leer und wird kein Fehler.
  - **Löschschutz:** `tests/db/test_protection.py` prüft je Tabelle auch den Schutz gegen UPDATE.
    - Auf jeder Tabelle außer `UPDATABLE_TABLES` muss `va_no_update` stehen, auf diesen dreien
      genau `va_guard_update`. Heute prüft der Test nur DELETE und TRUNCATE.
    - Die Liste der Schemas kommt aus `va_platform.db`, nicht aus einer Kopie im Test. Sonst würde
      ein neues Schema, das in der Kopie fehlt, still nicht geprüft.
    - Gegenprobe: Eine Tabelle ohne UPDATE-Trigger lässt den Test scheitern.
  - **Abschluss eines Laufs:** Ein UPDATE auf `batch.run` oder `market_data.fetch_run`, das
    `finished_at` nicht setzt, wird abgelehnt (rot). Heute lässt `va_guard_finished` beliebig
    viele UPDATEs zu, solange der Lauf offen ist.
  - **Contract:** `FundamentalsV1.from_flat` macht aus `NaT` und `pd.NA` ein `None`, statt den
    Abruf-Schritt scheitern zu lassen (rot). Heute behandelt `missing_to_none` nur NaN und inf.
  - **Dead Letter:** Die Fehlermail nach einem Dead Letter enthält den Traceback, nicht nur
    `repr()` (rot, `src/main.py`).
  - **Steuersatz:** `FetcherConfig` und `YahooFundamentals` verlangen `default_tax_rate`. Heute
    fallen beide still auf eine eingebettete 0,27 zurück (rot).
  - **Sicherungstest Scoring:** Ein Titel ohne Quality-Score bekommt heute den Value-Score als
    Composite und kein Value-Trap-Flag. Der Test macht dieses Verhalten sichtbar, bis über die
    Entscheidung unten befunden ist.
- **Implementierung:**
  - **Jahresabschlüsse:** `_ticker_data` ruft die Abschlüsse in `_yahoo_errors_raised()` ab.
    - Nach dem letzten Versuch kostet der Fehler den ganzen Titel, wie heute jeder Fehler, der aus
      `_ticker_data` herauskommt.
    - Begründung: Ohne Abschlüsse blieben nur P/B und Shareholder Yield, und der Titel bekäme über
      den Value-Score allein trotzdem einen Rang (siehe Entscheidung unten).
  - **Trigger:** `va_guard_finished` verlangt `NEW.finished_at IS NOT NULL`.
    - Dazu eine neue Migration `0005`. Sie schreibt die Funktion selbst aus, statt sie aus
      `va_platform.db.ddl` zu importieren, und `ddl.py` bekommt dieselbe Änderung. So sind frische
      und migrierte Datenbanken gleich.
    - Heute ändern nur `write_run_finish` und `write_fetch_run_finish` diese Tabellen. Beide
      setzen `finished_at`.
  - **Contract:** `missing_to_none` erkennt fehlende Werte ohne pandas-Import. Die Import-Grenze
    von `va_contracts` bleibt.
  - **Dead Letter:** `src/main.py` gibt `traceback.format_exception(dead.error)` weiter.
  - **Steuersatz:** `FetcherConfig.default_tax_rate` hat keinen Default mehr. Der Wert kommt nur
    aus den Settings.
  - **Untergrenze:** Die Untergrenze von 2 Faktoren in `_composite_mean` wird ein Feld in
    `ScoringConfig` (Standard 2). P2b.2 übernimmt es in `ScoringProfileParams`.
  - **yfinance-Namen:** Die `info`-Schlüssel (`marketCap`, `currentPrice`, `priceToBook`,
    `sector` usw.) und der Aufbau des FX-Symbols (`…=X`, `lastPrice`) kommen in eine Tabelle
    `INFO_FIELDS` am Kopf von `yahoo.py`. Heute stehen sie außerhalb der Tabellen, das verletzt
    die CLAUDE.md-Regel „yfinance-Feldnamen“.
  - **Abhängigkeit:** va-platform deklariert `psycopg`, weil die Engine `postgresql+psycopg`
    erzwingt. Heute steht es nur im Root-Projekt.
  - **Defaults im Report:** `build_report` verliert die veralteten Defaults (`version="0.2.0"`,
    Gewichte, `top_n`/`bottom_n`). Aufrufer übergeben sie ohnehin.
- **Doku:**
  - **CLAUDE.md:**
    - Rezept „Neues Workspace-Mitglied“:
      - Laufzeitabhängigkeit statt Dev-Gruppe.
      - Ergänzen: `testpaths`, Coverage (`[tool.coverage.run] source`, `--cov` in Makefile und
        CI) und die eigenen `[tool.uv.sources]` des Mitglieds. Heute würden die Tests eines neuen
        Mitglieds still nicht gesammelt.
    - Earnings Stability rechnet mit σ geteilt durch den Mittelwert der Beträge. So rechnet der
      Code seit dem ersten Commit, die Golden-Files halten das fest. Dasselbe im README.
    - „ADR-0001 bis ADR-0009“ wird „bis ADR-0011“.
    - Rezept „Neue Mail-Empfänger“: dazu `NotificationConfig.recipient` in `src/composition.py`.
    - `INFO_FIELDS` in die Liste der yfinance-Tabellen.
    - „CSV-Vollranking“ heißt: alle bewerteten Titel. Gefilterte und gescheiterte Titel fehlen in
      der CSV, stehen aber in der DB.
    - Rezept „Neues Universum“: `MIN_MARKET_CAP` wird in der Handelswährung verglichen. Das ist
      korrekt, solange das Universum nur `.DE`-Titel hat.
  - **code-struktur.md:**
    - Status und Ist-Analyse auf den Stand nach Phase 1 bringen.
    - Ports wie umgesetzt beschreiben: `load(fallback, cfg, today) -> LiveUniverse`,
      `fetch(ticker, history) -> Fundamentals` und `SnapshotStore` statt `RawFinancials`.
    - Validierung liegt in `domain/universe.py`.
    - Sieben import-linter-Verträge, `src` heißt „Batch“.
  - **architecture/README.md:**
    - Den Statusblock um Phase 0, Phase 1 und F1 ergänzen.
    - pyarrow bleibt für den Altdaten-Import.
    - pandas steht auch in va-platform und notification.
  - **README:**
    - Die Pipeline läuft über den Event-Bus statt über `send_report()`.
    - Das Schema `market_data` enthält auch die F1-Tabellen.
  - **Dieser Plan:**
    - F1.1 bis F1.6: je ein Hinweis, wohin die Module gezogen sind
      (`va_market_data.domain.consensus`/`history`, `adapters/yahoo.py`, `PostgresSnapshotStore`).
    - P2b.1: Die nächste freie Migration ist nach diesem Paket `0006`.
    - P1.2: „Pflicht sind nur Symbol, Name und Index“ gilt für `FundamentalsV1`, nicht für die
      Event-Payloads.
    - F1.3: Ab 2000 angefragt, Yahoo liefert ab etwa 2015.
    - P1.8, bewusster Unterschied: Scheitert der Abruf nach `start_fetch`, bleibt
      `batch.run.fetch_run_id` leer.
  - **Docstrings:**
    - `tests/test_contracts_v1.py`: „Altbestand“ und `main._ticker_label`.
    - `va_platform/__init__.py`: nennt Settings-Basis und Logging, aber nicht den Bus.
    - `services/scoring/tests/conftest.py`: „Kopie“.
    - Kommentar an `RunFailedV1.scoring_run_id`: Das Feld gilt nicht nur beim Rescore. Es ist ein
      `#`-Kommentar und ändert das Schema nicht.
    - Migration `0002`: `src.consensus`.
- **Grün:** Standard. Alle Golden-Files bleiben unverändert.
- **Review:** `/code-review high`. Gegenprobe zum Löschschutz-Test wie bei P1.1: Eine Tabelle ohne
  UPDATE-Trigger einbauen und den Test rot sehen.
- **Bewusst offen:**
  - **Alte Migrationen:** `0001` bis `0004` importieren ihre DDL aus `va_platform.db.ddl`. Ändert
    sich dort später etwas, weichen frische von migrierten Datenbanken ab. Sie bleiben, bis die
    Migrationen in Phase 5 je Service getrennt werden. Ändert eine Migration bestehende DDL (wie
    `0005` die Trigger-Funktion), schreibt sie sie aus, und ein Test vergleicht sie mit `ddl.py`.
    Neue Tabellen bekommen weiter `protect_table()`, den Schutz prüft `test_protection.py`.
  - **`notification.report.sent`** kommt auch bei `notify=False`, ohne dass eine Mail rausging.
    Wird erst mit Phase 3/4 relevant und dann im Contract geklärt.
  - **Randfälle des `InProcessBus`:** ein Fehler in `on_dead_letter` und die Reihenfolge der
    Abonnenten von `screening.run.failed`. Der Batch nutzt je Lauf einen frischen Bus, NATS
    ersetzt ihn in P4.3.
  - **Versandprotokoll:** Alarme aus dem Fallback in `src/main.py` (`notify_failure_without_run`)
    stehen nicht darin.
  - **`frequency` beim Lesen:** Die Lese-Methoden für `statement_value` prüfen `frequency` nicht.
    Ein Tippfehler ergibt ein leeres Ergebnis.
  - **Methodiktext im Template:** Er nennt feste Quartile statt der Schwellen 0,70/0,30. Das kommt
    mit P2b.3 (Profil im Footer).
- **Umgesetzt (30.10.2026):**
  - **Abweichungen vom Plan:**
    - Neben `INFO_FIELDS` gibt es `STATEMENT_FIELDS` (Attribute der Jahresabschlüsse) und
      `FX_FIELDS`. Der Ersatz `financials` für `income_stmt` entfällt, yfinance ab 1.7 hat immer
      `income_stmt`. `INFO_FIELDS` hält den Vorrang wie bisher mit `or`: Beim Kurs gilt
      `regularMarketPrice`, wenn `currentPrice` leer oder 0 ist.
    - Nur die drei Abschlüsse laufen in `_yahoo_errors_raised()`, `info` nicht. Dort verschluckt
      yfinance nur HTTP-Fehlerantworten, Netzfehler und Rate-Limit kommen schon an. Eine
      Fehlerantwort allein des Zusatzabrufs für `info` kostete sonst den ganzen Titel.
    - `build_report` behält die Defaults für `top_n`, `bottom_n` und die Gewichte. Sie
      entsprechen den Konfigurationswerten, und Tests sowie die J4125-Prüfung im Image nutzen
      sie. Nur die veraltete Versionsnummer `0.2.0` wird der Platzhalter `dev`.
    - Die Untergrenze heißt `ScoringConfig.min_factor_count`. Sie landet über `asdict` in der
      Konfiguration jedes neuen `scoring_run`.
  - **Tests:** Rot gesehen haben 13 neue Tests, aus dem erwarteten Grund (`9509864`). Dazu
    kommen:
    - ein Vergleich der Trigger-Funktion zwischen Migration `0005` und `ddl.py`
      (`tests/test_migrate.py`);
    - eine eingebaute Gegenprobe zum Löschschutz: eine Tabelle nur mit DELETE- und
      TRUNCATE-Trigger wird gemeldet.
  - **Live-Probe** am 30.10.2026: Basisabruf mit dem neuen Code für alle 90 Titel der
    Fallback-CSV. Kein Titel gescheitert, keiner mit leeren Abschlüssen oder ohne
    Marktkapitalisierung, im Median 1,0 s je Titel.
  - **Review** (`/code-review high`), behoben in `e1068fe`:
    - Nach einem Rate-Limit wiederholt der Basisabruf nicht mehr, wie die Zusatzabrufe.
    - `errors` nennt die Ursache statt `RetryError[...]`.
    - Ein Test prüft, dass jeder `INFO_FIELDS`-Eintrag mindestens einen Kandidaten hat.
  - **Review, bewusst offen:**
    - Ein Retry lädt auch `info` erneut. Das kostet nur im Fehlerfall zwei Anfragen.
    - `batch.run.error` bekommt nach einem Dead Letter weiter nur die Fehlermeldung. Den
      Traceback hat die Fehlermail.

**Entscheidung, nicht Teil des Pakets: Titel ohne Quality-Score**

> **Entschieden am 30.10.2026: Variante 1**, umgesetzt als eigenes Paket
> [M1](#m1-kein-composite-ohne-beide-teilscores).

- **Bis dahin:** Liegen weniger als 3 von 5 Quality-Faktoren vor, ist der Composite der Value-Score
  allein (`va_scoring.domain.scoring.score`). Das Value-Trap-Flag kann dann nicht greifen.
- **Betroffen:** echte Titel, etwa die Deutsche Bank (2 von 5 Quality-Faktoren). Ein Titel ohne
  Quality-Daten steht damit besser da als einer mit mittelmäßiger Quality. Das widerspricht
  CLAUDE.md: Quality soll Value-Traps unterdrücken.
- **Herkunft:** Das Verhalten stammt aus dem ersten Commit und ist nirgends dokumentiert.
- **Möglichkeiten:**
  1. Kein Composite ohne beide Teilscores: Der Titel bekommt keinen Rang und steht am Ende. Das
     entspricht der Regel aus ADR-0011: Wer unter den Mindestanteil fällt, bekommt keinen
     Composite-Score.
  2. Ein fehlender Teilscore zählt neutral (0,5).
  3. So lassen und in CLAUDE.md dokumentieren, bis F2.4 die Finanzwerte gesondert behandelt.
- **Folgen:** Varianten 1 und 2 ändern Ranking und Golden-Files. Sie gehören deshalb in die
  Entscheidung über ADR-0011 oder in ein eigenes Paket mit `--update-golden`. Der Replay-Vergleich
  aus [regressionstest.md](regressionstest.md) zeigt vorher, welche Titel sich verschieben.

### Methodik-Korrekturen

Bewusste Änderungen am Ranking außerhalb von ADR-0011. Sie liegen nicht in Phase 1, weil dort die
Golden-Files gleich bleiben müssen.

#### M1 Kein Composite ohne beide Teilscores

Entschieden am 30.10.2026 (Variante 1 aus P1.10).

- **Voraussetzung:** P1.10 (Sicherungstest `TestMissingQualityScore`).
- **Test:**
  - Der Sicherungstest aus P1.10 wird bewusst umgedreht: Ein Titel ohne Quality-Score bekommt
    keinen Composite und keinen Rang vor den bewerteten Titeln (rot).
  - Dasselbe für einen Titel ohne Value-Score (rot).
  - Titel ohne Composite stehen nicht in Top- und Flop-Liste der Mail, aber in der CSV, hinter
    allen bewerteten Titeln.
  - Die Golden-Files bleiben gleich: Im Golden-Datensatz haben alle Titel beide Teilscores.
- **Implementierung:** In `score()` entsteht der Composite nur, wenn Value- und Quality-Score
  vorliegen. Das Value-Trap-Flag bleibt wie es ist: Ohne Quality-Score kann es nicht greifen,
  der Titel hat dann aber auch keinen Rang mehr.
- **Review:**
  - Vergleich alt gegen neu mit echten Daten aller 90 Titel: Welche Titel verlieren ihren Rang,
    wie verschieben sich Top 20 und Flop 10?
  - Die Doku zur Methodik (CLAUDE.md, README) nennt die Regel.
- **Folge:** Betroffene Titel zählen in Betreffzeile und Kopf der Mail als „fehlgeschlagen“, und
  der Lauf heißt dann `partial`. So zählt die Mail heute schon Titel unter der Größenschwelle.
  Bis F2.4 einen Abschnitt „Finanzwerte“ bringt, erscheinen betroffene Banken nur in der CSV.
- **Umgesetzt (30.10.2026):**
  - Tests rot in `1ba0454`, Umsetzung in `aa236f4`. Der Composite ist
    `value_weight × Value + quality_weight × Quality`, fehlt ein Teilscore, bleibt er leer. Die
    Golden-Files sind unverändert.
  - **Vergleich alt gegen neu** mit echten Daten aller 90 Titel vom 30.10.2026 (Abruf mit dem
    Code aus P1.10, Zusatzdaten abgeschaltet):
    - Deutsche Bank und Commerzbank standen auf Platz 1 und 2, allein über den Value-Score
      (0,82 bzw. 0,81) ohne Quality-Score. Sie verlieren den Composite.
    - Sonst hat kein Titel nur einen Teilscore. Alle anderen rücken um zwei Plätze auf, ihr
      Composite ist exakt gleich.
    - Neu in der Top 20 sind Ströer und Fuchs. Die Flop 10 und das eine Value-Trap-Flag bleiben
      gleich.
    - Die Mail heißt `[partial 88/90] … Top: Allianz` statt `[ok 90/90] … Top: Deutsche Bank`. Im
      Kopf steht „2 fehlgeschlagen“, `batch.run` steht auf `partial`. Exit-Code und
      Healthcheck-Ping bleiben Erfolg.
  - **Bewusst so belassen** (Entscheidung 30.10.2026): Die Mail zählt Titel ohne Composite
    weiter als „fehlgeschlagen“, der Lauf heißt dann `partial`. Sie getrennt von gescheiterten
    Abrufen zu zählen, änderte Template und Golden-Files und wäre ein eigenes Paket.

### Track U – Umgebungen (lokal und NAS)

Beschlossen am 30.10.2026, Zielbild und Entscheidungen in [umgebungen.md](umgebungen.md).

#### U1 Lokaler Stack

- **Test (rot):**
  - Compose ohne Docker-Daemon (`docker compose config`, in einem temporären Ordner mit einer
    Dummy-`.env`):
    - Lokal wird `value-analyzer` aus dem Arbeitsstand gebaut, hat das Profil `run` und läuft
      ohne Cron.
    - SMTP zeigt fest auf Mailpit (`SMTP_PLAIN`), `HEALTHCHECK_URL` ist leer, auch wenn die
      `.env` etwas anderes sagt.
    - Alle veröffentlichten Ports binden nur an `127.0.0.1`.
    - pgweb nutzt die Rolle `va_read` und `--readonly`.
    - Die Datenbank liegt unter `./.local/pgdata`.
    - Die NAS-Definition allein bleibt, wie sie ist: Image aus GHCR, kein Build, weder
      Mailpit noch pgweb.
  - `SmtpSender` mit `plain`: kein STARTTLS, kein SSL, kein Login.
  - Settings: `SMTP_PLAIN` ist standardmäßig aus und landet in `SmtpConfig`.
- **Implementierung:**
  - `docker-compose.local.yml`: Mailpit und pgweb mit fester Version.
  - `SMTP_PLAIN` in Settings, `SmtpConfig` und `SmtpSender`.
  - `.env.local.example`.
  - `make local-up`, `local-run`, `local-dry`, `local-regression`, `local-logs`, `local-down`.
  - Doku: README, CLAUDE.md.
- **Fertig, wenn:** `make local-up && make local-run` eine echte Mail in Mailpit erzeugt und die
  Ergebnisse in pgweb zu sehen sind.
- **NAS:** nichts. `docker-compose.yml` bleibt die Definition des Live-Betriebs.
- **Umgesetzt (30.10.2026):**
  - Tests rot in `d10dc19`, Umsetzung in `1f0fb42`, Review-Korrektur in `64706f3`.
  - **Abweichung vom Vorschlag:** keine eigene `compose.nas.yaml`. Die bestehende
    `docker-compose.yml` bleibt die NAS-Definition, damit eine NAS nach `git pull` ohne
    Änderung an ihrer `.env` weiterläuft.
  - **Ergänzt:**
    - Der lokale Stack hat einen eigenen Projektnamen (`value-analyzer-local`) und eigene
      Containernamen.
    - Der Port der Datenbank lässt sich über `LOCAL_DB_PORT` verlegen.
    - Grund: Auf dem Entwicklungsrechner lief noch ein `value-analyzer-db` aus dem alten
      Worktree `phase-0` (`restart: unless-stopped`). Er belegte Port 5432 und den
      Containernamen.
  - **Probelauf (30.10.2026, echte Yahoo-Daten):**
    - `make local-up` und `make local-run` laufen durch. In Mailpit liegt die Mail
      `[partial 88/90] … Top: Allianz` mit CSV-Anhang.
    - pgweb zeigt als `va_read` alle Schemas und lehnt Schreibzugriffe ab.
    - Der Lauf steht in `batch.run` (`partial`, Exit 0). Ein Healthcheck-Ping ging nicht raus.
    - `make local-regression` meldet den Lauf als gleich.
  - **Hinweis zum Rechner:** Docker Desktop legt seine Daten auf C: ab (rund 41 GB). Bei einem
    vollen Laufwerk bricht der Image-Build mit `input/output error` ab. Der Speicherort lässt
    sich in Docker Desktop verlegen (Settings → Resources → Advanced → Disk image location).

#### U2 NAS-Daten lokal

- **Test:** Ein Dump aus der Test-Datenbank wird in eine leere lokale Datenbank eingespielt;
  Rollen und Rechte stimmen danach. In eine Datenbank mit Daten wird nichts eingespielt.
- **Implementierung:** `make local-restore DUMP=…` (pg_restore in den lokalen Container) und die
  Beschreibung, wie der Dump von der NAS auf den Rechner kommt.

#### U3 Test auf der NAS (optional)

- **Test:** `image_tags.py` vergibt für `feat/**` ein eigenes Tag (`branch-<name>`), aber nie
  `latest`.
- **Implementierung:** CI schiebt Branch-Images. Ein zweites Compose-Projekt auf der NAS
  (`-p va-test`) bekommt eine eigene Datenbank, gefüllt aus einem Dump der Live-Daten, dazu
  Mailpit und keinen Cron.

#### U4 Analysen im Browser

Entschieden am 31.10.2026: P3.1, P3.2, P3.4, P3.5, P3.6 und aus P3.7 die Ansichten Ranking, Runs
und Titel-Detail kommen vor Phase 2b. Die Pakete stehen unter Phase 3, hier nur das, was U4
an ihnen ändert:

- **Lokal zuerst:** Das web-api läuft bis P3.6 nur im lokalen Stack (`docker-compose.local.yml`)
  unter `127.0.0.1:8000`, mit Swagger unter `/docs`. Auf die NAS kommt es mit dem
  frontend-Container (P3.6). Dort hat es keinen eigenen Port.
- **Ein Image:** Das web-api läuft aus demselben Image wie der Batch, nur mit anderem Befehl
  (`uvicorn`). Eigene Images je Service bleiben bei P5.1.
- **Eigener Lesezugang:** `WEB_API_DATABASE_URL` mit der Rolle `va_read`, dazu eine
  schreibgeschützte Verbindung. Die Zugangsdaten des Batches (`DATABASE_URL`, SMTP) bekommt es
  nicht.
- **Keine Imports aus den Fach-Services:** Das web-api ist ein Service für sich (Vertrag
  „Services importieren einander nicht“). Es liest in P3.2 mit eigenen Abfragen aus den
  Schemas, aus denen ab Phase 4 Projektionen werden.
- **UI-Bibliothek:** Angular Material, entschieden am 31.10.2026.

#### U5 Lokaler End-to-End-Test

Geplant am 31.10.2026 als nächstes Paket, vor P2b.1. Ziel: Ein Befehl auf dem
Entwicklungsrechner prüft die ganze Kette, so wie sie auf der NAS läuft. Die Kette: Universum,
market-data, Datenbank, scoring, notification mit der Mail in Mailpit, web-api hinter nginx und
das UI im Browser.

**Stand vor U5:**
- Der lokale Stack aus U1 und U4 läuft: `make local-up`, `make local-run`, `make local-ui`
  bzw. `make ui`.
- Geprüft wird von Hand: Mail in Mailpit, Daten in pgweb, Ansichten im Browser.
- Jeder Lauf fragt iShares bzw. Deka, OpenFIGI und Yahoo ab. Das dauert und hängt an Yahoo,
  und das Ergebnis ist jedes Mal anders. Feste Erwartungswerte gibt es so nicht.
- Die Angular-Tests (Vitest) laufen gegen nachgebaute HTTP-Antworten, nie gegen das echte
  web-api.
- Die CI prüft nginx vor dem web-api (`docker/frontend-smoke.sh`), aber mit leerer Datenbank.

**U5.1 Replay-Quelle statt Yahoo**
- **Neues Setting `REPLAY_SOURCE`:** der Pfad zu einer Fixture aus `tests/fixtures/replay/`.
  - Ist es gesetzt, liefert der Adapter `va_market_data.adapters.replay` das Universum und die
    Fundamentaldaten aus dieser Datei, über die Ports `UniverseSource` und
    `FundamentalsProvider`.
  - Abgefragt wird dann weder iShares noch Deka, OpenFIGI oder Yahoo. Konsens, Quartale,
    Aktienanzahl und Kurse bleiben leer.
  - Die ISIN kommt aus der Fallback-CSV.
- **Kennzeichnung:** Der Abruf wird mit `provider = "replay"` gespeichert. Der Lauf trägt den
  Pfad in seinen Settings und ist so in der DB nie mit einem echten Abruf zu verwechseln.
- **Schutz:** Die Settings lehnen `REPLAY_SOURCE` ab, wenn `SMTP_PLAIN` aus ist oder
  `HEALTHCHECK_URL` gesetzt ist. Eine Mail mit Replay-Daten kann so nie über Gmail
  hinausgehen.
- **Verdrahtung:** `build_adapters` in `src/composition.py` wählt Universum und Abruf nach
  `REPLAY_SOURCE`.
- **Test (rot):**
  - Fixture → `Fundamentals` → `to_flat_dict()` ergibt wieder die Snapshot-Zeilen.
  - Das Universum hat 90 Titel mit Index und ISIN.
  - Settings: `REPLAY_SOURCE` ohne `SMTP_PLAIN` oder mit `HEALTHCHECK_URL` wird abgelehnt.
  - Mit gesperrtem Socket geht kein Aufruf nach außen.
  - DB-Test: Ein Lauf mit `REPLAY_SOURCE` ergibt dieselben Scores, Ränge und Flags wie die
    Fixture, der Abruf hat `provider = "replay"`.

**U5.2 E2E-Stack und Prüfungen (`make local-e2e`)**
- **Eigener Stack:** Compose-Projekt `value-analyzer-e2e` (`docker-compose.e2e.yml` über den
  beiden anderen).
  - Die Datenbank liegt auf tmpfs, ohne Volume. Wie bei `make test-db` ist sie eine
    Wegwerf-Datenbank: Replay-Daten landen nie in `.local/pgdata`.
  - Eigene Ports, nur auf `127.0.0.1`: UI auf 18080, Mailpit auf 18025. So läuft der Stack
    neben dem lokalen.
  - Das web-api hat keinen eigenen Port und ist wie auf der NAS nur über nginx erreichbar.
- **Ablauf von `make local-e2e`:**
  1. Images aus dem Arbeitsstand bauen.
  2. db, Mailpit, web-api und frontend starten.
  3. Einen Batch-Lauf mit `REPLAY_SOURCE` ausführen.
  4. Die Prüfungen laufen lassen.
  5. Den Stack abbauen, auch bei einem Fehler. Bei Fehlern vorher die Logs ausgeben.
- **Prüfungen:** pytest unter `tests/e2e/` mit Marker `e2e`. Ohne `E2E_BASE_URL` werden sie
  übersprungen, wie die DB-Tests ohne `TEST_DATABASE_URL`.
  - Der Batch endet mit Exit 0, `/api/v1/runs` zeigt den Lauf als abgeschlossen.
  - Mailpit-API: In Mailpit liegt genau eine Mail. Ihr Betreff nennt den Top-Titel der
    Fixture. Die angehängte CSV gleicht der CSV der Fixture inhaltlich, bis auf die
    Datumsfelder. Verglichen wird mit dem Vergleich aus `src/regression/compare.py`.
  - `/api/v1/ranking/latest` über nginx: Scores und Ränge wie in der Fixture.
  - `/api/v1/reports/{id}` liefert dasselbe HTML wie die Mail.
  - Frontend: `/` liefert die App mit den Sicherheits-Headern. Ein unbekannter Host bekommt
    keine Antwort.
- **Frontend ohne Node-Build in Docker:** Auf C: waren am 31.10.2026 nur 3,1 GB frei, und
  Docker Desktop liegt dort. `make local-e2e` baut Angular deshalb mit npm auf E:
  (`frontend/dist`). Build und nginx-Template hängt es in dasselbe Basis-Image
  (`nginx-unprivileged:1.30.6`). Das echte Frontend-Image prüft weiter die CI.
- **CI:** Der Job „Docker Build + J4125-Pruefung“ führt dieselben Prüfungen mit den frisch
  gebauten Images aus und ersetzt damit `docker/frontend-smoke.sh`.
- **Live-Variante `make local-check`:** dieselben Prüfungen ohne Vergleichswerte, gegen den
  laufenden lokalen Stack mit echten Yahoo-Daten nach `make local-run`. Geprüft wird: Lauf
  abgeschlossen, Mail da, Ranking nicht leer, UI erreichbar.

**U5.3 Browser-Test des UI (Playwright)**
- **Setup:** `@playwright/test` im Frontend, nur Chromium. Die Tests laufen gegen den Stack aus
  U5.2, `make local-e2e` ruft sie mit auf.
- **Prüfungen:**
  - Das Ranking zeigt die Top-Titel der Fixture in der richtigen Reihenfolge.
  - Ein Klick auf einen Titel öffnet das Titel-Detail.
  - Die Runs zeigen den Lauf. Im Detail steht die Mail im iframe mit `sandbox`.
  - In der Konsole stehen keine Fehler, auch keine Verstöße gegen die CSP.
- **Speicherort:** Die Browser liegen auf E: (`PLAYWRIGHT_BROWSERS_PATH=.local/playwright`),
  nicht unter `%LOCALAPPDATA%` auf C:.
- **CI:** installiert Chromium (`npx playwright install --with-deps chromium`) und führt die
  Browser-Tests gegen den Stack aus.

**Fertig, wenn:**
- `make local-e2e` läuft ohne Zugriff auf Yahoo, iShares, Deka und OpenFIGI in wenigen
  Minuten grün durch.
- Ein absichtlich anderes Gewicht (`VALUE_WEIGHT=0.5`) färbt es rot.
- Die CI macht dieselbe Prüfung bei jedem Push.

**NAS:** nichts. `REPLAY_SOURCE` bleibt dort leer, die Settings verhindern es ohnehin
zusammen mit Gmail.

**Umgesetzt (31.10.2026):**
- **U5.1:** `va_market_data.adapters.replay` und `REPLAY_SOURCE` (`FilePath`, nur mit
  `SMTP_PLAIN` und ohne `HEALTHCHECK_URL`). Die Composition Root liest die Fixture erst im Lauf.
  Ein Fehler darin lässt dann den Lauf scheitern, statt wie eine ausgefallene Datenbank
  auszusehen. Der DB-Test zeigt: Ein ganzer Lauf ergibt dieselben Scores, Faktor-Ränge und
  dieselbe CSV wie die Fixture.
- **U5.2:** `docker-compose.e2e.yml`, `docker/e2e.env`, `docker/e2e.sh`, `make local-e2e` und
  `make local-check`. Die CI ruft `docker/e2e.sh` mit ihren Images auf, `docker/frontend-smoke.sh`
  ist entfernt. 16 Prüfungen unter `tests/e2e/`.
- **U5.3:** Playwright 1.64.1 mit drei Browser-Tests unter `frontend/e2e/`, Chromium mit
  `make ui-e2e-install`.
- **Abweichungen vom Plan:**
  - Kein pytest-Marker: Die Tests unter `tests/e2e/` überspringen sich ohne `E2E_BASE_URL`
    selbst.
  - Das Frontend wird lokal nicht eingehängt. Die neue Stufe `prebuilt` im Frontend-Dockerfile
    nimmt den Build aus `frontend/dist` als zusätzlichen Build-Kontext. So stammen nginx,
    Template und Header aus demselben Dockerfile wie das Image der NAS.
  - `E2E_FIXTURE` ist überall der Dateiname unter `tests/fixtures/replay/`.
  - Playwright zeichnet keinen Trace auf. Die Aufzeichnung führt Skripte im abgeschotteten
    Mail-iframe aus, Chrome meldet das als Fehler in der Konsole.
- **Gefunden:** Hinter nginx griffen die globalen Styles des UI nie (seit P3.6). Angulars
  Inlining der kritischen CSS braucht ein Inline-Skript, die CSP (`script-src 'self'`) blockiert
  es. Behoben mit `inlineCritical: false` ([frontend.md](frontend.md)).
- **Gegenprobe:** Mit `VALUE_WEIGHT=0.5` scheitern genau die Vergleiche von Scores und CSV mit
  der Fixture.

### Phase 2b – Scoring-Profile

#### P2b.0 Replay-Regression über gespeicherte Wochen

Vorschlag B aus [regressionstest.md](regressionstest.md), entschieden am 30.10.2026. Es kommt vor
P2b.1, weil das Standardprofil (P2b.2) das heutige Ranking exakt reproduzieren soll. Genau das
prüft dieses Paket, für jede gespeicherte Woche.

- **Werkzeug** `python -m src.regression` (`make regression` im Container):
  - Es bewertet gespeicherte Abrufe mit dem aktuellen Code neu und vergleicht mit dem
    gespeicherten Bewertungslauf: Scores und Rang je Titel (`scoring.score_result`), Faktor-Ränge
    (`scoring.factor_score`) und die CSV des Reports (`reporting.report`), soweit vorhanden.
    Importierte Wochen haben nur Scores.
  - Es nimmt denselben Weg wie ein Lauf, der einen Abruf vom selben Tag wiederverwendet:
    Snapshots → `FundamentalsV1` → `marketdata.snapshot.completed` → Handler von scoring und
    notification auf einem eigenen Bus im Prozess. Speicher, Versand und Healthcheck sind dort
    Attrappen, die das Ergebnis nur festhalten.
  - Es schreibt nichts: Die Verbindung läuft mit `default_transaction_read_only`, egal mit
    welcher Rolle.
  - Auswahl: `--scoring-run N` oder `--fetch-run N` (beide mehrfach), ohne Angabe alle
    Bewertungsläufe außer Rescores. Die Konfiguration kommt wie im Batch aus `Settings`.
  - Ausgabe je Lauf: „gleich“ oder die abweichenden Titel mit altem und neuem Wert. Exit 0: alles
    gleich, 1: Abweichungen, 2: nichts zu vergleichen oder Fehler.
  - `--export DIR` schreibt je Lauf eine Fixture-Datei: Snapshot-Spalten und erwartete
    Ergebnisse.
- **CI:** `tests/test_replay_fixtures.py` spielt jede Datei unter `tests/fixtures/replay/` durch.
  Eine gewollte Änderung (Phase 2b, ADR-0011) schreibt die erwarteten Werte mit `--update-golden`
  neu, die Snapshots bleiben. Die erste Fixture ist eine echte Woche aus einem lokalen Dry-Run
  (90 Titel, öffentliche Marktdaten).
- **Test (rot):**
  - Vergleich ohne DB: Gleiche Ergebnisse ergeben keine Abweichung. Gemeldet werden ein
    geänderter Score, Rang oder Flag und ein fehlender oder zusätzlicher Titel. Unterschiede in
    der letzten Stelle und „leer“ gegen NaN zählen nicht.
  - CSV-Vergleich: inhaltlich gleich mit Toleranz; eine abweichende Zelle wird mit Titel und
    Spalte gemeldet.
  - Replay ohne DB: Ein Fall aus dem Golden-Datensatz läuft durch die Handler und ergibt
    dieselben Scores wie `score()`. JSON hin und zurück ändert nichts.
  - DB-Tests:
    - Ein kompletter Lauf (Yahoo gepatcht wie in `test_pipeline_db`) wird nachgespielt: gleich,
      Exit 0.
    - Mit einem anderen Gewicht gibt es Abweichungen, Exit 1.
    - Ein importierter Lauf ohne Faktor-Ränge und Report wird nur über die Scores verglichen.
    - Das Werkzeug kann nicht schreiben.
    - Nach dem Export ergibt das Replay aus der Datei dasselbe.
- **Implementierung:**
  - Paket `src/regression/` (Fall laden, Replay, Vergleich, Kommandozeile).
  - Der Speicher von scoring bildet seine Zeilen mit `score_rows`/`factor_rows`. Die Funktionen
    werden öffentlich, damit Replay und Speicher dieselben Zeilen bilden.
  - `scoring_config(settings)` in der Composition Root: Batch und Replay nutzen dieselbe
    Konfiguration.
  - Neue Lesezugriffe `get_scoring_runs` und `get_report_for_scoring_run`, dazu
    `create_db_engine(read_only=True)`.
- **NAS:** nach `make pull`, vor `make up`: `make regression`. Abweichungen sind nur dort in
  Ordnung, wo ein Paket eine Methodik-Änderung ankündigt (z. B. M1 für Wochen vor dem
  30.10.2026).
- **Umgesetzt (30.10.2026):**
  - Tests rot in `e4c4785`, Werkzeug in `6c23bed`. Kompaktes Fixture-Format und Ausgabe in
    `ec39c77`, erste echte Woche in `14dc29b`.
  - **Erster echter Einsatz:** Ein Dry-Run vom 30.10.2026 (90 Titel, echte Yahoo-Daten) wurde
    gespeichert und nachgespielt. 88 Titel mit allen Scores und Faktor-Rängen und ihre
    CSV-Zeilen waren exakt gleich.
  - **Befund:** Deutsche Bank und Commerzbank (beide ohne Composite, M1) tauschten Rang 89
    und 90. `score()` ließ Titel mit gleichem oder fehlendem Composite in der Reihenfolge der
    Eingabe stehen. Das ist beim Abruf die Reihenfolge des Universums, beim Wiederverwenden
    eines Abrufs vom selben Tag die alphabetische aus der DB. Derselbe Tag ergab so zwei
    verschiedene CSVs.
  - **Fix:** Bei Gleichstand entscheidet das Symbol (Test rot in `81864fc`, Fix in `99434b1`).
    Die Golden-Files sind unverändert, im Golden-Datensatz gibt es keinen Gleichstand. Die
    erwarteten Werte der Fixture sind darauf mit `--update-golden` erneuert. Der Diff besteht
    aus vier Zeilen: Rang 89/90 in den Scores und in der CSV.
  - **Für die NAS:** Wochen, die vor dem Fix gespeichert wurden, können bei Titeln ohne Composite
    genau diesen Tausch zeigen. Das ist gewollt.
  - **Größe:** Eine Woche als Fixture hat rund 170 KB. Die meisten Daten sind die
    Faktor-Ränge (790 Zeilen). Weitere Wochen kommen nach dem Deployment von der NAS
    (`make regression-export`). Am besten eignen sich Live-Wochen, denn nur sie haben
    Faktor-Ränge und CSV. Importierte Altwochen vergleicht `make regression` auf der NAS mit dem
    alten Code.

#### P2b.1 Profil-Tabellen

- **Test:** DB-Tests:
  - eine Version anlegen und aktivieren, die jüngste Aktivierung gewinnt
  - `UPDATE`/`DELETE` verboten (der Löschschutz-Test greift automatisch)
  - das Profil „Standard“ wird aus ENV angelegt, auch bei wiederholtem Start nur einmal
- **Implementierung:** eine neue Migration (die nächste freie Nummer ist `0006`, `0002` bis
  `0004` belegt Track F1, `0005` P1.10) mit `protect_table()` sowie ein Repository
  ([scoring-profile.md](scoring-profile.md)).
- **Entwurf (31.10.2026):**
  - **Tabellen** im Schema `scoring`. Die Modelle liegen in
    `va_scoring.adapters.postgres.models`, Migration `0006`:
    - `profile`: id, name (eindeutig), created_at.
    - `profile_version`: Schlüssel (profile_id, version). Die Version zählt je Profil ab 1.
      Dazu params (JSONB), parent_version, comment und created_at. parent_version verweist auf
      eine ältere Version desselben Profils.
    - `profile_activation`: id, profile_id, version (Fremdschlüssel auf die Version),
      activated_at. Aktiv ist die jüngste Zeile über alle Profile (activated_at, dann id).
    - Alle drei sind nur zum Anfügen da: `protect_table()` mit Schutz gegen `UPDATE`, Rechte wie
      die übrigen Tabellen von `scoring`.
  - **params:**
    - Die Werte aus [scoring-profile.md](scoring-profile.md), die Faktoren als sortierte Liste
      ihrer Schlüssel. `quality_weight` steht nicht drin, es ist `1 − value_weight`.
    - Dazu `min_factor_count`: heute fest 2, im UI nicht änderbar. So beschreibt ein Profil das
      Scoring vollständig, und ein altes Ranking bleibt nachrechenbar.
    - Gebildet von `profile_params(ScoringConfig)` in `va_scoring.domain.profile`. Das
      Pydantic-Modell mit Validierung folgt in P2b.2.
  - **Repository** (`ScoringRepository`): `write_profile`, `write_profile_version` (nächste
    Nummer), `write_profile_activation`, `get_profile_id`, `get_profile_version`,
    `get_active_profile_version` und `ensure_profile`.
  - **Profil „Standard“:**
    - Der Batch legt es beim Start an (`ScoringStore.ensure_default_profile`), mit den Werten
      aus ENV über `scoring_config(settings)`.
    - Gibt es „Standard“ schon, passiert nichts, auch wenn sich ENV geändert hat.
    - Aktiviert wird v1 nur, wenn noch keine Version aktiv ist. Ein später im UI angelegtes und
      aktiviertes Profil bleibt so aktiv.
    - Gleichzeitige Starts schützt `ON CONFLICT DO NOTHING` auf den Namen.
    - Ein Fehler dabei kippt den Lauf nicht, er landet als Warnung im Log. Bis P2b.3 rechnet das
      Scoring weiter mit den Werten aus ENV.
  - **Noch nicht in P2b.1:** die Validierung (P2b.2), das Profil im Lauf und in der Mail (P2b.3)
    und die API (P3.3).
- **Umgesetzt (31.10.2026):** wie im Entwurf. Die Migration `0006` stammt aus
  `alembic revision --autogenerate`, ergänzt um `protect_table()` und die Rechte. `alembic check`
  findet danach keinen Unterschied zwischen Modellen und Migrationen.
  - **Ergänzt:** Die Version der Vorlage (`parent_version`) ist ein Fremdschlüssel auf eine
    ältere Version desselben Profils. Ein `CHECK` sorgt dafür, dass sie kleiner ist.
  - **NAS:** Beim ersten Lauf nach dem Deployment entsteht „Standard“ v1 aus der `.env` der
    NAS. Am Ranking ändert sich nichts.

#### P2b.2 ScoringProfileParams

- **Test:**
  - Validierung: Grenzen, mindestens 2 Faktoren je Gruppe
  - Die Standardwerte entsprechen dem heutigen `ScoringConfig`, die Golden-Files bleiben also
    gleich.
  - Ein abgeschalteter Faktor verändert das Ranking wie erwartet.
- **Implementierung:** Pydantic-Modell und seine Abbildung auf `score()`.
- **Entwurf (31.10.2026):**
  - **Modell:** `ScoringProfileParams` in `va_scoring.domain.profile`, unveränderlich, ohne
    unbekannte Felder (ein Tippfehler in gespeicherten params fällt auf). Die Felder stehen in
    [scoring-profile.md](scoring-profile.md), dazu `min_factor_count` (Standard 2, mindestens 1)
    wie in P2b.1.
  - **Faktoren:** als Literal-Schlüssel `ValueFactorKey` und `QualityFactorKey`. Ein Test hält
    sie gleich mit `DEFAULT_VALUE_FACTORS` und `DEFAULT_QUALITY_FACTORS`, dem Katalog im Code.
  - **Regeln:**
    - Die Grenzen stehen am Feld (`ge`, `le`), damit sie später in OpenAPI landen.
    - Je Gruppe sind mindestens zwei Faktoren aktiv und mindestens so viele wie
      `min_factor_count`, sonst entstünde nie ein Score.
  - **JSON:** Die Faktoren erscheinen als sortierte Liste, also in derselben Form wie in P2b.1
    und mit stabilem Hash. `profile_params(cfg)` geht jetzt über das Modell. Die in P2b.1
    gespeicherte Version „Standard“ v1 bleibt gültig.
  - **Abbildung auf `score()`:** `to_config()` liefert eine `ScoringConfig` mit
    `quality_weight = 1 − value_weight` und den Faktoren in der Reihenfolge des Katalogs. Für
    die Standardwerte ist sie gleich `ScoringConfig()`, Golden-Files und Replay-Fixtures
    bleiben also unverändert.
  - **Abhängigkeit:** `pydantic` direkt in `va-scoring`, bisher kam es nur über `va-contracts`.
  - **Noch nicht in P2b.2:** Das Scoring rechnet erst ab P2b.3 mit dem Profil. OpenAPI und der
    Editor kommen in P3.3.
- **Umgesetzt (31.10.2026):** wie im Entwurf.
  - Die Felder haben ihren Standardwert als `Field(default=...)`. Pyright erkennt ihn nur so.
  - `from_config()` geht über `model_validate`: Ein Faktor außerhalb des Katalogs fällt auch
    dort auf.
  - Neuer Test in `tests/test_replay_fixtures.py`: Jede gespeicherte Woche ergibt mit dem
    Profil „Standard“ (Werte des Deployments) dasselbe Ergebnis. P2b.3 kann das Scoring damit
    umstellen, ohne dass sich eine Woche ändert.

#### P2b.3 Profil-Version im Lauf und in der Mail

- **Test:**
  - DB-Test: `scoring_run` speichert die Profil-Version.
  - Die Golden-Mail zeigt im Footer „Profil Standard v1“. Diese Änderung am Golden-File ist
    beabsichtigt.
- **Implementierung:** Verweis im Lauf, Footer im Template.
- **Entwurf (31.10.2026):**
  - **Das Scoring rechnet mit dem aktiven Profil.** Die ENV-Werte (`VALUE_WEIGHT`,
    `QUALITY_WEIGHT`, `MIN_MARKET_CAP`) wirken nur noch beim allerersten Lauf, als Startwerte für
    „Standard“ v1 (ADR-0009).
  - **Ports von scoring:**
    - `ScoringStore` speichert nur noch Läufe, `record_scoring` bekommt die Profil-Version mit.
    - Neu ist `ProfileStore` mit `ensure_default_profile`.
    - Neu ist `ProfileSource` mit `active() -> ActiveProfile`, also `ScoringConfig` und
      Profil-Version.
  - **Quellen:**
    - `StoredProfile` legt bei Bedarf „Standard“ an, liest die aktive Version und prüft sie
      mit `ScoringProfileParams`.
    - `FixedProfile` rechnet mit einer festen Konfiguration ohne Profil. Das nutzt das Replay.
  - **Umbau gegenüber P2b.1:**
    - Der Handler von scoring holt das Profil selbst, wenn er es braucht. Der Aufruf beim
      Start des Batches entfällt.
    - Ein Fehler dabei lässt den Lauf jetzt scheitern (Stufe scoring, Alarm), denn ohne Profil
      gibt es keine Bewertung.
    - Ungültige gespeicherte params scheitern laut, statt still mit anderen Werten zu rechnen.
  - **Migration `0007`:**
    - `scoring.scoring_run` bekommt `profile_id` und `profile_version`, beide leer bei Läufen
      vor P2b.3, beim Import und beim Replay.
    - Ein Fremdschlüssel verweist auf `profile_version` desselben Schemas.
    - Ein `CHECK` erlaubt nur beides oder keines.
  - **Event:** `ScoringRunCompletedV1.profile` gibt es schon (optional, P1). Der Handler füllt es
    jetzt. Der Vertrag ändert sich nicht, die Schema-Golden-Files bleiben.
  - **Mail:** Der Footer nennt „Profil Standard v1“. Ohne Profil steht dort nichts. Die
    HTML-Golden-Files ändern sich gewollt, CSV und Metadaten nicht.
  - **E2E:** Mit Replay-Daten prüft `tests/e2e`, dass die Mail „Profil Standard v1“ nennt.
  - **Noch nicht in P2b.3:**
    - Das Replay rechnet weiter mit den Settings statt mit dem gespeicherten Profil des Laufs.
      Solange es nur „Standard“ v1 aus denselben ENV-Werten gibt, ist das gleich.
    - Das gespeicherte Profil im Replay folgt mit dem Profil-Editor (P3.3).
    - Bis P3.3 lassen sich Gewichte nur noch über ein neues Profil in der Datenbank ändern,
      nicht mehr über die `.env`.
- **Umgesetzt (31.10.2026):** wie im Entwurf.
  - Die Migration `0007` stammt aus `alembic revision --autogenerate`. Den `CHECK` ergänzt sie
    von Hand, weil Alembic CHECK-Constraints nicht erkennt. `alembic check` findet danach keinen
    Unterschied.
  - `Adapters.scoring` hat den Typ `ScoringAdapter`, also `ScoringStore` und `ProfileStore`.
  - Golden-Files: In allen sechs Mails kommt im Footer „Profil Standard v1 &middot;“ dazu.
    Das ist gewollt, CSV und Metadaten bleiben gleich. `tests/test_pipeline_bus.py` vergleicht
    die Mail durch den ganzen Bus und rechnet mit „Standard“ v1 wie der Golden-Master.
  - **NAS:** Der erste Lauf nach dem Deployment legt „Standard“ v1 aus der `.env` der NAS an.
    Die Replay-Wochen zeigen, dass das Ranking dabei gleich bleibt (P2b.2). Danach wirkt eine
    Änderung von `VALUE_WEIGHT`, `QUALITY_WEIGHT` oder `MIN_MARKET_CAP` nicht mehr.

### Phase 3 – web-api und Angular

#### P3.1 Gerüst des web-api

- **Test:** Health-Endpoint (TestClient) und OpenAPI-Snapshot.
- **Implementierung:** `services/web-api` mit FastAPI-App, Lifespan und Settings.
- **Umgesetzt (31.10.2026, U4):**
  - Tests rot in `597e9fa`, Umsetzung in `82901a0`.
  - **Pakete:** `va-web-api` mit FastAPI 0.162 (bringt `opentelemetry-api` mit) und uvicorn
    ohne `[standard]`, beides reines Python. Die J4125-Prüfung lädt das web-api mit.
  - **App:** `create_app()` als Fabrik (`uvicorn --factory`). Swagger liegt unter `/api/docs`,
    die OpenAPI unter `/api/v1/openapi.json`. Beides reicht nginx später mit `/api/*` weiter.
  - **Lesezugang:** Der Lifespan öffnet `WEB_API_DATABASE_URL` (Rolle `va_read`)
    schreibgeschützt. Health braucht keine Datenbank.
  - **Snapshot:** `tests/golden/openapi/v1.json`.
  - **Lokal:** Der Container `web-api` im lokalen Stack bekommt nur die Leserolle, startet ohne
    Migrationslauf und lauscht auf `127.0.0.1:8000`. Für die `.venv` gibt es `make api`.
  - **httpx statt httpx2:** Starlette 1.10 empfiehlt für den TestClient `httpx2`. Es ist erst
    wenige Wochen alt, deshalb bleibt es vorerst bei `httpx` 0.28. Die Warnung ist in der
    pytest-Konfiguration ausgeblendet.

#### P3.2 Lese-Endpunkte

- **Test:** API-Tests gegen die Test-Datenbank mit Beispieldaten (Runs, Ranking, Titel,
  gerenderte Mail), Zugriff über die Rolle `va_read`.
- **Implementierung:** Router `runs`, `ranking`, `instruments`, `reports`
  ([web-api-realtime.md](web-api-realtime.md)).
- **Entwurf (31.10.2026, U4):**

  | Endpunkt | Inhalt | Quelle |
  |---|---|---|
  | `GET /runs?limit&offset` | Läufe, neueste zuerst: Art, Status, Zeiten, Dry-Run, Zähler, Exit-Code | `batch.run` |
  | `GET /runs/{id}` | dazu Fehler und die IDs von Abruf, Bewertung und Report | `batch.run` |
  | `GET /ranking/latest` | jüngster Bewertungslauf außer Rescores | `scoring.*`, Snapshot des Abrufs |
  | `GET /ranking/{scoring_run_id}` | alle Titel mit Rang, Scores, Flag, Größenfilter und den Faktor-Kennzahlen, dazu Gewichte und Abruftag | wie oben |
  | `GET /instruments/{symbol}` | Stammdaten, neuester gültiger Snapshot, Score-Verlauf über alle Bewertungsläufe | `market_data.*`, `scoring.*` |
  | `GET /reports/{id}` | Betreff, Zeitpunkt, HTML der Mail | `reporting.report` |
  | `GET /reports/{id}/csv` | die CSV als Download (`text/csv`) | `reporting.report` |

  - **Eigene Abfragen:** Das web-api liest mit eigenem SQL (`va_web_api.read`), ohne die
    Repositories der Fach-Services. Ab Phase 4 lösen Projektionen das ab, die REST-Antworten
    bleiben gleich.
  - **Fehlende Daten:** Unbekannte IDs und Symbole ergeben 404. Ist die Datenbank nicht
    erreichbar, kommt 503 statt 500.
  - **Snapshot:** Der OpenAPI-Snapshot ändert sich bewusst.
- **Umgesetzt (31.10.2026):**
  - Tests rot in `9806327`.
  - **Code:** Antwortmodelle in `va_web_api.models`. Sie verbieten unbekannte Felder, damit
    Tippfehler in einer Abfrage auffallen. Die Abfragen stehen in `va_web_api.read`, die Router
    unter `va_web_api.api` (`runs`, `ranking`, `instruments`, `reports`).
  - **503:** Fällt die Datenbank aus, antworten die Endpunkte ohne Details mit 503.
  - **Probe mit echten Daten** (Lauf vom 30.10.2026 im lokalen Stack, 90 Titel):
    - Das Ranking beginnt mit Allianz, Porsche SE und freenet.
    - Commerzbank und Deutsche Bank stehen ohne Composite auf 89 und 90.
    - Titel, Report und CSV-Download liefern die erwarteten Daten.
  - **Befund aus U1, hier behoben:** `.env.local.example` nutzte `localhost`. Unter Windows
    hing damit jede Verbindung aus der `.venv`, erst über IPv6, dann bis zum Abbruch. Die
    Vorlage nutzt jetzt `127.0.0.1`.

#### P3.3 Profil-Endpunkte und Vorschau

- **Test:**
  - `PUT` mit veraltetem `If-Match` ergibt 409.
  - Die Vorschau mit nur einem Faktor ergibt 422.
  - Aktivieren legt eine neue Aktivierung an.
- **Implementierung:** Router `scoring`, dazu der Port `ScoringPreview`, vorerst im selben Prozess.
- **Entwurf (01.11.2026):** Erst die API, der Editor im UI folgt als eigenes Paket (Rest von P3.7)
  auf dem neu erzeugten Client.
  - **Schreibrechte (Entscheidung 01.11.2026):**
    - Eine eigene Rolle `va_profiles`, statt die Rolle `va_app` des Batches mitzunutzen. Sie darf
      die drei Profil-Tabellen lesen und in `profile_version` und `profile_activation` anfügen,
      sonst nichts.
    - Das web-api bekommt dafür eine zweite Adresse (`WEB_API_PROFILES_DATABASE_URL`). Lesen
      bleibt bei `va_read` mit schreibgeschützter Verbindung.
    - Die Rolle entsteht in einer neuen Datenbank über `db/init/01_roles.sh`
      (`VA_PROFILES_PASSWORD`). In einer bestehenden legt `python -m src.db.migrate` sie an,
      wenn das Passwort gesetzt ist, und gleicht es an. Die Rechte vergibt die Migration
      `0008`.
    - Ab Phase 4 schreibt der Service scoring selbst (P4.8), die Rolle geht dann in den Rollen
      je Service auf (P5.3).
  - **Parameter als Contract:** `ScoringProfileParams` zieht als `ProfileParamsV1` nach
    `va_contracts`, mit Feldern, Grenzen, Literal-Schlüsseln und Validator. Das web-api darf
    `va_scoring` nicht importieren, braucht das Modell aber für OpenAPI und die 422.
    `va_scoring` erbt davon und ergänzt `from_config()` und `to_config()`. Das Format im JSON
    bleibt gleich, gespeicherte Versionen bleiben gültig.
  - **Endpunkte** (Router `scoring`, [web-api-realtime.md](web-api-realtime.md)):
    - `GET /scoring/factors`: der Katalog mit Gruppe, Richtung und Methodik-Hinweis.
    - `GET /scoring/profiles` und `GET /scoring/profiles/{id}`: Profile, ihre Versionen und
      welche aktiv ist. Die Detail-Antwort trägt die jüngste Version als `ETag`.
    - `PUT /scoring/profiles/{id}`: neue Version aus `params` und `comment`.
      - `If-Match` ist Pflicht und nennt die Version, auf der die Änderung beruht. Ohne ihn
        antwortet der Server mit 428, mit veralteter Version mit 409.
      - Die neue Version verweist auf diese als `parent_version`.
      - Speichern zwei gleichzeitig, scheitert der zweite am Schlüssel (409).
    - `POST /scoring/profiles/{id}/activate` mit `version`: legt eine Aktivierung an. Der
      nächste Lauf rechnet damit. Einen Rescore löst die Aktivierung erst mit Phase 4 aus.
    - `POST /scoring/preview` mit `params`: Ranking auf dem Abruf des jüngsten Bewertungslaufs,
      verglichen mit dem aktiven Profil auf denselben Daten. Das ergibt Rang und Value-Trap je
      Titel vorher und nachher sowie die neuen und weggefallenen Titel in den Top 20.
      Ungültige params ergeben 422. Gespeichert wird nichts.
  - **Im selben Prozess:** Die Ports `ScoringPreview` und `ProfileCommands` liegen im web-api,
    ihre Umsetzung kommt von außen.
    - `src/web.py` ist die Composition Root des web-api-Prozesses. Sie darf `va_scoring` und
      `va_market_data` importieren und verdrahtet die Ports mit deren Code.
    - Der Startbefehl wird `uvicorn --factory src.web:create_app`.
    - Ohne `WEB_API_PROFILES_DATABASE_URL` antworten die schreibenden Endpunkte mit 503.
  - **Test (rot):**
    - Ohne Datenbank, mit Fake-Ports: 428 ohne und 409 mit veraltetem `If-Match`, 422 für die
      Vorschau mit nur einem Faktor, 503 ohne Schreibzugang, 415 ohne JSON.
    - DB-Tests über `src.web`, mit einem Replay-Lauf als Datenbestand:
      - Versionen ansehen.
      - Speichern ergibt v2 mit `parent_version` 1.
      - Ein gleichzeitiges Speichern ergibt 409.
      - Aktivieren legt eine neue Aktivierung an, und der nächste Lauf rechnet mit v2.
      - Die Vorschau mit anderem Gewicht verschiebt Ränge.
    - Rechte: `va_profiles` kann Versionen und Aktivierungen anlegen, aber keine Bewertungsläufe
      und kein `market_data`. UPDATE und DELETE bleiben verboten. Die Migration legt die Rolle
      in einer bestehenden Datenbank an.
    - Compose: Das web-api bekommt genau die beiden Adressen und keine Zugangsdaten des
      Batches.
  - **Danach im selben Commit:** OpenAPI-Snapshot und der erzeugte TS-Client.
- **Umgesetzt (01.11.2026):** wie im Entwurf.
  - `ProfileParamsV1` in `va_contracts.profile`, `ScoringProfileParams` erbt davon. Methodik-
    Hinweise je Faktor stehen in `FACTOR_INFO` (`va_scoring.domain.profile`).
  - `src.db.migrate` legt fehlende Login-Rollen mit `ensure_login_role` an und setzt das
    Passwort sonst neu. Name und Passwort gehen gequotet über psycopg ins SQL. Ein Fehler dabei
    hält den Batch nicht auf, er landet als Warnung im Log.
  - Die Vorschau rechnet auf dem Abruf des jüngsten Bewertungslaufs, ohne Rescores
    (`get_latest_scoring_run`). Ohne aktives Profil gelten die Standardwerte.
  - `tests/e2e` prüft im Stack: Standard ist aktiv, die Vorschau mit dem aktiven Profil
    verschiebt nichts, und Speichern verlangt die neueste Version (201, dann 409).
  - **NAS:** Vor `make up` gehört `VA_PROFILES_PASSWORD` in die `.env`, sonst bricht Compose mit
    einem Hinweis ab. Die Rolle entsteht beim ersten Start des Batches.
  - **Lokal:** Eine `.env` aus einer älteren `.env.local.example` braucht ebenfalls
    `VA_PROFILES_PASSWORD` und für `make api` auch `WEB_API_PROFILES_DATABASE_URL`.
  - **Als Nächstes:** der Profil-Editor im UI (Rest von P3.7) auf dem neuen Client.

#### P3.4 Sicherheitsgrundlagen 🔒

- **Test:**
  - Ein `POST` mit `text/plain` wird abgelehnt.
  - Bei fremdem `Origin` kommen keine CORS-Header.
- **Implementierung:** Mutationen nur mit JSON, CORS bleibt aus
  ([ADR-0007](../adr/0007-lan-only-ohne-login.md)).
- **Umgesetzt (31.10.2026, U4):**
  - Tests rot in `f32cb74`.
  - **415:** `JsonOnlyMiddleware` (`va_web_api.security`) lehnt jedes POST, PUT, PATCH und
    DELETE ohne `application/json` ab, auch ohne Body. Ein `fetch` ohne Body käme sonst ohne
    Vorabprüfung des Browsers durch.
  - **Kein CORS:** Es gibt keine CORS-Middleware. Das sichern Tests ab, ebenso dass die OpenAPI
    keine Secrets nennt (Passwort, SMTP, Datenbank-URL, Settings).
  - **Noch offen:** Origin-Prüfung des WebSockets (P4.5) und Hostnamen-Filter in nginx (P3.6).

#### P3.5 Angular-Gerüst und generierter Client

- **Voraussetzung:** Die UI-Bibliothek ist entschieden.
- **Test:** Vitest-Smoke-Test und ein CI-Job mit `npm ci`, Lint, Test und Build.
- **Implementierung:** Angular-22-Workspace und hey-api-Konfiguration (Angular- und Zod-Plugin)
  auf Basis des OpenAPI-Snapshots.
- **Umgesetzt (31.10.2026, U4):**
  - Smoke-Test rot in `e0aba04`.
  - **Versionen:** Angular 22.2 (zoneless, Vitest 5, TypeScript 6.0), Angular Material 22.2,
    angular-eslint 22.6, hey-api 0.99, Zod 4.6.
  - **Client:** `frontend/src/app/api/` aus `tests/golden/openapi/v1.json`, mit Requests,
    `httpResource`-Funktionen, Typen und Zod-Schemas. Er wird committet und ist vom Lint
    ausgenommen.
  - **Namen:** Das web-api nutzt die Funktionsnamen als Operation-IDs (`1b0f799`). Der Client
    heißt deshalb `latestRankingResource` statt `latestRankingApiV1RankingLatestGetResource`.
  - **App-Hülle:** Material-Toolbar mit Navigation zu Ranking und Runs. Bis P3.7 stehen dort
    Platzhalter. HTTP läuft über `fetch`, nur mit relativen Pfaden. Lokal leitet
    `proxy.conf.json` an `127.0.0.1:8000`.
  - **Ohne Google Fonts:** Die Systemschrift ersetzt Roboto aus dem Internet, die Links aus
    `ng add` sind entfernt.
  - **CI:** eigener Job „Frontend Lint + Test + Build“ mit Node 24, `npm ci`, Abgleich des
    Clients mit dem Snapshot, Prettier, ESLint, Vitest und Produktions-Build.
  - **Lokal:** `make ui-install`, `make ui`, `make ui-api`, `make ui-check`.
  - **Build:** 324 kB beim ersten Laden, komprimiert 83 kB.
  - **Hinweis:** `npm audit` meldet 0 Schwachstellen in den Laufzeitpaketen. Die 22 Meldungen
    betreffen nur Entwicklungswerkzeuge (`js-yaml`, `minimatch`) und landen nicht im Build.
  - **Befund aus U1, hier behoben:** `.dockerignore` schloss `.local/` nicht aus. Jeder
    Image-Build im lokalen Stack schickte die lokale Datenbank (`.local/pgdata`) als
    Build-Kontext an Docker. Jetzt sind `.local/` und `frontend/` ausgeschlossen. Das Frontend
    bekommt in P3.6 ein eigenes Image.

#### P3.6 frontend-Container 🔒

- **Test:** Container-Smoke in der CI:
  - `nginx -t` läuft durch.
  - `/` und `/runs/1` liefern `index.html`.
  - `/api/v1/health` antwortet über nginx mit 200.
  - Bei unbekanntem Host wird die Verbindung geschlossen (`return 444`).
- **Implementierung:** Dockerfile, `nginx/default.conf` und der Compose-Eintrag
  ([frontend.md](frontend.md)).
- **NAS (du):** Container deployen, Firewall-Regel für Port 8080 auf das eigene Subnetz.
- **Umgesetzt (31.10.2026, U4, nach P3.7):**
  - Tests rot in `7846cbd`:
    - Compose: Die NAS hat `web-api` ohne Port und nur mit der Leserolle, dazu `frontend` aus
      GHCR auf `UI_LAN_BIND:8080`. Lokal liegt das frontend auf `127.0.0.1`.
    - Regeln der nginx-Konfiguration, statisch geprüft.
    - Container-Smoke für die CI (`docker/frontend-smoke.sh`).
  - **Image:** `frontend/Dockerfile` baut mit `node:24.22.2-alpine`, `nginxinc/nginx-unprivileged:1.30.6-alpine`
    liefert aus (ohne root, Port 8080).
  - **nginx-Vorlage:** `return 444` für unbekannte Hostnamen, `UI_SERVER_NAMES` per `envsubst`,
    `/api/` mit `^~` und Auflösung zur Laufzeit, Sicherheits-Header ohne `add_header` in den
    Abschnitten, `index.html` ohne Cache, SPA-Fallback.
  - **CI:**
    - Baut das Image und prüft es zusammen mit dem web-api aus dem App-Image: `nginx -t`,
      `/` und `/runs/1` liefern `index.html`, `/api/v1/health` geht über nginx, Header stimmen,
      ein fremder Host bekommt keine Antwort.
    - Schiebt es mit denselben Tags wie das App-Image nach GHCR (`va-frontend`).
  - **Lokal:** `make local-ui` baut und startet nginx unter `127.0.0.1:8080`, nur auf Wunsch (Profil
    `ui`), weil der Node-Build viel Platz braucht. `nginx -t` mit der echten Vorlage lief lokal
    durch.
  - **Hinweis:** Swagger (`/api/docs`) lädt sein Skript von einem CDN und geht hinter nginx wegen
    der CSP nicht. Lokal bleibt es am web-api erreichbar.

#### P3.7 Ansichten

- **Test:** Komponententests je Ansicht, geschrieben vor der Ansicht selbst: Darstellung,
  Filter, Validierungsmeldungen, Aufruf der Vorschau, Umgang mit 409.
- **Implementierung:** Ranking, Runs, Titel-Detail und der Profil-Editor (Signal Forms mit
  `validateStandardSchema`).
- **Entwurf Profil-Editor (01.11.2026):** auf den Endpunkten aus P3.3 und dem erzeugten Client.
  - **Routen:**
    - `/profiles` zeigt die Profile mit neuester Version und markiert das aktive.
    - `/profiles/:profileId` öffnet den Editor.
    - In der Navigation steht „Profile“.
  - **Formular:**
    - Signal Forms (`form`, `[formField]`), geprüft mit `validateStandardSchema` und dem
      erzeugten `zProfileParamsV1Input`. Die Meldungen stehen am Feld.
    - Felder: Value-Gewicht (Quality als Rest daneben), Mindest-Marktkapitalisierung,
      Mindestanteile, Value-Trap-Schwellen, Ausschluss negativer Multiples.
    - Die Faktoren erscheinen als Checkboxen je Gruppe, mit Richtung und Methodik-Hinweis aus
      `/scoring/factors`.
    - Grundlage ist die neueste Version. Beim Laden und nach dem Speichern füllt sie das
      Formular.
  - **Live-Vorschau:**
    - 300 ms nach der letzten Änderung geht die Anfrage an `/scoring/preview`, nur bei gültigem
      Formular. Die Wartezeit ist ein Token, Tests setzen sie auf 0.
    - Angezeigt werden neu und raus in den Top 20, geänderte Value-Trap-Markierungen und die
      Top 20 mit Rang vorher und nachher.
    - Regeln über mehrere Felder, etwa „mindestens 2 Faktoren“, meldet die Vorschau als 422.
      Die Meldung erscheint im Editor, Speichern ist dann gesperrt. Die Regel steht so nur im
      Contract.
  - **Speichern:**
    - Ein `PUT` mit `If-Match` der Grundlage und optionalem Kommentar.
    - 201: Das Profil lädt neu, Hinweis „Version n gespeichert, noch nicht aktiv“.
    - 409: Hinweis, dass inzwischen eine neuere Version gespeichert wurde, mit „Neu laden“.
  - **Versionen:**
    - Die Liste zeigt die neueste zuerst, mit Datum, Kommentar und Grundlage. Die aktive ist
      markiert.
    - „Aktivieren“ gibt es je Version, auch für ältere (Zurückrollen). Hinweis: Das wirkt ab
      dem nächsten Lauf.
  - **Test (rot):** Komponententests mit `HttpTestingController`:
    - Liste.
    - Der Editor lädt die neueste Version ins Formular.
    - Ein ungültiger Wert zeigt eine Meldung und schickt keine Vorschau.
    - Die Vorschau nach einer Änderung.
    - Eine 422 erscheint als Meldung.
    - Speichern mit `If-Match` und Kommentar.
    - Eine 409 bietet „Neu laden“ an.
    - Aktivieren.
    - Im Browser-Test (`frontend/e2e`) ändert ein Lauf das Gewicht, sieht die Vorschau,
      speichert und findet v2 in der Liste.
- **Profil-Editor umgesetzt (01.11.2026):** wie im Entwurf.
  - Signal Forms verbieten `name`, `min` und `max` an Feldern, die `[formField]` steuert. Die
    Grenzen kommen aus dem Schema, Tests finden die Felder über `data-field`.
  - Die erzeugten Ausgabe-Typen haben wegen der Standardwerte optionale Felder. Das Formular
    normalisiert die Parameter deshalb über `zProfileParamsV1Input`.
  - Zod meldet auf Deutsch (`z.config(z.locales.de())` in `locale.ts`).
  - Der Browser-Test speichert nur im Wegwerf-Stack (`E2E_FIXTURE` gesetzt), nie in
    `make local-check`.
- **Umgesetzt für U4 (31.10.2026), ohne den Profil-Editor:**
  - Komponententests rot in `5a80ca3`, 24 Tests für drei Ansichten. Sie laufen gegen
    `HttpTestingController`, mit Beispieldaten im Format des generierten Clients.
  - **Ranking** (`/ranking`, `/ranking/:scoringRunId`):
    - Kopf mit Lauf, Abruftag, Quelle und Gewichten.
    - Tabelle mit Rang, Titel (Link zum Detail), Index, Sektor, den drei Scores,
      Value-Trap-Markierung, Marktkapitalisierung, EV/EBIT, KBV und ROIC.
    - Filter für den Index, Suche nach Name oder Symbol, Titel unter der Größenschwelle auf
      Wunsch am Ende.
    - Sortierung je Spalte, fehlende Werte stehen immer hinten.
  - **Runs** (`/runs`, `/runs/:runId`):
    - Liste mit Status auf Deutsch, Zählern und Dry-Run-Kennzeichen.
    - Detail mit Zeiten, Fehlertext, Link zum Ranking des Laufs und CSV-Download.
    - Die Mail läuft im iframe mit leerem `sandbox`-Attribut: keine Skripte, kein Zugriff auf
      die Seite. Deshalb darf ihr eigenes CSS bleiben (`bypassSecurityTrustHtml` nur dafür).
  - **Titel-Detail** (`/instruments/:symbol`): Stammdaten, 15 Kennzahlen des neuesten Abrufs mit
    Hinweisen vom Abruf, Score-Verlauf mit der neuesten Bewertung zuerst und Links zum
    jeweiligen Ranking.
  - **Gemeinsam:**
    - Deutsche Formate über `LOCALE_ID` `de-DE` (0,78; 12,3 %; 140,0 Mrd; 30.10.2026).
    - Verständliche Meldungen bei 404 („Noch kein Bewertungslauf“) und bei Ausfall des web-api.
    - Die Resources bekommen ihre Parameter aus den Routen (`withComponentInputBinding`).
  - **Probe mit echten Daten** (lokaler Lauf vom 30.10.2026, `ng serve` gegen das web-api):
    - Ranking mit 90 Titeln, BMW als Value-Trap markiert.
    - Lauf 1 mit Mail und CSV, Titel-Seiten mit allen Kennzahlen.
    - Keine Fehler in der Browser-Konsole.
  - **Testhelfer:** Eine offene Anfrage hält die App „instabil“. Der Helfer stößt Anfragen
    deshalb mit `TestBed.tick()` an, statt auf `whenStable()` zu warten. Sonst warteten Test
    und Anfrage aufeinander, etwa bei Lauf → Report.
  - **Größe:** Der erste Seitenaufruf lädt komprimiert 104 kB, die Ranking-Seite mit
    Tabelle, Sortierung und Formularfeldern 30 kB dazu.

#### P3.8 Schutz der Schnittstelle

- **Test:** CI-Schritt `oasdiff breaking` gegen `main`. Mit einer absichtlich inkompatiblen
  Änderung wird er einmal rot gesehen.
- **Implementierung:** Workflow-Schritt, Referenz ist die OpenAPI von `main`.
- **Entwurf (01.11.2026):**
  - **Werkzeug:** oasdiff v1.34.0 als Docker-Image `tufin/oasdiff`, lokal und in der CI
    dasselbe. Node oder Go braucht es dafür nicht.
  - **Vergleich:** `docker/api-breaking.sh` vergleicht den OpenAPI-Snapshot
    `tests/golden/openapi/v1.json` mit dem Snapshot am Abzweigpunkt von `main` (`git
    merge-base`). Auf `main` selbst nimmt es den Stand davor. Dass der Snapshot zur App passt,
    sichert schon `tests/test_openapi.py`.
  - **Regel:** `--fail-on ERR`. Neue Pfade, Felder und Endpunkte sind erlaubt. Inkompatibel sind
    etwa entfernte Pfade, entfernte Pflichtfelder einer Antwort und neue Pflichtfelder einer
    Anfrage.
  - **CI:** Im Job „Lint + Type-Check + Tests“ früh, gleich nach dem Checkout mit voller
    Historie. Ein Bruch fällt so auf, bevor die Tests laufen.
  - **Lokal:** `make api-breaking`.
  - **Gegenprobe (vorab lokal):**
    - Der Snapshot gegen sich selbst ergibt Exit 0.
    - Der Stand vor P3.3 gegen den nach P3.3 ergibt Exit 0, das ist additiv.
    - Eine Kopie ohne `/api/v1/runs/{run_id}` und ohne `exit_code` in `RunSummary` ergibt
      Exit 1 mit zwei Fehlern.
  - **In der CI einmal rot:** Ein Commit auf dem Branch entfernt einen Pfad aus dem Snapshot, ein
    zweiter nimmt das zurück.
- **Umgesetzt (01.11.2026):** wie im Entwurf.
  - Gesehen rot: CI-Lauf 41340270622. Der Schritt „API-Kompatibilität (oasdiff breaking gegen
    main)“ meldete „api path removed without deprecation“. Nach dem Revert war die CI wieder grün.
  - Eine absichtliche Änderung am Snapshot färbt zusätzlich die Prüfung „API-Client passt zum
    OpenAPI-Snapshot“ im Frontend-Job rot. Eine echte inkompatible Änderung käme also nicht nur
    an oasdiff vorbei.
  - `.local/oasdiff/` nimmt die beiden verglichenen Fassungen auf (von git ignoriert).

### Phase 4 – Events und Echtzeit

#### P4.1 NATS-Infrastruktur

- **Test:** Integrationstest gegen einen NATS-Service-Container: Der Stream `VA_EVENTS` hat die
  Subjects `va.>` und das Deduplizierungsfenster. Die Consumer werden idempotent angelegt.
- **Implementierung:** Compose-Dienst und Provisionierung in `va-platform`
  ([events.md](events.md)).
- **Entwurf (01.11.2026):**
  - **Versionen:** NATS Server 2.15.1 (`nats:2.15.1-alpine`, ein Go-Binary ohne AVX) und der
    Client `nats-py` 2.16.0. Diese Abhängigkeit kommt in `va-platform` dazu. FastStream folgt erst
    mit P4.3, wenn NATS der Bus wird.
  - **Provisionierung** in `va_platform.nats`:
    - `provision(js)` legt Stream und Consumer an oder gleicht sie an die Vorgabe an. Ein
      zweiter Aufruf ändert nichts.
    - Stream `VA_EVENTS`: Subjects `va.>`, Speicherung in Dateien, Aufbewahrung 30 Tage,
      Deduplizierung 10 Minuten. Flüchtige Meldungen (`live.va.…`) landen nicht darin.
    - Durable Pull-Consumer aus der Tabelle in events.md, alle mit explizitem Ack und
      `max_deliver` 5:
      - `market-data` (`va.screening.run.requested`): Der Abruf dauert Minuten,
        In-Progress-Acks kommen mit P4.3.
      - `scoring` (`va.marketdata.snapshot.completed`).
      - `notification` (`va.scoring.run.completed`, `va.screening.run.failed`).
      - `web-api` (`va.>`).
    - Aufruf von der Kommandozeile: `python -m va_platform.nats` mit `NATS_URL`, lokal
      `make nats-provision`. Die Services rufen `provision` ab P4.3 beim Start selbst.
  - **Compose:**
    - Dienst `nats` mit JetStream und Daten unter `./natsdata`, ohne Port nach außen,
      Healthcheck über `/healthz`.
    - Lokal: `.local/natsdata` und Port `127.0.0.1:4222`. Im E2E-Stack auf tmpfs.
    - Bis P4.3 nutzt ihn noch niemand.
  - **Test (rot):** Integrationstests gegen einen echten NATS-Server.
    - Ohne `TEST_NATS_URL` überspringen sie sich, wie die DB-Tests. Lokal
      `make test-nats-up` (Port 54222), in der CI ein Container mit `-js`.
    - Geprüft wird:
      - Der Stream hat Subjects, Aufbewahrung, Deduplizierung und Dateispeicher.
      - Ein zweiter Aufruf ändert nichts, eine abweichende Einstellung wird angeglichen.
      - Alle Consumer existieren mit Filter, Ack und `max_deliver`.
      - Dieselbe `Nats-Msg-Id` landet nur einmal im Stream.
      - `live.va.…` landet nicht im Stream.
    - Compose: `nats` mit fester Version, auf der NAS ohne Port, lokal getrennte Daten, im
      E2E-Stack auf tmpfs.
- **Umgesetzt (01.11.2026):** wie im Entwurf.
  - Alle Consumer warten 60 s auf ein Ack (`ack_wait`). Länger braucht nur market-data, und das
    regelt P4.3 über In-Progress-Acks.
  - Ein Stream wird nur in den eigenen Feldern angeglichen (Subjects, Aufbewahrung,
    Deduplizierung). Die übrigen behalten die Werte des Servers.
  - Ein Consumer mit abweichendem Filter, Ack oder `max_deliver` wird über dieselbe Anfrage
    geändert (NATS ab 2.10).
  - nats-py meldet bei der ersten Nachricht `duplicate=None` statt `False`, die Tests prüfen
    deshalb auf falsy.
  - Der Healthcheck (`wget` auf `/healthz?js-enabled-only=true`) ist im Image ausprobiert.
  - **NAS:** Beim nächsten `make up` startet `nats` mit, Daten unter `./natsdata`. Den Ordner
    sollte Hyper Backup mitsichern, er ist aber nicht die Wahrheit, die liegt in Postgres.

#### P4.2 Outbox und Inbox

- **Test:** DB-Tests:
  - Ein Event entsteht nur bei Commit, ein Rollback hinterlässt keinen Outbox-Eintrag.
  - Das Relay veröffentlicht offene Einträge und markiert sie.
  - Eine doppelte Event-ID wird nur einmal verarbeitet.
  - `UPDATE` auf der Outbox ist nur für `published_at` erlaubt.
- **Implementierung:** Outbox, Relay und Inbox in `va-platform`.
- **Entwurf (01.11.2026):**
  - **Tabellen** (Migration `0009`): `outbox` und `inbox` in jedem der vier Schemas, wie in
    [events.md](events.md).
    - Die Modelle legt der Besitzer des Schemas an (`ScoringOutbox`, `ScoringInbox` usw.), die
      Spalten kommen aus Mixins in `va_platform.messaging`. So bleibt jede Tabelle bei ihrem
      Modul, und die Logik gibt es nur einmal.
    - `outbox`: `id` (Event-ID), `subject`, `payload` (die ganze Hülle als JSONB),
      `created_at` und `published_at`. Ein Teilindex deckt die offenen Einträge ab.
    - `inbox`: `message_id`, `consumer`, `processed_at` und `error`, Schlüssel ist
      `(message_id, consumer)`. `error` ist nur bei einem aufgegebenen Event gesetzt
      (Dead Letter, ab P4.3).
  - **Schreibschutz:**
    - Die Inbox ist nur zum Anfügen da, wie die Faktentabellen.
    - Auf der Outbox lässt der Trigger `va_guard_outbox` nur ein UPDATE zu, das `published_at`
      einmal setzt. Er vergleicht die Zeile ohne `published_at`, also bleibt jede andere Spalte
      gleich, auch eine spätere. Ein zweites Setzen ist verboten.
    - `va_app` bekommt nur das Spaltenrecht `UPDATE (published_at)`.
  - **`va_platform.messaging`:**
    - `Outbox(model).add(session, envelope)` schreibt das Event in die Transaktion des
      Aufrufers. Das Subject kommt aus dem Katalog (`va.<type>`). Flüchtige Events (`live.va.…`)
      lehnt sie ab, die laufen nie über die Outbox.
    - `OutboxRelay(engine, outbox, publisher)`:
      - `publish_pending()` veröffentlicht die offenen Einträge in der Reihenfolge ihres
        Entstehens und markiert jeden nach dem Ack des Publishers.
      - Scheitert ein Versand, bricht es ab. Dieser und alle späteren Einträge bleiben offen und
        kommen beim nächsten Mal dran. Doppelt veröffentlichen ist harmlos, JetStream verwirft
        Duplikate über die `Nats-Msg-Id`.
      - `run(stop, interval=…)` wiederholt das, bis `stop` gesetzt ist. Ein Fehler wird geloggt
        und beendet die Schleife nicht.
      - Die Datenbank läuft synchron und deshalb per `asyncio.to_thread`
        ([datenhaltung.md](datenhaltung.md)).
    - `Inbox(model)`:
      - `claim(session, message_id, consumer)` legt den Eintrag in der Transaktion des Handlers
        an und meldet, ob das Event für diesen Consumer neu ist.
      - `process_once(engine, message_id, consumer, work)` verpackt das: Inbox-Eintrag,
        Fachdaten und Folge-Events (über die Outbox) landen in einer Transaktion oder gar nicht.
      - `record_dead_letter(…)` vermerkt ein aufgegebenes Event mit Fehler, danach gilt es für
        den Consumer als erledigt.
  - **Publisher für NATS:** `va_platform.nats.JetStreamPublisher` setzt `Nats-Msg-Id` gleich der
    Event-ID und verlangt den Stream `VA_EVENTS`.
  - **Nicht in P4.2:** Die Kette läuft weiter über den Bus im Prozess. Handler, die über Inbox
    und Outbox laufen, und das Relay in den Services kommen mit P4.3.
  - **Test (rot):**
    - DB-Tests:
      - Ein Event entsteht nur bei Commit: Vor dem Commit sieht das Relay nichts, nach einem
        Rollback gibt es keinen Eintrag.
      - Das Relay veröffentlicht offene Einträge in Reihenfolge und markiert sie. Ein zweiter
        Lauf veröffentlicht nichts.
      - Scheitert ein Versand, bleiben dieser und alle späteren Einträge offen, der nächste Lauf
        holt sie nach. `run` übersteht einen Fehler.
      - Eine doppelte Event-ID wird je Consumer nur einmal verarbeitet.
      - Scheitert die Verarbeitung, bleibt kein Inbox-Eintrag. Inbox-Eintrag, Fachdaten und
        Folge-Event fallen gemeinsam weg.
      - Nach einem Dead Letter wird das Event nicht mehr verarbeitet.
      - Ein UPDATE auf der Outbox ist nur für `published_at` erlaubt und nur einmal, in allen
        vier Schemas. `va_app` darf keine andere Spalte ändern.
      - Flüchtige Events landen nicht in der Outbox.
      - Jedes Schema hat `outbox` und `inbox`, als Modell und in der migrierten Datenbank.
    - Ohne Datenbank: Die Filter der Consumer aus P4.1 sind Subjects dauerhafter Events im
      Katalog.
    - NATS: Der Publisher veröffentlicht mit `Nats-Msg-Id`, dasselbe Event zweimal landet nur
      einmal im Stream.
- **Umgesetzt (01.11.2026):** wie im Entwurf, dazu:
  - **Parallele Zustellung:** Kommt dasselbe Event noch einmal, während die erste Zustellung
    läuft, wartet die zweite auf deren Transaktion. Nach einem Commit überspringt sie das Event,
    nach einem Rollback verarbeitet sie es selbst (Test mit zwei echten Transaktionen).
  - **Backoff im Relay:** `run` verdoppelt die Pause nach einem Fehler bis `max_interval`
    (30 s). Nur der erste Fehler einer Serie kommt mit Traceback ins Log, die Erholung wird
    gemeldet. Sonst schriebe ein NATS-Ausfall jede Sekunde einen Traceback.
  - **Reihenfolge:** Innerhalb einer Transaktion bleibt sie erhalten, über Transaktionen nur
    ungefähr. `created_at` ist der Beginn der Transaktion, nicht ihr Commit.
  - **Migration `0009`:** Die Trigger-Funktion `va_guard_outbox` steht ausgeschrieben in der
    Migration, wie in `0005`. Die Schemas stehen dort fest, nicht aus `ddl.SCHEMAS`.
  - Modelle und migrierte Datenbank stimmen überein: Alembic findet beim Vergleich keine
    Abweichung.
  - Ohne Nutzer bis P4.3. Die neuen Tabellen bleiben auf der NAS leer, bis die Services über
    Inbox und Outbox laufen.

#### P4.3 NATS als Bus

- **Test:** Die Bus-Vertragstests aus P1.8 laufen zusätzlich gegen NATS und sind dort zunächst rot.
- **Implementierung:** NATS-Implementierung der Bus-Schnittstelle, Umschaltung per Konfiguration.
- **Entwurf (03.11.2026):**
  - **Entscheidung (User, 03.11.2026):** ein eigener Adapter mit nats-py statt FastStream.
    - Die Schnittstelle `EventBus` aus P1.8 bleibt, Handler und Contracts ändern sich nicht.
    - nats-py ist seit P4.1 da, es kommt keine Abhängigkeit dazu.
    - [ADR-0002](../adr/0002-nats-jetstream-und-faststream.md) bekommt einen Nachtrag: FastStream
      frühestens, wenn die Services in Phase 5 eigene Prozesse werden.
  - **`va_platform.nats.NatsBus`:**
    - `EventBus` über JetStream, synchron nach außen. Intern läuft eine Event-Loop in einem
      eigenen Thread. Die Handler laufen in einem Thread-Pool und dürfen selbst `publish`
      aufrufen.
    - Beim Start ruft er `provision()` aus P4.1. Der Stream entsteht also nie anders als
      vorgegeben (Dateispeicher, 30 Tage, Deduplizierung).
    - **Consumer:**
      - Ein Consumer, den die Provisionierung kennt, wird so benutzt, wie er ist. Deckt sein
        Filter ein abonniertes Subject nicht ab, ist das ein Fehler beim `subscribe`.
      - Einen unbekannten Namen (in den Tests) legt der Bus selbst an, mit genau den
        abonnierten Subjects. Er bekommt nur neue Nachrichten, alte im Stream nicht.
      - Je Consumer läuft eine Abholschleife. Er verarbeitet nacheinander und verteilt nach
        Event-Typ an die Handler. Ein Typ ohne Handler wird bestätigt und übersprungen.
    - **Senden:**
      - `Nats-Msg-Id` ist die Event-ID, das übernimmt der `JetStreamPublisher` aus P4.2.
      - `publish` kehrt erst nach dem Ack von JetStream zurück. Folge-Events liegen also im
        Stream, bevor das auslösende Event bestätigt wird.
      - Flüchtige Events (`live.va.…`) gehen über Core-NATS. Sie zu abonnieren kommt mit P4.5.
    - **Wiederholungen:**
      - Es gilt die Grenze des Busses, wie im Prozess. Der Batch bleibt bei `max_deliver=1`,
        eine Mail geht also nicht durch eine Wiederholung doppelt raus.
      - Ist die Grenze erreicht: Dead-Letter-Callback, danach `term()`. Darunter `nak()` mit
        kurzer Pause.
      - Die Grenze des Busses darf höchstens die des Consumers sein (5), sonst verwürfe NATS
        das Event still.
    - **In-Progress-Acks:** Solange ein Handler läuft, meldet der Bus alle `ack_wait / 3`
      Sekunden, dass er noch arbeitet. Der Abruf von market-data dauert Minuten, ohne das
      stellte JetStream nach 60 s erneut zu.
    - **Nicht lesbar:** Ist schon die Hülle unlesbar, wird die Nachricht geloggt und mit
      `term()` verworfen. Eine unbekannte Payload behandelt der Bus wie einen gescheiterten
      Handler: erst Wiederholung, dann Dead Letter mit der Hülle.
    - **`settle(timeout)`:** wartet, bis die eigenen Consumer nichts mehr offen haben und kein
      Handler mehr läuft (zweimal hintereinander geprüft).
    - **`close()`:** holt nichts Neues mehr ab, lässt laufende Handler zu Ende laufen und
      bestätigen, dann trennt er die Verbindung.
  - **Umschaltung im Batch:**
    - In `Settings` kommen dazu:
      - `EVENT_BUS` (`in_process` oder `nats`, Standard `in_process`)
      - `NATS_URL`, Pflicht bei `nats`
      - `RUN_TIMEOUT_MINUTES` (Standard 120)
    - Der Bus im Prozess ist fertig, wenn `publish` zurückkehrt. Über NATS wartet `src/main.py`:
      - bis der `RunTracker` ein Ergebnis hat, höchstens `RUN_TIMEOUT_MINUTES`;
      - dann bis `settle`, damit ein spätes `screening.run.failed` noch zählt;
      - dann `close`.
      - Ohne Ergebnis endet der Lauf wie bisher als „Lauf ohne Ergebnis“ mit Alarm.
    - Der `RunTracker` meldet sein Ergebnis über ein `threading.Event` und ist gegen parallele
      Aufrufe geschützt.
    - Er bekommt einen eigenen provisionierten Consumer `batch` mit seinen vier Subjects. Er ist
      der Vorläufer der Run-Projektion im web-api.
    - Mit `EVENT_BUS=nats` warnt der Batch im Log: Die Handler sind erst ab P4.3b idempotent.
      Auf der NAS bleibt der Standard `in_process`.
  - **Nicht in P4.3** (eigenes Paket P4.3b, User-Entscheidung 03.11.2026):
    - Handler über Inbox und Outbox
    - Umgang mit veralteten Events aus einem abgebrochenen Lauf
  - **Test (rot):**
    - Die Vertragstests aus `test_bus.py` laufen unverändert zusätzlich gegen NATS (Fixture
      `nats`, mit `TEST_NATS_URL`, jeder Test mit frischem Stream).
    - Zusätzlich gegen NATS:
      - Eine unlesbare Payload wird nach der Grenze zum Dead Letter.
      - Ein Handler, der länger als `ack_wait` läuft, wird nur einmal aufgerufen
        (In-Progress-Acks).
      - `close` während eines laufenden Handlers: Er läuft zu Ende, die Nachricht ist danach
        bestätigt und kommt nicht wieder.
      - Der Stream des Busses hat Dateispeicher, ein provisionierter Consumer bleibt
        unverändert.
      - Ein provisionierter Consumer, dessen Filter das Subject nicht abdeckt, lehnt das Abo
        ab.
      - Die Grenze des Busses darf nicht über der des Consumers liegen.
      - Flüchtige Events gehen nicht in den Stream.
    - Die Kette aus `tests/test_pipeline_bus.py` (Golden-Datensatz ergibt die Golden-Mail) läuft
      auch über NATS.
    - Der Batch mit `EVENT_BUS=nats`:
      - Er wartet auf das Ergebnis, schließt den Lauf mit Erfolg ab und schickt genau eine Mail.
      - Ein Dead Letter beendet den Lauf als gescheitert mit Alarm.
      - Ein Timeout endet als „Lauf ohne Ergebnis“.
    - Settings: `EVENT_BUS=nats` ohne `NATS_URL` ist ein Konfigurationsfehler.
    - Provisionierung: Der Consumer `batch` existiert mit seinen Subjects.
- **Umgesetzt (03.11.2026):** wie im Entwurf, dazu:
  - **Schließen ohne `drain()`:** `drain()` von nats-py lief mit Pull-Abos in sein Timeout
    von 30 s. Der Bus wartet stattdessen auf seine Abholschleifen, schickt mit `flush()` die
    letzten Acks und trennt dann.
  - `NATS_URL` steht bei den Settings, die nie in `batch.run` landen (Verbindungs-URL).
  - `make test-nats` führt jetzt alle NATS-Integrationstests aus, nicht nur die
    Provisionierung.
  - Lokal setzt `docker-compose.local.yml` für den Batch `NATS_URL`. Mit `EVENT_BUS=nats` in
    der `.env` läuft `make local-run` über NATS.
  - **Bekannte Grenze, gilt nur für `EVENT_BUS=nats`:**
    - Hängt ein Handler über `RUN_TIMEOUT_MINUTES` hinaus, endet der Lauf als „Lauf ohne
      Ergebnis“, der Handler-Thread läuft aber weiter.
    - Python wartet beim Beenden auf ihn.
    - Der Watchdog (P4.7) und P4.3b gehen das an.

#### P4.3b Idempotente Handler

- **Test:**
  - Eine erneute Zustellung desselben Events ändert nichts mehr: kein zweiter Abruf, kein
    zweiter Bewertungslauf, keine zweite Mail.
  - Folge-Events entstehen in derselben Transaktion wie die Fachdaten.
  - Ein veraltetes Event aus einem abgebrochenen Lauf startet keinen neuen Abruf.
- **Implementierung:** Die Stores von market-data, scoring und notification schreiben
  Inbox-Eintrag, Fachdaten und Folge-Event über die Outbox in einer Transaktion (P4.2). Das
  Relay läuft im Batch mit. Erst danach wird NATS auf der NAS eingeschaltet.
- **Entwurf (04.11.2026):**
  - **Entscheidung (User, 04.11.2026): pragmatisch.** Gewählt ist ein gemeinsamer Wrapper je
    Service statt eines Umbaus aller Store-Ports.
    - Inbox-Eintrag und Folge-Events kommen in eine Transaktion. Die Fachdaten schreibt der
      Handler wie bisher kurz davor.
    - **Rest-Risiko:** Ein Absturz genau zwischen Fachdaten und Abschluss lässt den Handler bei
      erneuter Zustellung noch einmal laufen.
    - Dagegen stehen fachliche Sperren: market-data nutzt den Abruf des Tages wieder, und
      notification verschickt keine zweite Mail.
    - Ein zweiter Bewertungslauf schadet nicht, die Tabellen sind nur zum Anfügen.
  - **`va_platform.messaging.ReliableBus`:** Er umhüllt den Bus für die Handler eines Service,
    mit Inbox und Outbox aus dessen Schema.
    - **Zustellung:**
      1. Ist das Event älter als `max_age`, wird es übersprungen. Das ist ein veraltetes Event
         aus einem abgebrochenen Lauf.
      2. Hat dieser Consumer das Event schon verarbeitet, wird es übersprungen.
      3. Sonst läuft der Handler. Was er dabei veröffentlicht, sammelt der Wrapper.
      4. Danach kommen Inbox-Eintrag und gesammelte Events in einer Transaktion in die Outbox.
      5. Dann gibt der Wrapper die offenen Einträge an den Bus weiter.
    - Wirft der Handler, gibt es weder Inbox-Eintrag noch Folge-Events. Der Bus entscheidet
      dann wie bisher über Wiederholung oder Dead Letter.
    - Flüchtige Events und alles, was außerhalb einer Zustellung veröffentlicht wird (Start des
      Laufs, Dead Letter in `src/main.py`), gehen direkt an den Bus.
    - **Weitergeben:** `drain_outbox` ist die synchrone Schwester des `OutboxRelay` aus P4.2,
      ohne eigene Event-Loop. Auch bei einem schon verarbeiteten Event gibt der Wrapper
      Liegengebliebenes weiter, etwa nach einem Fehler beim letzten Versand.
  - **Verdrahtung:**
    - `Adapters.messaging` liefert in `build_adapters` je Service den `ReliableBus` mit der
      Engine. `max_age` ist `RUN_TIMEOUT_MINUTES`.
    - Tests mit Fakes lassen es leer, dann hängen die Handler wie bisher direkt am Bus.
    - Der Wrapper gilt auch im Prozess, damit der Weg auf der NAS und im E2E-Test derselbe ist.
  - **Sperre in notification:** Hat ein Bewertungslauf schon eine erfolgreich verschickte
    Report-Mail, geht keine zweite raus.
    - Es entsteht kein zweiter Report und kein Ping. Der Handler meldet `report.sent` mit dem
      vorhandenen Report.
    - Dafür gibt es den Port `ReportStore.delivered_report(scoring_run_id)`.
  - **NATS:** Die Warnung „erst ab P4.3b idempotent“ entfällt. Der Standard bleibt der Bus im
    Prozess. NATS auf der NAS ist eine eigene Entscheidung beim Deployment.
  - **Test (rot):**
    - DB-Tests für den `ReliableBus` (Bus im Prozess, Schema `scoring`):
      - Folge-Events gehen über die Outbox und sind danach veröffentlicht.
      - Eine doppelte Zustellung ruft den Handler nur einmal auf.
      - Ein werfender Handler hinterlässt weder Inbox- noch Outbox-Eintrag.
      - Ein veraltetes Event wird übersprungen.
      - Flüchtige Events und Events außerhalb einer Zustellung gehen direkt an den Bus.
      - Ein liegengebliebener Outbox-Eintrag geht mit der nächsten Zustellung raus.
    - `drain_outbox`: in Reihenfolge, markiert, bricht bei einem Fehler ab.
    - Batch mit echter Datenbank: Dasselbe `screening.run.requested` zweimal zugestellt ergibt
      einen Abruf, einen Bewertungslauf und eine Mail.
    - Ein `screening.run.requested` älter als `RUN_TIMEOUT_MINUTES` startet keinen Abruf.
    - notification: Bei schon verschickter Mail keine zweite, aber `report.sent`.
    - Repository: `delivered_report` findet nur erfolgreich verschickte Reports.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - `drain_outbox` und `OutboxRelay` teilen sich die Abfragen (offene Einträge, Markieren).
  - **Fehler beim Weitergeben:** Scheitert `drain_outbox` nach dem Abschluss, wirft der
    Wrapper. Der Bus entscheidet dann über Wiederholung. Die erneute Zustellung trifft auf
    den Inbox-Eintrag und gibt das Liegengebliebene weiter.
  - **Folge für die NAS:** Auch im Prozess schreibt jeder Lauf je Stufe einen Inbox- und einen
    Outbox-Eintrag (Migration `0009`, Rolle `va_app`). Der E2E-Test läuft diesen Weg mit
    echter Datenbank.
  - Das Replay-Werkzeug hängt die Handler weiter direkt an den Bus und schreibt nichts.

#### P4.4 Eventmanager und Projektionen

- **Test:**
  - Die Projektion läuft vor dem Broadcast, der Broadcast erst nach dem Commit.
  - Bei einem Fehler gibt es keinen Broadcast, die Exception führt zur Wiederholung.
  - Eine Wiederholung ist idempotent.
- **Implementierung:** Eventmanager, Schema `web` (Migration) und die Projektionen
  ([web-api-realtime.md](web-api-realtime.md)).
- **Entwurf (04.11.2026):**
  - **Woher die Events kommen:**
    - Das web-api liest über den provisionierten Consumer `web-api` (`va.>`) mit dem `NatsBus`
      aus P4.3.
    - Läuft die Kette im Prozess (Standard, auch auf der NAS), kommt beim web-api nichts an,
      und die Projektionen bleiben leer.
    - Die REST-Endpunkte lesen deshalb weiter aus den Tabellen des Batches (`va_read`). Auf die
      Projektionen wechseln sie, wenn NATS der Standard ist. Das ist ein eigener Schritt beim
      Deployment, die REST-API bleibt dabei gleich.
  - **Schema `web`** (Migration `0010`, Besitzer `va_web_api.adapters.postgres`), in
    `APP_SCHEMAS`:
    - `inbox` und `outbox` wie in jedem Service-Schema (P4.2). Die Outbox nutzt erst P4.7.
    - `run_status`: eine Zeile je Run.
      - Spalten: Status (`requested`, `fetched`, `scored`, `reported`, `failed`, `no_data`),
        Trigger, IDs von Abruf, Bewertung und Report, Größe des Universums, Zahl bewerteter
        Titel, Fehler, zuletzt verarbeitetes Event und dessen Zeit.
      - Ein Fehlschlag gewinnt, wie im `RunTracker`.
      - Als Projektion ist `run_status` die bewusst gekennzeichnete veränderliche Tabelle
        ([datenhaltung.md](datenhaltung.md)): `UPDATE` erlaubt, `DELETE` und `TRUNCATE` nicht.
    - `ranking_row`: je Bewertungslauf und Titel Rang, die drei Scores, Value-Trap-Flag, Name,
      Index und Run.
      - Nur zum Anfügen, auch bei einem Rescore.
      - Daraus ergeben sich das aktuelle Ranking und der Score-Verlauf je Titel.
  - **Rolle `va_web`:** Sie darf im Schema `web` lesen und anfügen und `run_status` ändern,
    sonst nichts. `va_read` darf `web` lesen.
    - Angelegt wird sie wie `va_profiles`: von `db/init/01_roles.sh` bei einer neuen
      Datenbank, von `python -m src.db.migrate` mit `VA_WEB_PASSWORD` bei einer bestehenden.
    - Das web-api bekommt sie über `WEB_API_PROJECTIONS_DATABASE_URL`, nie die Zugangsdaten des
      Batches.
  - **`va_web_api.events.EventManager`** (synchron, läuft in den Handler-Threads des
    `NatsBus`):
    - `dispatch(envelope, seq)`:
      1. Inbox-Eintrag und alle Projektionen des Event-Typs laufen in einer Transaktion.
      2. Nach dem Commit gehen die Meldungen an den `Broadcaster`, je Topic aus
         [web-api-realtime.md](web-api-realtime.md): `runs`, `ranking`, `profiles`.
    - Wirft eine Projektion, wird zurückgerollt, nichts gesendet, und die Exception geht an
      den Bus. JetStream stellt dann erneut zu.
    - Eine erneute Zustellung ändert nichts und sendet nichts.
    - Ein Fehler des `Broadcaster` kostet nur die Meldung, nicht das Event.
    - Der `Broadcaster` ist ein Port. Bis P4.5 (WebSocket-Hub) protokolliert er nur.
  - **`seq`:** Der `NatsBus` legt die Stream-Sequenz der gerade verarbeiteten Nachricht in einen
    Kontext (`current_sequence()`). Über NATS reicht das web-api sie mit, im Prozess gibt es
    keine.
  - **Start im web-api:** Mit `WEB_API_NATS_URL` und `WEB_API_PROJECTIONS_DATABASE_URL` öffnet der
    Lifespan einen `NatsBus` (Consumer `web-api`, alle dauerhaften Events) und schließt ihn am
    Ende.
    - Fehlt eins davon, gibt es keine Projektionen, die App läuft trotzdem.
    - Ist NATS beim Start nicht erreichbar, wird das geloggt, und die App startet ohne
      Projektionen.
  - **Compose:**
    - Lokal bekommt das web-api beide Variablen.
    - Auf der NAS bleibt es vorerst ohne. Dort läuft die Kette im Prozess, also gäbe es nichts
      zu projizieren.
  - **Test (rot):**
    - DB-Tests für den `EventManager` (Schema `web`, echte Datenbank, Fake-`Broadcaster`):
      - Beim Broadcast ist die Projektion schon committet (eine zweite Verbindung sieht sie).
      - Wirft eine Projektion, gibt es keinen Broadcast und weder Inbox-Eintrag noch
        Projektion. Die Exception kommt beim Aufrufer an.
      - Dasselbe Event zweimal: nur einmal projiziert und gesendet.
      - Der Run-Status folgt der Kette (`requested` bis `reported`), ein Fehlschlag gewinnt
        gegen ein späteres `report.sent`.
      - `scoring.run.completed` legt die Ranking-Zeilen an, ein Rescore ohne Run ebenso, aber
        ohne Run-Status.
      - Topics: `runs`, `ranking` und `profiles` je nach Event.
    - Schutz und Rollen:
      - `ranking_row` und `inbox` sind nur zum Anfügen.
      - `run_status` lässt sich ändern, aber nicht löschen.
      - `va_web` schreibt nur in `web`, `va_read` liest `web`.
      - Die Migration legt `va_web` an.
    - Schema-Grenzen: `web` hat einen Besitzer, `outbox` und `inbox`.
    - NATS und DB: Ein über NATS veröffentlichtes Event landet in der Projektion, mit der
      Stream-Sequenz.
    - web-api: Ohne NATS-Einstellungen startet die App ohne Consumer.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - **Dead Letter:** Ein Event, das der Eventmanager auch nach `max_deliver` (5) nicht
    verarbeitet, vermerkt er mit Fehler in `web.inbox` (`record_dead_letter` aus P4.2).
  - **Stream-Sequenz:** `current_sequence()` setzt der `NatsBus` im Handler-Thread selbst.
    Ein `run_in_executor` reicht den Kontext nicht weiter.
  - **Rechte:** `va_app` (Batch) bekommt im Schema `web` keine Rechte.
  - **Modelle und Migration** stimmen überein, Alembic findet beim Vergleich keine Abweichung.
  - **Für P4.5:** Die Meldung zu `scoring.run.completed` trägt die ganze Rangliste. Für den
    WebSocket sollte sie schlanker werden (Kopf des Laufs, Rangliste per REST).

#### P4.5 WebSocket-Hub und Protokoll v1 🔒

- **Test:**
  - Ohne Subprotokoll `va.v1` wird die Verbindung abgelehnt, ebenso bei fremdem `Origin`.
  - Abos filtern nach Topic.
  - Eine volle Queue führt zum Schließen mit Code 1013.
  - `resumeFrom` spielt verpasste Events nach bzw. löst `resync` aus.
- **Implementierung:** Hub, Protokoll und Endpunkt `/ws`.
- **Entwurf (04.11.2026):**
  - **Endpunkt `/ws`** im web-api, nginx reicht ihn weiter: `location = /ws` mit Upgrade-Headern,
    `Host $http_host` und `proxy_read_timeout` 3600 s. Uvicorn pingt alle 20 s.
  - **Handshake (🔒), abgelehnt wird vor dem `accept` (HTTP 403):**
    - wenn der Client das Subprotokoll `va.v1` nicht anbietet;
    - wenn `Origin` fehlt oder fremd ist.
    - Erlaubt ist ohne Einstellung nur dieselbe Herkunft: Host und Port von `Origin` gleich dem
      `Host`-Header, den nginx mit Port weiterreicht. Mit `WEB_API_ALLOWED_ORIGINS` (durch Komma
      getrennt, kein JSON) gelten genau diese.
  - **Protokoll v1** (`va_web_api.realtime.protocol`), Pydantic-Modelle mit camelCase:
    - Client: `subscribe` (`topics`, optional `resumeFrom` ≥ 0), `unsubscribe`, `ping`.
    - Server: `hello` (`serverTime`, `lastSeq`), `event`, `resync`, `pong`, `error`.
    - Topics: `runs`, `ranking`, `profiles` und `instrument:<SYMBOL>` (Muster geprüft), höchstens
      20 je Nachricht.
    - Fehlerhafte Eingaben beenden die Verbindung nicht, der Server antwortet mit `error`:
      ungültiges JSON, Binärdaten, unbekanntes `op`, unbekanntes Topic, falsche Typen.
    - Eine Nachricht über 4 KiB schließt die Verbindung mit 1009.
    - Die Event-Daten bildet der Server auf camelCase ab. `scoring.run.completed` kommt ohne die
      Rangliste, stattdessen mit `rankingSize`. Die Rangliste holt das UI per REST.
  - **Hub** (`va_web_api.realtime.hub`, in der Event-Loop von Uvicorn):
    - Je Client eine Warteschlange (256) und ein eigener Schreib-Task. Ist sie voll, wird der
      Client mit 1013 getrennt, die anderen merken nichts.
    - Abos filtern nach Topic. Ein Event geht genau an die Clients, die sein Topic abonniert
      haben.
    - Der `HubBroadcaster` reicht die Meldungen des Eventmanagers (Threads des `NatsBus`) per
      `call_soon_threadsafe` an die Event-Loop. Er ersetzt den `LoggingBroadcaster` aus P4.4.
  - **Nachspielen** (`resumeFrom`):
    - Ein `NatsReplayer` liest den Stream `VA_EVENTS` ab der Sequenz, gefiltert auf die
      Topics, höchstens 500 Events. Ist die Lücke größer, älter als der Stream oder NATS nicht
      da, schickt er je Topic `resync`.
    - Live-Events eines Clients hält der Hub zurück, solange sein Nachspielen läuft. Danach
      verschickt er sie, ohne Sequenzen, die schon nachgespielt sind. So kommt nichts doppelt
      und nichts vertauscht an.
  - **Fortschritt:** Der `NatsBus` kann jetzt flüchtige Events abonnieren (Core-NATS, ohne
    Wiederholung). Das web-api leitet `marketdata.fetch.progressed` direkt an das Topic `runs`
    weiter, ohne `seq` und ohne Projektion.
  - **Abhängigkeit:** `websockets` (16) steht künftig selbst beim web-api. Bisher kam es nur über
    yfinance ins Image, und Uvicorn braucht es für WebSockets.
  - **Ohne NATS** (NAS, E2E): Der Endpunkt funktioniert, `lastSeq` ist leer, `resumeFrom` führt
    zu `resync`.
  - **Test (rot):**
    - web-api mit TestClient:
      - Handshake ohne `va.v1`, mit fremdem oder fehlendem `Origin` wird abgelehnt. Dieselbe
        Herkunft und eine erlaubte Herkunft gehen durch.
      - `hello` nach dem Verbindungsaufbau.
      - Abos filtern nach Topic, `unsubscribe` beendet sie, `ping` ergibt `pong`.
      - Fehlerhafte Eingaben ergeben `error`, und die Verbindung bleibt. Eine zu große Nachricht
        schließt sie mit 1009.
      - `resumeFrom`: Nachgespieltes kommt vor Live-Events, nichts doppelt. Bei zu großer Lücke
        kommt `resync`.
      - `scoring.run.completed` kommt ohne Rangliste, in camelCase.
    - Hub: Eine volle Warteschlange schließt mit 1013, andere Clients bekommen weiter.
      `HubBroadcaster` aus einem anderen Thread erreicht den Client.
    - NATS: Der `NatsReplayer` liefert die Events nach einer Sequenz mit Topic und `seq` und
      meldet eine zu große oder zu alte Lücke. Der `NatsBus` liefert flüchtige Events an ein
      Abo.
    - E2E (über nginx): Handshake mit eigener Herkunft ergibt `hello`, eine fremde Herkunft
      wird abgelehnt.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - **`NatsBus._call`:** Bei einer Zeitüberschreitung bricht der Bus die Koroutine in seiner
    Loop jetzt ab, statt sie weiterlaufen zu lassen.
  - **nginx:** Die statische Prüfung (`tests/test_nginx_conf.py`) hält `location = /ws` fest:
    Upgrade-Header, Host mit Port, Timeout über 60 s.
  - **`uv.lock`:** ändert sich nur um die Kante zu `websockets` 16.0. Das Paket war schon im
    Image, die J4125-Prüfung lief also bereits damit.
  - **Grenze:** Ist `WEB_API_NATS_URL` gesetzt, NATS aber nicht erreichbar, kommt `hello` erst
    nach dem gescheiterten Verbindungsversuch des Replayers (einige Sekunden). Ohne die Variable
    (NAS, E2E) gibt es keinen Replayer.

#### P4.6 Echtzeit im Frontend

- **Test:** `RealtimeService` mit Mock-WebSocket:
  - Wiederverbinden mit Backoff
  - `resumeFrom` beim Wiederverbinden
  - Events landen im Store
- **Implementierung:** Service, NgRx-Events und Reducer.
- **Entwurf (04.11.2026):**
  - **Abhängigkeit:** `@ngrx/signals` 22.0.1 (passt zu Angular 22), daraus SignalStore und das
    Events-Plugin (`@ngrx/signals/events`), wie in [frontend.md](frontend.md) vorgesehen.
  - **`RealtimeService`** (`frontend/src/app/shared/realtime/`):
    - Kapselt `rxjs/webSocket` mit dem Subprotokoll `va.v1`. Die Adresse ist relativ zur Seite
      (`ws://<host>/ws`, unter HTTPS `wss`).
    - Status als Signal: `connecting`, `online`, `offline`.
    - Abonniert beim Öffnen die Topics `runs`, `ranking` und `profiles`. Beim Wiederverbinden
      schickt er dazu `resumeFrom` mit der letzten gesehenen `seq`. Vor dem ersten Event gilt
      die `lastSeq` aus `hello`.
    - Bricht die Verbindung ab, verbindet er neu: 1 s, 2 s, 4 s … bis 30 s, je mit Zufallsanteil
      (50–100 %). Nach einer erfolgreichen Verbindung beginnt die Folge von vorn.
    - Servernachrichten gehen als NgRx-Events weiter (`eventGroup({ source: 'Server' })`):
      `event` und `resync`. `pong` und `error` schluckt er, damit die Konsole leer bleibt
      (Regel der Browser-Tests).
    - Für Tests ist die WebSocket-Klasse austauschbar (`WebSocketCtor` von `rxjs/webSocket`),
      ebenso Wartezeiten und Zufall.
  - **`LiveStore`** (SignalStore, `withReducer`):
    - Je Topic ein Zähler `version`. Er steigt bei jedem dauerhaften Event und bei `resync`
      dieses Topics.
    - Fortschritt je Run aus `marketdata.fetch.progressed` (`done`, `total`, `symbol`). Mit dem
      Abschluss des Runs fällt er weg.
  - **Ansichten:**
    - Die Liste der Runs lädt neu, wenn `version('runs')` steigt, und zeigt den Fortschritt
      laufender Runs.
    - Das Ranking lädt neu bei `version('ranking')`.
    - Die Toolbar zeigt „offline“, solange keine Verbindung besteht.
  - **Protokoll-Typen** (`protocol.ts`): von Hand, gespiegelt aus `va_web_api.realtime.protocol`.
    Damit eine Änderung auffällt, hält ein Python-Golden-Test das JSON-Schema der
    Protokoll-Modelle fest (`tests/golden/realtime/v1.json`). Generiert wird erst, wenn das
    Protokoll wächst.
  - **Entwicklung:** `proxy.conf.json` reicht `/ws` (mit `ws: true`) an das web-api weiter.
  - **Test (rot):**
    - `RealtimeService` mit Fake-WebSocket:
      - Verbindet mit `va.v1` und abonniert die Topics.
      - Status `online`, nach Abbruch `offline`.
      - Wiederverbinden mit wachsender, gedeckelter Wartezeit und Zufallsanteil, nach Erfolg
        wieder ab 1 s.
      - `resumeFrom` mit der letzten `seq`, ohne Events mit der `lastSeq` aus `hello`.
      - Events und `resync` landen im `LiveStore`.
    - `LiveStore`: Versionen je Topic, Fortschritt kommt und geht.
    - Ansichten:
      - Runs laden bei einem Run-Event neu und zeigen den Fortschritt.
      - Das Ranking lädt bei einem Ranking-Event neu.
      - Die Toolbar zeigt „offline“.
    - Python: Golden-Schema des Protokolls.
    - E2E (Playwright): Die Toolbar steht nach dem Laden auf „online“, die Konsole bleibt leer.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - **Status `idle`:** Er gilt, solange der Service nicht gestartet ist. Nur die App startet
    ihn (`provideAppInitializer`). Komponententests ohne App bauen also keine Verbindung auf.
  - **Senden:** Das Abo geht im `openObserver` raus. `rxjs/webSocket` puffert es und sendet es
    nach dem Öffnen.
  - **Budget:** Der Build warnt weiter wegen des initialen Budgets (500 kB). Das Bundle liegt
    bei 753 kB, NgRx trägt einige kB bei. Das war schon vorher über der Grenze und ist keine
    neue Warnung.

#### P4.7 Runs aus dem UI, Watchdog, Scheduler

- **Test:** mit einer steuerbaren Uhr:
  - Der Watchdog meldet einen Timeout.
  - Derselbe Cron-Termin erzeugt nur einen Run.
  - Ein Start aus dem UI legt einen Run an.
- **Implementierung:** Run-Verwaltung im web-api und Anzeige des Fortschritts im UI.
- **Entwurf (04.11.2026):**
  - **Wer einen Run ausführt:** Bisher hängen die Handler nur im kurzlebigen Batch-Prozess am
    Bus. Ein Start aus dem UI braucht einen Prozess, der dauerhaft lauscht.
    - Neu ist der Dienste-Prozess `python -m src.worker`. Er hängt market-data, scoring und
      notification wie der Batch an den `NatsBus` (`wire`, je Service ein `ReliableBus`) und läuft,
      bis er SIGTERM bekommt.
    - Er legt keine Runs an und schließt keine ab, das macht das web-api.
    - Scheitert ein Handler endgültig (Dead Letter), meldet der Worker `screening.run.failed`.
      `trigger` und `options` nimmt er aus dem Event. Dieselbe Funktion nutzt auch der Batch.
    - P5.1 teilt ihn in ein Image je Service auf.
    - Compose: Dienst `worker` aus dem App-Image, eigener Einstieg ohne Migration (wie das
      web-api), nur mit dem Profil `nats`. Auf der NAS läuft er also erst nach dem Umstieg,
      lokal startet `make local-up` ihn mit.
  - **Run-Verwaltung im web-api** (`va_web_api.runs`):
    - `RunManager.start(trigger, options, slot=None)` legt den Run in einer Transaktion an:
      - eine Zeile in `batch.run` (Art `batch`, Status `running`);
      - eine Zeile in `web.run_request` (Trigger, Optionen, Termin);
      - eine Zeile `requested` in `web.run_status`;
      - `screening.run.requested` in die Outbox `web.outbox`.

      Danach leert er die Outbox an NATS. Ist NATS gerade weg, holt das der nächste Takt nach.
    - Die ID muss aus `batch.run` kommen, alle Services verweisen darauf. Das web-api schreibt
      deshalb in `batch.run`, wie es die Zielarchitektur vorsieht (`batch` gehört dem web-api,
      [datenhaltung.md](datenhaltung.md)).
    - **Abschluss:** Eine Projektion schließt `batch.run` ab, wenn `notification.report.sent` oder
      `screening.run.failed` ankommt. Das geschieht in der Transaktion des Eventmanagers und nur
      für Runs des web-api (Zeile in `web.run_request`).
      - Die Regeln sind die des `RunTracker`: `success` oder `partial` nach den Zählern,
        `no_data` mit Exit 3, sonst `failed` mit Exit 1.
      - Abgeschlossen wird beim ersten Ergebnis. Ein späterer Fehlschlag steht nur in
        `web.run_status`, weil `batch.run` nur einmal abgeschlossen werden darf.
      - Runs des Batches (Cron, `make run`) schließt weiter der Batch selbst ab.
    - **Nur ein manueller Run zur Zeit:** Läuft schon ein Run des web-api, antwortet ein Start
      aus dem UI mit 409. Zwei Abrufe zugleich verdoppelten die Last auf Yahoo. Eine Sperre
      (`pg_advisory_xact_lock`) verhindert, dass zwei Klicks gleichzeitig durchkommen. Der
      Scheduler startet trotzdem: Ein hängender manueller Run blockiert den Wochenlauf nicht,
      der Watchdog räumt ihn ab.
  - **Scheduler:**
    - `WEB_API_SCHEDULE` ist ein Cron-Ausdruck, ausgewertet in `WEB_API_SCHEDULE_TIMEZONE`
      (Standard `Europe/Berlin`), unabhängig von der Zeitzone des Containers. Die Bibliothek ist
      `cronsim`: klein, ohne Abhängigkeiten, Sommerzeit wie cron.
    - Leer (Standard) heißt aus. Liefen Cron im Container und Scheduler zugleich, gäbe es zwei
      Wochenläufe. Den Umstieg macht P5.4: Standard wird der Scheduler, der Cron entfällt.
    - Jeder Takt (60 s) nimmt den jüngsten Termin. Liegt er höchstens eine Stunde zurück,
      legt der Takt ihn als Run mit `trigger=scheduled` an. Ein Neustart kurz nach dem Termin
      holt ihn also nach.
    - Idempotent über einen eindeutigen Index auf `web.run_request.slot`. Derselbe Termin ergibt
      nur einen Run, auch bei mehreren Takten, einem Neustart oder zwei Instanzen.
  - **Watchdog:** Er prüft im selben Takt die offenen Runs des web-api, also Runs ohne Ergebnis in
    `web.run_status`. Die Grenzen sind einstellbar:
    - Abruf: `WEB_API_WATCHDOG_FETCH_MINUTES`, Standard 45, ab der Anfrage.
    - Bewertung: `…_SCORING_MINUTES`, Standard 5, ab `fetched`.
    - Mail: `…_REPORT_MINUTES`, Standard 5, ab `scored`.

    Ist eine Grenze überschritten, kommt in einer Transaktion zusammen:
    - `screening.run.failed` (`stage=watchdog`, `reason=timeout`, im `detail` die Stufe) in die
      Outbox;
    - `failed` in `web.run_status`;
    - der Abschluss von `batch.run`.

    Der nächste Takt sieht den Run nicht mehr als offen und meldet ihn kein zweites Mal.
    notification schickt die Fehlermail, bei `scheduled` auch den Ping auf `/fail`. Liefert eine
    Stufe danach doch noch, bleibt der Run gescheitert. Eine Mail kann dann trotzdem rausgehen,
    abbrechen kann das web-api den Abruf nicht.
  - **Takt:** eine Hintergrund-Aufgabe im Lifespan, gestartet nur mit NATS und
    Projektions-Datenbank. Sie ruft Scheduler, Watchdog und Outbox im Thread auf. Die Uhr ist
    ein Parameter, Tests steuern sie.
  - **Datenbank (Migration `0011`):**
    - Neue Tabelle `web.run_request`, nur zum Anfügen, mit eindeutigem `slot`.
    - `va_web` bekommt Rechte im Schema `batch`: `SELECT` und `INSERT` auf `batch.run`,
      `UPDATE` nur auf die Spalten des Abschlusses, dazu die Sequenz. Der Trigger
      `va_guard_finished` lässt weiter nur den einmaligen Abschluss zu.
    - Keine neue Rolle: Aus `va_web` wird in P5.3 die Rolle des web-api.
  - **REST:** `POST /api/v1/runs` mit `force_refresh`, `dry_run`, `notify`:
    - Erfolg: 202 mit der ID des Runs.
    - 409: Es läuft schon ein Run.
    - 503: Ohne NATS oder Projektions-Datenbank.

    Additiv: neuer OpenAPI-Snapshot und neuer TS-Client.
  - **UI:** Auf der Seite Runs ein Formular „Lauf starten“ mit den drei Optionen. Nach dem Start
    erscheint der Run über das Run-Event in der Liste, der Fortschritt kommt aus P4.6. Fehler
    (409, 503) stehen als Meldung über der Tabelle.
  - **Nebenbei:** `entrypoint.sh` gibt `EVENT_BUS`, `NATS_URL` und `RUN_TIMEOUT_MINUTES` an den
    Cron-Lauf weiter. Bisher lief der Cron-Batch immer im Prozess, egal was in der `.env` stand.
  - **Test (rot):**
    - Scheduler, rein:
      - Der jüngste Termin in `Europe/Berlin`, auch über die Sommerzeit.
      - Kein Termin, wenn der letzte über eine Stunde zurückliegt.
      - Ein ungültiger Ausdruck scheitert beim Start der Settings.
    - Datenbank (`tests/db/web_api/test_runs.py`, mit steuerbarer Uhr):
      - Ein Start legt `batch.run`, `run_request`, `run_status` und das Event in der Outbox an.
      - Derselbe Termin zweimal ergibt einen Run.
      - Ein manueller Start bei offenem Run wird abgelehnt.
      - Der Watchdog meldet einen Timeout:
        - Vor der Grenze passiert nichts.
        - Danach stehen `run.failed` in der Outbox, `failed` in `run_status` und der Abschluss
          von `batch.run`.
        - Ein zweiter Takt meldet nichts mehr.
        - Die Grenze gilt je Stufe.
      - Die Projektion schließt Runs des web-api ab: `success`/`partial`, `no_data`, `failed`.
        Runs des Batches bleiben unberührt.
      - Rechte: `va_web` legt Runs an und schließt sie einmal ab. Löschen und ein zweiter
        Abschluss scheitern.
    - API: 202 mit ID, 409, 503, nur JSON, unbekannte Felder 422.
    - NATS und Datenbank (`tests/test_worker_nats.py`): Das web-api startet einen Run, der Worker
      führt ihn aus, der Eventmanager schließt `batch.run` mit `success` ab, die Mail ist da.
    - Worker: Ein Dead Letter wird zu `screening.run.failed` mit Trigger und Optionen des
      Events.
    - Compose und Entrypoint: Dienst `worker` mit Profil `nats` und ohne Migration, die neuen
      Variablen im Cron-Lauf.
    - Frontend: Das Formular schickt die Optionen und zeigt 409 und 503 als Meldung.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - **Ohne Zeile in `run_status` beim Start:** Sie entsteht wie bei jedem Run erst mit dem Event,
    das über NATS zurückkommt. Der Watchdog misst den Abruf ab `run_request.requested_at`.
  - **Stufe geht nie zurück:** `run_status` geht nur vorwärts, `last_event_at` ebenso. Die
    Handler des `NatsBus` laufen parallel. Ein spätes `requested` hätte sonst ein `fetched`
    überschrieben, und der Watchdog hätte die Bewertung ab dem früheren Zeitpunkt gemessen.
  - **`batch.run` aus dem web-api:**
    - Eine schlanke Tabellenbeschreibung (`va_web_api.adapters.postgres.batch_run`), weil das
      web-api `src` nicht importieren darf.
    - `app_version` ist die Version des Batches, `src.web` reicht sie an `create_app` weiter.
    - `settings` und `universe_mode` bleiben leer, das web-api kennt die Settings des Batches nicht.
  - **Dead Letter:** `src.dead_letters.run_failure` nutzen Batch und Worker gemeinsam. Run, Trigger
    und Optionen kommen aus dem Event. Ein Rescore scheitert als Rescore.
  - **Senden:** Ein Start aus dem UI leert die Outbox sofort über den Bus des Event-Consumers. Sonst
    tut das der Takt (60 s).
  - **Cron-Lauf:** `entrypoint.sh` gibt alle Settings des Batches weiter, auch `REPLAY_SOURCE`.
    `tests/test_entrypoint.py` prüft das künftig für jedes neue Feld.
  - **Langsamer Test:** Auf dem Windows-Rechner läuft eine Verbindung zu `127.0.0.1:1` erst nach
    130 s in den Timeout. Der Test mit unerreichbarem NATS gibt der Datenbank-URL deshalb
    `connect_timeout=2` mit, denn der Takt verbindet sich gleich beim Start.
  - **Offen:**
    - Die Log-Zeilen eines Worker-Runs landen nicht in `batch.run_log`, nur im Log des
      Containers. Das kommt mit dem Tracing (P5.5).
    - Den Umstieg vom Cron auf den Scheduler macht P5.4.

#### P4.8 Vorschau und Profil-Befehle über NATS

- **Test:** Die API-Tests aus P3.3 laufen unverändert über den RPC-Adapter.
- **Implementierung:** Request/Reply-Adapter für `ScoringPreview` und die Profil-Befehle.
- **Entwurf (04.11.2026):**
  - **Contracts** (`va_contracts.rpc.v1`, neu und additiv):
    - Je Befehl ein Anfrage- und ein Antwortmodell. `RpcSpec` verbindet Name, Subject
      (`rpc.va.<name>`) und Modelle, wie `EventSpec` bei den Events. Katalog `RPCS`.
    - Befehle: `scoring.factors`, `scoring.preview`, `scoring.profiles.save`,
      `scoring.profiles.activate`.
    - Jede Antwort hat ein optionales Feld `error` mit `code` und `message`, bei einem Konflikt
      auch `newest`. Codes: `no_data`, `unknown_profile`, `unknown_version`, `conflict`,
      `invalid`, `internal`.
    - Die JSON-Schemas liegen als Golden-Files unter `tests/golden/contracts/rpc/v1/`.
  - **Transport** (`NatsBus`, Core-NATS ohne Stream):
    - `call(spec, request)` wartet auf die Antwort. Antwortet niemand oder läuft die Zeit ab,
      gibt es `RpcUnavailable`.
    - `serve(spec, handler, queue=…)` beantwortet Anfragen im Thread-Pool. Mehrere Worker teilen
      sich eine Queue-Gruppe. Eine ungültige Anfrage ergibt den Code `invalid`, eine Exception
      im Handler `internal`.
  - **web-api** (`va_web_api.rpc`):
    - `RemoteScoring` setzt beide Ports (`ScoringPreview`, `ProfileCommands`) über `call` um.
      Die Fehlercodes werden wieder zu den Exceptions der Ports.
    - `scoring_handlers(preview, commands)` ist die Gegenseite: Sie macht aus beliebigen
      Umsetzungen der Ports die Handler für `serve`.
    - Beide Richtungen liegen beim web-api, weil die Befehle die entfernte Form seiner Ports
      sind. Das Format steht neutral in `va_contracts`.
  - **Wer antwortet:** Der Worker (`python -m src.worker`, P4.7) bedient die vier Subjects mit
    dem Code aus P3.3 und der Rolle `va_app`.
    - `InProcessPreview` und `InProcessCommands` ziehen dafür von `src/web.py` nach
      `src/scoring_ops.py`, damit der Worker FastAPI nicht lädt.
    - Die Vorschau liest weiter die Snapshots aus `market_data`. Das geht nur in der Composition
      Root und wird erst mit den Rollen je Service (P5.3) zur lokalen Kopie bei scoring.
  - **Wann über NATS:** mit `WEB_API_NATS_URL`. Ohne sie bleibt alles im Prozess, wie auf der NAS
    und im E2E-Stack.
    - Das web-api öffnet dafür eine eigene NATS-Verbindung im Hintergrund, mit Wiederholung wie
      der Event-Consumer.
    - Ist NATS oder der Worker nicht erreichbar, antworten die vier Endpunkte mit 503
      („Scoring nicht erreichbar“).
    - `WEB_API_PROFILES_DATABASE_URL` braucht es in diesem Fall nicht mehr.
  - **Profil-Events:** Nach Speichern und Aktivieren meldet der Worker `scoring.profile.saved`
    bzw. `scoring.profile.activated`. Der Eventmanager reicht sie an die offenen Tabs weiter
    (Topic `profiles`).
    - Sie gehen direkt an den Bus, ohne Outbox: Sie ändern keine Projektion.
    - Ein verlorenes Event heißt nur, dass ein anderer Tab erst beim nächsten Laden die neue
      Version sieht.
  - **Test (rot):**
    - Contracts:
      - Golden-Schemas je Anfrage und Antwort.
      - Subjects unter `rpc.va.`.
      - Fehler mit `newest` kommen unverändert durch JSON.
    - `NatsBus` mit NATS:
      - `call`/`serve` hin und zurück.
      - Ungültige Anfrage und Exception im Handler ergeben `invalid` bzw. `internal`.
      - Ohne Antwortenden schnell `RpcUnavailable`.
      - Zwei Server in einer Queue-Gruppe antworten nur einmal.
    - Die API-Tests aus P3.3 laufen unverändert ein zweites Mal über NATS:
      - mit den Fakes (`services/web-api/tests/test_scoring_api.py`);
      - mit echter Datenbank über den Worker (`tests/db/web_api/test_scoring_api.py`).

      Dafür bekommen die Fixtures `client` bzw. `api` einen Parameter.
    - web-api: Ist NATS nicht erreichbar, antworten die Endpunkte mit 503.
    - Worker: Nach dem Speichern über NATS kommt `scoring.profile.saved` beim Eventmanager an.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - **Verbindungen im web-api:** Request/Reply und Event-Consumer haben je eine eigene
    NATS-Verbindung. Beide startet dieselbe Hintergrund-Aufgabe mit Wiederholung
    (`_keep_started`, alle 30 s).
  - **`scoring.factors`** ist ein eigener Befehl. Der Katalog hängt am Code von scoring, nicht an
    den Profilen.
  - **Fehler `invalid` und `internal`** sind Bugs und ergeben im web-api eine 500, wie bisher eine
    Exception im selben Prozess.
  - **`src/web.py`** enthält nur noch die Fabrik. Die Umsetzung der Ports liegt in
    `src/scoring_ops.py`, und der Worker importiert sie ohne FastAPI.

#### P4.9 REST aus Projektionen und Request/Reply (nachgetragen 04.11.2026)

- **Ziel:** Mit NATS liest das web-api nur noch, was ihm gehört: das Schema `web` und `batch.run`.
  Alles andere kommt aus Projektionen oder per Request/Reply. Die REST-Antworten bleiben gleich.
  Das ist die Voraussetzung für eine Rolle je Service (P5.3).
- **Test:** Die Lese-Tests aus P3.2 (`tests/db/web_api/test_read_api.py`) laufen unverändert
  zweimal, einmal aus den Tabellen und einmal aus Projektionen mit Request/Reply.
- **Entwurf (04.11.2026):**
  - **Umschalten:** Die Quelle wählt die Konfiguration, wie beim Event-Consumer.
    - Mit `WEB_API_NATS_URL` und `WEB_API_PROJECTIONS_DATABASE_URL` liest das web-api aus den
      Projektionen.
    - Ohne bleibt es bei den Tabellen über `va_read`, so wie heute auf der NAS und im E2E-Stack.
  - **Port `ReadModel`:** Die Router fragen ein Lesemodell statt eigener Verbindungen.
    - `TableReadModel` umhüllt die bisherigen Abfragen (`va_web_api.read`).
    - `ProjectionReadModel` liest aus `web` und `batch.run`.
  - **Projektionen (Migration `0012`, nur zum Anfügen):**
    - `web.snapshot_row` aus `marketdata.snapshot.completed`: je Abruf und Titel die Spalten, die
      Ranking und Titelseite brauchen, mit `fetch_ok` (Marktkapitalisierung vorhanden) und ISIN.
    - `web.ranking_run` aus `scoring.run.completed`: Kopf eines Bewertungslaufs mit Abruf, Herkunft
      (`live` oder `rescore`), Tag, Indexquelle, Gewichten und Zeitpunkt.
    - Am Größenfilter gescheiterte Titel stehen nicht im Event. Sie ergeben sich beim Lesen: Titel
      des Abrufs ohne Zeile in `ranking_row`.
  - **Contract, additiv:** `SnapshotCompletedV1.isins` (Symbol → ISIN). market-data füllt es aus
    dem Universum, die Titelseite zeigt die ISIN weiter.
  - **Request/Reply, neu:** Der Worker beantwortet die Anfragen mit den Abfragen aus
    `va_web_api.read`. Sie berühren nur das Schema des jeweiligen Besitzers.
    - `notification.report` und `notification.report.csv` (die CSV als Base64).
    - `scoring.profiles.list` und `scoring.profiles.get`.
    - Nicht gefunden heißt leere Antwort, nicht Fehler. Daraus wird im web-api 404.
  - **`GET /runs/{id}`:** Die Report-ID eines laufenden Runs kommt aus `web.run_status` statt aus
    `reporting.report`.
  - **Nachfüllen aus den Tabellen:** Der Stream hält Events nur 30 Tage, die Historie liegt in
    den Tabellen.
    - `src.db.backfill` füllt `snapshot_row`, `ranking_run` und `ranking_row` aus `market_data`
      und `scoring`, idempotent (`ON CONFLICT DO NOTHING`).
    - `python -m src.db.migrate` ruft es nach jeder Migration mit der Owner-Rolle auf. So stehen
      auch Läufe im Prozess, etwa vor dem Umstieg, in den Projektionen.
  - **Nicht erreichbar:** Antwortet niemand, kommt 503 mit dem Namen des Service, etwa
    „Notification nicht erreichbar“.
  - **Test (rot):**
    - Contracts:
      - die vier neuen Befehle im Katalog, mit Golden-Schemas;
      - `isins` im Golden-Schema des Snapshot-Events.
    - Lese-API: `api` und `empty_api` bekommen den Parameter `tables`/`projections`. Für
      `projections` gilt:
      - erst der Lauf, dann das Nachfüllen;
      - der Worker beantwortet Reports und Profile;
      - das web-api läuft mit NATS und Projektionen.
    - Nachfüllen: Zweimal hintereinander ändert nichts. `migrate` ruft es auf.
    - Projektionen: Das Snapshot-Event füllt `snapshot_row` mit ISIN und `fetch_ok`, das
      Scoring-Event `ranking_run`.
    - NATS mit Worker: Ranking und Titelseite aus den Projektionen eines Laufs über NATS sind
      gleich denen aus den Tabellen, bis auf den Zeitpunkt des Bewertungslaufs.
    - market-data: Das Snapshot-Event trägt die ISINs des Universums.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - **Gleiche Antworten nachgewiesen:**
    - Die Lese-Tests aus P3.2 laufen in beiden Varianten.
    - Ein Lauf über NATS ergibt aus den Projektionen dasselbe Ranking und dieselben Titelseiten
      wie aus den Tabellen. Einzige Ausnahme ist der Zeitpunkt des Bewertungslaufs: Mit
      Projektionen ist es der des Events, Millisekunden nach `scoring_run.created_at`.
  - **Nachfüllen in Python:** Der Tag eines Abrufs entsteht wie in `va_web_api.read` aus der
    lokalen Zeit des Containers, nicht mit der Zeitzone der Datenbank. Gezählt wird über
    `RETURNING`, weil `rowcount` bei mehreren Zeilen −1 ist.
  - **`run_id` eines Bewertungslaufs** steht nicht in `scoring.scoring_run`. Das Nachfüllen holt
    sie aus `batch.run.scoring_run_id`.
  - **Queue-Gruppe je Service:** `queue_of` nimmt den ersten Teil des Namens (`scoring`,
    `notification`).
  - **503 je Service:** `RemoteUnavailable` mit `ScoringUnavailable` und
    `NotificationUnavailable`.

### Phase 5 – Aufteilen in Services

#### P5.1a Einstiegspunkte je Service (nachgetragen 04.11.2026)

- **Warum vorher:** Für ein schlankes Image je Service (ADR-0004, `uv sync --package`) muss jeder
  Service allein starten können. Heute baut `src` alle Adapter aus den Settings des Batches.
  Vorschau, Profile und Reports beantwortet der Worker mit Code, der mehrere Schemas liest
  (`src/scoring_ops.py`, `va_web_api.read`). Ein Image nur mit `va-scoring` könnte das nicht.
- **Test:** Jeder Service startet für sich (`python -m va_market_data` usw.) und erledigt seinen
  Teil der Kette über NATS. Drei getrennte Service-Prozesse ergeben denselben Lauf wie der Worker.
- **Entwurf (04.11.2026):**
  - **Gemeinsam** (`va_platform.service`):
    - `ServiceSettings` mit `DATABASE_URL`, `NATS_URL` (Pflicht), `RUN_TIMEOUT_MINUTES` und
      `LOGS_DIR`.
    - `run_service(…)` startet den `NatsBus`, ruft die Verdrahtung des Service auf und läuft bis
      SIGTERM. Ein Dead Letter wird zu `screening.run.failed` (`run_failure`, aus
      `src/dead_letters.py` hierher).
    - `LocalCaller` beantwortet Request/Reply im selben Prozess, mit denselben Handlern wie über
      NATS.
  - **Je Service** (`entrypoints/settings.py`, `entrypoints/service.py`, `__main__.py`):
    - eigene Settings mit nur den eigenen Feldern;
    - Adapter bauen und den Handler am `ReliableBus` anmelden;
    - die eigenen Request/Reply-Befehle beantworten.
    - Der Batch (`src.config.Settings`) erbt die Settings aller drei Services. Es gibt jedes Feld
      nur einmal, und `src/composition.py` baut die Adapter mit denselben Funktionen.
  - **Request/Reply beim Besitzer:**
    - scoring (`va_scoring.entrypoints.rpc`): Faktoren, Vorschau, Speichern, Aktivieren,
      Profile lesen. Der Code kommt aus `src/scoring_ops.py` und `va_web_api.read`, die Antworten
      sind die Contracts.
    - notification (`va_notification.entrypoints.rpc`): Report und CSV.
    - `va_web_api.rpc.read_handlers` und `src/scoring_ops.py` entfallen.
    - `scoring_handlers` bleibt als Server für beliebige Umsetzungen der Ports, etwa die Fakes
      der API-Tests.
  - **Vorschau ohne `market_data`:** scoring speichert beim Bewerten die Eingangsdaten
    (`scoring.input_snapshot`, Migration `0013`, je Abruf und Titel die flache Zeile wie für
    `score()`, nur zum Anfügen). Die Vorschau rechnet daraus. `src.db.backfill` füllt sie für
    ältere Läufe aus `market_data` nach.
  - **web-api ohne NATS:** `src.web` verdrahtet `RemoteScoring` mit einem `LocalCaller` auf die
    Handler von scoring. Lesen geht mit `va_read`, Speichern und Aktivieren mit `va_profiles`. Die
    Vorschau rechnet also in beiden Fällen mit demselben Code.
  - **Replay:** Die Fixture liest market-data selbst (`va_market_data.adapters.replay`), ohne
    `src.regression`.
  - **Worker:** `python -m src.worker` startet die drei Services in einem Prozess, mit denselben
    Funktionen wie die einzelnen Einstiege. Er bleibt für einen Container ohne eigene Images.
  - **Test (rot):**
    - Settings je Service: Pflichtfelder, Standardwerte. Der Batch erbt sie.
    - `run_service` startet, meldet Dead Letter und endet mit dem Stopp-Event. `LocalCaller`
      antwortet wie `serve`, auch mit `internal` bei einer Exception.
    - Je Service über NATS mit echter Datenbank:
      - market-data mit Replay: Aus der Anfrage wird das Snapshot-Event.
      - scoring: Aus dem Snapshot-Event wird das Ranking, `input_snapshot` ist gefüllt, die
        Vorschau rechnet daraus.
      - notification: Aus dem Ranking werden Report und Mail. Report und CSV kommen per
        Request/Reply.
    - Drei getrennte Services und das web-api: Ein Start aus dem UI endet mit `success` oder
      `partial`, wie mit dem Worker.
    - Die P3.3-Tests mit Datenbank laufen weiter in beiden Varianten, jetzt mit den Handlern
      von scoring.
    - Nachfüllen: `input_snapshot` für alte Läufe, ein zweiter Aufruf ändert nichts.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - **Code an seinem Platz:**
    - `smtp_config` und `alert_channels` stehen jetzt in `va_notification.entrypoints.service`,
      `scoring_config` in `va_scoring.entrypoints.service`, `load_universe` als `live_universe` in
      `va_market_data.entrypoints.service`.
    - `src.composition` reicht sie weiter, alte Importe bleiben gültig.
    - Die Fallback-CSV des Batches bleibt die im Repo, außer `FALLBACK_CSV` ist gesetzt. Der
      Cron-Lauf bekommt die Variable mit.
  - **`LocalCaller` und `serve`** teilen sich `answer_request`: Eine Exception im Handler wird
    in beiden Fällen zur Antwort mit `internal`.
  - **Tag des Abrufs in der Vorschau:** Er kommt aus den Zeitpunkten der Titel in den
    Eingangsdaten (`fetched_at`). Fehlen sie, gilt der Tag des Bewertungslaufs.
  - **Offen für P5.3:** scoring liest beim Speichern weiter `market_data.instrument`. Dort holt es
    die IDs der Titel für `score_result`, das ist der letzte Lesezugriff über die Schemagrenze.

#### P5.1 Images je Service

- **Test:** Smoke-Test je Image (Import, Startbefehl) und die J4125-Prüfung aus P0.6.
- **Implementierung:** Dockerfiles mit `uv sync --package`, CI baut alle Images
  ([betrieb-synology.md](betrieb-synology.md)).
- **Entwurf (04.11.2026):**
  - **Dockerfile:** neue Stufen neben `runtime`.
    - `service-base`: Python und Zeitzone, ohne Cron.
    - Daraus je Service eine Stufe `market-data`, `scoring`, `notification` und `web-api`.
    - Jede installiert mit `uv sync --package va-<service>` nur ihr Paket samt `va-platform`
      und `va-contracts`.
    - Einstieg ist `python -m va_<service>` bzw. Uvicorn mit `va_web_api.main:create_app`.
    - market-data bekommt dazu `data/` mit der Fallback-CSV.
    - Das App-Image (`runtime`) bleibt für Batch, Migration und das web-api ohne NATS.
  - **CI:** Der Docker-Job baut die vier Images und prüft jedes:
    - Der Service ist importierbar.
    - Kein anderer Service ist im Image.
    - Ohne Konfiguration endet der Start mit Exit 2.

    Auf `main` schiebt die CI sie nach GHCR (`va-market-data`, `va-scoring`, `va-notification`,
    `va-web-api`), mit denselben Tags wie `value-analyzer`.
  - **J4125:** Die Service-Images enthalten nur Teilmengen derselben Pakete aus `uv.lock`.
    Die QEMU-Prüfung des App-Images deckt sie deshalb mit ab. Vier weitere QEMU-Läufe brächten
    keine neue Aussage.
  - **Compose:**
    - Auf der NAS (`docker-compose.yml`) ersetzen die Dienste `market-data`, `scoring` und
      `notification` mit den neuen Images den Worker, weiter mit dem Profil `nats`.
    - Jeder bekommt nur seine Variablen. Die Zugangsdaten für SMTP sieht nur notification.
    - Das web-api bleibt bis P5.4 auf dem App-Image, weil es ohne NATS den Code von scoring im
      Prozess braucht.
    - Lokal laufen die drei Dienste aus dem App-Image (`value-analyzer:local`) mit ihrem
      eigenen Einstieg. So entsteht lokal kein weiteres Image, auf C: ist wenig Platz.
  - **Test (rot):**
    - Dockerfile: Stufen je Service mit `uv sync --package`, Einstieg und Fallback-CSV.
    - CI: baut, prüft und schiebt die vier Images.
    - Compose:
      - Die drei Dienste stehen mit Profil `nats` und eigenem Image auf der NAS.
      - Nur notification sieht SMTP.
      - Lokal kommen sie aus dem App-Image, mit Mailpit.
      - Den Worker gibt es im Compose nicht mehr.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - **Prüfskript:** `docker/service_smoke.sh` prüft die vier Images in der CI. Das web-api
    startet erst mit Datenbank-URL, für sein Image gilt nur der Import.
  - **Leere Variablen:** Compose reicht nicht gesetzte Variablen als leeren Text durch
    (`${MAIL_FROM:-}`). `ServiceSettings` lässt sie deshalb weg (`env_ignore_empty`), es gilt der
    Standardwert. Das gilt auch für den Batch.
  - **Größe:** Lokal gebaut ist das Image von scoring 469 MB groß.
  - **Worker:** `src.worker` bleibt als Modul für einen Prozess mit allen drei Services, etwa beim
    Entwickeln aus der `.venv`.

#### P5.2 End-to-End-Test des ganzen Stacks

- **Test:** Die CI startet den kompletten Compose-Stack, löst über die API einen Dry-Run aus und
  vergleicht die Mail mit dem Golden-File.
- **Implementierung:** Compose-Datei für die CI und Warte-Logik auf `notification.report.sent`.
- **Entwurf (04.11.2026):** Der E2E-Stack aus U5 (`docker-compose.e2e.yml`, `docker/e2e.sh`)
  wird zum ganzen Stack. Die Prüfungen unter `tests/e2e` und `frontend/e2e` bleiben gleich.
  - **Stack:**
    - NATS, die drei Services und das web-api mit NATS und Projektionen (Rolle `va_web`,
      `VA_WEB_PASSWORD` in `docker/e2e.env`).
    - market-data liest die Replay-Fixture, notification schickt an Mailpit.
    - In der CI laufen die vier Service-Images aus P5.1 (`E2E_WEB_API_IMAGE`,
      `E2E_MARKET_DATA_IMAGE` usw.). Lokal laufen sie aus dem App-Image, wie im lokalen Stack.
    - Das web-api startet mit `va_web_api.main:create_app`. Das geht mit beiden Images.
  - **Ablauf von `docker/e2e.sh`:**
    1. Datenbank, NATS und Mailpit starten.
    2. Mit dem App-Image migrieren (`python -m src.db.migrate`).
    3. Services, web-api und frontend starten.
    4. `docker/e2e_run.py` startet den Lauf über `POST /api/v1/runs`, über nginx wie das UI.
       Vorher wartet es, bis scoring antwortet.
    5. Warten, bis `batch.run` abgeschlossen ist. Das geschieht mit
       `notification.report.sent` (P4.7).
    6. Die Prüfungen laufen.
  - **Kein Dry-Run:** Ein Dry-Run verschickt keine Mail. Verglichen wird aber die Mail in Mailpit
    mit der Fixture, wie bisher. Der Lauf startet deshalb mit Versand.
  - **Test (rot):**
    - Compose:
      - Der E2E-Stack hat NATS, die Services und das web-api mit Projektionen.
      - market-data spielt die Fixture ab, notification schickt nur an Mailpit.
      - Die CI setzt die Images unter Test, lokal kommt alles aus dem App-Image.
    - Skript und CI:
      - Erst die Migration, dann der Start über die API, kein Batch-Lauf mehr.
      - Die CI reicht die Service-Images durch.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - **Eine Version für alle Pakete:** Seit P5.1 kennt jeder Service nur seine Paketversion. Die
    stand bei 0.1.0 und wäre in die Fußzeile der Mail und in `scoring_run.app_version`
    gelangt. Alle Workspace-Pakete tragen jetzt die Version des Projekts (0.3.0). Das prüft
    `tests/test_versions.py`. Im OpenAPI-Snapshot ändert sich nur `info.version`.
  - **Migration im E2E-Stack:** `docker compose run --entrypoint python value-analyzer -m
    src.db.migrate`, ohne den Cron des Entrypoints.

#### P5.3 Eine DB-Rolle je Service 🔒

- **Test:** Rechte-Tests, z. B. die Rolle `va_scoring` kann das Schema `market_data` nicht lesen.
- **Implementierung:** Migration mit den Service-Rollen, `va_app` entfällt.
- **Entwurf (04.11.2026):**
  - **Rollen:** `va_market_data`, `va_scoring` und `va_notification`.
    - Jede liest und fügt nur im eigenen Schema an, auch in künftigen Tabellen (Default
      Privileges).
    - `UPDATE` gibt es nur, wo `va_app` es auch darf: Abschluss eines Abrufs, ISIN,
      `published_at` der Outbox. `DELETE` nie.
    - Migration `0014` vergibt die Rechte (`service_grant_statements`).
    - Die Rollen legen `db/init` (neue Datenbank) bzw. `python -m src.db.migrate` an, mit
      `VA_<SERVICE>_PASSWORD`.
  - **Letzter Zugriff über die Grenze:** scoring las die IDs der Titel aus
    `market_data.instrument`. Jetzt schickt market-data sie im Snapshot-Event mit
    (`SnapshotCompletedV1.instrument_ids`, additiv, Port `SnapshotStore.instrument_ids`).
    Ohne IDs, etwa im Batch, liest der Speicher sie wie bisher.
  - **Compose:** Die drei Dienste verbinden sich mit ihrer Rolle, die Datenbank bekommt die
    drei Passwörter für `db/init`.
  - **`va_app` bleibt vorerst:** Der Batch im Prozess (`make run`, Cron bis P5.4) verbindet alle
    drei Services über eine Verbindung und braucht sie. Sie entfällt, wenn der Batch nicht mehr
    gebraucht wird (P5.6).
  - **Test (rot):**
    - Für jede Tabelle der App-Schemas gilt: `SELECT` und `INSERT` nur im eigenen Schema,
      `DELETE` und `TRUNCATE` nirgends, `UPDATE` nur auf den freigegebenen Tabellen.
    - scoring liest `market_data` nicht, notification liest `scoring` nicht.
    - Die drei Services erledigen die Kette mit ihren Rollen (`tests/db/test_services_nats.py`).
    - Das Snapshot-Event trägt die IDs, scoring gibt sie an den Speicher weiter.
    - Compose: Rollen in den Verbindungen, Passwörter bei der Datenbank.
- **Umgesetzt (04.11.2026):** wie im Entwurf.

#### P5.4 Scheduler im web-api

- **Test:** Cron-Termin mit Zeitzone `Europe/Berlin`, derselbe Termin erzeugt nur einen Run.
- **Implementierung:** Scheduler im web-api, der Cron im Container entfällt.
- **Entwurf (04.11.2026):** Der Umstieg. Den Scheduler gibt es seit P4.7; jetzt ist er Standard,
  und NATS mit den drei Services ist es auch.
  - **Kein Cron:**
    - Das App-Image enthält keinen Cron mehr.
    - `entrypoint.sh` migriert und führt den übergebenen Befehl aus. Ohne Befehl endet es nach
      der Migration.
    - Das web-api plant den Wochenlauf: `WEB_API_SCHEDULE` kommt auf der NAS aus `CRON_SCHEDULE`
      der `.env`, in `Europe/Berlin`, ein Run je Termin (P4.7).
  - **Compose auf der NAS:**
    - Neuer Dienst `migrate` (App-Image, `python -m src.db.migrate`, läuft einmal).
      Services und web-api warten auf ihn (`service_completed_successfully`).
    - market-data, scoring und notification laufen ohne Profil.
    - Das web-api läuft mit eigenem Image (`va-web-api`), NATS, Projektionen (`va_web`) und dem
      Wochenplan. `va_profiles` braucht es nicht mehr, scoring speichert die Profile selbst.
    - Der Batch (`value-analyzer`) bekommt das Profil `run`. Er läuft nur auf Wunsch:
      `make docker-run`, Regression, Import.
  - **Neue Pflichtvariablen auf der NAS:** `VA_WEB_PASSWORD`, `VA_MARKET_DATA_PASSWORD`,
    `VA_SCORING_PASSWORD` und `VA_NOTIFICATION_PASSWORD`. `.env.example` führt sie.
  - **Lokal:**
    - Dieselbe Aufteilung aus dem App-Image.
    - Das web-api startet mit `va_web_api.main:create_app` und ohne Wochenplan.
  - **E2E:** Die Migration übernimmt der Dienst `migrate`. Das web-api plant dort nichts.
  - **Test (rot):**
    - Compose:
      - Dienste der NAS ohne Profil.
      - `migrate` vor allen anderen.
      - Das web-api mit NATS, Projektionen und dem Termin aus `CRON_SCHEDULE`.
      - Der Batch nur mit dem Profil `run`.
      - Lokal ohne Wochenplan.
    - Image: kein Cron im App-Image und im Entrypoint.
- **Umgesetzt (04.11.2026):** wie im Entwurf, dazu:
  - **Pflicht in der `.env` der NAS:** Compose bricht mit einer Meldung ab, solange
    `VA_WEB_PASSWORD` oder ein `VA_<SERVICE>_PASSWORD` fehlt. In `.env.example` stehen sie nicht
    mehr auskommentiert.
  - **`make pull`** lädt alle Images, auch die des Batches (`--profile run`).
    **`make db-migrate`** startet den Dienst `migrate`.
  - **`tests/test_entrypoint.py` entfällt:** Ohne Cron gibt es kein `ENV_PATTERN` mehr.

#### P5.5 Tracing

- **Test:** Mit einem In-Memory-Exporter erzeugt ein Run zusammenhängende Spans über Publish und
  Consume hinweg.
- **Implementierung:** OpenTelemetry in FastAPI und FastStream, Weitergabe der run_id.
- **Entwurf (04.11.2026):** Ein Trace je Run, vom Anlegen bis zur Mail, über alle Services.
  - **Abweichung:** Ohne FastStream (eigener `NatsBus` seit P4.3) und ohne die
    Auto-Instrumentierung von FastAPI. Gemessen wird der Run, nicht jeder HTTP-Aufruf. Die Spans
    entstehen an wenigen Stellen von Hand, in `va_platform.tracing` (OpenTelemetry API und SDK).
  - **Weitergabe:** Der Trace-Kontext reist als `traceparent` (W3C Trace Context) in der Hülle.
    Das Feld ist die CloudEvents-Erweiterung für verteiltes Tracing, optional, also additiv.
    Busse und Outbox setzen es beim Senden (`stamp`), ein gesetztes bleibt.
  - **Spans:**
    - `run`: die Wurzel, wo der Run entsteht (`RunManager` im web-api, `src/main.py` im Batch).
      Attribut `va.run_id`.
    - Je verarbeitetem Event `<consumer> <type>` (Art CONSUMER) mit Consumer, Event-Typ,
      Event-ID und `va.run_id`. Vorgänger ist der Span, in dem das Event entstand.
  - **Einschalten:** `OTEL_TRACES_EXPORTER` (Settings der Services und des Batches,
    `WEB_API_OTEL_TRACES_EXPORTER` im web-api). Standard `none`: kein Provider, die Hülle bleibt
    unverändert. `console` schreibt die Spans als JSON ins Log jedes Containers. Ein Collector
    (OTLP) ist auf der NAS nicht vorgesehen.
  - **Test (rot):**
    - Im Prozess und über NATS ergibt ein Run einen Trace (In-Memory-Exporter).
      Die Kette market-data → scoring → notification hängt an der Wurzel.
    - Der `traceparent` übersteht das Serialisieren.
    - Ohne Provider bleibt die Hülle gleich.
    - Ein Start im web-api öffnet den Trace, das Event in der Outbox trägt ihn.
- **Umgesetzt (04.11.2026):** wie im Entwurf. Das Golden-File der Hülle hat das neue Feld
  `traceparent`.

#### P5.6 Abschluss-Doku

- **Test:** Der Link-Check der Doku läuft durch.
- **Implementierung:** CLAUDE.md auf die Zielarchitektur umschreiben, dazu ein Runbook für die NAS.
- **Entwurf (04.11.2026):** Die Doku beschreibt den Stack, wie er jetzt läuft.
  - **CLAUDE.md:**
    - Statt „Architektur in einem Satz“ mit der Historie der Pakete eine Übersicht: Dienste,
      Ablauf eines Runs, Aufbau eines Service, web-api, Batch nur auf Wunsch, Umgebungen.
    - Veraltete Verweise richten: Verdrahtung in `entrypoints/service.py` statt
      `src/composition.py`, kein `ENV_PATTERN`, kein FastStream, kein `src/scoring_ops.py`.
    - „Zielarchitektur (in Umsetzung)“ wird „Entscheidungen und Arbeitsweise“.
  - **Runbook** (`betrieb-synology.md`): statt der Skizzen von Compose und Dockerfile:
    - die echten Dienste mit Startreihenfolge;
    - Erstinstallation;
    - die einmalige Umstellung vom Batch mit Cron, mit `docker compose --profile run down`,
      damit der alte Batch-Container mit Cron nicht weiterläuft;
    - Update, Läufe, Störungen, Secrets, Backup und Überwachung.
  - **README:** Quick Start, Update, Pipeline, Konfiguration (neue Passwörter, Wochenplan,
    Tracing), Projektstruktur und CI auf den Stack.
  - **Status-Zeilen** in `architecture/` (README, events, frontend, code-struktur, umgebungen,
    web-api-realtime, datenhaltung): umgesetzt statt Plan, kein FastStream und kein Cron mehr.
    ADRs bleiben, wie sie sind (Pflegeregel).
  - **Test:** `tests/test_doc_links.py` prüft jeden relativen Link in den Markdown-Dateien des
    Repos: Die Datei existiert, ein Anker trifft eine Überschrift (Regeln von GitHub). Externe
    Links prüft er nicht, er läuft ohne Netz.
- **Umgesetzt (04.11.2026):** wie im Entwurf. Der Link-Check war schon vor den Änderungen grün und
  hält die Umbauten der Doku seitdem zusammen.

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
  - F1.1 bis F1.6 sind vor Phase 1 entstanden und nennen die alten Orte. Seit Phase 1 liegen sie
    hier:
    - `src/consensus.py` → `va_market_data.domain.consensus`, `src/history.py` →
      `va_market_data.domain.history`
    - `data_fetcher` (`fetch_one`, `fetch_consensus`, `fetch_quarterly`, `fetch_prices`,
      `_additional`, `CONSENSUS_FIELDS`, `QUARTERLY_FIELDS`, `PRICE_FIELDS`) →
      `va_market_data.adapters.yahoo`; `fetch_all` → `va_market_data.application.fetch`
    - der Recorder (`BatchRecorder.history_state`, die Savepoints, `_OptionalWrites`) →
      `PostgresSnapshotStore` und `_OptionalWrites` in `va_market_data.adapters.postgres.store`
    - das Repository (`write_consensus`, `write_statements`, `get_statements_as_of` usw.) →
      `MarketDataRepository` in `va_market_data.adapters.postgres.repository`
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
  Das Fehlerverhalten der Adapter (Retry, Rate-Limit, verschluckte Fehler) prüfen Fakes, die
  yfinance nachbilden, oder echtes yfinance mit gepatchter HTTP-Schicht.

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
  - Die Zuordnung Art → yfinance-Attribut steht in `data_fetcher.CONSENSUS_FIELDS`.
    Benennt yfinance um, bleiben die Namen in der DB gleich.
  - HTTP-Fehler, die yfinance nur loggt, werden als `error` gespeichert, nicht als
    `empty`. Nach einem Rate-Limit (429) gibt es keinen Retry, die übrigen Arten des Titels
    werden übersprungen.
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
- **Implementierung:**
  - `quarterly_income_stmt`, `quarterly_balance_sheet` und `quarterly_cashflow` abrufen
    (`data_fetcher.fetch_quarterly`, Zuordnung in `QUARTERLY_FIELDS`) und über
    `write_statements(..., frequency="quarterly")` speichern.
  - Die Spalte `frequency` ist freier Text, eine Migration ist nicht nötig. Das Repository
    akzeptiert nur `annual` und `quarterly`, `get_statement_history` fragt je Frequenz ab.
  - Ein Fehler kostet nur den betroffenen Abschluss. Nach einem Rate-Limit bleiben die restlichen
    Abschlüsse des Titels aus.
- **Review:** Gemessen am 30.09.2026 an 8 DAX/MDAX-Titeln:
  - Der Quartalsabruf kostet im Median 0,58 s je Titel, also rund 50 s je Lauf.
  - Yahoo liefert 5 bis 7 Quartale je Abschluss. Banken und Versicherer (Allianz, Deutsche Bank)
    haben keinen Quartals-Cashflow.
  - Im Median fallen rund 700 Werte je Titel an, ab der zweiten Woche wird nur Neues oder
    Geändertes gespeichert.

#### F1.3 Historie der Aktienanzahl

- **Voraussetzung:** wie F1.1.
- **Test:**
  - Parser-Test: Eine aufgezeichnete `get_shares_full`-Serie wird zu einem Wert je Tag (bei
    mehreren Werten am selben Tag gilt der letzte).
  - DB-Tests: Eine Zeile entsteht nur für ein neues Datum oder einen geänderten Wert.
- **Implementierung:**
  - Tabelle `market_data.share_count` (`instrument_id`, `as_of`, `shares`,
    `first_seen_fetch_run_id`, `first_seen_at`) mit `protect_table()`, Migration `0003`.
  - Beim ersten Abruf ab 2000-01-01 (`FetcherConfig.shares_history_start`), danach ab dem
    letzten gespeicherten Datum. Den Stand je Titel liest `BatchRecorder.history_state` vor dem
    Abruf und reicht ihn als `HistoryState` über `fetch_all` an `fetch_one` weiter. Ist er nicht
    lesbar, wird die ganze Historie geholt.
  - Parser `daily_share_counts` im neuen Modul `src/history.py`. Der Tag ist der Kalendertag in
    der Zeitzone der Börse (dieselbe Datumsregel wie für Abschlüsse). Fehlende und nicht positive
    Werte zählen nicht.
  - Ein Fehler kostet nur die Aktienanzahl dieser Woche, der nächste Lauf holt die Lücke nach.
- **NAS (du):** Nur deployen, die Migration läuft beim Start. Der erste Lauf fragt die Historie ab
  2000-01-01 an, Yahoo liefert sie ab etwa 2015/2016. Das kostet je Titel unter einer Sekunde.
- **Review:** Gemessen am 19.10.2026 mit yfinance 1.7:
  - Der Abruf kostet 0,1 bis 0,5 s je Titel, beim ersten Titel eines Laufs bis 2,4 s.
  - Yahoo liefert die Aktienanzahl ab 2015/2016, rund 700 Tage je Titel. Danach kommen wenige
    Zeilen pro Woche hinzu.
  - Rund 60 Tage je Titel liefert Yahoo doppelt, teils mit zwei abwechselnden Werten.
    yfinance sortiert nicht stabil. Deshalb wurde verglichen, ob ein kurzes Fenster wie im
    Wochenlauf denselben „letzten“ Wert ergibt wie der Vollabruf: 36 Stichproben bei SAP,
    Allianz und Telekom, keine Abweichung.

#### F1.4 Kurshistorie

- **Voraussetzung:** wie F1.1.
- **Test:**
  - Ein Parser-Test mit einer aufgezeichneten Antwort von
    `history(auto_adjust=False, actions=True)`.
  - DB-Tests: die Erstbefüllung, die inkrementelle Ergänzung und der Split-Fall. Ändern sich alte
    Kurse durch einen Split, entstehen neue Versionen, und die alten bleiben erhalten.
- **Implementierung:**
  - Tabelle `market_data.price_bar` (`instrument_id`, `trade_date`, `close`, `adj_close`,
    `dividend`, `split`, `first_seen_fetch_run_id`, `first_seen_at`) mit `protect_table()`,
    Migration `0004`.
  - Der erste Abruf holt `period="max"`. Danach beginnt das Fenster beim letzten gespeicherten Tag
    minus 8 Wochen (`FetcherConfig.price_overlap_days = 56`, rund 40 Handelstage). Anders als
    „die letzten 40 Handelstage“ hinterlassen so auch ausgefallene Läufe keine Lücke.
  - Steht im Fenster ein Split, der noch nicht gespeichert ist, wird die ganze Historie geholt.
    Yahoo passt bei einem Split alle früheren Kurse an, so entstehen für alle Tage neue Versionen.
  - Der Tag des Abrufs (Börsenzeit) zählt nicht, er läuft noch. Sonst landete bei einem Lauf unter
    der Woche ein Intraday-Stand als Schlusskurs.
  - Die yfinance-Spaltennamen stehen in `data_fetcher.PRICE_FIELDS`. `fetch_prices` benennt sie
    um, der Parser `daily_price_bars` in `src/history.py` kennt nur die eigenen Namen.
  - Verglichen wird mit relativer Toleranz `1e-5` (`PriceBar.same_as`): Yahoo liefert `Adj Close`
    bei jedem Abruf minimal anders (gemessen bis `6e-7` relativ, an rund 4.800 von 7.300 Tagen bei
    SAP). Ein exakter Vergleich erzeugte jede Woche Schein-Versionen.
- **Review:** Gemessen am 19.10.2026 mit allen 90 Titeln und yfinance 1.7:
  - Erstbefüllung: 499.871 Zeilen ab 1996, Tabelle 51 MB, mit Indizes 92 MB. Das ist mehr als die
    geschätzten „niedrig zweistelligen MB“, für die NAS aber unkritisch. Danach kommen rund
    450 Zeilen pro Woche hinzu, nach Dividenden zusätzlich neue Versionen von `adj_close` im
    Fenster.
  - Abruf im Median 0,4 s je Titel, die Erstbefüllung verlängert den Lauf um rund 1,5 Minuten.
  - Ein Folgeabruf direkt danach erzeugte 0 neue Zeilen, die Toleranz greift.
- **NAS (du):** Der erste Lauf nach dem Deployment dauert wegen der Erstbefüllung länger.

#### F1.5 Fix-Paket Zusatzdaten

Aus dem Review von F1.2 bis F1.4 entstanden.

- **Test:**
  - yfinance verschluckt Fehler standardmäßig (`config.debug.hide_exceptions`) und liefert leer.
    Ein Test auf HTTP-Ebene (`YfData.get` gepatcht) zeigt, dass Retry, Abbruch nach Rate-Limit
    und Log der Quartalsabschlüsse nie griffen. Dasselbe gilt für Netzfehler bei Aktienanzahl und
    Kursen.
  - Nach einem Rate-Limit liefen die übrigen Zusatzabrufe des Titels weiter.
  - Ein Datenfehler beim Speichern von Zusatzdaten kostete den ganzen Titel, nachgewiesen mit einem
    Pipeline-Test gegen Postgres. Auslöser waren eine Aktienanzahl, die gerundet 0 ergibt, und
    Werte über BIGINT.
  - Sicherungstests: Der Stand zu einem früheren Zeitpunkt enthält keine später neuen Tage.
- **Implementierung:**
  - `_yahoo_errors_raised()` schaltet `hide_exceptions` während der Zusatzabrufe ab (Quartale,
    Aktienanzahl, Kurse). Der Konsens erkennt geloggte HTTP-Fehler weiter über
    `_YfErrorCapture`.
  - `note_rate_limit` merkt sich ein Rate-Limit je Titel. `fetch_one` lässt danach die
    restlichen Zusatzabrufe aus und setzt den Zustand für den nächsten Titel zurück.
  - Der Recorder schreibt Konsens, Quartale, Aktienanzahl und Kurse je in einem Savepoint. Ein
    Datenfehler (`IntegrityError`, `DataError`) wird geloggt und kostet nur diese Daten.
  - `daily_share_counts` prüft nach dem Runden auf `0 < n <= 2**63 - 1`.
- **Review:** Live mit allen 90 Titeln am 19.10.2026: keine Warnung, kein Rate-Limit. „Keine
  Daten“ bleibt ein leeres Ergebnis und wird kein Fehler, etwa der fehlende Quartals-Cashflow bei
  Banken und Versicherern (24 leere Quartalsabschlüsse).

#### F1.6 Fix-Paket Gesamt-Review Track F

Aus dem Gesamt-Review am 19.10.2026 entstanden.

- **Test:**
  - Scheitert nach einem neuen Split der Vollabruf, wurde bisher das Fenster gespeichert. Der
    Split galt damit als bekannt, und die Altkurse blieben dauerhaft unbereinigt.
  - Konsens: yfinance liest `eps_trend`, `eps_revisions`, `earnings_estimate`,
    `revenue_estimate` und `growth_estimates` aus einem gemeinsamen Abruf und loggt dessen
    Fehler nur einmal. Die anderen Arten standen dann als `empty` statt `error` in der DB (Test
    mit echtem yfinance und gepatchter HTTP-Schicht).
  - Ein unerwarteter Python-Fehler in einem Zusatzabruf oder beim Speichern der Zusatzdaten
    kostete den Titel (Pipeline-Test gegen Postgres).
  - Sicherungstests: echter CHECK-Verstoß im Savepoint, Rate-Limit-Verdrahtung bei Konsens und
    Aktienanzahl.
- **Implementierung:**
  - Gescheiterter Vollabruf nach Split: diese Woche keine Kurse. Der Split steht nächste Woche
    wieder im Fenster.
  - `CONSENSUS_SHARED_SOURCE`: Ist der gemeinsame Abruf mit `YahooResponseError` gescheitert,
    werden leere Arten der Gruppe zum Folgefehler. Ein Fehler beim Parsen einer einzelnen Art
    zählt nicht.
  - `fetch_one` ruft jede Zusatzquelle über `_additional()` auf, der Recorder schreibt sie über
    `_OptionalWrites`: Ein unerwarteter Fehler kostet nur diese Daten. Vorübergehende
    DB-Störungen laufen weiter in den Retry der ganzen Transaktion.
  - Docstring: Der Retry hilft nur bei Netzfehlern, HTTP-Fehlerantworten cacht yfinance.
- **Bewusst offen:** Yahoo-Anpassungen ohne Split-Marker an Tagen vor dem Fenster werden nicht
  erkannt. Die Aktienanzahl wird ab dem letzten gespeicherten Tag ohne Überlappung geholt,
  spätere Korrekturen an älteren Tagen kommen nicht an.

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
  - Das 12-1-Momentum aus Fixture-Kursen, der letzte Monat ausgelassen. Eine zu kurze Historie
    ergibt `None`. Gerechnet wird aus `close`, `dividend` und `split`, nicht aus dem
    gespeicherten `adj_close`: Das wird nur im 8-Wochen-Fenster nachgezogen, über zwölf Monate
    mischt es Bereinigungsstände (Fehler etwa in Höhe der Dividendenrendite).
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

### Track G – Gestaltung des UI

Grundlage sind die [Spec](ui-neugestaltung.md) und die [Designvorlage](../design/vorlage.html),
beide abgenommen am 06.11.2026. Zyklus und Definition of Done gelten unverändert, ab G1 läuft
zusätzlich `make local-e2e`. G4 bis G7 laufen nach G2 in getrennten Worktrees. Was mehrere von
ihnen brauchen (Muster-Klassen, Tabellen, Formularfelder), legt deshalb schon G1 an.

#### G1 Fundament und Hülle

- **Voraussetzung:** Spec und G0 abgenommen, Ergänzung des Styleguides `676ae81`.
- **Test:**
  - `tests/test_frontend_styles.py` (Test 6 der Spec): Kein Farbliteral (`#…`, `rgb(`, `hsl(`,
    Farbnamen) in `frontend/src/**/*.scss` außer in `_paper.scss` und dem weißen Hintergrund der
    Mail-Vorschau. In `_paper.scss` ist jeder Wert ein Grauton (Kanäle höchstens 16 auseinander),
    und jede Rolle der Palette hat einen hellen und einen dunklen Wert.
  - Bausteine (`ui.spec.ts`): `app-icon` zeichnet das SVG aus der festen Liste, mit
    `aria-hidden`, in zwei Größen, Drehung nur auf Wunsch. `app-section` setzt den Titel und hat
    Platz für ⓘ und Aktionen. `app-state` zeigt den Ladebalken erst nach 300 ms, einen Fehler mit
    `role="alert"` und den leeren Zustand mit Icon, Satz und nächstem Schritt.
  - App-Hülle (`app.spec.ts`): Navigation mit Icons und „Läufe“, der aktive Eintrag mit
    `aria-current`, Tooltips an den Einträgen, der Offline-Chip mit Icon und Tooltip, die
    Fußzeile mit Hinweis und Version aus `GET /api/v1/health` (ohne Antwort ohne Version), der
    Titel „Läufe · Value-Analyzer“ und die Standardwerte der Tooltips.
- **Implementierung:**
  - `src/styles/_paper.scss`: Palette mit `light-dark()` über `mat.theme-overrides`, Overrides
    für Karte, Dialog, Menü, Tooltip und Tabelle (ohne Schatten, Haarlinien, Linie in Tinte unter
    dem Tabellenkopf). Serifen für Überschriften über `brand-family`.
  - Neue Tokens, `breakpoints.$compact`, Fokusring, Links in Tinte. Muster-Klassen für G4 bis G7:
    `.num`, `.card-grid`, `.stat-grid`, `.sticky-bar`, `.badge--muted`. `.badge` und `.notice`
    nehmen die Stufen der Palette.
  - `MAT_TOOLTIP_DEFAULT_OPTIONS` in `app.config.ts`. Formularfelder mit Rand
    (`FORM_FIELD_DEFAULTS`) nehmen die Ansichten mit Feldern in ihre `providers`: In
    `app.config.ts` holte der Import Formularfeld und Angular Forms ins Start-Bundle (587 statt
    453 kB).
  - `app-icon`, `app-section` und `app-state` unter `shared/ui/`.
  - App-Hülle: Marke, Navigation mit Icons (unter `$compact` nur Icons), Offline-Chip, Fußzeile,
    Inhalt höchstens `--va-content-max` breit. „Läufe“ statt „Runs“, auch im Titel des Tabs.
  - Die Meldungen in `api-error.ts` nennen den Server statt „das web-api“.
  - Styleguide: Farben, Typografie, Tokens, Icons und die neuen Bausteine.
- **Nicht in G1:** das Icon „Begriffe“ und das Glossar (G2), der Umbau der Seiten (G4 bis G7). Die
  Seiten bekommen mit G1 nur das neue Theme.
- **Review:** hell und dunkel bei 1366 px und 375 px angesehen, Start-Bundle unter 500 kB.
- **NAS (du):** nichts Eigenes, es kommt mit dem Image `va-frontend`.
