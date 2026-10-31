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
| Daten ansehen | pgweb (nur lesen) unter <http://localhost:8081>, web-api mit Swagger unter <http://localhost:8000/api/docs>, später die Web-UI | später die Web-UI unter `http://<nas>:8080` |
| Ports | nur `127.0.0.1` | Postgres optional im LAN (`DB_LAN_BIND`) |
| Tests | `make check`, `make test-db` (Wegwerf-DB auf 55432), `make local-regression` | `make regression` nach `make pull`, vor `make up` |

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
  `make local-up` startet nur Datenbank, Mailpit und pgweb, `make local-run` startet einen Lauf.
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

## Was gleich bleibt

- Die NAS baut nichts, Images kommen nur aus der CI (ADR-0008).
- Node läuft nur lokal, nie auf der NAS.
- Die Datenbank löscht nie, auch lokal nicht. Lokal neu anfangen heißt: `make local-down` und
  den Ordner `./.local/pgdata` von Hand entfernen.
- Gemergt wird nach Abnahme.
