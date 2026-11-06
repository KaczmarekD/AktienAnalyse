# Betrieb auf der Synology

> **Status:** Runbook für den Stack mit Services (P5.6, 04.11.2026). Entscheidungen:
> [ADR-0007](../adr/0007-lan-only-ohne-login.md) (nur LAN) und
> [ADR-0008](../adr/0008-zielhardware-j4125.md) (Zielhardware).

## Zielhardware

| Eigenschaft | Wert | Folge |
|---|---|---|
| CPU | Intel Celeron J4125: x86_64, 4 Kerne, 2,0–2,7 GHz | reicht; der Engpass ist Yahoos Rate-Limit, nicht die CPU |
| Befehlssatz | bis SSE4.2 (x86-64-v2), **kein AVX/AVX2** | keine Pakete, die x86-64-v3 voraussetzen |
| RAM | 18 GB | kein Engpass; Speicherlimits dienen nur als Sicherheitsnetz |
| Betriebssystem | DSM 7.x, Plattform geminilake, **Kernel 4.4** | nichts, was einen neueren Kernel voraussetzt |
| Container | Container Manager (Docker 24 mit Compose) | Compose-Datei wie unten |

## Drei feste Regeln

1. **Images nur für `linux/amd64`, gebaut ausschließlich in GitHub Actions.** Die NAS lädt fertige
   Images aus der GitHub Container Registry (GHCR) und baut selbst nichts. Kernel 4.4 fehlen
   neuere Systemaufrufe wie `statx` (erst ab 4.11), daran scheitern moderne Build-Tools. Für Bun
   ist das auf genau diesem Prozessor dokumentiert. Node läuft deshalb nie auf der NAS.
2. **Kein AVX2-Code.** NumPy setzt seit Version 2.4 x86-64-v2 voraus, das schafft der J4125 gerade
   noch. Pakete, die x86-64-v3 brauchen, stürzen mit `Illegal instruction` ab. Nach jedem
   Dependency-Upgrade und vor dem Deployment prüfen (die CI macht dasselbe bei jedem Push):
   ```
   make check-j4125
   ```
   Das baut die Stufe `j4125-check` des Dockerfiles, also das App-Image plus QEMU, und führt
   Python darin mit dem CPU-Modell Denverton aus (Goldmont, dieselbe Klasse wie der J4125:
   SSE4.2, kein AVX; ein Goldmont-Plus-Modell hat QEMU nicht). Zuerst führt `run.sh` eine
   einzelne AVX2-Instruktion aus. Sie muss mit SIGILL enden, sonst fängt die Emulation AVX2
   nicht ab und die Prüfung bricht ab. Danach stellt das Prüfskript
   (`docker/j4125-check/check_imports.py`) sicher, dass das CPU-Modell kein AVX meldet, lädt
   jede native Erweiterung im Image und den Importgraph der App und rechnet wie im Wochenlauf:
   Ranking, Mail-Report, Parquet-Durchlauf. Ein Paket mit AVX-Code beendet den Lauf mit
   Exit-Code 132.

   Die Images kommen aus der CI: Der Job „Docker Build + J4125-Pruefung“ baut sie, prüft sie
   (Smoke-Test, J4125, End-to-End-Test) und schiebt sie bei einem Push auf `main` und bei Tags
   `v*` nach `ghcr.io/kaczmarekd/` (`sha-<commit>`, `latest`, `<version>`). Die Images der
   Services enthalten dieselben Pakete wie das App-Image, dessen J4125-Prüfung deckt sie mit ab.
   Nach jedem `make pull` zusätzlich auf der echten CPU prüfen (ohne DB, ohne Migration):
   ```
   docker compose run --rm --no-deps --entrypoint python value-analyzer -c "import src.main"
   ```
3. **Keine Kernel-Features jenseits von 4.4.** Postgres 18 bleibt beim Standard-`io_method`, die
   neue `io_uring`-Option wird nicht aktiviert. Es gibt keine cgroup-v2-Features.

## Netzwerk

- Nur der `frontend`-Container veröffentlicht einen Port (8080). web-api, Postgres und NATS hängen
  ausschließlich im internen Docker-Netz.
- Zugriff über `http://<nas>:8080`. Die DSM-Firewall gibt den Port nur für das eigene Subnetz frei.
- Seit P3.6 in `docker-compose.yml`: Port 8080 bindet an `UI_LAN_BIND` (Default `127.0.0.1`, also
  nur auf der NAS selbst). Für das LAN die NAS-IP eintragen und in `UI_SERVER_NAMES` die Namen,
  unter denen das UI aufgerufen wird. Alle anderen Hostnamen bekommen keine Antwort.
- HTTPS ist optional über den DSM-Reverse-Proxy möglich. Dann dort die WebSocket-Header
  aktivieren: Reverse Proxy → Benutzerdefinierter Header → Erstellen → WebSocket.
- Weitere Sicherheitsregeln (Origin-Prüfung, nur JSON, Hostnamen-Filter):
  [web-api-realtime.md](web-api-realtime.md#sicherheitsregeln-lan-ohne-login).

## Dienste

`docker-compose.yml` im Repo ist die Compose-Datei der NAS. Alle Dienste hängen im internen
Docker-Netz des Projekts, nur `frontend` hat einen Port im LAN.

| Dienst | Image | Startet nach | Aufgabe |
|---|---|---|---|
| `db` | `postgres:18` | – | Datenbank, Daten in `./pgdata` |
| `nats` | `nats:2.15.1-alpine` | – | Event-Bus mit JetStream, Daten in `./natsdata` |
| `migrate` | `value-analyzer` | `db` gesund | migriert, legt neue Rollen an, füllt die Projektionen nach; endet danach |
| `market-data` | `va-market-data` | `db`, `nats`, `migrate` | Universum, Abruf bei Yahoo, Kennzahlen |
| `scoring` | `va-scoring` | wie oben | Bewertung, Scoring-Profile, Vorschau |
| `notification` | `va-notification` | wie oben | Mail (SMTP), Healthchecks.io |
| `web-api` | `va-web-api` | wie oben | REST, WebSocket, Wochenplan, Watchdog |
| `frontend` | `va-frontend` | `web-api` | UI (nginx), Port 8080 |
| `value-analyzer` | `value-analyzer` | `db` | Batch und Werkzeuge, nur mit Profil `run` |

`REG` (Standard `ghcr.io/kaczmarekd`) und `VERSION` (Standard `latest`) in der `.env` wählen die
Images. `latest` folgt `main`, `sha-<commit>` oder eine Version wie `0.3.0` pinnt. Jeder Dienst
bekommt nur die Variablen, die in der Compose-Datei bei ihm stehen. SMTP sieht nur
`notification`, und jeder Service meldet sich mit seiner eigenen Rolle an der Datenbank an
(`va_market_data`, `va_scoring`, `va_notification`, `va_web`, seit P5.3).

Den Wochenlauf plant das web-api nach `CRON_SCHEDULE` aus der `.env` (Standard `30 7 * * 6`,
also Samstag 07:30, Zeitzone `Europe/Berlin`). Einen Cron im Container gibt es nicht mehr.

## Erstinstallation

```bash
cd /volume1/docker/
git clone https://github.com/KaczmarekD/AktienAnalyse.git value-analyzer
cd value-analyzer
cp .env.example .env
nano .env          # Passwörter, SMTP_*, MAIL_TO, UI_LAN_BIND, UI_SERVER_NAMES
make pull          # alle Images aus GHCR, die NAS baut nichts
docker compose run --rm --no-deps --entrypoint python value-analyzer -c "import src.main"
make up            # db, nats, migrate, Services, web-api, frontend
docker compose ps  # migrate "exited (0)", alle anderen "running" bzw. "healthy"
```

Pflicht in der `.env` sind `POSTGRES_PASSWORD`, `VA_APP_PASSWORD`, `VA_READ_PASSWORD`,
`VA_PROFILES_PASSWORD`, `VA_WEB_PASSWORD`, `VA_MARKET_DATA_PASSWORD`, `VA_SCORING_PASSWORD`,
`VA_NOTIFICATION_PASSWORD`, seit D1.1 `VA_IDENTITY_PASSWORD`, dazu `SMTP_USER`, `SMTP_PASSWORD`
und `MAIL_TO`. Fehlt ein
Passwort, bricht Compose mit einem Hinweis wie „VA_WEB_PASSWORD in .env setzen“ ab. Fehlen die
Angaben für die Mail, startet `notification` nicht und nennt das Feld in
`docker compose logs notification`.

Sind die Pakete in GHCR privat, braucht die NAS einmalig `docker login ghcr.io` mit einem Token,
das nur `read:packages` darf.

**Konten (seit D1.1):** Den ersten Admin legt ein Kommando im Container des web-api an. Es fragt
das Passwort zweimal ab (mindestens 12 Zeichen):

```bash
docker compose exec web-api python -m va_web_api.admin create-user <name> --admin --email <mail>
```

Weitere Konten ohne `--admin`. Anmelden im Browser geht erst mit HTTPS (D1.5), denn das
Sitzungs-Cookie ist `Secure`. Bis dahin bleiben alle bisherigen Ansichten ohne Anmeldung nutzbar:
`docker-compose.yml` setzt dafür `WEB_API_AUTH_REQUIRED=false` (seit D1.2, entfällt mit D1.5).

## Umstellung vom Batch mit Cron (einmalig)

Bis P5.4 lief auf der NAS der Batch-Container `value-analyzer` mit einem Cron. Seit P5.4 hat er das
Profil `run`. `make up` startet ihn nicht mehr, ein laufender alter Container bliebe aber stehen und
startete am Samstag einen zweiten Lauf. Läuft auf der NAS noch eine Fassung vor Phase 2 (ohne
Datenbank), kommen die Altdateien dazu: Kennzahlen als `fundamentals_*.parquet` und Rankings als
`value_ranking_*.csv` in `data/`. Dieser Abschnitt deckt beide Fälle ab und erledigt alle offenen
NAS-Punkte der Roadmap in einem Durchgang.

**Vorab, solange der alte Batch läuft:** In der `.env` `RETENTION_DAYS=0` setzen und den
Container mit `docker compose up -d` neu anlegen, damit er die Variable liest. Sonst löscht das alte
Housekeeping beim nächsten Lauf Altdateien, die der Import braucht.

1. Sicherung des Projektordners (Hyper Backup oder Kopie). Wichtig sind `data/` mit den
   Altdateien, die `.env` und, falls es ihn schon gibt, `pgdata/`.
2. `git pull`, dann die `.env` mit `.env.example` vergleichen. Neu sind je nach Stand
   `POSTGRES_PASSWORD`, `VA_APP_PASSWORD` und `VA_READ_PASSWORD` (Phase 2),
   `VA_PROFILES_PASSWORD` (P3.3), `VA_WEB_PASSWORD` (P4.4), die drei `VA_<SERVICE>_PASSWORD`
   (P5.3) und `VA_IDENTITY_PASSWORD` (D1.1). Für das UI im LAN `UI_LAN_BIND` und
   `UI_SERVER_NAMES` setzen.
3. `make pull` und der Import-Test aus Regel 2.
4. Alles stoppen, auch den alten Batch-Container:
   ```bash
   docker compose --profile run down
   ```
   `down` entfernt nur Container. `./data`, `./pgdata` und `./natsdata` bleiben.
5. Altdaten importieren:
   ```bash
   make db-import
   ```
   Das startet die Datenbank, migriert das Schema und liest die Parquet- und CSV-Dateien aus
   `data/` ein. Je Datum entsteht ein Lauf vom Typ `import`. Jede Datei wird über ihren SHA-256
   genau einmal importiert, ein zweiter Aufruf ändert nichts. Die Dateien bleiben liegen. Am Ende
   steht „Fertig: N Dateien importiert, M bereits vorhanden“, ohne Altdateien mit N = 0.
6. `make regression`: Die gespeicherten Wochen, auch die importierten, müssen mit dem neuen Code
   dieselben Ergebnisse liefern (Exit 0). Abweichungen sind nur dort in Ordnung, wo die Roadmap eine
   Methodik-Änderung nennt. Bei Wochen vor M1 fehlt Banken wie Deutsche Bank und Commerzbank
   jetzt der Composite. Exit 2 mit „nichts zu vergleichen“ heißt: Es gibt noch keine Wochen.
7. `make up`. Der Dienst `migrate` legt die neuen Rollen an und füllt die Projektionen des
   web-api mit allen Läufen nach, auch mit den importierten. Deshalb kommt der Import vorher.
8. Prüfen:
   - `docker compose ps`: kein Container `value-analyzer` mehr.
   - Das UI unter `http://<nas>:8080` zeigt die alten Läufe.
   - Auf der Seite „Runs“ einen Dry-Run starten. Er läuft durch die drei Services und speichert
     die Mail, ohne sie zu senden.
9. Aufräumen und sichern:
   - `RETENTION_DAYS` aus der `.env` entfernen. Das neue Image kennt die Variable nicht mehr und
     löscht nie etwas.
   - Die Sicherung einrichten wie unter [Backup](#backup) beschrieben.

Zurück geht es mit `VERSION` auf dem alten Stand und der alten Compose-Datei
(`git checkout <commit> -- docker-compose.yml`). Die Datenbank bleibt gültig, denn Migrationen
sind nur additiv.

## Update

Nach einem Merge auf `main` baut die CI die Images, prüft sie und schiebt sie nach GHCR. Auf der
NAS:

```bash
cd /volume1/docker/value-analyzer
make db-backup     # Dump nach backups/
git pull           # Compose-Datei, Fallback-CSV, Doku
make pull
docker compose run --rm --no-deps --entrypoint python value-analyzer -c "import src.main"
make regression    # schreibt nichts, Exit 0 heißt: alles gleich
make up            # migrate läuft zuerst, dann starten die geänderten Dienste neu
```

Das Volume `./data` verdeckt die Fallback-CSV im Image, neue Fassungen kommen deshalb mit
`git pull`. Neue Variablen nennt `.env.example`.

## Läufe

- **Geplant:** Das web-api legt zum Termin aus `CRON_SCHEDULE` einen Run an, je Termin einen.
  Einen verpassten Termin holt es bis eine Stunde danach nach, später nicht mehr.
- **Von Hand:** im UI auf der Seite „Runs“, mit den Optionen Dry-Run, Mail und Neu abrufen.
  Läuft schon ein Run, lehnt das web-api einen zweiten ab.
- **Batch im Prozess:** `make docker-run` (`make docker-dry` ohne Mail) führt einen Lauf ohne
  NATS im Batch-Container aus. Das ist der Notweg, wenn die Services nicht laufen.

## Störungen

| Was man sieht | Ursache und Abhilfe |
|---|---|
| Run bleibt hängen, nach einer Weile „gescheitert (watchdog)“ | Der Watchdog meldet eine Stufe, die zu lange braucht: Abruf 45, Bewertung 5, Mail 5 Minuten. `docker compose logs market-data` (bzw. `scoring`, `notification`) zeigt den Grund, oft ein Rate-Limit von Yahoo. |
| UI meldet 503 „… nicht erreichbar“ | Der zuständige Service läuft nicht. `docker compose ps`, dann `docker compose up -d <dienst>`. |
| Mail „FEHLER beim Batch-Run“ | Eine Stufe ist gescheitert. Die Mail nennt den Grund, die Logs des Dienstes den Rest. |
| Ein Dienst startet nicht, `migrate` „exited (1)“ | `docker compose logs migrate`. Meist fehlt eine Variable oder die Datenbank war nicht bereit; `make up` erneut. |
| Keine Mail und kein Ping am Samstag | Healthchecks.io meldet den fehlenden Ping. `docker compose logs web-api` zeigt, ob der Run angelegt wurde. |

Die Logs liegen bei Docker (`make logs` oder `docker compose logs -f <dienst>`). Für die Spans
eines Runs `OTEL_TRACES_EXPORTER=console` in der `.env` setzen und `make up`: Jeder Dienst schreibt
dann seine Spans als JSON ins Log, alle Spans eines Runs haben dieselbe Trace-ID (P5.5).

## Secrets

Zugangsdaten stehen in der `.env` neben der Compose-Datei. Die Datei gehört dem Admin und ist
nicht im Repo. Jeder Dienst bekommt nur die Variablen, die er braucht, über die API ist keine
lesbar. Docker-Secrets (`/run/secrets`) sind möglich, aber nicht umgesetzt.

## Backup

Die Datenbank in `./pgdata` ist die einzige Quelle der Wahrheit, gelöscht wird dort nie etwas.

- **Dump:** `make db-backup` schreibt einen Dump (`pg_dump -Fc`) nach
  `backups/value_analyzer_<datum>_<zeit>.dump`. Er ist die verlässliche Sicherung. Eine Kopie von
  `pgdata/` im laufenden Betrieb kann inkonsistent sein. Alte Dumps bleiben liegen.
- **Einrichten (einmalig):**
  - Im DSM-Aufgabenplaner eine geplante Aufgabe anlegen: benutzerdefiniertes Skript, Benutzer
    `root`, wöchentlich nach dem Lauf, etwa Sonntag 03:00:
    ```bash
    cd /volume1/docker/value-analyzer && make db-backup
    ```
  - Eine Hyper-Backup-Aufgabe für den Projektordner anlegen, mit `backups/`, `data/` und der
    `.env`. Das Ziel verschlüsseln, denn die `.env` enthält die Passwörter.
- **Vor jedem Update** zusätzlich `make db-backup` (siehe [Update](#update)).
- **`./natsdata`** braucht kein Backup. Der Stream hält Zustellungen 30 Tage, die Fachdaten liegen
  in Postgres.

## Überwachung

- Healthchecks.io bleibt der Dead-Man's-Switch (`HEALTHCHECK_URL`). notification pingt bei
  geplanten Runs, bei einem Fehlschlag mit `/fail` ([events.md](events.md)).
- `db` und `nats` haben einen Healthcheck, die Services starten erst danach.
- Docker rotiert die Logs.
- Tracing: siehe Störungen. Ein Grafana-Stack (etwa `grafana/otel-lgtm`) wäre mit einem
  OTLP-Exporter möglich, ist aber nicht vorgesehen.
