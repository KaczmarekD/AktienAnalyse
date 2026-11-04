# Value-Analyzer – Projekt-Kontext für Maintainer & Agents

Dieses Dokument hält fest, **warum** der Code so aussieht – die Entscheidungen
hinter den Defaults, die Methodik-Grundlage und die Konventionen. Es ergänzt
den README (der zeigt, **wie** das Projekt betrieben wird).

## Was das Projekt tut

Wöchentlicher Batch-Job auf einer Synology, der DAX/MDAX (90 Werte) nach
einer Value-+-Quality-Methodik durchscoresd und das Ergebnis als E-Mail
versendet (HTML-Top/Flop-Tabellen + CSV-Vollranking). Die CSV enthält alle
Titel, die den Größenfilter passieren, auch die ohne Score. Titel unter
`MIN_MARKET_CAP` und gescheiterte Abrufe fehlen dort, stehen aber in der DB
(`market_data.fundamental_snapshot`, `scoring.score_result` mit `passed_filter = false`).

## Architektur in einem Satz

`src/main.py` legt den Lauf an und startet die Event-Kette auf dem Bus im Prozess
(`va_platform.bus.InProcessBus`): market-data (Universum, yfinance) →
`marketdata.snapshot.completed` → scoring (Cross-Sektional-Ranking) →
`scoring.run.completed` → notification (HTML+CSV, SMTP, Healthcheck). Die Handler
liegen unter `entrypoints/handlers.py` der Module, `src/composition.py` verdrahtet
sie, `src/run_tracker.py` leitet aus den Events den Abschluss von `batch.run` ab.
Jedes Modul speichert selbst in PostgreSQL 18 (`adapters/postgres/store.py`).
Geplant via Cron im Container.

**Umgebungen** ([docs/architecture/umgebungen.md](docs/architecture/umgebungen.md)):
`docker-compose.yml` beschreibt den Live-Betrieb auf der NAS. Lokal legt
`docker-compose.local.yml` den Build aus dem Arbeitsstand, Mailpit und pgweb darüber
(`make local-*`). Dort zeigt SMTP fest auf Mailpit (`SMTP_PLAIN`, ohne TLS und Login) und
`HEALTHCHECK_URL` ist leer, damit lokal nichts nach außen geht. Das web-api
(`services/web-api`, FastAPI, ab P3.1) läuft aus demselben Image, lokal unter
`localhost:8000`. Es liest mit `WEB_API_DATABASE_URL` (Rolle `va_read`, schreibgeschützte
Verbindung) und speichert Scoring-Profile mit `WEB_API_PROFILES_DATABASE_URL` (Rolle
`va_profiles`, darf nur in `profile_version` und `profile_activation` anfügen, seit P3.3). Die
Zugangsdaten des Batches bekommt es nie. Gestartet wird es über `src.web:create_app`: Diese
Composition Root verdrahtet Vorschau und Profil-Befehle mit dem Code von scoring im selben
Prozess (`src/scoring_ops.py`), denn `va_web_api` darf `va_scoring` nicht importieren. Mit
`WEB_API_NATS_URL` beantwortet sie seit P4.8 der Worker über Request/Reply (`va_contracts.rpc.v1`,
`va_web_api.rpc`), ohne Worker antworten sie mit 503. Seit P4.9 lesen die REST-Endpunkte mit NATS
aus den Projektionen (Port `ReadModel`, `ProjectionReadModel`), Profile und Reports per
Request/Reply; die Historie füllt `src.db.backfill` bei jeder Migration nach. Seit P5.1a startet
jeder Service auch allein (`python -m va_market_data`, `va_scoring`, `va_notification`): eigene
Settings (`entrypoints/settings.py`, der Batch erbt sie), eigener Einstieg
(`entrypoints/service.py`, Laufrahmen `va_platform.service.run_service`). Request/Reply
beantworten die Besitzer (`entrypoints/rpc.py`), die Vorschau rechnet scoring aus seiner Kopie
der Eingangsdaten (`scoring.input_snapshot`). Seit P3.6
laufen auf der NAS
web-api und `frontend` (nginx, eigenes Image `va-frontend`, Port 8080 über `UI_LAN_BIND`) mit;
nur das frontend hat einen Port, es reicht `/api/` an das web-api weiter.
Seit P4.1 läuft im Compose auch `nats` (NATS 2.15 mit JetStream, Daten unter `./natsdata`, nur
im Docker-Netz). `python -m va_platform.nats` legt Stream `VA_EVENTS` und die Consumer aus
[docs/architecture/events.md](docs/architecture/events.md) an. Seit P4.3 kann der Batch die Kette
über NATS laufen lassen: `EVENT_BUS=nats` mit `NATS_URL`, `va_platform.nats.NatsBus` (eigener
Adapter mit nats-py statt FastStream, Nachtrag in ADR-0002). Dann wartet `src/main.py` höchstens
`RUN_TIMEOUT_MINUTES` auf das Ergebnis des `RunTracker`. Standard, auch auf der NAS, bleibt der
Bus im Prozess. Seit P4.4 füllt das web-api mit `WEB_API_NATS_URL` und
`WEB_API_PROJECTIONS_DATABASE_URL` (Rolle `va_web`) die Projektionen im Schema `web` aus dem
Consumer `web-api` (`va_web_api.events.EventManager`). Seit P4.5 meldet der WebSocket `/ws`
(Subprotokoll `va.v1`, nur dieselbe Herkunft oder `WEB_API_ALLOWED_ORIGINS`) die Änderungen an die
offenen Tabs, nginx reicht `/ws` weiter. Seit P4.7 legt das web-api Runs an (`POST /api/v1/runs`, Scheduler mit
`WEB_API_SCHEDULE`, standardmäßig aus) und überwacht sie (Watchdog). Es schreibt dafür mit `va_web` in
`batch.run` und `web.run_request`. Ausgeführt werden diese Runs von den drei Services. Sie
laufen seit P5.1 je in einem Container mit eigenem Image (`va-market-data`, `va-scoring`,
`va-notification`, Profil `nats`). `python -m src.worker` startet alle drei in einem Prozess. Seit P4.3b hängt jeder Service über einen
`ReliableBus` am Bus, in beiden Modi:
Er verarbeitet ein Event einmal, überspringt Reste abgebrochener Läufe (älter als
`RUN_TIMEOUT_MINUTES`) und schickt Folge-Events über seine Outbox.
`make local-e2e` (U5) legt `docker-compose.e2e.yml` darüber: ein Wegwerf-Stack mit Datenbank auf
tmpfs, in dem market-data eine Replay-Fixture statt Yahoo liest (`REPLAY_SOURCE`, Mail nur an
Mailpit). Seit P5.2 ist das der ganze Stack mit NATS, den drei Services und dem web-api mit
Projektionen, der Lauf startet über die API (`docker/e2e_run.py`).

## Methodik-Entscheidungen

> **Stand der Entscheidungen (30.09.2026):**
> - ADR-0010 (`docs/adr/`) beschließt, zusätzlich Konsensschätzungen, Quartalsabschlüsse,
>   Aktienanzahl und Kurse zu speichern (Track F1). Das ist ohne Einfluss auf das Ranking.
> - ADR-0011 schlägt Änderungen an Faktoren und Value-Trap-Flag sowie Branchenregeln für
>   Finanzwerte vor. Es ist nur *vorgeschlagen*.
>
> Bis ADR-0011 angenommen und F2.5 umgesetzt ist, gilt die Methodik unten unverändert. Grundlage ist
> die Recherche unter `docs/research/fundamentalanalyse-sota/`.

**Scoring-Profile (ADR-0009, seit P2b.3):** Gewichte und Schwellen kommen aus dem aktiven Profil
in der Datenbank (`ScoringProfileParams` in `va_scoring.domain.profile`). Die Werte unten sind
dessen Standardwerte und die des Profils „Standard“ v1, das der erste Lauf aus den ENV-Werten
anlegt. Jeder Bewertungslauf speichert seine Profil-Version, die Mail nennt sie im Footer.

**Composite = 0.6 × Value + 0.4 × Quality** – die Quality-Komponente
existiert primär, um klassische *Value Traps* zu unterdrücken (vgl.
Asness/Frazzini/Pedersen, "Quality Minus Junk"). Reines Value-Investing
kauft die billigsten Aktien – die sind meistens berechtigt billig.
Deshalb gibt es einen Composite **nur mit beiden Teilscores** (M1, 30.10.2026). Fehlt einer,
bleibt der Titel ohne Composite am Ende der CSV und fehlt in Top- und Flop-Liste. Sonst stünde
ein Titel ohne Quality-Daten besser da als einer mit mittelmäßiger Quality. Heute betrifft das
Banken wie Deutsche Bank und Commerzbank, denen ROIC, operative Marge und Net Debt/EBITDA fehlen.
Bei gleichem oder fehlendem Composite entscheidet das Symbol über die Reihenfolge, damit der Rang
nicht von der Reihenfolge der Eingabe abhängt.

**Value-Faktoren** (alle als Perzentilrang, niedriger Multiple = besser):
EV/EBIT (kapitalstruktur-neutral, Greenblatt-Logik), P/B, P/FCF (FCF ist
schwerer zu manipulieren als E), Shareholder Yield = Div + Buybacks (hoch
= besser). PE bewusst nicht im Composite, weil zu volatil und durch
Einmaleffekte verzerrt.

**Quality-Faktoren**: ROIC, FCF-Marge, Operating Margin, Net Debt/EBITDA
(invertiert), Earnings Stability (1 − min(σ/μ, 1) des Net Income über die letzten
5 Geschäftsjahre, davon mindestens 4 gültige; σ ist die Standardabweichung der
Grundgesamtheit, μ der Mittelwert der *Beträge*).
ROIC nutzt die *effektive* Steuerquote pro Unternehmen, wenn Pretax und
Tax Expense vorhanden sind – Fallback ist `DEFAULT_TAX_RATE=0.27`
(deutsche Durchschnittssteuerlast). Begrenzt auf [0, 0.6], um Ausreißer
durch Verlust-Quartale zu kappen.

**Negative Bewertungs-Multiples werden aus dem Value-Ranking
ausgeschlossen**, nicht mit 0 bestraft. Sonst sähen Pleitekandidaten mit
negativem EV/EBIT wie Schnäppchen aus.

**`MIN_MARKET_CAP=300 Mio EUR`** – schließt Micro-Caps aus, in denen
yfinance-Fundamentaldaten oft fehlerhaft oder veraltet sind und die
Liquidität für einen Privatanleger ohnehin grenzwertig ist.

**Value-Trap-Flag** bei oberem Value-Quartil (≥0.70) und unterem
Quality-Quartil (≤0.30). Die Werte sind bewusst weicher als die exakten
0.75/0.25-Quartil-Grenzen, damit auch borderline-Fälle gefangen werden.

## Konventionen

**Datenfluss-Format**: Innerhalb des Codes arbeiten wir mit der
`Fundamentals`-Dataclass (semantisch aufgeteilt in Identity/MarketData/
ValueMetrics/QualityMetrics/Growth). An der Grenze zu pandas (Scoring,
Reporting) wird via `to_flat_dict()` flachgeklopft. Diese Trennung ist
gewollt: Sub-Dataclasses für Lesbarkeit, flat dict für DataFrame-Effizienz.

**Contracts** (`packages/va-contracts`, Events zwischen den Services) ändern
sich nur additiv: neue Felder optional, sonst eine neue Version (`v2`). Die
JSON-Schemas liegen als Golden-Files unter `tests/golden/contracts/v1/`. Eine
Änderung dort braucht `--update-golden` und eine Begründung im Review. Auch ein
Pydantic-Update oder eine geänderte Docstring (landet als `description` im
Schema) färbt sie rot, ohne dass sich der Vertrag ändert. Events per
Konstruktor erzeugen: `model_validate` ignoriert unbekannte Felder, also auch
Tippfehler.

**Frontend** (`frontend/`, Angular 22 mit Angular Material, ab P3.5): Der API-Client unter
`frontend/src/app/api/` entsteht mit hey-api aus dem OpenAPI-Snapshot
`tests/golden/openapi/v1.json` (`make ui-api`) und wird nie von Hand geändert. Die CI prüft, dass
er zum Snapshot passt. Ändert sich die API, kommen neuer Snapshot und neuer Client in denselben
Commit. Die API ändert sich nur additiv: `oasdiff breaking` (P3.8, `make api-breaking`) vergleicht
den Snapshot in der CI mit dem Abzweigpunkt von `main` und bricht bei inkompatiblen Änderungen
ab. Braucht es einen Bruch, kommt er als `/api/v2`. Das UI ruft nur relative Pfade (`/api/v1/...`,
seit P4.6 auch den WebSocket `/ws`) und lädt nichts aus dem Internet. Echtzeit (P4.6):
`RealtimeService` und `LiveStore` (NgRx SignalStore) unter `frontend/src/app/shared/realtime/`. Die
Protokoll-Typen dort sind von Hand gespiegelt, das Golden-Schema `tests/golden/realtime/v1.json`
und `protocol.ts` ändern sich im selben Commit.

**yfinance-Feldnamen** stehen ausschließlich in den Tabellen am Kopf von
`services/market-data/src/va_market_data/adapters/yahoo.py`:
- `FIELD_MAP`: Zeilen der Abschlüsse
- `STATEMENT_FIELDS`: Attribute der Jahresabschlüsse (`income_stmt`, `balance_sheet`, `cashflow`)
- `INFO_FIELDS`: Schlüssel in `info` (`marketCap`, `currentPrice` …), Reihenfolge = Vorrang
- `FX_FIELDS`: Aufbau des FX-Symbols (`…=X`) und das Feld `lastPrice` in `fast_info`
- `CONSENSUS_FIELDS`, `QUARTERLY_FIELDS` und `PRICE_FIELDS`: Zusatzdaten (ADR-0010)

yfinance benennt unangekündigt um ("Total Revenue" → "TotalRevenue") – wenn
das passiert, ist dort die einzige zu ändernde Stelle.

**Konfiguration kommt aus Pydantic Settings**, niemals aus eingebetteten
Konstanten. Wenn du eine Konstante brauchst und sie könnte sich je nach
Deployment unterscheiden, geh durch `Settings`. Seit P5.1a gehört jedes Feld in die Settings
seines Service (`va_<service>.entrypoints.settings`). `src.config.Settings` erbt alle drei und
ergänzt nur, was allein der Batch braucht. Ein neues Feld muss auch in `ENV_PATTERN` von
`entrypoint.sh` stehen, das prüft `tests/test_entrypoint.py`. Ausnahme seit P2b.3 (ADR-0009): Die fachlichen
Scoring-Parameter stehen in den Profilen. `VALUE_WEIGHT`, `QUALITY_WEIGHT` und `MIN_MARKET_CAP`
sind nur die Startwerte für das Profil „Standard“.

**Magic Numbers im Scoring gehören in die Profil-Parameter**: Felder, Grenzen und Regeln stehen
im Contract `ProfileParamsV1` (`va_contracts.profile`, seit P3.3, das web-api braucht ihn für
OpenAPI), `ScoringProfileParams` in `va_scoring.domain.profile` erbt davon und bildet über
`to_config()` auf `ScoringConfig` ab. Ein neuer
Schwellwert bekommt einen Standardwert, gespeicherte Profile ohne ihn erhalten ihn beim Lesen.

**Universum-Quellen: iShares → Deka → Fallback-CSV** (Kette in
`va_market_data.application.universe`, Quellen in `va_market_data.adapters`,
Verdrahtung mit dem CSV-Pfad in `src/composition.py`).
Wikipedia wurde ersetzt, weil die englische MDAX-Seite nachweislich veraltet
war und die deutsche keine Ticker hat. Jede Live-Quelle wird hart validiert
(lesbares JSON/XLSX, exakt 40/50 Aktien; iShares zusätzlich Stichtag
plausibel und ≤ 10 Tage – die Deka-Datei enthält kein Datum, der Report
zeigt dann „ohne Stichtag“). Die undokumentierte iShares-API brach im
Sept. 2026 schon einmal still (HTML mit HTTP 200). Abweichungen zur CSV
werden über Symbol + Index + ISIN erkannt, also auch Auf-/Abstiege.
Recherche und Abwägung: `docs/research/dax-mdax-datenquellen/bericht.md` (Rohnotizen unter `notizen/`).

**Fallback-CSV `data/dax_mdax_fallback.csv` (symbol,name,index,isin)** wird
von Hand gepflegt und nie automatisch überschrieben – sie ist das geprüfte
Sicherheitsnetz. Die ISIN ist der Schlüssel für die Deka-Quelle. Weicht die
Live-Quelle ab (Indexreview), zeigt der Mail-Report „Fallback-CSV pflegen“.

**Datenhaltung: PostgreSQL, Daten werden niemals gelöscht.** Die DB ist die
einzige Quelle der Wahrheit (keine Parquet-Caches, kein Housekeeping mehr).
Warum: Snapshots sind nicht rekonstruierbar – yfinance liefert nur den
aktuellen, teils nachträglich korrigierten Stand und maximal 4 Geschäftsjahre.
- Schemas = spätere Services: `batch`, `market_data`, `scoring`, `reporting`, dazu seit P4.4
  `web` (Projektionen des web-api, seit P4.9 auch die Lesemodelle für REST).
  Fremdschlüssel nur innerhalb eines Schemas, dazwischen Verweis per ID
  (`tests/db/test_schema_boundaries.py` prüft Modelle und migrierte DB).
- Jedes Schema gehört einem Modul, Modelle und Repository liegen dort unter
  `adapters/postgres/`: `market_data` → `va_market_data`, `scoring` → `va_scoring`,
  `reporting` → `va_notification`, `web` → `va_web_api`, `batch` → `src/db` (Ablaufsteuerung). Basis,
  Engine/Session und DDL-Helfer stehen in `va_platform.db`. Die Alembic-Historie
  ist eine; `src/db/models/__init__.py` sammelt alle Modelle für sie.
- Die DB erzwingt „niemals löschen“ selbst (`va_platform.db.ddl`): Trigger gegen
  DELETE/TRUNCATE auf jeder Tabelle, Faktentabellen zusätzlich gegen UPDATE.
  Einzige UPDATEs: einmaliger Abschluss von `batch.run`/`market_data.fetch_run`
  (das UPDATE muss `finished_at` setzen, Migration `0005`), das Nachtragen einer
  ISIN und das einmalige Setzen von `published_at` in der Outbox (Trigger `va_guard_outbox`,
  `va_app` hat nur dieses Spaltenrecht). Projektionen sind veränderlich, aber nie löschbar
  (`MUTABLE_TABLES`, heute `web.run_status`). Rollen: `va_app` ohne DELETE, `va_read` nur SELECT (LAN-Auswertungen), `va_profiles`
  nur Profile lesen und Versionen/Aktivierungen anfügen (web-api, P3.3), `va_web` nur im Schema
  `web` lesen, anfügen und `run_status` ändern (web-api, P4.4, `VA_WEB_PASSWORD`), seit P4.7 dazu
  Runs in `batch.run` anlegen und einmal abschließen. Seit P5.3 je Service eine Rolle nur fürs
  eigene Schema (`va_market_data`, `va_scoring`, `va_notification`, `SERVICE_ROLES`,
  `VA_<SERVICE>_PASSWORD`); `va_app` bleibt für den Batch im Prozess. Eine Rolle, die nach
  dem ersten Start dazukommt, legt `python -m src.db.migrate` an (`db/init` läuft nur einmal).
- Neu-Berechnungen erzeugen neue Zeilen (z.B. neuer `scoring_run` auf alten
  Abruf), nie Überschreibungen. Abschlusswerte sind versioniert
  (`statement_value`: neue Zeile nur bei geändertem Wert → Restatements sichtbar,
  Abfrage „Stand zu Datum X“ über `get_statements_as_of`).
- Scoring-Profile (ADR-0009, seit P2b.1) liegen in `scoring.profile`, `profile_version` und
  `profile_activation`, alle nur zum Anfügen. Aktiv ist die jüngste Aktivierung. Der Handler
  von scoring legt beim ersten Bewertungslauf „Standard“ aus den ENV-Werten an
  (`StoredProfile`) und rechnet seit P2b.3 immer mit der aktiven Version.
  `scoring_run.profile_id`/`profile_version` halten fest, welche das war.
- Outbox und Inbox (P4.2, Migration `0009`): Jedes Schema hat `outbox` und `inbox`. Die Modelle
  legt der Besitzer mit `OutboxMixin`/`InboxMixin` an (`ScoringOutbox` usw.), die Logik steht in
  `va_platform.messaging` (`Outbox`, `OutboxRelay`, `Inbox`). Events gehen mit den Fachdaten in
  einer Transaktion in die Outbox, empfangene Events über `Inbox.process_once`. Seit P4.3b nutzt
  sie der `ReliableBus` je Service (`src/composition.py`, `Adapters.messaging`):
  - Inbox-Eintrag und Folge-Events kommen in einer Transaktion in die Outbox.
  - Die Fachdaten schreibt der Handler kurz davor selbst, das ist die pragmatische Variante.
  - Dazu kommen fachliche Sperren: Der Abruf des Tages wird wiederverwendet, und für einen
    Bewertungslauf geht höchstens eine Report-Mail raus (`ReportStore.delivered_report`).
- Zugriffe nur über die Repositories der Module (`get_*`/`write_*`,
  bewusst ohne delete). Jeder Titel wird sofort nach dem Abruf gespeichert.
- Migrationen (Alembic, `migrations/`) sind nur additiv; jede neue Tabelle
  braucht `protect_table()` – `tests/db/test_protection.py` prüft das.
- Ist die DB nicht erreichbar, bricht der Lauf mit Exit 4 ab: ohne
  Speicherung kein Report; ein manueller Nachlauf am selben Tag reicht.

**Robustheit vor Performance**: yfinance fällt regelmäßig aus, gibt
inkonsistente Daten zurück, ETF-Anbieter bauen Websites um. Jeder externe Call hat
Retry+Fallback. Lieber einen Ticker verlieren als den ganzen Batch.

**Python 3.14**: Die Version steht in `requires-python` der `pyproject.toml`
(Root und jedes Workspace-Mitglied), in `.python-version` und im `FROM` des
Dockerfiles. Ruff, Pyright und die CI leiten sie davon ab. Ab 3.14 schreibt der
Formatter Ausnahmen ohne Klammern (`except TypeError, ValueError:`, PEP 758).
Das fängt beide Typen ab und ist kein Python-2-Binding.

## Zielarchitektur (beschlossen, in Umsetzung)

Das Projekt wird schrittweise zu ereignisgetriebenen Microservices
umgebaut: `market-data`, `scoring`, `notification` und `web-api` (FastAPI:
REST, WebSocket, Eventmanager), dazu ein Angular-Frontend im eigenen
nginx-Container, NATS JetStream und PostgreSQL. Plan und Roadmap:
`docs/architecture/README.md`, Entscheidungen: `docs/adr/` (ADR-0001 bis
ADR-0011; ADR-0011 ist nur vorgeschlagen), Recherche: `docs/research/`.

Bis eine Phase umgesetzt ist, beschreibt dieses Dokument den **Ist-Stand**.
Neue Arbeit folgt der Zielrichtung, bei Widersprüchen gelten die ADRs.
Pläne und Recherche-Ergebnisse werden in `docs/` fortgeschrieben, nicht nur
im Chat besprochen.

**Arbeitsweise:** Umgesetzt wird in Arbeitspaketen nach dem Zyklus
Test → Implementierung → Grün → Review
(`docs/architecture/implementierungsplan.md`):
1. Tests zuerst.
2. Code, bis die neuen Tests grün sind.
3. Die komplette Prüfkette läuft durch (`make check` und `make test-db`).
4. Review des Diffs.

Gemergt wird erst nach Abnahme durch den User. Abgehakt wird in
`docs/architecture/roadmap.md`.

**Grenzen der Zielhardware** (Synology mit Celeron J4125, ADR-0008):
- Kein AVX/AVX2: keine Pakete, die x86-64-v3 voraussetzen. Nach jedem
  Dependency-Upgrade (`make lock`/`make upgrade`) und vor dem Deployment
  `make check-j4125` ausführen; die CI macht dasselbe bei jedem Push. Das baut
  die Stufe `j4125-check` des Dockerfiles (App-Image plus QEMU) und startet
  Python darin mit einem CPU-Modell ohne AVX (Denverton). Ein Paket, das AVX
  braucht, bricht dort mit „Illegal instruction“ ab.
- DSM-Kernel 4.4: Images entstehen nur in der CI (`linux/amd64`, Job
  „Docker Build + J4125-Pruefung“) und liegen in GHCR. Seit P5.1 sind das das App-Image
  (`value-analyzer`), `va-frontend` und je Service ein Image (`va-market-data`, `va-scoring`,
  `va-notification`, `va-web-api`, Dockerfile-Stufen mit `uv sync --package`). Sie enthalten
  dieselben Pakete wie das App-Image, dessen J4125-Prüfung deckt sie mit ab. Die NAS zieht sie
  (`make pull`) und baut nichts selbst. Node/Bun laufen nie auf der NAS.

## Was NICHT in dieses Projekt gehört

- Backtesting/Performance-Tracking. Das ist ein **Screener**, kein Backtest.
  Wenn das gewünscht wird, separate Pipeline mit `vectorbt`.
- Sektor-relatives Ranking. Aktuell global. Wäre für Banken/Versicherer
  sauberer, aber bei 90 Werten zu wenig Daten pro Sektor.
- Echtzeit-Daten oder Intraday. Wöchentlicher Batch reicht für
  Fundamentaldaten, die sich quartalsweise ändern. Der geplante WebSocket
  im web-api synchronisiert nur die UI und streamt keine Kurse.
- Ein separates Dependency-Injection-Framework. `Depends` von FastAPI und
  FastStream reicht.

Früher stand hier auch „Microservices/Message Queues“. Das ist durch
ADR-0001 und ADR-0002 aufgehoben.

## Wenn du was änderst

**Neuer Scoring-Faktor**:
1. Feld in passende `*Metrics`-Dataclass in `va_market_data.domain.fundamentals`
2. Berechnung als reine Funktion in `va_market_data.domain.metrics`
   (`Metrics`, `compute_metrics`), Test unter `services/market-data/tests/`.
   Der Feldname muss in `Metrics` und in der Dataclass gleich sein, ein Test
   prüft das
3. Feld im Contract `FundamentalsV1` (`va_contracts`) und dessen
   Schema-Golden-Files unter `tests/golden/contracts/v1/` (additiv)
4. Auslesen der Rohwerte in `va_market_data.adapters.yahoo.fetch_one()` (`StatementFigures`
   bzw. `MarketFigures`; `FIELD_MAP` bzw. `INFO_FIELDS` erweitern, falls yfinance-Roh-Feld
   nötig)
5. Eintrag in `DEFAULT_VALUE_FACTORS` oder `DEFAULT_QUALITY_FACTORS` (`va_scoring.domain.scoring`)
   und derselbe Schlüssel im Literal `ValueFactorKey` bzw. `QualityFactorKey`
   (`va_contracts.profile`), ein Test hält beide gleich, dazu Name und Methodik-Hinweis in
   `FACTOR_INFO` (`va_scoring.domain.profile`, für das UI). Bestehende Profile schalten ihn
   nicht von selbst ein: Dafür braucht es eine neue Profil-Version. Der OpenAPI-Snapshot und
   der TS-Client ändern sich mit (`make ui-api`)
6. Spalte in `FundamentalSnapshot` (`va_market_data.adapters.postgres.models`) und
   Migration: `alembic revision --autogenerate -m "..."` (nur additiv) –
   sonst lehnt `write_snapshot` die unbekannte Spalte ab
7. Test in `services/scoring/tests/test_scoring.py`, Golden-Files der Kennzahlen
   (`tests/golden/metrics/`) bewusst mit `--update-golden` erneuern. Ein Faktor im Composite
   verschiebt das Ranking, dann auch die Replay-Fixtures (`tests/test_replay_fixtures.py`)

**Neues Universum (z.B. Stoxx 600)**:
1. Quelle als Adapter in `va_market_data.adapters` (Klasse mit `name` und
   `load()`, Port `UniverseSource`; URL-Konstanten am Dateikopf), Soll-Anzahl
   in `UniverseConfig.expected_counts`, Reihenfolge der Kette in `src/composition.py` (`load_universe`)
2. Fallback-CSV in `data/` inkl. ISIN-Spalte
3. ENV `UNIVERSE` in `config.py` um neuen Literal-Wert erweitern
4. Filter im Handler von market-data (`RunRequestedHandler`, heute `dax_only`) und
   seine Verdrahtung in `src/composition.py:wire`
5. Währung prüfen: `MIN_MARKET_CAP` wird mit der Marktkapitalisierung in Handelswährung
   verglichen (Yahoo `marketCap`). Das stimmt, solange das Universum nur `.DE`-Titel (EUR)
   hat. Ein Universum mit anderen Währungen braucht vorher eine Umrechnung.

**Neues Workspace-Mitglied** (Paket oder Service, ADR-0004):
1. Verzeichnis unter `packages/` oder `services/` mit `pyproject.toml`
   (Name `va-<name>`, Build-Backend `uv_build`), Code unter `src/va_<name>/`, Tests
   unter `tests/`. Nutzt es `va-contracts` oder `va-platform`, stehen diese in seinen
   `dependencies` und in seinem eigenen `[tool.uv.sources]` (`workspace = true`)
2. Root-`pyproject.toml`: als Laufzeitabhängigkeit in `[project] dependencies` (der Batch
   importiert es) und unter `[tool.uv.sources]` (`workspace = true`), Import-Name in
   `known-first-party`
3. Tests: Pfad in `[tool.pytest.ini_options] testpaths`, sonst sammelt pytest sie still
   nicht
4. Coverage: Import-Name in `[tool.coverage.run] source` und als `--cov=va_<name>` in
   `make test-cov` (`Makefile`) und im Pytest-Schritt von `.github/workflows/ci.yml`
5. import-linter: Import-Name in `root_packages` und in die passenden Verträge
6. Dockerfile: seine `pyproject.toml` beim ersten `uv sync` einbinden, sonst scheitert
   `--locked`, und `--refresh-package va-<name>` beim zweiten, sonst baut uv aus dem
   Cache einen alten Stand ins Image
7. `make lock`

**Neue Mail-Empfänger**: `MAIL_TO` ist heute Single-Recipient. Wenn mehrere,
auf Liste umstellen (`pydantic.EmailStr` → `list[EmailStr]`, `;`-getrennt
parsen), `SmtpConfig` in `va_notification.adapters.smtp` und `smtp_config` in
`src/composition.py` anpassen. Dazu `NotificationConfig.recipient`
(`va_notification.entrypoints.handlers`, gesetzt in `src/composition.py:wire`): Es
landet im Versandprotokoll.

## Externe Quellen, von denen wir abhängen

- **yfinance** (Yahoo Finance): kostenlos, kein Vertrag. Kann jederzeit
  rate-limiten oder umbenennen. Wenn das chronisch wird, Wechsel zu FMP
  oder EODHD über einen neuen Adapter hinter dem Port `FundamentalsProvider`. Achtung:
  yfinance verschluckt Fehler standardmäßig (`config.debug.hide_exceptions`)
  und liefert dann leer, auch bei einem Rate-Limit. Abrufe, die Retry oder
  Abbruch brauchen, laufen deshalb in `_yahoo_errors_raised()`: Jahresabschlüsse,
  Quartale, Aktienanzahl und Kurse. Der Konsens erkennt geloggte HTTP-Fehler über
  `_YfErrorCapture`. `info` bleibt bewusst außen vor, dort verschluckt yfinance nur
  HTTP-Fehlerantworten (Begründung an `_ticker_data`). Tests dafür modellieren
  dieses Verhalten (siehe `_SwallowingTicker`), statt direkt aus dem Attribut zu
  werfen.
- **iShares-Holdings (EXS1/EXS3)**: undokumentierte Frontend-API von
  BlackRock, liefert Ticker + ISIN. Kann jederzeit umziehen – dann URL/Params
  am Kopf von `va_market_data/adapters/ishares.py` anpassen.
- **Deka-ETF-XLSX**: Blatt „Indexzusammensetzung“, nur ISIN/WKN.
- **OpenFIGI**: ISIN → Xetra-Ticker für Neuaufnahmen, die noch nicht in der
  CSV stehen; ohne API-Key (10 ISINs pro Request).
- Keine dieser Quellen erlaubt automatisierten Abruf ausdrücklich; robots.txt
  sperrt die genutzten Pfade nicht. Private Nutzung, 1× pro Woche.
- **Gmail SMTP**: kostenlos bis ~500 Mails/Tag; App-Passwort erforderlich.
- **Healthchecks.io** (optional): Free-Tier reicht für einen wöchentlichen
  Check; alternativ Self-Hosted oder gar nicht.

## Qualitätssicherung

`make check` läuft Ruff + Pyright + import-linter + Pytest. CI auf GitHub Actions macht
dasselbe bei jedem Push auf `main` und `feat/**` sowie bei Pull Requests.
Die Tests der Module liegen bei ihnen (`services/*/tests/`, `packages/va-platform/tests/`:
Kennzahlen, Scoring, Report, Handler, Bus-Verträge), übergreifende unter `tests/`
(Golden-Master, Contracts, Batch-Ablauf, Config, DB). yfinance-Calls werden in
Tests *nicht* gemockt – die Funktionen, die nur abrufen, sind kein Teil
der Test-Suite (zu viel Mocking-Overhead, zu wenig Wert). Ausnahme sind die
Adapter der Zusatzdaten (Retry, Rate-Limit, Fehler): Sie laufen gegen kleine
Fakes, die das Verhalten von yfinance nachbilden, oder gegen echtes yfinance
mit gepatchter HTTP-Schicht (`YfData`), ohne Netz.

DB-Tests (`tests/db/`) laufen gegen ein echtes PostgreSQL, nicht gegen
SQLite oder Mocks – Trigger, Rollenrechte und `DISTINCT ON` sind der
eigentliche Prüfgegenstand. Jede Testfunktion bekommt eine frische DB aus
einer migrierten Vorlage (Löschen ist ja verboten). Ohne `TEST_DATABASE_URL`
werden sie übersprungen; lokal `make test-db-up && make test-db`, in CI
per Postgres-Service-Container. Genauso laufen die NATS-Integrationstests nur mit
`TEST_NATS_URL`: Provisionierung, `NatsBus`, die Bus-Vertragstests in ihrer NATS-Variante, die
Golden-Kette (`tests/test_pipeline_bus.py`) und der Batch über NATS (`tests/test_main_nats.py`).
Lokal `make test-nats-up && make test-nats`, in der CI ein Container mit `-js`.

**Replay-Regression** (`src/regression/`, P2b.0): Weil die DB nie löscht, ist jede gespeicherte
Woche ein Testfall. `python -m src.regression` (`make regression`) schickt die Snapshots eines
Abrufs durch die echten Handler von scoring und notification und vergleicht Scores, Faktor-Ränge
und CSV mit dem gespeicherten Bewertungslauf. Das Werkzeug schreibt nichts: Die Verbindung ist
schreibgeschützt (`create_db_engine(read_only=True)`). Echte Wochen liegen als Fixtures unter
`tests/fixtures/replay/` (Export mit `--export`) und laufen in der CI. Eine gewollte
Methodik-Änderung schreibt ihre erwarteten Werte mit `--update-golden` neu, wie beim
Golden-Master. Auf der NAS läuft `make regression` nach `make pull` und vor `make up`.

**End-to-End-Test** (U5, `docker/e2e.sh`, `make local-e2e`, in der CI im Docker-Job): Ein Lauf
mit der Replay-Fixture aus `docker/e2e.env` läuft durch den ganzen Stack (seit P5.2 über NATS
und die drei Services, gestartet über `POST /api/v1/runs`; die CI nimmt die Images je Service). Dann prüfen
`tests/e2e/` (pytest, von außen über nginx und die Mailpit-API) und `frontend/e2e/` (Playwright,
Chromium unter `.local/playwright`), dass Mail, API und UI denselben Lauf mit den Werten der
Fixture zeigen. Die Browser-Tests verlangen eine leere Konsole: Ein CSP-Verstoß ist ein Fehler.
Ohne `E2E_BASE_URL` überspringen sich die Tests. Eine gewollte Methodik-Änderung erneuert
zuerst die Replay-Fixture (`--update-golden`), dann stimmt auch der E2E-Test wieder.

**Golden-Master der Mail** (`tests/test_golden_report.py`, Dateien unter
`tests/golden/`): Ein eingefrorener Datensatz
(`golden/input_fundamentals.json`, bewusst nicht die geteilte Fixture) läuft
durch `score()` und `build_report()`. Dabei gilt:
- HTML (je Zweig der Indexquelle) und Metadaten müssen byte-gleich bleiben.
- Die CSV muss inhaltlich gleich bleiben, Gleitkommazahlen mit Toleranz in
  der letzten Stelle.
- Format-Regeln: BOM, `;`, Dezimalkomma, LF.

Das ist das Sicherungsnetz für Umbauten, in Phase 1 dürfen sich die Dateien
nicht ändern. Ist eine Änderung an der Mail gewollt, die Dateien mit
`pytest tests/test_golden_report.py --update-golden` neu schreiben. Geänderte
Dateien melden sich dabei als „übersprungen“, und der Diff wird im Review
begründet. In der CI ist `--update-golden` verboten. `build_report` bekommt
dafür einen festen Zeitpunkt (`now=`), die CSV hat immer LF-Zeilenenden.

## Disclaimer

Dieses Werkzeug liefert eine quantitative Vorauswahl. **Keine
Anlageempfehlung.** Jede Position muss qualitativ überprüft werden:
Geschäftsmodell, Wettbewerbsposition, Insider-Aktivität, Bilanzqualität.
Quantitative Screens identifizieren Kandidaten – sie ersetzen das Lesen
des Geschäftsberichts nicht.
