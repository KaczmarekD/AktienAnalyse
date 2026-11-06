# News zu den Wertpapieren

> **Status:** Spezifikation, Entwurf vom 04.11.2026. Teil der
> [Depot-Spezifikation](README.md), Stufe D6. Quellen:
> [Recherche 11/2026](../../research/2026-11-depot-datenquellen-und-bankzugang.md#news).

## Ziel

Zu jedem Wertpapier in einem Depot oder auf einer Beobachtungsliste zeigt das UI aktuelle
Meldungen. Pflichtmitteilungen der Unternehmen (Ad-hoc, Eigengeschäfte von Führungskräften)
stehen vorn, weil sie kursrelevant sein können. News fließen in Hinweise (HIN-N01, HIN-N02) und in
die Berichte ein.

## Anforderungen

| ID | Prio | Anforderung |
|---|---|---|
| NEWS-01 | Muss | Je Meldung: Schlagzeile, Quelle, Zeitpunkt, Link, Art, Sprache, optional ein Auszug von höchstens 300 Zeichen. **Kein Volltext.** |
| NEWS-02 | Muss | Arten: `adhoc` (Ad-hoc-Mitteilung), `directors_dealings`, `voting_rights` (Stimmrechte), `company` (Unternehmensmeldung), `press` (Presse). |
| NEWS-03 | Muss | Abruf für die Abdeckung (alle Wertpapiere in Depots und Beobachtungslisten), mehrmals am Tag, Standard alle 4 Stunden zwischen 6 und 22 Uhr. |
| NEWS-04 | Muss | Duplikate werden erkannt: gleiche kanonische URL, oder gleiche Schlagzeile, Quelle und Tag. |
| NEWS-05 | Muss | Jede Zuordnung zu einem Wertpapier hat eine Herkunft: von der Quelle genannt (`source_symbol`), aus Pflichtmitteilung (`disclosure`) oder per Namensabgleich (`name`). Namensabgleiche erscheinen im UI gekennzeichnet. |
| NEWS-13 | Muss | Relevanz: Eine Meldung ist **Hauptthema** eines Wertpapiers, wenn die Quelle höchstens zwei Titel nennt oder der Name des Unternehmens in der Schlagzeile steht. Sonst ist sie eine **Erwähnung** (z. B. ein Vergleichsartikel mit acht Titeln). Das UI zeigt Hauptthemen zuerst, Erwähnungen eingeklappt. Berichte und Hinweise nutzen nur Hauptthemen. |
| NEWS-06 | Muss | Fällt eine Quelle aus, laufen die anderen weiter. Der Fehler steht im Log und im Abruflauf. |
| NEWS-07 | Muss | UI: News je Depot und je Wertpapier, Filter nach Art, Quelle und Zeitraum, Markierung „neu seit dem letzten Besuch“. |
| NEWS-08 | Muss | Ein Link „Weitere News suchen“ öffnet eine Google-News-Suche zum Wertpapier im Browser. Das System selbst ruft Google News nicht ab. |
| NEWS-09 | Soll | Pflichtmitteilungen über Mail-Alarme von EQS News: ein eigenes Postfach, das ein Adapter per IMAP nur liest. |
| NEWS-10 | Soll | Ersatzquelle GDELT für Wertpapiere ohne Treffer bei yfinance, mit Sprachfilter Deutsch und Englisch. |
| NEWS-11 | Kann | Finnhub für US-Titel (kostenloser API-Schlüssel in der `.env`). |
| NEWS-12 | Kann | Zusammenfassung oder Einordnung durch ein Sprachmodell. Braucht ein eigenes ADR, wie die LLM-Lesehilfe unter „Danach“ in der Roadmap. |

## Quellen

| Quelle | Rolle | Voraussetzung |
|---|---|---|
| yfinance `get_news` | erste Quelle für Aktien mit Listing | Upgrade auf yfinance ≥ 1.8. 1.7 nutzt einen Endpunkt, den Yahoo laut Code von 1.8 abgeschaltet hat. Live geprüft am 06.11.2026: 10 Meldungen je Titel, nur englisch, mit Locale `de-DE` keine, für ETFs keine. Jede Meldung nennt ihre Titel in `finance.stockTickers`, SAP dort als US-Symbol `SAP`: Die Zuordnung geht über alle Listings der ISIN. |
| EQS-Mail-Alarme per IMAP | Pflichtmitteilungen deutscher Emittenten | eigenes Postfach; die Watchlist bei EQS pflegt der Admin von Hand, das UI zeigt die fehlenden Unternehmen |
| GDELT DOC 2.0 | Ersatz, Abgleich über den Namen; einzige freie Quelle für deutschsprachige Presse | höchstens eine Anfrage je 5 s, Quellenangabe |
| Finnhub | US-Titel | API-Schlüssel |

Ausgeschlossen: Google-News-RSS im Abruf (robots.txt und Bedingungen verbieten es), NewsAPI
(Free Tier nur für Entwicklung), Bundesanzeiger-Scraping.

Jede Quelle ist ein Adapter hinter dem Port `NewsProvider` in market-data. market-data bleibt der
einzige Service, der Marktdaten von außen holt.

```python
class NewsProvider(Protocol):
    name: str
    def fetch(self, securities: Sequence[SecurityRef], since: datetime) -> NewsBatch: ...
    # wirft nie; Fehler je Wertpapier stehen in NewsBatch.errors
```

## Ablauf

```
web-api Scheduler (WEB_API_NEWS_SCHEDULE) ─ va.marketdata.news.requested ─► market-data
market-data: je Quelle abrufen, normieren, Duplikate erkennen, speichern
market-data ─ va.marketdata.news.collected {items[] mit Zuordnungen} ─► portfolio
portfolio: lokale Kopie für betroffene Wertpapiere, Hinweise HIN-N01/N02 prüfen
portfolio ─ va.portfolio.depot.news {depot_id, count, adhoc} ─► web-api ─WS depot:<id>─► Browser
```

- `news.collected` trägt nur Daten über Wertpapiere, nichts über Nutzer. Es darf im Stream
  `VA_EVENTS` liegen.
- portfolio hält eine Kopie nur der Meldungen, die ein gehaltenes Wertpapier betreffen
  (`portfolio.news_view`), für Hinweise, Berichte und das UI.
- Der Abruf läuft unabhängig vom Wochenlauf. Er nutzt keinen Run in `batch.run`, nur einen
  eigenen Abruflauf (`market_data.news_fetch_run`).

## Datenmodell

| Tabelle | Schema | Inhalt | Schreibweise |
|---|---|---|---|
| `news_fetch_run` | `market_data` | id, provider, started_at, finished_at, status, items, errors | anfügen, Abschluss wie `fetch_run` |
| `news_item` | `market_data` | id, provider, provider_id, url, url_hash (eindeutig), title, snippet, published_at, fetched_at, language, kind | anfügen |
| `news_link` | `market_data` | news_id, isin, matched_by, confidence | anfügen |
| `news_view` | `portfolio` | news_id, isin, title, url, source, published_at, kind, received_at | anfügen |
| `news_read_marker` | `portfolio` | user_id, depot_id, read_until, at | anfügen, gültig ist die jüngste Zeile |

Mengen: bei 200 Wertpapieren und etwa 5 Meldungen pro Tag rund 1.000 Zeilen am Tag, weniger als
200 MB im Jahr. Gelöscht wird nichts.

## API

| Methode und Pfad | Zweck |
|---|---|
| `GET /api/v1/depots/{id}/news?kind=&since=&limit=` | News zu den Positionen eines Depots |
| `GET /api/v1/securities/{isin}/news` | News zu einem Wertpapier (nur wenn es in einem eigenen Depot steht) |
| `POST /api/v1/depots/{id}/news/read` | Marke „gelesen bis“ setzen |

## Tests und Abnahme

- Normieren: Fixtures je Quelle (gespeicherte Antworten von yfinance, GDELT, eine EQS-Mail),
  Auszug auf 300 Zeichen gekürzt, Art richtig erkannt.
- Duplikate: dieselbe Meldung aus zwei Quellen ergibt eine Zeile mit zwei Zuordnungen.
- Namensabgleich: „SAP“ trifft nicht „SAPPI“, Titel mit kurzen oder allgemeinen Namen brauchen
  Börsenkürzel oder ISIN im Text.
- Relevanz (NEWS-13): Fixtures mit den Mustern aus der Live-Prüfung, z. B. „DocuSign vs.
  Monday.com“ mit acht Tickern ist für SAP eine Erwähnung, „SAP Stocks Rise 4.1% …“ ein
  Hauptthema.
- Ausfall einer Quelle: die anderen liefern, der Lauf endet mit Status `partial`.
- Kein Volltext in der Datenbank (Test prüft die Länge von `snippet`).
- Adapter von yfinance werden wie heute nicht gemockt. Getestet werden Normieren und Abgleich in
  `domain/`.
