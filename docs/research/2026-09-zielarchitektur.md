# Recherche: Zielarchitektur (29./30.09.2026)

Notizen zur Architektur-Recherche, auf der die [Zielarchitektur](../architecture/README.md) und die
[ADRs](../adr/README.md) beruhen. Alle Versionsangaben wurden per Websuche bzw. auf den offiziellen
Seiten am angegebenen Tag geprüft. Sie veralten, deshalb vor der Umsetzung erneut prüfen.

## Anlass

Der Nutzer wünscht:

- eine moderne Architektur,
- ein Angular-Frontend,
- FastAPI, Pydantic und PostgreSQL,
- Microservices,
- WebSocket für die Frontend-Synchronisation,
- einen Eventmanager im Web-Backend.

Entscheidungen des Nutzers am 30.09.2026:

- nur im lokalen Netz erreichbar,
- NAS mit Intel Celeron J4125 und 18 GB RAM,
- das Frontend als eigener Container,
- Scoring im UI anpassbar.

## Verifizierte Versionen

| Komponente | Stand | Anmerkung |
|---|---|---|
| Python | 3.14 aktuell, 3.15 final geplant am 01.10.2026 | 3.14: 99,7 % der 360 populärsten Pakete haben Wheels |
| FastAPI | 0.14x; SSE ab 0.135, `app.frontend()` ab 0.138, natives OpenTelemetry in 0.142 | `app.frontend()` liefert SPA-Builds aus, wird wegen des eigenen Frontend-Containers nicht genutzt |
| Pydantic | 2.13.5 (28.08.2026) | keine v3 angekündigt |
| FastStream | 0.7.7 (23.09.2026), Python 3.10–3.14 | FastAPI-Integration ausgelagert nach `faststream_fastapi`; vor 1.0 können Minor-Versionen brechen |
| NATS Server | 2.12 (seit 22.09.2025): atomare Batches, verzögerte Nachrichten, verteilte Zähler | JetStream-API-Level 2 |
| PostgreSQL | 18 stabil; 19 Beta 4 am 24.09.2026, GA-Ziel Ende Oktober 2026 | PG-18-Image: Volume auf `/var/lib/postgresql`, Daten unter `18/docker` |
| SQLAlchemy | 2.1.0 GA am 24.09.2026, 2.1.1 am 25.09.2026 | greenlet nur noch über das Extra `sqlalchemy[asyncio]` |
| pandas | 3.0.0 (21.01.2026), aktuell 3.0.x | Copy-on-Write als einziger Modus, eigener String-Dtype (mit pyarrow, sonst NumPy) |
| NumPy | 2.4: Mindestanforderung x86-64-v2 | relevant für den J4125 |
| yfinance | 1.x, aktuell 1.7.0 | 1.0 ohne Breaking Changes, `curl_cffi` seit 1.4 optional; das Repo pinnt noch `<0.3` |
| Angular | 22: OnPush als Standard, Signal Forms und Resource-API stabil, TypeScript 6, Node ≥ 22 | 21: zoneless als Standard, Vitest statt Karma |
| NgRx | Events-Plugin für SignalStore stabil seit 21 (`withEffects` heißt jetzt `withEventHandlers`) | |
| @hey-api/openapi-ts | Angular-Plugin (`httpResource`) und Zod-v4-Plugin | Signal Forms validieren Zod über `validateStandardSchema` (Angular ≥ 21, Zod ≥ 4) |

## Hardware und DSM

- **J4125:** x86_64, 4 Kerne, 2,0–2,7 GHz, Befehlssätze bis SSE4.2, **kein AVX/AVX2**. Damit
  x86-64-v2, aber nicht v3.
- **RAM-Ausstattung ab Werk:** DS220+, DS420+ und DS720+ haben 2 GB (offiziell max. 6 GB), die
  DS920+ 4 GB (max. 8 GB). Der Nutzer hat 18 GB, RAM ist also kein Engpass.
- **DSM 7.3** auf der Plattform geminilake läuft mit Kernel 4.4.302+. Container Manager bringt
  Docker 24 mit Compose.
- **Dokumentierter Fehlerfall** auf einer DS920+: Bun ab 1.2.3 bricht wegen `statx` (Kernel ≥ 4.11)
  ab, Bun-Binaries außerhalb der Baseline mit `Illegal instruction` (fehlendes AVX2). Die Lösung
  dort: Images auf einem modernen Kernel bauen und auf der NAS nur laden.
- **DSM-Reverse-Proxy:** WebSocket braucht die Header `Upgrade` und `Connection` (Voreinstellung
  „WebSocket“ unter Benutzerdefinierter Header).

## Messwerte und Beobachtungen (30.09.2026)

- `score()` mit 110 synthetischen Werten: **8,48 ms** pro Lauf. Gemessen auf AMD Zen 3
  (Family 25 Model 33) mit pandas 3.0.0 und NumPy 2.3.5, gemittelt über 200 Läufe. Für den J4125
  sind grob das Drei- bis Vierfache zu erwarten, also etwa 25–35 ms.
- Das globale Python des Entwicklungsrechners hat bereits pandas 3.0.0, aber weder pytest noch
  yfinance. Die Test-Suite lief deshalb noch nicht unter pandas 3.
- Zu yfinance (verifiziert am 29.09.2026 mit yfinance 0.2.66):
  - Die Statements liefern höchstens 4 befüllte Geschäftsjahre. `revenue_growth_5y` ist deshalb
    faktisch ein CAGR über 3 Jahre.
  - Die Zahlen sind nachträglich korrigiert (restated), z. B. SAP-Umsatz 2022 mit 29,5 Mrd. statt
    ursprünglich ~30,9 Mrd.

  Stichtagsdaten lassen sich also später nicht rekonstruieren. Das begründet
  [ADR-0003](../adr/0003-postgresql-schema-pro-service.md).

## Parallele Arbeiten (Stand 30.09.2026)

- Das Universum kommt jetzt von iShares/Deka statt Wikipedia (`ca85d93`, `c14fa32`). Die Recherche
  dazu liegt unter [dax-mdax-datenquellen/](dax-mdax-datenquellen/bericht.md).
- Die Postgres-Persistenz wird auf `feat/postgres-persistence` umgesetzt: Schemas `batch`,
  `market_data`, `scoring`, `reporting`, Löschschutz per Trigger, Rollen `va_app` und `va_read`,
  Altdaten-Import. Die Zielarchitektur baut darauf auf ([datenhaltung.md](../architecture/datenhaltung.md)).

## Offene Punkte

- UI-Bibliothek (Angular Material oder PrimeNG), ggf. AG Grid für die Ranking-Tabelle
- Content-Security-Policy für den nginx-Container
- Zeitpunkt für die Upgrades auf PostgreSQL 19 und Python 3.15
- Async-Engine je Service oder synchrones SQLAlchemy mit `asyncio.to_thread`
- Lauf-Protokoll im UI: heute `batch.run_log`, später aus zentralem Logging?

## Quellen

- [Angular v22 (InfoQ)](https://www.infoq.com/news/2026/08/angular-v22-released/)
- [Angular 21 (angular.love)](https://angular.love/angular-21-whats-new)
- [Angular Signal Forms: Validierung](https://angular.dev/guide/forms/signals/validation)
- [FastAPI Release Notes](https://fastapi.tiangolo.com/release-notes/)
- [FastAPI SSE](https://fastapi.tiangolo.com/tutorial/server-sent-events/)
- [FastAPI app.frontend()](https://umesh-malik.com/blog/fastapi-spa-app-frontend-explained)
- [FastStream (PyPI)](https://pypi.org/project/faststream/)
- [FastStream (GitHub)](https://github.com/ag2ai/faststream)
- [NATS Server 2.12](https://nats.io/blog/nats-server-2.12-release/)
- [PostgreSQL 19 Zeitplan](https://layerbase.com/blog/when-will-postgres-19-be-released)
- [Postgres Docker Image](https://hub.docker.com/_/postgres)
- [SQLAlchemy 2.1.0](https://www.sqlalchemy.org/blog/2026/09/24/sqlalchemy-2.1.0-released/)
- [Pydantic (PyPI)](https://pypi.org/project/pydantic/)
- [pandas 3.0](https://pandas.pydata.org/docs/whatsnew/v3.0.0.html)
- [NumPy 2.4 Release Notes](https://numpy.org/doc/stable//release/2.4.0-notes.html)
- [yfinance Changelog](https://github.com/ranaroussi/yfinance/blob/main/CHANGELOG.rst)
- [uv Workspaces](https://docs.astral.sh/uv/concepts/projects/workspaces/)
- [Hey API Angular-Plugin](https://heyapi.dev/openapi-ts/plugins/angular)
- [Hey API Zod-v4-Plugin](https://heyapi.dev/docs/openapi/typescript/plugins/zod/v4)
- [NgRx SignalStore Events](https://arcadioquintero.com/en/blog/ngrx-signalstore-events-plugin/)
- [Python 3.15 RC2](https://www.python.org/downloads/release/python-3150rc2/)
- [Python 3.14 Readiness](http://pyreadiness.org/3.14/)
- [Intel Celeron J4125](https://www.intel.com/content/www/us/en/products/sku/197305/intel-celeron-processor-j4125-4m-cache-up-to-2-70-ghz/specifications.html)
- [Kernel je Synology-Plattform](https://github.com/007revad/Synology_Information_Wiki/blob/main/pages/Linux-Kernel-in-each-platform-arch.md)
- [Docker Images Do Not Bring a Kernel (DS920+)](https://blog.harianto.dev/posts/docker-images-do-not-bring-a-kernel)
- [Synology Docker 24](https://mariushosting.com/synology-new-docker-version-24-0-2-1543/)
- [RAM DS920+](https://mariushosting.com/synology-which-ram-to-buy-for-ds920-nas/)
- [RAM DS720+](https://mariushosting.com/synology-which-ram-to-buy-for-ds720-nas/)
- [Synology WebSocket-Header](https://mariushosting.com/synology-some-docker-containers-need-websocket/)
