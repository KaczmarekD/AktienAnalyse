# Depots, mehrere Nutzer und Bankanbindung – Spezifikation

> **Status:** Spezifikation vom 04.11.2026, zum Fortschreiben. Die Grundsatzentscheidungen hat
> der User am 06.11.2026 angenommen:
> [ADR-0012](../../adr/0012-mehrbenutzer-mit-lokalen-konten.md) (Login),
> [ADR-0013](../../adr/0013-depots-im-service-portfolio.md) (Depots und Bewertung),
> [ADR-0014](../../adr/0014-bankanbindung-nur-lesend-ueber-ports.md) (Bankanbindung).
> Dazu die Fragen 1, 2, 3 und 6 ([Offene Fragen](#offene-fragen)). Umgesetzt ist noch nichts.
> Grundlage ist der Stand nach Phase 5 ([Roadmap](../roadmap.md)). Quellen:
> [Recherche 11/2026](../../research/2026-11-depot-datenquellen-und-bankzugang.md).

## Ziel

Wunsch des Users vom 04.11.2026:

- Das UI bedient **mehrere Nutzer**. Jeder legt eigene **Depots** an.
- Die bisherigen Analysen, die auf DAX/MDAX laufen, laufen auch **auf das Depot**.
- Ins Depot kommen **beliebige Aktien, ETFs und Anleihen**. Dazu gibt es ihre **Analyse** und
  **News**.
- Ein **zusammengefasster Bericht** kommt in einem **frei einstellbaren Intervall**.
- **Hinweise** zeigen, wo sich das Depot verbessern ließe.
- Später kommt der Bestand über eine **Depot-API**: generisch über Ports, je Schnittstelle ein
  Adapter, **nur mit Leserechten**. Zuerst die **DKB**.

## Leitgedanken

1. **Die bestehende Architektur weiterführen:** Choreografie über Events, Ports und Adapter,
   Contracts nur additiv, nichts löschen, lieber einen Titel verlieren als den ganzen Lauf.
2. **Der Screener bleibt ein Screener.** Er ordnet ein und gibt Hinweise mit Messwert und
   Begründung. Er empfiehlt keine Käufe oder Verkäufe und erteilt keine Aufträge.
3. **Bei der Bank wird nur gelesen**, durchgesetzt in mehreren Schichten.
4. **Persönliche Daten bleiben getrennt:** eigene Schemas ohne Rechte für `va_read`, keine
   Inhalte in Logs oder im 30-Tage-Stream. market-data kennt keine Nutzer.
5. **Der Marktbericht bleibt unverändert.** Nach jeder Stufe läuft die Samstags-Mail wie bisher,
   Golden-Master und Replay-Fixtures bleiben grün.
6. **Die Grenzen des J4125 gelten** ([ADR-0008](../../adr/0008-zielhardware-j4125.md)). Neue
   Pakete (argon2-cffi, cryptography, fints) laufen durch `make check-j4125`.

## Begriffe

| Begriff | Bedeutung |
|---|---|
| Depot | Positionen eines Nutzers, Basiswährung EUR. Eine Beobachtungsliste ist ein Depot ohne Mengen. |
| Depotstand | vollständiger, unveränderlicher Bestand eines Depots zu einem Zeitpunkt |
| Wertpapier | über die ISIN eindeutig, mit Anlageklasse (Aktie, ETF, Anleihe, Sonstiges) |
| Listing | Handel eines Wertpapiers an einer Börse, mit Symbol. Das heutige `market_data.instrument`. |
| Abdeckung | Wertpapiere, für die market-data Daten holt: Referenzuniversum plus alle Depots |
| Referenzuniversum | Vergleichsgruppe für die Perzentilränge, heute DAX/MDAX |
| Einordnung | Score einer Aktie außerhalb des Referenzuniversums, gemessen an diesem |
| Hinweis | regelbasierte Beobachtung am Depot mit Messwert, Schwelle, Begründung, Ansatzpunkt |
| Abo | Berichts-Abo eines Nutzers mit Intervall und Bausteinen |
| Depotquelle | Adapter hinter dem Port `DepotSource`: Datei oder Bank |

## Anwendungsfälle

| ID | Wer | Was | Spezifikation |
|---|---|---|---|
| UC-01 | Admin | Nutzer anlegen, deaktivieren | [nutzer.md](nutzer.md) |
| UC-02 | Nutzer | Anmelden und nur die eigenen Daten sehen | [nutzer.md](nutzer.md) |
| UC-03 | Nutzer | Depot anlegen, Aktien, ETFs und Anleihen erfassen | [depots.md](depots.md), [wertpapiere.md](wertpapiere.md) |
| UC-04 | Nutzer | Bestand aus einer Datei übernehmen | [depots.md](depots.md), [bankanbindung.md](bankanbindung.md) |
| UC-05 | Nutzer | Die eigenen Aktien so bewertet sehen wie im DAX/MDAX-Ranking | [analyse.md](analyse.md) |
| UC-06 | Nutzer | Allokation, Konzentration, Kosten und Anleihen des Depots sehen | [analyse.md](analyse.md) |
| UC-07 | Nutzer | Hinweise bekommen, wo sich das Depot verbessern ließe | [analyse.md](analyse.md#hinweise) |
| UC-08 | Nutzer | News zu den eigenen Wertpapieren lesen | [news.md](news.md) |
| UC-09 | Nutzer | Einen Bericht im selbst gewählten Intervall bekommen | [berichte.md](berichte.md) |
| UC-10 | Nutzer | Den Bestand von der DKB abrufen, nur lesend | [bankanbindung.md](bankanbindung.md) |

## Nicht-Ziele

- **Aufträge, Überweisungen** oder andere schreibende Zugriffe auf ein Bankkonto.
- **Anlageberatung:** keine Kauf- oder Verkaufsempfehlung, kein Kursziel. Hinweise sind
  Beobachtungen (siehe Disclaimer in [CLAUDE.md](../../../CLAUDE.md#disclaimer)).
- **Renditeberechnung, Performance-Vergleich, Backtesting.** Das bleibt draußen wie bisher.
  Einstand und Differenz zum Wert werden nur angezeigt (Frage 6, entschieden am 06.11.2026).
- **Steuern** (Abgeltungsteuer, Verlustverrechnung).
- **Echtzeit- oder Intraday-Kurse.** Schlusskurse der Handelstage genügen.
- **Automatischer Bankabruf im Zeitplan.** Die DKB verlangt bei jedem Abruf eine Freigabe.
- **Zugriff aus dem Internet ohne VPN.**
- **Sektor-relatives Ranking** bleibt draußen wie bisher.

## Zielbild

```
Browser (LAN oder VPN) ── https://<nas> ──► frontend (nginx · Angular-Build)
                                              │ /api/* · /ws
┌─────────────────────────────────────────────▼──────────────────────────────────┐
│ web-api (BFF): Login und Sitzungen · REST /api/v1 · WebSocket (Topics je Nutzer)│
│ Eventmanager · Scheduler: Runs, Tageskurse, News, Berichte · Watchdog           │
└───────┬───────────────────────────────────────────────────────────────▲────────┘
        │ Befehle, Request/Reply                                 Events │
══ NATS: VA_EVENTS (va.>, 30 Tage) · VA_PRIVATE (priv.va.>, 24 h) · rpc.va.> · live.va.> ══
   ▲▼             ▲▼             ▲▼               ▲▼               ▲▼
┌────────────┐ ┌────────────┐ ┌────────────────┐ ┌──────────────┐ ┌──────────────────┐
│market-data │ │ scoring    │ │ portfolio  NEU │ │ notification │ │ depot-gateway NEU│
│+Wertpapiere│ │+Einordnung │ │ Depots, Stände │ │+Depotbericht │ │ Port DepotSource │
│+Tageskurse │ │  (place)   │ │ Analyse        │ │              │ │ Dateien · DKB    │
│+News       │ │            │ │ Hinweise       │ │              │ │ (nur lesen)      │
└────────────┘ └────────────┘ └────────────────┘ └──────────────┘ └──────────────────┘
      ▼              ▼                ▼                 ▼                  ▼
═ PostgreSQL 18: market_data · scoring · portfolio · reporting · bank · web · identity · batch ═
```

| Dienst | Neu oder geändert | Aufgabe |
|---|---|---|
| `web-api` | geändert | Login, Sitzungen, Rollen (Schema `identity`), Topics je Nutzer, neue Routen, Scheduler für Tageskurse, News und Berichte, Berichts-Abos |
| `market-data` | geändert | Wertpapiere über die ISIN, Suche, Abdeckung, Tageskurse, ETF- und Anleihedaten, News. Bleibt der einzige Dienst für Marktdaten. |
| `scoring` | geändert | `place()`: Einordnung der Depot-Aktien ins Referenzuniversum, im selben Bewertungslauf |
| `notification` | geändert | Depotbericht rendern und versenden, Archiv |
| `portfolio` | neu | Depots, Depotstände, Zielallokation, Analyse, Hinweise, Berichtsdaten |
| `depot-gateway` | neu | Bestände von außen: Port `DepotSource`, Datei-Adapter, DKB über FinTS. Nur lesend. |

### Schemas und Rollen

| Schema | Besitzer | Rolle | `va_read` |
|---|---|---|---|
| `identity` (neu) | web-api | `va_identity` | keine Rechte |
| `portfolio` (neu) | portfolio | `va_portfolio` | keine Rechte |
| `bank` (neu) | depot-gateway | `va_bank` | keine Rechte |
| `digest` (neu) | notification | `va_notification` | keine Rechte |
| `reporting`, `web` | wie bisher | wie bisher | wie bisher, ohne persönliche Tabellen |
| `market_data`, `scoring` | wie bisher | wie bisher | wie bisher. Neu darin: Wertpapiere, News, Einordnungen. Sie verraten, welche Titel jemand hält, aber nicht wer. |

Die persönlichen Schemas stehen nicht in `SCHEMAS` von `va_platform.db.ddl`, sonst bekämen `va_read` und `va_app` jede neue Tabelle automatisch ([nutzer.md](nutzer.md#persönliche-schemas-und-va_read)). Alle neuen Tabellen bekommen den Löschschutz (`protect_table()`). Die einzige Ausnahme vom
Löschverbot ist das Admin-Kommando für die Daten einer Person
([nutzer.md](nutzer.md#personenbezogene-daten-und-das-löschverbot)).

## Events im Überblick

Neue Events und Änderungen an bestehenden. Die Contracts stehen in `va-contracts`, die
bestehenden ändern sich nur additiv.

| Subject | Sender → Empfänger | Zweck | Stufe |
|---|---|---|---|
| `va.portfolio.coverage.changed` | portfolio → market-data | Menge der abzudeckenden Wertpapiere, ohne Nutzer und Mengen | D3 |
| `va.marketdata.securities.updated` | market-data → portfolio | Stammdaten, ETF-Struktur, Anleihedaten | D2 |
| `va.marketdata.prices.requested` | web-api → market-data | Tageskurse anstoßen (Scheduler) | D2 |
| `va.marketdata.prices.completed` | market-data → portfolio | Schlusskurse und Währungskurse | D2 |
| `va.marketdata.snapshot.completed` | market-data → scoring | bestehend, neu `covered[]` | D2 |
| `va.scoring.run.completed` | scoring → notification, portfolio, web-api | bestehend, neu `placements[]` | D4 |
| `va.portfolio.depot.changed` | portfolio → web-api | Depot und Version, keine Inhalte | D3 |
| `va.portfolio.analysis.completed` | portfolio → web-api | Analyse fertig, Zahl der Hinweise | D4 |
| `va.marketdata.news.requested` | web-api → market-data | News-Abruf anstoßen (Scheduler) | D6 |
| `va.marketdata.news.collected` | market-data → portfolio | neue Meldungen mit Zuordnungen | D6 |
| `va.portfolio.news.matched` | portfolio → web-api | neue Meldungen zu einem Depot (nur Anzahl) | D6 |
| `va.marketdata.coverage.fetched` | market-data → scoring | Fundamentaldaten neu abgedeckter Aktien | D4 |
| `va.scoring.placements.updated` | scoring → portfolio | Einordnung gegen den letzten Bewertungslauf | D4 |
| `va.portfolio.alert.raised` | portfolio → web-api | Anlass für eine Sofortmeldung (nur Anzahl) | D7 |
| `priv.va.identity.email_confirmation.requested` | web-api → notification | Bestätigungsmail (NUT-10) | D1 |
| `priv.va.digest.run.requested` | web-api → portfolio | Bericht fällig, mit Empfänger | D7 |
| `priv.va.portfolio.digest.prepared` | portfolio → notification | Berichtsdaten | D7 |
| `va.digest.run.failed` | jede Stufe → web-api | Bericht gescheitert | D7 |
| `va.notification.digest.sent` | notification → web-api | Bericht versendet (neu; `report.sent` bleibt dem Marktbericht) | D7 |
| `priv.va.bank.holdings.fetched` | depot-gateway → portfolio | abgerufener Bestand | D8 |
| `live.va.bank.sync.progressed` | depot-gateway → web-api | Fortschritt und Freigabe-Aufforderung, flüchtig | D8 |

Request/Reply (Core-NATS, nicht gespeichert):

| Subject | Zweck | Stufe |
|---|---|---|
| `rpc.va.marketdata.securities.search`, `….resolve` | Suche, ISIN → Listing und Stammdaten | D2 |
| `rpc.va.portfolio.*` | Depots lesen und ändern, Analyse, Hinweise, News, Berichtsvorschau | D3–D7 |
| `rpc.va.bank.sync.start`, `….answer`, `….cancel`, `….status` | Bankabruf; nur hier steht die PIN | D8 |
| `rpc.va.bank.connections.*`, `rpc.va.bank.file.parse` | Verbindungen, Datei-Adapter | D8 |

**Streams:**

| Stream | Subjects | Aufbewahrung | Inhalt |
|---|---|---|---|
| `VA_EVENTS` | `va.>` | 30 Tage | wie heute, ohne Mengen, Beträge und Mail-Adressen |
| `VA_PRIVATE` (neu) | `priv.va.>` | 24 h, nur im Speicher (nicht in `natsdata`, also nicht im Backup) | Bankbestand, Berichtsdaten, Empfänger |

Das web-api abonniert `VA_PRIVATE` nicht. Nachspielen für WebSocket-Clients (`resumeFrom`) gibt es
nur aus `VA_EVENTS`. Die Provisionierung (`python -m va_platform.nats`) legt beide Streams an. Consumer von
`VA_PRIVATE`: portfolio (`digest.run.requested`, `bank.holdings.fetched`), notification
(`portfolio.digest.prepared`, `identity.email_confirmation.requested`).

### Änderungen an der Plattform

Was `va-platform` und `va-contracts` dafür brauchen:

- **Katalog:** Präfix `priv.va.` und ein Merkmal `private` in `EventSpec`. Heute kennt der Katalog
  nur `va.` und `live.va.`.
- **Publisher je Stream:** `JetStreamPublisher` verlangt heute die Bestätigung von `VA_EVENTS`.
- **Provisionierung** für zwei Streams und die neuen Consumer.
- **Höchstalter je Event-Art:** Der `ReliableBus` verwirft heute jedes Event, das älter als
  `RUN_TIMEOUT_MINUTES` (120 min) ist. Das passt zur Run-Kette. Abdeckung, Kurse, News,
  Bankbestand und Berichte brauchen 24 h, sonst gehen sie nach einem NAS-Neustart still verloren.
  Festhalten in [events.md](../events.md), absichern mit einem Test.
- **NATS-Nutzer je Dienst** mit Rechten nur auf die eigenen Subjects (ab D1,
  [nutzer.md](nutzer.md#sicherheitsregeln), Regel 11).
- **Grants** für die persönlichen Schemas außerhalb von `SCHEMAS`.

## Oberfläche

| Bereich | Inhalt | Wer |
|---|---|---|
| Anmelden | Login, Passwort ändern | alle |
| Meine Depots | Startseite: Kacheln mit Wert, Stand, Hinweisen | Nutzer |
| Depot | Übersicht, Positionen, Analyse, Hinweise, News, Verlauf, Einstellungen | Besitzer |
| Wertpapier | heutiges Titel-Detail, erweitert um ETF und Anleihe | alle |
| Markt | Ranking und Runs wie heute | alle (Runs starten: Admin) |
| Berichte | Abos, Vorschau, Archiv | Nutzer |
| Konto | Profil, Sitzungen, Bankverbindungen | Nutzer |
| Verwaltung | Nutzer, Scoring-Profile, Runs | Admin |

Gestaltet wird mit den Bausteinen des Designsystems im Frontend (Angular Material, Farben aus
`--mat-sys-*`).

## Stufenplan

Jede Stufe besteht aus Arbeitspaketen nach dem Zyklus Test → Implementierung → Grün → Review
([Implementierungsplan](../implementierungsplan.md#der-zyklus-test--implementierung--grün--review)).
Die Pakete schneidet die Stufe zu Beginn, als Entwurf im Implementierungsplan. 🔒 heißt
`/security-review` ist Pflicht.

| Stufe | Inhalt | Braucht | Fertig, wenn |
|---|---|---|---|
| D0 | Spezifikation abstimmen, ADR-0012 bis 0014 entscheiden, FinTS-Produktnummer beantragen | – | die ADRs angenommen oder angepasst sind |
| D1 🔒 | Login, Sitzungen, Rollen, HTTPS, WebSocket mit Sitzung, Admin-Kommando, Schema `identity`, NATS-Nutzer je Dienst | D0 | jeder Zugriff eine Anmeldung braucht und der E2E-Test mit Testnutzer grün ist |
| D2 | Wertpapiere über ISIN, Suche, Abdeckung, Tageskurse, ETF- und Anleihedaten. Bis portfolio die Abdeckung meldet (D3), füllen sie Tests und ein Kommando. | D0 | die Suche Aktie, ETF und Anleihe findet und der Wochenlauf mit `covered[]` dieselbe Mail liefert |
| D3 | Dienst portfolio, Depots, Erfassung, eigenes CSV, Verlauf, „Meine Depots“ | D1, D2 | ein Nutzer ein Depot anlegt, der Wert stimmt und fremde Depots unsichtbar sind |
| D4 | `place()`, `analyze()`, ETF- und Anleihe-Rechnungen, Ansicht Analyse | D3 | eine Aktie im Depot denselben Score zeigt wie im Ranking und die Golden-Master unverändert sind |
| D5 | Hinweise: Katalog, Schwellen je Depot, Lebenszyklus, Prüfkandidaten | D4 | jede Regel des Katalogs getestet und im UI sichtbar ist |
| D6 | News: Port, yfinance ≥ 1.8, GDELT, EQS-Postfach (Soll), Ansicht | D2, D3 | ein Depot die News seiner Positionen zeigt |
| D7 | Berichte: Abos, Termine, Depotbericht, Archiv, `VA_PRIVATE` | D4 (D5, D6 für ihre Bausteine) | ein Bericht im gewählten Intervall in Mailpit ankommt |
| D8 🔒 | depot-gateway, Port `DepotSource`, Datei-Adapter | D3 | ein Bestand aus einer Portfolio-Performance-CSV über den Port ins Depot kommt |
| D9 🔒 | DKB über FinTS: Spike, Adapter, Erlaubnisliste, MT535-Parser | D1 (HTTPS), D8, Produktnummer | ein Abruf mit Freigabe in der DKB-App einen Depotstand erzeugt |

Parallel möglich: D6 neben D4/D5, D8 neben D4. D9 ist bewusst zuletzt, entsprechend „später“ im
Wunsch. Die Produktnummer sollte trotzdem jetzt beantragt werden, sie braucht 2–3 Wochen.

## Was sich bei Annahme an bestehenden Regeln ändert

- [ADR-0007](../../adr/0007-lan-only-ohne-login.md) wird durch ADR-0012 ersetzt. Seine vier
  Schutzregeln bleiben.
- [ADR-0001](../../adr/0001-microservices-ueber-modularen-monolithen.md): zwei Dienste mehr,
  portfolio und depot-gateway. Die Zielarchitektur nennt market-data nicht mehr als „einzigen
  Service mit Zugriff auf externe Datenquellen“, sondern als einzigen für Marktdaten.
- [ADR-0003](../../adr/0003-postgresql-schema-pro-service.md): drei Schemas mehr, eine Ausnahme vom
  Löschverbot für die Daten einer Person.
- [events.md](../events.md): Präfix `priv.va.` und Stream `VA_PRIVATE`.
- [web-api-realtime.md](../web-api-realtime.md): Sicherheitsregeln 5 bis 9, Topics je Nutzer.
- CLAUDE.md: Ist-Stand je umgesetzter Stufe. Unter „Was NICHT in dieses Projekt gehört“ kommen
  Aufträge an die Bank dazu.
- yfinance von 1.7 auf ≥ 1.8 (News), mit `make check-j4125`.
- CLAUDE.md „Echtzeit… Wöchentlicher Batch reicht“: Tageskurse und News alle 4 h kommen dazu, Intraday bleibt draußen.
- portfolio und depot-gateway folgen dem Rezept „Neues Workspace-Mitglied“ (Images, CI, Rollen in `src.db.migrate`, import-linter).

## Offene Fragen

Jede Frage mit Empfehlung. Die Antworten fließen in die ADRs und hier in die Abschnitte ein.

| Nr. | Frage | Empfehlung |
|---|---|---|
| 1 | Login: lokale Konten oder SSO Server von DSM (OIDC)? | ✅ **Entschieden 06.11.2026:** lokale Konten, OIDC später als Adapter (ADR-0012) |
| 2 | HTTPS: über den Reverse-Proxy von DSM oder Zertifikat im `frontend`-Container? Mit eigener Domain (Let's Encrypt per DNS) oder eigener CA auf den Geräten? | ✅ **Entschieden 06.11.2026:** Reverse-Proxy von DSM. Offen bleibt das Zertifikat (eigene Domain oder eigene CA), spätestens mit D1.5. |
| 3 | Darf ein Admin-Kommando die Daten einer Person auf Wunsch endgültig löschen? | ✅ **Entschieden 06.11.2026:** ja, als einzige, protokollierte Ausnahme |
| 4 | Scoring-Profile global oder je Nutzer? | zunächst global, nur der Admin ändert |
| 5 | Referenzuniversum für Aktien außerhalb DAX/MDAX? | zunächst DAX/MDAX mit Hinweis HIN-Q06; STOXX Europe 600 als eigenes Paket, wenn viele europäische Titel gehalten werden |
| 6 | Einstand und Differenz zum aktuellen Wert anzeigen, und im Bericht den Wert zu Beginn des Zeitraums? | ✅ **Entschieden 06.11.2026:** ja, als reine Anzeige der erfassten oder gelieferten Werte; keine Renditeberechnung |
| 7 | Transaktionen statt nur Bestände (DEP-12)? | nein, nicht in den Stufen D1–D9 |
| 8 | Eigenes Postfach für die EQS-Alarme (Pflichtmitteilungen)? | ja, wenn ein Postfach verfügbar ist; sonst fehlen Ad-hoc-Mitteilungen weitgehend |
| 9 | Sofortmeldung bei kritischem Hinweis oder Ad-hoc (BER-10)? | ja, höchstens eine Mail je Depot und Tag |
| 10 | Marktbericht als Abo für alle Nutzer (BER-12)? | später; bis dahin bleibt `MAIL_TO` |
| 11 | Depots mit anderen Nutzern teilen (NUT-13)? | später |
| 12 | D8 (Datei-Import über den Port) vor D4 ziehen? | nur, wenn Depots mit vielen Positionen schnell befüllt werden sollen |
| 13 | Wer beantragt die FinTS-Produktnummer? | der User selbst, jetzt (kostenlos, 10–15 Arbeitstage) |

## Dokumente

| Dokument | Inhalt | Stufe |
|---|---|---|
| [nutzer.md](nutzer.md) | Anmeldung, Rollen, Sitzungen, Sicherheitsregeln, personenbezogene Daten | D1 |
| [wertpapiere.md](wertpapiere.md) | Aktien, ETFs, Anleihen über die ISIN, Quellen, Suche, Abdeckung, Tageskurse | D2 |
| [depots.md](depots.md) | Depots, Depotstände, Erfassung, Import, Verlauf | D3 |
| [analyse.md](analyse.md) | Einordnung ins Referenzuniversum, ETF, Anleihen, Depot-Analyse, Hinweise | D4, D5 |
| [news.md](news.md) | Quellen, Zuordnung, Speicherung, Ansicht | D6 |
| [berichte.md](berichte.md) | Abos mit Intervall, Bausteine, Ablauf | D7 |
| [bankanbindung.md](bankanbindung.md) | Port `DepotSource`, nur lesen, Datei-Adapter, DKB über FinTS | D8, D9 |

## Pflege dieser Spezifikation

- **IDs** (`NUT-`, `WP-`, `DEP-`, `ANA-`, `HIN-`, `NEWS-`, `BER-`, `BANK-`) werden nie neu vergeben.
  Eine gestrichene Anforderung bleibt mit „gestrichen am …“ stehen.
- **Prioritäten:** Muss (Stufe ist ohne nicht fertig), Soll (gehört in die Stufe, darf mit
  Begründung später kommen), Kann (Idee, eigene Entscheidung).
- **Grundsatzentscheidungen** kommen in ein ADR, nicht nur hierher.
- **Wenn eine Stufe umgesetzt ist**, bekommt der Abschnitt einen Vermerk „Umgesetzt (Datum,
  Commit)“ wie im Implementierungsplan, und die Abweichungen stehen dabei.
- **Änderungen** an dieser Spezifikation kurz unten eintragen.

## Änderungen

| Datum | Änderung |
|---|---|
| 04.11.2026 | Erster Entwurf mit Recherche zu DKB, News, ETF- und Anleihedaten |
| 06.11.2026 | User nimmt ADR-0012 bis ADR-0014 an und entscheidet die Fragen 1, 2, 3 und 6 (lokale Konten, HTTPS über DSM, Löschkommando, Einstand als Anzeige). Stufe D1 in Pakete geschnitten ([Implementierungsplan](../implementierungsplan.md#d1-mehrere-nutzer--paketschnitt)). |
| 06.11.2026 | Live-Prüfung von yfinance 1.8 (News, ETF-Daten), OpenFIGI und ESMA FIRDS eingearbeitet: Relevanzregel für News (NEWS-13), FIRDS als Quelle für Anleihe-Stammdaten und LEI (HIN-K06 damit machbar), ETF-Länder und -Volumen nur aus Anbieterdateien; Begriff „Herkunft“ statt „Quelle“ beim Depotstand |
| 04.11.2026 | Review eingearbeitet: eigene Events für Depotberichte, Höchstalter je Event-Art, persönliche Schemas außerhalb von `SCHEMAS`, NATS-Nutzer, mehrere Listings je ISIN, `role` der Snapshots, Composite-Perzentil, Tageskurse in eigenen Tabellen |
