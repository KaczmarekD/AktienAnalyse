# Bankanbindung: nur lesender Zugang über einen generischen Port

> **Status:** Spezifikation, Entwurf vom 04.11.2026. Teil der
> [Depot-Spezifikation](README.md), Stufen D8 (Port, Dienst, Datei-Adapter) und D9 (DKB).
> Grundsatzentscheidung: [ADR-0014](../../adr/0014-bankanbindung-nur-lesend-ueber-ports.md)
> (vorgeschlagen). Recherche:
> [DKB-Zugangswege](../../research/2026-11-depot-datenquellen-und-bankzugang.md#dkb-zugangswege).

## Ziel

Bestände eines Depots sollen direkt von der Bank kommen, nicht von Hand. Der Zugang ist
**ausschließlich lesend**. Ein generischer Port beschreibt, was das System von einer Quelle
braucht. Je Schnittstelle gibt es einen Adapter, der die konkrete API abbildet. Zuerst kommt die
DKB.

## Anforderungen

| ID | Prio | Anforderung |
|---|---|---|
| BANK-01 | Muss | Ein Port `DepotSource` für alle Quellen von Depotbeständen. Er hat **keine** schreibenden Operationen: keine Aufträge, keine Überweisungen, keine Änderung von Daten bei der Bank. |
| BANK-02 | Muss | Jeder Adapter meldet seine Fähigkeiten (Bestand, Einstand, Kasse, Umsätze) und seine Anmeldeart (keine, PIN mit TAN, …). UI und portfolio richten sich danach. |
| BANK-03 | Muss | Alle Adapter liefern dasselbe normierte Ergebnis (`HoldingsStatementV1`). portfolio kennt keine Bank. |
| BANK-04 | Muss | PIN und TAN werden **nie gespeichert**: nicht in der Datenbank, nicht im Stream, nicht in Logs oder Traces. Sie leben nur im Speicher des Abrufs. |
| BANK-05 | Muss | Der FinTS-Adapter schickt nur Geschäftsvorfälle aus einer festen Erlaubnisliste. Jeder andere Vorfall bricht vor dem Senden ab. |
| BANK-06 | Muss | Ein Abruf startet nur durch den Nutzer im UI. Die DKB verlangt bei jedem Abruf eine Freigabe in der App, ein Abruf im Wochenlauf ist nicht möglich. |
| BANK-07 | Muss | Der Abruf zeigt seinen Fortschritt live: verbinden, Freigabe in der App nötig, TAN eingeben, abrufen, fertig, Fehler. Nach 5 Minuten ohne Freigabe bricht er ab. |
| BANK-08 | Muss | Eine Bankverbindung gehört einem Nutzer. Sie lässt sich mit einem oder mehreren seiner Depots verknüpfen (je Depotkonto ein Depot). |
| BANK-09 | Muss | Datei-Adapter ohne Anmeldung für fremde Formate, zuerst der CSV-Export von Portfolio Performance. Das eigene CSV-Format gehört zu portfolio (DEP-05). |
| BANK-10 | Muss | DKB über FinTS 3.0: Depotkonten (HKSPA), Bestand (HKWPD), Kasse des Verrechnungskontos (HKSAL). Einstand je Posten aus MT535 mit eigenem Parser. |
| BANK-11 | Soll | Depotumsätze (HKWDU), wenn die Bank sie in ihren Parametern anbietet. Sie sind kein Teil der ersten Stufe, siehe DEP-12. |
| BANK-12 | Soll | Weitere Banken mit FinTS über denselben Adapter mit eigenem Bankprofil (Adresse, BLZ, TAN-Verfahren, Eigenheiten). |
| BANK-13 | Kann | Weitere Schnittstellen über neue Adapter, z. B. Depotauszug als PDF. Jede neue Quelle braucht eine Prüfung von Nutzungsbedingungen und Wartungsrisiko. |
| BANK-14 | Muss | Keine automatische Wiederholung bei Anmeldung und PIN. Das ist eine bewusste Ausnahme von „Jeder externe Call hat Retry+Fallback“ (CLAUDE.md): Wiederholte Fehlversuche sperren den Zugang bei der Bank. Je Verbindung läuft höchstens ein Abruf, ein zweiter ergibt 409. |

## Ausgeschlossen

Begründung in der [Recherche](../../research/2026-11-depot-datenquellen-und-bankzugang.md#dkb-zugangswege):

- **Scraping der Banking-Seite** (z. B. dkb-robo): Die DKB schützt den Login seit 11/2025 mit
  Captcha und Bot-Erkennung. Ein Adapter müsste das umgehen.
- **PSD2/XS2A:** deckt keine Depots ab und verlangt eine BaFin-Erlaubnis.
- **Aggregatoren** (finAPI u. a.): ab 60–200 EUR im Monat, die Freigabe je Abruf bleibt.

## Der Port

Der Port liegt in `va_depot_gateway.application.ports`, die Adapter unter `adapters/`, wie bei
market-data.

```python
class DepotSource(Protocol):
    """Liest Depotbestände aus einer Quelle. Hat bewusst keine schreibenden Methoden."""

    info: SourceInfo  # id ("dkb-fints", "file-csv", ...), Name, Fähigkeiten, Anmeldeart

    def start(self, request: SyncRequest) -> SyncStep: ...
    def resume(self, sync: SyncHandle, answer: ChallengeAnswer | None) -> SyncStep: ...
    def cancel(self, sync: SyncHandle) -> None: ...


SyncStep = Challenge | HoldingsResult | SyncFailed
```

- `SyncRequest`: Verbindung (Anmeldename, gespeicherter Zustand), PIN nur bei Bedarf, bei
  Datei-Adaptern der Inhalt.
- `Challenge`: Art (`decoupled` „in der App freigeben“, `tan` mit Text oder Bild für chipTAN QR),
  Hinweistext der Bank, Frist.
- `HoldingsResult`: die Konten mit ihren Beständen (`HoldingsStatementV1`) und der neue Zustand
  der Verbindung (bei FinTS System-ID, Bankparameter, TAN-Verfahren).
- `SyncFailed`: Grund (`auth`, `sca_timeout`, `unsupported`, `bank_error`, `parse_error`), Text
  ohne Geheimnisse.

Der Ablauf ist eine kleine Zustandsmaschine. Ein Datei-Adapter liefert beim ersten Schritt sofort
`HoldingsResult`. Der FinTS-Adapter liefert erst eine `Challenge` und nach der Freigabe das
Ergebnis.

```
gestartet → verbinden → Freigabe nötig ⇄ (warten auf App / TAN) → abrufen → fertig
                └────────────┴───────────────────────────────────────┴──→ fehlgeschlagen
```

## Normiertes Ergebnis

`HoldingsStatementV1` in `va-contracts`:

| Feld | Inhalt |
|---|---|
| `source` | Adapter-ID, z. B. `dkb-fints` |
| `account_ref` | Depotnummer, im UI und in Logs nur maskiert (`…4711`) |
| `as_of` | Stand laut Bank |
| `holdings[]` | isin, wkn, name, quantity (Decimal), unit (`pieces`/`nominal`), price, price_currency, price_date, market_value, market_value_currency, cost_basis (optional), lots[] (optional: Kaufdatum, Kaufkurs, Menge) |
| `cash[]` | Konto (maskiert), currency, amount |
| `warnings[]` | z. B. „Einstand für 2 Posten nicht lesbar“ |

## Ablauf eines Abrufs

```
UI ─ POST /api/v1/bank/connections/{id}/syncs {pin} ─► web-api (Besitz prüfen, Rate-Limit)
web-api ─ rpc.va.bank.sync.start {sync_id, user_id, connection_id, pin} ─► depot-gateway
depot-gateway: Zustand laden, Adapter starten (Hintergrund-Aufgabe), sofort antworten
depot-gateway ─ live.va.bank.sync.progressed {sync_id, state, challenge} ─► web-api ─WS bank-sync:<id>─► Browser
              „Bitte in der DKB-App freigeben“            (bei chipTAN: UI ─ POST …/syncs/{id}/tan ─► rpc.va.bank.sync.answer)
depot-gateway: Bestand abrufen, normieren, Zustand speichern, PIN verwerfen
depot-gateway ─ priv.va.bank.holdings.fetched {sync_id, user_id, connection_id, statements[]} ─► portfolio
portfolio: je verknüpftem Depot ein neuer Depotstand (Herkunft bank), Analyse
portfolio ─ va.portfolio.depot.changed ─► web-api ─WS─► Browser
```

- **Die PIN** geht nur über Request/Reply (Core-NATS, nicht gespeichert), nie über JetStream.
  NATS verlangt dafür eine Anmeldung je Dienst: Nur das web-api darf `rpc.va.bank.>` senden, nur
  depot-gateway darf es empfangen ([nutzer.md](nutzer.md#sicherheitsregeln), Regel 11).
- **Eine Instanz:** depot-gateway läuft genau einmal, ohne Queue-Gruppe. Offene Dialoge mit der
  Bank liegen in seinem Speicher, `answer`, `cancel` und `status` erreichen so immer den richtigen
  Dialog. Nach einem Neustart sind offene Abrufe verloren, der Nutzer startet neu.
- **Der Bestand** enthält Mengen und Werte. Er geht über den Stream `VA_PRIVATE` (nur im Speicher,
  24 h, Präfix `priv.va.`), nicht über `VA_EVENTS` mit 30 Tagen im Backup-Ordner
  ([README](README.md#events-im-überblick)).
- **Fortschritt** ist flüchtig (`live.va.`). Geht eine Meldung verloren, fragt das UI per REST
  nach (`GET /api/v1/bank/syncs/{id}`).
- **Fehlt portfolio** beim Abruf, verarbeitet es das Event später. Sein Consumer verwirft es erst
  nach 24 h, nicht schon nach `RUN_TIMEOUT_MINUTES` wie die Run-Kette
  ([README](README.md#änderungen-an-der-plattform)). Startet NATS neu, ist der Stream im Speicher
  leer, und der Nutzer wiederholt den Abruf.
- **Ohne Outbox:** depot-gateway veröffentlicht `holdings.fetched` direkt, nicht über
  `bank.outbox`. Sonst lägen die Bestände dauerhaft im Schema `bank`. Scheitert das Senden, ist
  der Abruf fehlgeschlagen, und der Nutzer wiederholt ihn.

## Nur lesen: wie es durchgesetzt wird

Die DKB bietet keinen lesenden Zugang an. Mit PIN und Freigabe ließen sich technisch auch Aufträge
erteilen. Deshalb setzt das System die Grenze selbst, in mehreren Schichten:

1. **Port:** `DepotSource` hat keine schreibende Methode. portfolio und web-api können nichts
   anderes anfordern.
2. **Erlaubnisliste im FinTS-Adapter:** Der Adapter umhüllt den Dialog von python-fints. Erlaubt
   sind nur Dialog- und Sicherheitsvorfälle (HKIDN, HKVVB, HKSYN, HKTAN, HKEND) und die lesenden
   Vorfälle HKSPA, HKWPD, HKSAL, später HKWDU. Jeder andere Vorfall wirft vor dem Senden.
3. **Import-Grenze:** Nur das Modul `va_depot_gateway.adapters.fints` darf `fints` importieren
   (import-linter, Vertrag „forbidden“).
4. **Tests:** Ein Test versucht die schreibenden Methoden von python-fints (z. B.
   `simple_sepa_transfer`) über den umhüllten Dialog und erwartet den Abbruch. Ein zweiter
   prüft, dass die Erlaubnisliste genau diese Vorfälle enthält.
5. **Keine gespeicherte PIN:** Ohne PIN kann niemand nachträglich einen Dialog öffnen.
6. **Bankseite:** Jeder Auftrag bräuchte eine eigene Freigabe in der DKB-App mit seinen Details.

## DKB

| Punkt | Wert |
|---|---|
| Schnittstelle | FinTS 3.0 PIN/TAN, `https://fints.dkb.de/fints`, BLZ 120 300 00 |
| Anmeldung | Anmeldename als Benutzerkennung, Kunden-ID leer, PIN je Abruf |
| Freigabe | DKB-App (entkoppelt, Verfahren 940) oder chipTAN manuell/QR; bei jedem Abruf |
| Bibliothek | python-fints 5.x (LGPL-3.0), Bestand über `get_holdings`, MT535 mit eigenem Parser für den Einstand |
| Produktnummer | eigene, kostenlose FinTS-Produktregistrierung als „Privatanwender-Software“, 10–15 Arbeitstage. Als `DEPOT_GATEWAY_FINTS_PRODUCT_ID` in der `.env`. Keine fremde Nummer nutzen. |
| Risiko | Umzug der Wertpapierabwicklung zu Upvest (Neukunden 2026, Bestandskunden 2027). Danach den Adapter erneut prüfen. Datei-Adapter bleiben als Rückfallweg. |

**Erster Schritt von D9 ist ein Spike** mit dem Konto des Users: Bankparameter auf HIWPDS und
HIWDUS prüfen, eine MT535-Antwort anonymisiert als Testdaten sichern. Dafür muss der User am
Gerät sein (PIN, Freigabe).

## Dienst `depot-gateway`

- Eigener Service mit eigenem Container, Schema `bank` und Rolle `va_bank`. Er liest keine
  anderen Schemas. Er läuft **nicht** im Worker-Prozess (`python -m src.worker`): Der nutzt die
  Rolle `va_app`, und Bankcode und PIN lägen im Prozess der anderen Dienste.
- Warum nicht in portfolio: Bankbibliothek und Zugangsdaten sind vom Rest getrennt. Ein Fehler
  oder eine Lücke im Bankcode erreicht die Depots aller Nutzer nicht. Ein Wechsel der Bank betrifft
  nur diesen Dienst, so wie ein Wechsel des Datenanbieters nur market-data betrifft.
- Gespeichert wird nur, was ohne PIN nutzlos ist: Verbindung, Anmeldename, Zustand von
  python-fints. Der Zustand wird verschlüsselt (Fernet, Schlüssel als Docker-Secret
  `DEPOT_GATEWAY_STATE_KEY`), sofern `cryptography` die J4125-Prüfung besteht.

### Datenmodell (Schema `bank`)

| Tabelle | Inhalt | Schreibweise |
|---|---|---|
| `connection` | id, owner_user_id, source (`dkb-fints`, …), login_name, created_at | anfügen |
| `connection_version` | connection_id, label, created_at | anfügen, gültig ist die jüngste Zeile |
| `connection_status` | connection_id, status (`active`/`ended`), at | anfügen |
| `connection_state` | connection_id, state (verschlüsselt), key_id, created_at | anfügen, gültig ist die jüngste Zeile |
| `account` | id, connection_id, account_key (HMAC-SHA256 der Konto- bzw. Depotnummer), masked (`…4711`), kind (`depot`/`cash`), first_seen_at | anfügen, eindeutig (connection_id, account_key) |
| `sync_run` | id, connection_id, user_id, started_at | anfügen |
| `sync_event` | sync_id, state, reason, detail (ohne Geheimnisse), at | anfügen |
| `outbox`, `inbox` | wie in den anderen Schemas | wie dort |

Die Verknüpfung von Depotkonto und Depot liegt in portfolio (`portfolio.depot_link`: depot_id,
connection_id, account_id, at; anfügen). Die maskierte Nummer ist dafür kein Schlüssel, sie kann
bei zwei Konten gleich enden.

## API

| Methode und Pfad | Zweck |
|---|---|
| `GET /api/v1/bank/sources` | verfügbare Adapter mit Fähigkeiten und Anmeldeart |
| `GET /api/v1/bank/connections`, `POST …` | eigene Verbindungen, neue anlegen (Depotquelle, Anmeldename, Name) |
| `PUT /api/v1/bank/connections/{id}`, `POST …/{id}/end` | umbenennen, beenden |
| `POST /api/v1/bank/connections/{id}/syncs` | Abruf starten, Body `{"pin"}`, Antwort 202 mit `sync_id` |
| `GET /api/v1/bank/syncs/{id}` | Stand des Abrufs, ggf. mit Challenge |
| `POST /api/v1/bank/syncs/{id}/tan`, `…/cancel` | TAN senden, abbrechen |
| `GET /api/v1/bank/connections/{id}/accounts` | Konten der Verbindung aus `bank.account` (maskiert) |
| `PUT /api/v1/depots/{id}/bank-link` | Depot mit einem Depotkonto (`account_id`) verknüpfen oder lösen |
| `POST /api/v1/depots/{id}/import/preview` mit `{"source": "file-portfolio-performance", …}` | Datei über einen Datei-Adapter lesen |

Die PIN steht nur im Body von `…/syncs`. Das Rate-Limit erlaubt 3 Abrufe je Verbindung und
Stunde. Zu viele falsche PINs sperren den Zugang bei der Bank.

## Oberfläche

- **Einstellungen → Bankverbindungen:** Verbindungen anlegen, Depotkonten den Depots zuordnen.
- **Depot → „Bestand von der Bank abrufen“:** Dialog mit PIN-Feld (`autocomplete="off"`), danach
  Live-Status: „Bitte in der DKB-App freigeben“ mit Countdown, bei chipTAN Bild oder Text und
  TAN-Feld. Am Ende der Abgleich zum vorherigen Depotstand.
- Das UI zeigt bei jeder Verbindung: „Nur lesender Zugriff. Dieses System kann keine Aufträge
  erteilen.“

## Tests und Abnahme

- Port: ein Fake-Adapter mit Challenge, Antwort, Timeout und Fehler treibt die Zustandsmaschine
  durch.
- Datei-Adapter: Fixtures für eigenes CSV und Portfolio-Performance-CSV, mit Umlauten,
  Dezimalkomma, unbekannter ISIN, leerer Datei.
- FinTS: MT535-Parser gegen anonymisierte Antworten aus dem Spike (mit und ohne Einstand,
  Bruchstücke, Anleihe mit Nennwert). Erlaubnisliste und Import-Grenze wie oben.
- Kein Live-Test gegen die DKB in der CI. Der Adapter läuft in Tests gegen einen nachgebildeten
  Dialog, wie die Zusatzdaten von Yahoo gegen `_SwallowingTicker`.
- Geheimnisse: Ein Abruf mit PIN hinterlässt die PIN weder in Logs noch in Traces, Stream,
  Datenbank oder Fehlermeldung (Test durchsucht alle Ausgaben nach der PIN).
- `/security-review` ist Pflicht (D8 und D9 mit 🔒).
