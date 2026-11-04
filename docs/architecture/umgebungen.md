# Umgebungen: lokal und NAS

> **Status:** beschlossen am 30.10.2026, Umsetzung als Track U ([Roadmap](roadmap.md),
> [Implementierungsplan](implementierungsplan.md#track-u--umgebungen-lokal-und-nas)).

## Ziel

Dieselben Images laufen an zwei Orten. Sie unterscheiden sich nur in Daten, Mailziel und
Zeitplan:

- **Lokal** (Entwicklungsrechner, `localhost`): jede neue Implementierung mit echten Daten
  ausprobieren, Ergebnisse im Browser ansehen, Tests ausführen. Es geht keine Mail nach außen
  und kein Healthcheck-Ping raus.
- **NAS** (live): wöchentlicher Lauf per Cron, echte Mail. Die NAS baut nichts und zieht
  fertige Images aus GHCR ([betrieb-synology.md](betrieb-synology.md)).

| | Lokal | NAS |
|---|---|---|
| Compose | `docker-compose.yml` + `docker-compose.local.yml` (`make local-*`) | `docker-compose.yml` |
| Image | aus dem Arbeitsstand gebaut (`value-analyzer:local`) | aus GHCR (`latest`, `sha-…`, Version) |
| Läufe | auf Knopfdruck (`make local-run`), kein Cron | Cron (Samstag 07:30) |
| Mail | Mailpit, Postfach unter <http://localhost:8025> | Gmail |
| Healthcheck | aus | Healthchecks.io, falls eingerichtet |
| Datenbank | eigene, Daten in `./.local/pgdata` | `./pgdata`, nie gelöscht |
| Daten ansehen | pgweb (nur lesen) unter <http://localhost:8081>, web-api mit Swagger unter <http://localhost:8000/api/docs>, das UI mit `make ui` unter <http://localhost:4200> (oder hinter nginx mit `make local-ui` unter <http://localhost:8080>) | Web-UI unter `http://<nas-ip>:8080` (seit P3.6, `UI_LAN_BIND`) |
| Ports | nur `127.0.0.1` | Postgres optional im LAN (`DB_LAN_BIND`) |
| Tests | `make check`, `make test-db` (Wegwerf-DB auf 55432), `make local-regression` | `make regression` nach `make pull`, vor `make up` |
| End-to-End (ab U5) | `make local-e2e`: ganze Kette mit festen Daten (Replay), Wegwerf-DB; `make local-check` gegen den lokalen Stack | – (die CI prüft dieselbe Kette bei jedem Push) |

## Entscheidungen

- **Keine eigene Compose-Datei für die NAS.** `docker-compose.yml` bleibt die Definition des
  Live-Betriebs. Lokal legt `docker-compose.local.yml` nur Unterschiede darüber. So läuft eine
  bestehende NAS-Installation nach `git pull` ohne Änderung an ihrer `.env` weiter.
- **Lokal kann nichts nach außen gehen.** Die lokale Datei setzt SMTP fest auf Mailpit und
  leert `HEALTHCHECK_URL`. Diese Werte stehen unter `environment` und schlagen damit die `.env`.
  Ein lokaler Lauf erreicht also weder Gmail noch den Healthcheck, auch wenn dort echte
  Zugangsdaten stehen. Ein lokaler Ping würde einen Ausfall der NAS verdecken.
- **`SMTP_PLAIN`:** ohne TLS und ohne Login, nur für einen lokalen Mail-Catcher. Es wird dabei
  kein Passwort gesendet. Der Versand bleibt sonst unverändert: STARTTLS oder SSL, jeweils mit
  Zertifikatsprüfung.
- **Der Batch läuft lokal nicht dauerhaft.** `value-analyzer` hat dort das Profil `run`.
  `make local-up` startet Datenbank, NATS, Mailpit, pgweb und das web-api, `make local-run`
  startet einen Lauf.
- **Runs aus dem UI (P4.7, seit P5.1 drei Container):** `make local-up` startet mit dem Profil
  `nats` auch market-data, scoring und notification, lokal aus dem App-Image mit ihrem eigenen
  Einstieg (`python -m va_market_data` usw.). notification schickt Mails wie der Batch nur an
  Mailpit. Damit lassen sich Runs auf der Seite Runs starten. Auf der NAS haben die Dienste
  dasselbe Profil und eigene Images aus GHCR (`va-market-data` usw.). Sie laufen erst
  nach dem Umstieg auf NATS.
- **pgweb liest mit der Rolle `va_read`** und zusätzlich im Modus `--readonly`.
- **Eigene Namen:** Der lokale Stack heißt `value-analyzer-local`, seine Container auch. Er
  kollidiert so nicht mit einem Stack aus `docker-compose.yml` auf demselben Rechner. Ist Port
  5432 belegt, verlegt `LOCAL_DB_PORT` die lokale Datenbank.
- **Der schnelle Weg bleibt:** `make dry` und `make run` laufen weiter aus der `.venv` gegen
  dieselbe lokale Datenbank (`127.0.0.1:5432`), Mails gehen dann an `127.0.0.1:1025`
  ([.env.local.example](../../.env.local.example)). Bewusst `127.0.0.1` statt `localhost`:
  Windows versucht bei `localhost` zuerst IPv6, die Ports lauschen aber nur auf IPv4. Jede
  Verbindung wartete dann, bis der Versuch abbricht (gemessen 16 s, ohne Timeout bis zu 2 min).

## Pakete

- **U1 Lokaler Stack:** `docker-compose.local.yml` mit Mailpit und pgweb, `SMTP_PLAIN`,
  `.env.local.example`, `make local-*`.
- **U2 NAS-Daten lokal:** Ein Dump der NAS (`make db-backup`) wird lokal eingespielt
  (`make local-restore`). Danach prüft `make local-regression` jede neue Implementierung gegen
  alle echten Wochen, bevor sie auf die NAS geht.
- **U3 Test auf der NAS (optional):** Die CI baut auch für `feat/**` ein Image. Auf der NAS läuft
  dafür ein zweites Compose-Projekt mit eigener Datenbank (Kopie der Live-Daten), ohne Cron und
  mit Mailpit. Getrennt, weil ein Branch-Image seine Migrationen sonst für immer in die
  Live-Datenbank schreibt. Das Live-Image fände danach eine ihm unbekannte Revision vor.
- **U4 Analysen im Browser:** Teile von Phase 3 vorziehen: web-api mit Lese-Endpunkten
  (P3.1, P3.2) und die Ansichten Ranking, Runs und Titel-Detail. Lokal mit `ng serve`, auf der
  NAS als frontend-Container. Der Profil-Editor wartet auf Phase 2b. **Entschieden am
  31.10.2026:** U4 kommt vor Phase 2b.
- **U5 Lokaler End-to-End-Test:** `make local-e2e` prüft die ganze Kette mit einem Befehl:
  Batch, Mail in Mailpit, web-api hinter nginx und das UI im Browser (Playwright). Die Daten
  kommen aus einer Replay-Fixture statt von Yahoo, damit das Ergebnis feststeht. Umgesetzt am
  31.10.2026, vor P2b.1 ([Implementierungsplan](implementierungsplan.md#u5-lokaler-end-to-end-test)).

## Neue Implementierung lokal prüfen (ab U5)

Einmalig: `make ui-install` und `make ui-e2e-install` (Chromium nach `.local/playwright`, rund
720 MB auf E:, nicht auf C:).

1. Code: `make check`, `make test-db`, bei Änderungen am UI `make ui-check`.
2. Ganze Kette mit festen Daten: `make local-e2e`. Das dauert rund zwei Minuten, die meiste Zeit
   für den Image-Build. `E2E_KEEP=1 make local-e2e` lässt den Stack zum Ansehen stehen (UI unter
   <http://localhost:18080>, Mailpit unter <http://localhost:18025>).
3. Alle gespeicherten Wochen: `make local-regression`, nach U2 mit den Daten der NAS.
4. Bei Bedarf mit echten Daten ansehen: `make local-up`, `make local-run`, `make local-ui`,
   dann `make local-check`, Mailpit und das UI im Browser.

## Was gleich bleibt

- Die NAS baut nichts, Images kommen nur aus der CI (ADR-0008).
- Node läuft nur lokal, nie auf der NAS.
- Die Datenbank löscht nie, auch lokal nicht. Lokal neu anfangen heißt: `make local-down` und
  den Ordner `./.local/pgdata` von Hand entfernen.
- Gemergt wird nach Abnahme.
