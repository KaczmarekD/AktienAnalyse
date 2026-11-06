# Berichte mit eigenem Intervall

> **Status:** Spezifikation, Entwurf vom 04.11.2026. Teil der
> [Depot-Spezifikation](README.md), Stufe D7.

## Ausgangslage

Heute gibt es genau einen Bericht: die Samstags-Mail mit Top und Flop von DAX/MDAX an `MAIL_TO`,
ausgelöst vom Scheduler im web-api ([events.md](../events.md#scheduler-und-watchdog-im-web-api)).
Neu ist der **Depotbericht**: je Nutzer und Depot, mit eigenem Intervall und wählbarem Inhalt.

Die Samstags-Mail heißt in dieser Spezifikation **Marktbericht**. Sie bleibt unverändert, ihr
Golden-Master auch. Depotberichte nutzen eigene Events und Tabellen, damit Run-Verwaltung,
Projektionen und `RunTracker` von ihnen nichts merken.

## Anforderungen

| ID | Prio | Anforderung |
|---|---|---|
| BER-01 | Muss | Ein Nutzer legt Berichts-Abos an: für ein Depot oder für alle eigenen Depots zusammen. Mehrere Abos je Nutzer sind erlaubt. |
| BER-02 | Muss | Intervall frei wählbar: täglich (Handelstage Mo–Fr), wöchentlich (Wochentag), alle N Tage (1–90), monatlich (Tag 1–28 oder „letzter Handelstag“), quartalsweise. Dazu Uhrzeit und Zeitzone (Standard `Europe/Berlin`). |
| BER-03 | Muss | Inhalt aus Bausteinen wählbar (siehe unten). |
| BER-04 | Muss | Der Berichtszeitraum beginnt beim letzten verschickten Bericht dieses Abos, nicht beim rechnerischen Intervall. Fällt ein Bericht aus, fehlt im nächsten nichts. Höchstens 92 Tage zurück. |
| BER-05 | Muss | Jeder fällige Termin ergibt höchstens einen Bericht, auch wenn der Scheduler doppelt feuert (eindeutiger Schlüssel aus Abo und Termin, wie `web.run_request.slot`). |
| BER-06 | Muss | Empfänger ist die Mail-Adresse des Nutzerkontos: vom Admin hinterlegt oder vom Nutzer bestätigt ([nutzer.md](nutzer.md), NUT-10). Sie reist im Event zu notification. |
| BER-07 | Muss | Vorschau im UI und „Jetzt senden“ zum Testen. |
| BER-08 | Muss | Archiv: Der Nutzer sieht seine verschickten Berichte im UI. |
| BER-09 | Muss | Abo pausieren und wieder aufnehmen, ändern, beenden (beendet heißt inaktiv, nicht gelöscht). |
| BER-10 | Soll | Sofortmeldung: bei neuem kritischem Hinweis oder neuer Ad-hoc-Mitteilung zu einer Position, höchstens eine Mail je Depot und Tag. Je Abo ein- und ausschaltbar. |
| BER-11 | Soll | CSV der Positionen als Anhang (Format wie die Report-CSV: BOM, `;`, Dezimalkomma). |
| BER-12 | Kann | Marktbericht als Abo für jeden Nutzer, statt fest an `MAIL_TO`. |
| BER-13 | Kann | Weitere Kanäle über den Port `ReportSender`, z. B. Telegram (steht schon unter „Danach“ in der Roadmap). |

## Bausteine

| Baustein | Inhalt | Quelle |
|---|---|---|
| Überblick | Depotwert, Allokation, Einstand und Differenz (DEP-13), dazu der Wert des heutigen Bestands zu Beginn des Zeitraums (reiner Kurseffekt, keine Rendite; [Frage 6](README.md#offene-fragen), entschieden am 06.11.2026) | Analyse |
| Hinweise | neu, weiterhin bestehend (nur Warnung und Kritisch), erledigt | Analyse |
| Scores | Positionen, deren Composite-Perzentil sich um mindestens 10 Prozentpunkte geändert hat; Value-Trap-Flags | Einordnung |
| News | Schlagzeilen seit dem letzten Bericht je Position, Pflichtmitteilungen zuerst | [news.md](news.md) |
| Fälligkeiten | Anleihen und Kupons in den nächsten 90 Tagen | Analyse |
| Markt | Top und Flop des Referenzuniversums (wie im Marktbericht, gekürzt) | Ranking |

Jeder Bericht trägt im Footer Datenstand, Profil-Version und den Disclaimer, wie die Samstags-Mail.

## Ablauf

```
web-api Scheduler (Takt 60 s): fällige Abos ermitteln, je Termin einen Slot anlegen
web-api ─ priv.va.digest.run.requested {subscription_id, slot, user_id, depot_ids, period, modules, recipient} ─► portfolio
portfolio: Analyse auf aktuellen Stand bringen, Berichtsdaten zusammenstellen
portfolio ─ priv.va.portfolio.digest.prepared {… Berichtsdaten …} ─────────► notification
notification: rendern (Jinja-Template), in Schema digest speichern, an den Empfänger senden
notification ─ va.notification.digest.sent {digest_id, subscription_id, slot} ─► web-api ─WS user:<id>─► Browser
```

**Sofortmeldung (BER-10):** portfolio meldet bei einem neuen kritischen Hinweis oder einer neuen
Ad-hoc-Mitteilung `va.portfolio.alert.raised` (depot_id, Anzahl, ohne Inhalte). Das web-api prüft,
ob ein Abo dieses Depots Sofortmeldungen will und ob heute schon eine kam. Dann legt es einen Slot
der Art `alert` an (Schlüssel: Abo und Tag) und startet dieselbe Kette mit den Bausteinen Hinweise
und News.

Der Ablauf folgt der Choreografie der Runs ([events.md](../events.md#grundprinzipien)):

- Der Scheduler bleibt an einer Stelle, im web-api.
- portfolio stellt die Daten zusammen, weil ihm die Depots gehören.
- notification rendert und versendet, wie heute. `ReportSender` bekommt dafür den Empfänger als
  Parameter, statt fest an `MAIL_TO` zu senden (Rezept „Neue Mail-Empfänger“ in CLAUDE.md).

**Persönliche Daten unterwegs:** Berichtsdaten und Mail-Adresse reisen in den beiden
`priv.va.`-Events. Sie laufen über den Stream `VA_PRIVATE` (nur im Speicher, 24 h), nicht über
`VA_EVENTS` (30 Tage, im Backup). In den Outboxen liegen sie dauerhaft, aber nur in persönlichen
Schemas, die dieselben Daten ohnehin halten: `identity.outbox` und `portfolio.outbox`
([README](README.md#events-im-überblick)).

**Fehler:** Scheitert eine Stufe, kommt `va.digest.run.failed` (Slot, Stufe, Grund). Der Slot
bleibt offen und wird im nächsten Takt neu versucht, höchstens dreimal. Danach bekommt der Nutzer
im UI einen Hinweis, der Admin eine Fehlermail wie bei einem gescheiterten Run. Die Empfänger
dieser Kette dürfen Events nicht schon nach `RUN_TIMEOUT_MINUTES` verwerfen, sondern erst nach
24 h (Höchstalter je Event-Art, [README](README.md#änderungen-an-der-plattform)).

**Datenstand:** Fundamentaldaten kommen wöchentlich, Kurse an jedem Handelstag
([wertpapiere.md](wertpapiere.md#abdeckung-und-abrufe)). Ein täglicher Bericht zeigt also täglich
neue Kurse und News, aber nur wöchentlich neue Scores. Der Bericht nennt das.

## Datenmodell

Alles nur zum Anfügen, keine neue Ausnahme für `UPDATE`.

| Tabelle | Schema (Besitzer) | Inhalt |
|---|---|---|
| `report_subscription` | `identity` (web-api) | id, user_id, created_at |
| `report_subscription_version` | `identity` | subscription_id, depot_ids, schedule (JSONB: Art, Tag, N, Uhrzeit, Zeitzone), modules, alerts (bool), status (`active`/`paused`/`ended`), created_at; gültig ist die jüngste Zeile |
| `report_slot` | `identity` | id, subscription_id, kind (`scheduled`/`alert`/`manual`), due_at; eindeutig (subscription_id, kind, due_at) |
| `report_slot_event` | `identity` | slot_id, state (`requested`/`sent`/`failed`), stage, attempt, at; gültig ist die jüngste Zeile |
| `digest` | `digest` (notification, neu) | id, user_id, subscription_id, slot_id, period_from, period_to, subject, html, csv, created_at |
| `digest_delivery` | `digest` | digest_id, channel, recipient, ok, error, at |

Die Abos liegen in `identity` und nicht in `web`, die Depotberichte im neuen Schema `digest` und
nicht in `reporting`. `web` und `reporting` stehen in `SCHEMAS` und vergeben jede neue Tabelle
automatisch an `va_read`. Die persönlichen Schemas tun das nicht
([nutzer.md](nutzer.md#persönliche-schemas-und-va_read)). `reporting.report` und
`reporting.delivery` bleiben für den Marktbericht unverändert.

## Events

| Subject | Sender → Empfänger | Inhalt |
|---|---|---|
| `priv.va.digest.run.requested` | web-api → portfolio | subscription_id, slot_id, kind, user_id, depot_ids, period_from, period_to, modules, recipient |
| `priv.va.portfolio.digest.prepared` | portfolio → notification | wie oben plus Berichtsdaten je Baustein |
| `va.notification.digest.sent` | notification → web-api | digest_id, subscription_id, slot_id (neues Event `DigestSentV1`) |
| `va.digest.run.failed` | jede Stufe → web-api | subscription_id, slot_id, stage, reason |
| `va.portfolio.alert.raised` | portfolio → web-api | depot_id, Anzahl neuer kritischer Hinweise und Ad-hoc-Mitteilungen |

`va.notification.report.sent` bleibt dem Marktbericht vorbehalten. Sein `run_id` ist Pflicht,
und das web-api schließt damit Runs ab.

## API

| Methode und Pfad | Zweck |
|---|---|
| `GET /api/v1/report-subscriptions` | eigene Abos |
| `POST /api/v1/report-subscriptions` | anlegen |
| `PUT /api/v1/report-subscriptions/{id}` | ändern (neue Version) |
| `POST /api/v1/report-subscriptions/{id}/pause`, `…/resume`, `…/end` | Status |
| `POST /api/v1/report-subscriptions/{id}/preview` | Bericht rendern, nicht senden |
| `POST /api/v1/report-subscriptions/{id}/send-now` | sofort senden (höchstens einmal pro Minute) |
| `GET /api/v1/digests`, `GET /api/v1/digests/{id}` | Archiv |

## Tests und Abnahme

- Termine: jede Intervall-Art über Monatsenden, Schaltjahr, Zeitumstellung (`Europe/Berlin`),
  „letzter Handelstag“ am Wochenende, „alle N Tage“ über einen Jahreswechsel.
- Idempotenz: doppelter Takt ergibt einen Bericht; Ausfall eines Termins verlängert den
  Zeitraum des nächsten; höchstens eine Sofortmeldung je Depot und Tag.
- Golden-Master des Depotberichts: eingefrorenes Beispieldepot, fester Zeitpunkt, byte-gleiches
  HTML, wie beim Marktbericht.
- Der Golden-Master des Marktberichts bleibt unverändert. Ein Depotbericht berührt weder
  `batch.run` noch die Run-Projektionen.
- Ein Event der Kette, das 3 h alt ist (NAS-Neustart), wird noch verarbeitet.
- Datentrennung: Abo und Archiv eines anderen Nutzers ergeben 404.
- E2E: Abo mit „Jetzt senden“, die Mail kommt in Mailpit an die Adresse des Testnutzers.
