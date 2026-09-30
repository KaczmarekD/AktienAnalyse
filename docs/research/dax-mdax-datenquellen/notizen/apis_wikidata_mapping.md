# DAX/MDAX-Konstituenten: Daten-APIs, Wikidata und ISIN-zu-Ticker-Mapping (Stand 2026-09-29)

Methodik-Hinweis: Neben Doku-Recherche wurden am 2026-09-29 Live-Tests aus einem Windows-Rechner (Python/curl) durchgeführt: Wikidata SPARQL, OpenFIGI `/v3/mapping` ohne API-Key, Yahoo `v1/finance/search`, EODHD `demo`-Key, FMP `demo`-Key, yfiua-CSV. Wo "Live-Test" steht, ist die Quelle der eigene Aufruf (URL angegeben). Vergleichsbasis für Vollständigkeit war `data/dax_mdax_fallback.csv` des Projekts (40 DAX + 50 MDAX, zuletzt geändert 2026-09-29) – die ist selbst keine autoritative Quelle; eine offizielle STOXX/Deutsche-Börse-Liste wurde nicht gegengeprüft.

## (a) Kommerzielle/Freemium-APIs: Gibt es einen Endpoint für DAX- UND MDAX-Konstituenten, was kostet er, welche IDs?

### Takeaway
Kein Freemium-Anbieter liefert DAX+MDAX-Konstituenten im Gratis-Tier. Realistisch sind nur **EODHD** (Fundamentals-Paket, Index-Ticker `GDAXI.INDX`/`MDAXI.INDX`, ab ca. 50–60 EUR/Monat) und **Finnhub** (`/index/constituents`, Premium, liefert ISIN + Yahoo-artige Symbole, ab ca. 50 USD/Monat pro Markt). Beides liegt klar über dem Budget von < 10 EUR/Monat. FMP, Twelve Data, Alpha Vantage, Marketstack, Massive (Polygon) und Tiingo haben entweder nur US-Indizes oder gar keinen Konstituenten-Endpoint; yfinance/Yahoo bietet keine Index-Komponenten.

### Cited Findings

**EODHD**
- Index-Konstituenten kommen über die Fundamentals-API, wenn man einen Index-Ticker der Pseudo-Börse `INDX` abfragt (z. B. `GSPC.INDX`); Abschnitt `Components` = aktuelle Mitglieder, `HistoricalTickerComponents` = Historie. — [EODHD Fundamentals API](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds)
- Die Historie gibt es nur für die S&P-Familie; für alle anderen Indizes (also auch DAX/MDAX) nur die aktuellen Mitglieder. Historie für 100+ Indizes weltweit gibt es nur als separates, kostenpflichtiges Marketplace-Produkt. — [EODHD Fundamentals API](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds); [EODHD Marketplace](https://eodhd.com/marketplace/unicornbay/spglobal)
- Zugriff nur für Nutzer mit Fundamentaldaten ("All-in-One & Fundamental Data plans"). Abgedeckt sind "around 100 indices"; pro Komponente kommen Code, Börse, Name, Sektor und Branche. — [EODHD-Blog Index Constituents API](https://eodhd.com/financial-apis-blog/index-constituents-or-index-components-api) (über die Suchmaschinen-Zusammenfassung; auf der Blogseite selbst stand beim Abruf keine Tarifangabe)
- Preise (laut EODHD-Preisseite, in EUR): Sandbox kostenlos mit 20 Calls/Tag und 1 Jahr EOD-Historie, ohne Fundamentals; Historian 19,99 €/Monat; Active Trader 29,99 €/Monat; **Equity Analyst (Fundamentals) 59,99 €/Monat bzw. 49,99 €/Monat bei jährlicher Zahlung**; ALL-IN-ONE 99,99 €/Monat. Studenten bekommen 50 % Rabatt. — [EODHD Pricing](https://eodhd.com/pricing)
- Live-Test: `https://eodhd.com/api/fundamentals/GDAXI.INDX?api_token=demo` und sogar `GSPC.INDX?api_token=demo` antworten mit "Forbidden. Please contact support@eodhistoricaldata.com". Der Demo-Key deckt Index-Fundamentals also nicht (mehr) ab, und ob DAX/MDAX wirklich abgedeckt sind, ließ sich nicht direkt prüfen. — Live-Test 2026-09-29 (URL oben)
- Die Doku nennt GDAXI/MDAXI nirgends ausdrücklich. — [EODHD Fundamentals API](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds)

**Finnhub**
- Endpoint `GET /index/constituents?symbol=^IBEX`, gekennzeichnet mit "Premium Access Required". Die Liste der unterstützten Indizes gibt es unter `/api/v1/index/list?token=`. Die Beispielantwort enthält `constituents` im Yahoo-artigen Format (`SAN.MC`, `IBE.MC`) und `constituentsBreakdown` mit **isin**, cusip, name, shareClassFIGI, symbol und weight sowie `atDate` (Beispiel mit Datum 2026-07-24). Europäische Indizes werden also grundsätzlich unterstützt. — [Finnhub Docs: Indices Constituents](https://finnhub.io/docs/api/indices-constituents) (per curl ausgelesenes eingebettetes OpenAPI-JSON)
- Laut Suchmaschinen-Zusammenfassung ist Index Constituents seit dem 24. Juli (Jahr in der Quelle unklar) nicht mehr im Free-Plan. Fundamental-1 kostet 50 USD/Monat/Markt, Fundamental-2 200 USD/Monat/Markt. — [Finnhub Pricing](https://finnhub.io/pricing) (WebFetch lieferte den Seiteninhalt nicht, die Zahlen stammen aus der Suchzusammenfassung, also nicht verifiziert)
- Ob `^GDAXI` und `^MDAXI` in der Liste der unterstützten Indizes stehen, ließ sich ohne Token nicht prüfen. — [Finnhub Docs](https://finnhub.io/docs/api/indices-constituents)

**Financial Modeling Prep (FMP)**
- Die Stable-Doku hat Konstituenten-Endpoints für S&P 500 (`latestConstituents`, Seite "sp-500") und Nasdaq (`stable/nasdaq-constituent`), dazu Dow Jones. Einen DAX- oder MDAX-Endpoint gibt es nicht. — [FMP Docs S&P 500](https://site.financialmodelingprep.com/developer/docs/stable/sp-500); [FMP Docs Nasdaq](https://site.financialmodelingprep.com/developer/docs/stable/nasdaq); [FMP Index-Datasets](https://site.financialmodelingprep.com/datasets/indexes) ("S&P 500, Nasdaq, Dow Jones, and more", laut Suchzusammenfassung)
- Preise: Basic kostenlos mit 250 Calls/Tag (nur EOD, ca. 5 Jahre); Starter 19 USD/Monat; Premium 49 USD/Monat; Ultimate 99 USD/Monat (jeweils bei jährlicher Zahlung). — [FMP Pricing](https://site.financialmodelingprep.com/pricing-plans) (über Suchzusammenfassung)
- Live-Test: Der Key `demo` gibt bei `/stable/sp500-constituent` "Invalid API KEY" zurück. — Live-Test 2026-09-29

**Twelve Data**
- Einen Endpoint für Index-Konstituenten gibt es nicht. Nur `/etfs/etf-composition` und `/mutual-funds/mf-composition` (höhere Tarife, "High demand"). — [Twelve Data Docs](https://twelvedata.com/docs)
- Rund 5.000 Indizes gibt es nur als Kursdaten. — [Twelve Data Indices](https://twelvedata.com/indices)

**Alpha Vantage**
- In der Doku gibt es keinen "constituent"-Endpoint. Nur `ETF_PROFILE` (ETF-Holdings, Beispiel QQQ). — [Alpha Vantage Documentation](https://www.alphavantage.co/documentation/) (per curl durchsucht)

**Marketstack / Tiingo / Massive (ex-Polygon)**
- In den Docs von Marketstack und Tiingo fand die Suche nach "constituent" nichts. Massive hat nur "ETF Global Constituents" (Partner-Daten, ETFs). Massive heißt seit Oktober 2025 so (vorher Polygon.io) und konzentriert sich auf US-Märkte. — [Massive Docs](https://massive.com/docs/rest/quickstart); [apilayer-Vergleich](https://blog.apilayer.com/marketstack-vs-alpha-vantage-vs-polygon-io-which-stock-market-api-is-actually-worth-paying-for-in-2026/); [Geekflare](https://geekflare.com/guides/best-stock-market-api/)

**yfinance / Yahoo**
- yfinance hat keine `get_components()`-Funktion. Der Feature-Request wurde mit dem Rat beantwortet, die Konstituenten anderswo zu beschaffen. — [yfinance Issue #935](https://github.com/ranaroussi/yfinance/issues/935)
- Live-Test: Yahoo-Search findet `^GDAXI` als `quoteType: INDEX` mit Name und Börse, aber ohne Komponentenliste. — Live-Test `https://query1.finance.yahoo.com/v1/finance/search?q=%5EGDAXI`

**Open-Source-Alternative yfiua/index-constituents**
- Liefert CSV/JSON mit Yahoo-Symbolen für 12 Indizes, darunter DAX, aber **nicht MDAX**. Wird monatlich aktualisiert, Apache-2.0-Lizenz, URL-Muster `constituents-dax.csv`. — [GitHub yfiua/index-constituents](https://github.com/yfiua/index-constituents)
- Live-Test: `https://yfiua.github.io/index-constituents/constituents-dax.csv` enthält am 2026-09-29 noch **PAH3.DE** und kein **HOT.DE**. Laut Wikidata (Hochtief DAX-Start 2026-06-22) und Projekt-CSV ist die Liste damit mindestens 3 Monate veraltet. — Live-Test 2026-09-29

### Inferences
- Für Privatnutzer unter 10 EUR/Monat gibt es keine kommerzielle API, die DAX+MDAX-Konstituenten liefert. Die billigste gesicherte Option (EODHD Equity Analyst, ca. 50 €/Monat bei jährlicher Zahlung) kostet das Fünffache. Das lohnt sich höchstens, wenn man EODHD ohnehin als yfinance-Ersatz für Fundamentaldaten nutzt (vgl. CLAUDE.md: "Wechsel zu FMP oder EODHD").
- Finnhubs Ausgabeformat (Yahoo-artige Symbole plus ISIN) würde am besten zum Projekt passen. Unklar bleibt aber, ob DAX/MDAX abgedeckt sind und wie viel es kostet.
- yfiua eignet sich höchstens als Plausibilitätsprüfung für den DAX, nicht als Primärquelle (kein MDAX, verzögert).

### Gaps
- Ob EODHD `MDAXI.INDX` tatsächlich Komponenten liefert und wie aktuell sie sind, ließ sich nicht prüfen, weil der Demo-Key gesperrt war.
- Die Finnhub-Indexliste (`/index/list`) braucht einen Token, deshalb ist unklar, ob `^GDAXI`/`^MDAXI` enthalten sind. Auch der genaue Preis für den Plan mit Index Constituents ist nicht auf der Originalseite verifiziert.
- Die Nutzungsbedingungen der Gratis-Tiers (EODHD, FMP, Finnhub) zu privater Nutzung wurden nicht im Wortlaut geprüft.

## (b) Wikidata/SPARQL: Wie aktuell und vollständig sind DAX/MDAX-Mitglieder mit ISIN und Ticker?

### Takeaway
Die Wikidata-Mitgliedschaft (P361 "part of" mit Qualifier P580/P582) war im Live-Test **überraschend aktuell**: 40 DAX- und 50 MDAX-Firmen, deckungsgleich mit der Projekt-Fallback-CSV. Dabei waren auch Aumovio, TKMS, Renk, Schaeffler und die Wechsel von März/Juni 2026. Die **ISINs sind aber teils veraltet** (Kapitalmaßnahmen, Umfirmierungen), und die Ticker (P249) sind lückenhaft und nicht zu gebrauchen. Wikidata taugt als Mitgliedsquelle; ISIN und Ticker sollten anderswo aufgelöst werden.

### Cited Findings
- Die Wikidata-Items sind DAX = `Q155718` und MDAX = `Q595622` (es gibt weitere Items mit dem Label "DAX", z. B. Q17104553, Q27076994, die nicht der Index sind). — Live-Test [query.wikidata.org](https://query.wikidata.org/sparql)
- Aktuelle Mitglieder über P361 ohne Endedatum (`pq:P582`): **DAX 41 Treffer, MDAX 50**. Der 41. DAX-Treffer ist **DivDAX (Q1230458)**, ein Index und kein Unternehmen, also ein Modellierungsfehler. Das ergibt 40 echte DAX-Mitglieder. Über die Gegenrichtung P527 ("has part") auf dem Index-Item kommen inkonsistent **33 (DAX) bzw. 60 (MDAX)** Treffer. P527 ist also unzuverlässig, man sollte P361 auf der Firma nutzen. — Live-Test 2026-09-29
- Abgleich mit `data/dax_mdax_fallback.csv`: Die Firmen in P361 entsprechen **exakt** den 40 DAX- und 50 MDAX-Einträgen der CSV, ohne fehlende oder zusätzliche Einträge (abgesehen von DivDAX). Beispiele mit Startdatum: Hochtief DAX seit 2026-06-22; GEA und Scout24 DAX seit 2025-09-22; **Aumovio MDAX seit 2025-12-22**; **TKMS MDAX seit 2025-12-22**; **Renk MDAX seit 2025-03-24**; **Schaeffler MDAX seit 2026-03-09** (ungewöhnliches Datum, kein regulärer Review-Termin, Quelle unklar); Deutz, Jenoptik und Salzgitter seit 2026-03-23; Elmos, Siltronic, Suss Microtec und Porsche SE MDAX seit 2026-06-22. — Live-Test 2026-09-29
- **ISIN-Qualität (P946)**, verglichen mit OpenFIGI und Yahoo: Veraltete oder falsche ISINs gibt es u. a. bei Renk (`DE0007850000` = alte RENK AG statt `DE000RENK730`), Schaeffler (`DE000SHA0019` statt `DE000SHA0100`), Qiagen (`NL0000240000` statt `NL0015002CX3`), Aroundtown (`CY0105562116` statt `LU1673108939`), Jenoptik (`DE0006229107` statt `DE000A2NB601`) und Fuchs (`DE0005790406/…430` statt `DE000A3E5D64`). Bei Lufthansa **fehlt die ISIN ganz**. Brenntag hat zusätzlich eine US-ADR-ISIN. Bei BMW, VW, Henkel, Sartorius, TUI und Fuchs stehen mehrere ISINs (Stamm/Vorzug, alt/neu) ohne Rang-Markierung. Insgesamt hatten ~8 der 90 Firmen keine aktuell gültige ISIN. — Live-Test 2026-09-29 (Gegenprüfung mit OpenFIGI: alte ISINs gaben "No identifier found", die korrigierten ISINs lieferten R3NK/SHA0/AT1/JEN/FPE3/LHA mit exchCode GY)
- **Ticker-Qualität (P414/P249)**: Etwa 20 der 50 MDAX-Firmen haben gar keinen Ticker (z. B. Aumovio, TKMS, Renk, Bechtle, Fraport, Hugo Boss). Andere haben US-OTC- oder ADR-Ticker (Adidas "ADDYY", GEA nur "GEAGY", Siemens Healthineers nur "SMMNY") oder numerische Codes ("4863", "8651"). Ohne Filter auf die Börse (Xetra/Frankfurt) lässt sich P249 nicht nutzen. — Live-Test 2026-09-29
- Die verwendete Abfrage (liefert CSV mit `Accept: text/csv`; ein User-Agent-Header ist laut Wikimedia-Policy Pflicht):
  ```sparql
  SELECT ?idx ?c ?cLabel ?isin ?start (GROUP_CONCAT(DISTINCT ?tick; separator="|") AS ?ticks) WHERE {
    VALUES ?idx { wd:Q155718 wd:Q595622 }
    ?c p:P361 ?st . ?st ps:P361 ?idx .
    FILTER NOT EXISTS { ?st pq:P582 ?e }
    OPTIONAL { ?st pq:P580 ?start }
    OPTIONAL { ?c wdt:P946 ?isin }
    OPTIONAL { ?c p:P414 ?ls . ?ls ps:P414 ?exch . ?ls pq:P249 ?tick . }
    SERVICE wikibase:label { bd:serviceParam wikibase:language "de,en". }
  } GROUP BY ?idx ?c ?cLabel ?isin ?start ORDER BY ?idx ?cLabel
  ```
  — ausgeführt gegen [query.wikidata.org/sparql](https://query.wikidata.org/sparql), Antwortzeit wenige Sekunden

### Inferences
- Wikidata eignet sich als **zweite Mitgliedsquelle neben Wikipedia/Fallback-CSV**. Es ist kostenlos, braucht keinen Key, steht unter CC0 und liefert strukturierte Daten statt HTML. Robustheit: Filter `?c wdt:P31/wdt:P279* wd:Q4830453` (business) oder ein Ausschluss von Index-Items gegen Fehler wie DivDAX; Plausibilitätsprüfung der Anzahl (DAX == 40, MDAX == 50) mit Fallback bei Abweichung.
- Die Aktualität hängt davon ab, dass Freiwillige die Index-Reviews nachpflegen. Hier geschah das offenbar zeitnah (die Juni-2026-Wechsel sind drin), garantiert ist das nicht. Wahrscheinlich pflegen Wikipedia und Wikidata dieselben Editoren, sodass beide Quellen korrelierte Fehler haben können.
- ISINs aus Wikidata sollte man nur als Hinweis nutzen und immer über OpenFIGI oder Yahoo validieren. Wenn der Lookup mit der Wikidata-ISIN scheitert, als Fallback per Name suchen.

### Gaps
- Nicht geprüft wurde, ob der reguläre September-Review 2026 (wirksam ca. 21./22.09.2026) Änderungen brachte. Der Abgleich lief nur gegen die Projekt-CSV, nicht gegen die offizielle STOXX/Deutsche-Börse-Zusammensetzung.
- Die Historie der Pflege-Latenz (wie viele Tage nach einem Index-Wechsel Wikidata aktualisiert wird) wurde nicht ausgewertet.

## (c) ISIN zum Xetra-/Yahoo-Ticker: OpenFIGI und Yahoo-Search

### Takeaway
**OpenFIGI** ist kostenlos, offiziell dokumentiert und liefert mit `exchCode: "GY"` (Xetra) direkt das Xetra-Kürzel (`SAP`, `R3NK`, `8TRA`). Mit angehängtem `.DE` ergibt das den Yahoo-Ticker. Im Test lösten 85 von 96 Wikidata-ISINs auf; alle Fehlschläge außer Fresenius und neuer Qiagen-ISIN lagen an veralteten ISINs. Die **Yahoo-Search** (`v1/finance/search?q=<ISIN>`) funktioniert ohne Key und liefert direkt `XXX.DE`. Sie ist aber inoffiziell und in Randfällen unzuverlässig (nur `.F`, `.PA`, `.MI` statt `.DE`). Robuste Lösung: OpenFIGI GY zuerst, dann Yahoo-Search als Fallback, jeweils mit Prüfung auf `.DE`.

### Cited Findings
- OpenFIGI-Rate-Limits für `/v3/mapping`: **ohne Key 25 Requests/Minute mit max. 10 Jobs (ISINs) pro Request; mit kostenlosem Key 25 Requests/6 Sekunden mit 100 Jobs pro Request.** `/v3/search` und `/v3/filter`: 5/Minute ohne Key, 20/Minute mit Key. Der Dienst ist "free and open to the public"; eine Abschaltung von v3 ist nicht angekündigt. — [OpenFIGI API Documentation](https://www.openfigi.com/api/documentation)
- Live-Test bestätigt: Header `ratelimit-policy: 25;w=60`. Ein Request mit 11 Jobs ohne Key gibt **HTTP 413 Payload Too Large** zurück. — Live-Test 2026-09-29 (`POST https://api.openfigi.com/v3/mapping`)
- Live-Test: Mapping `{"idType":"ID_ISIN","idValue":"DE0007164600","exchCode":"GY"}` ergibt genau einen Treffer `ticker: SAP, exchCode: GY, name: SAP SE, compositeFIGI BBG000BG7DY8`. Ohne exchCode kommen alle Listings (GR = Composite Deutschland, GY = Xetra, GF = Frankfurt, GD/GS/GM/GI/GH = Regionalbörsen, SW, US-OTC "SAPGF"). — Live-Test 2026-09-29
- Live-Test über 96 Wikidata-ISINs mit `exchCode: GY` (10 Batches, 2,6 s Pause, ca. 30 s gesamt): **85 aufgelöst**, alle mit korrekten Xetra-Kürzeln (z. B. G1A, G24, 8TRA, AMV0, TKMS, P911, PAH3, HOT, RRTL für RTL Group mit LU-ISIN, AIR für Airbus mit NL-ISIN). 11 fehlgeschlagen, davon 9 wegen veralteter oder Nebengattungs-ISINs aus Wikidata. Mit aktuellen ISINs lösten Renk, Schaeffler, Aroundtown, Jenoptik, Fuchs, Lufthansa, DWS und TKMS korrekt auf. **Nicht aufgelöst trotz vermutlich korrekter ISIN:** Fresenius `DE0005785604` und Qiagen neu `NL0015002CX3` (leere Antwort auch ohne exchCode-Filter). — Live-Test 2026-09-29
- Yahoo-Search-Live-Test (`https://query1.finance.yahoo.com/v1/finance/search?q=<ISIN>&quotesCount=5&newsCount=0`, Browser-User-Agent, 0,5 s Pause, 96 Anfragen ohne 429): **83 von 96 ISINs lieferten ein `.DE`-Symbol** (z. B. `SAP.DE`, Feld `exchDisp: "XETRA"`). Die Fehlschläge zeigen typische Schwächen:
  - Airbus liefert nur `AIR.PA`, Fresenius nur `1FRE.MI`, Qiagen neu nur `1QGEN.MI`.
  - DWS liefert nur `DWS.F`, TKMS nur `TKMS.F`, Schaeffler neu nur `SHA0.F`, obwohl `DWS.DE` und `TKMS.DE` per Symbolsuche existieren.
  - Die Brenntag-ADR-ISIN liefert `BNTGY`.
  - Alte ISINs bringen leere Ergebnisse.

  — Live-Test 2026-09-29
- Yahoo hat keine offizielle API. yfinance ruft inoffizielle Endpoints ab, die seit 2025 immer wieder mit 429 "Too Many Requests" und Crumb-Fehlern auffallen. Laut Sekundärquellen ist die Nutzung nur privat vorgesehen, kommerzielle Nutzung kann gegen die Yahoo-ToS verstoßen. — [yfinance Issue #2422](https://github.com/ranaroussi/yfinance/issues/2422); [yfinance Discussion #2581](https://github.com/ranaroussi/yfinance/discussions/2581); [marketxls Guide](https://marketxls.com/blog/yahoo-finance-api-ultimate-guide) (Sekundärquelle)

### Inferences
- Empfohlene Pipeline für das Projekt:
  1. Mitglieder mit Namen und ISIN aus Wikidata (oder Wikipedia) holen.
  2. OpenFIGI `ID_ISIN` + `exchCode: GY` in 10er-Batches (ohne Key; bei ~90 ISINs ca. 9 Requests, weit unter 25/Minute), Ergebnis `ticker + ".DE"`.
  3. Fallback: Yahoo-Search mit der ISIN, nur `.DE`-Symbole akzeptieren.
  4. Fallback: Yahoo-Search bzw. OpenFIGI `/v3/search` mit dem Firmennamen.
  5. Letzter Fallback: das Symbol aus der Fallback-CSV.
- Ein kostenloser OpenFIGI-Key lohnt sich (alles in einem Request), ist bei ~90 Werten und wöchentlichem Lauf aber nicht nötig.
- Die OpenFIGI-Kürzel (Bloomberg-Ticker) stimmten in allen getesteten Fällen mit Yahoos `.DE`-Stamm überein. Garantiert ist das nicht. Ein Validierungsschritt, bei dem yfinance einen Kurs für `ticker.DE` abruft, fängt Abweichungen ab.
- Ergebnisse sollten gecacht werden (ISIN→Ticker ändert sich selten), das reduziert die Abhängigkeit von beiden Diensten.

### Gaps
- Warum OpenFIGI Fresenius (`DE0005785604`) und die neue Qiagen-ISIN nicht auflöst, wurde nicht geklärt (möglicherweise Datenlücke bei OpenFIGI).
- Yahoo veröffentlicht keine Limits oder Stabilitätszusagen für den Search-Endpoint. Die 96 Anfragen ohne Fehler sind eine Einzelbeobachtung von einer privaten IP und sagen nichts über Verhalten aus Rechenzentrums-IPs.
- Die Nutzungsbedingungen von OpenFIGI (Terms of Service) wurden über die Aussage "free and open to the public" hinaus nicht im Wortlaut geprüft.
