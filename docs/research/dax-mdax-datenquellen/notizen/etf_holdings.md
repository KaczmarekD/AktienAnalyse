# ETF-Holdings-Dateien als Quelle für DAX/MDAX-Konstituenten

Stand der Prüfung: 2026-09-29. Alle "beobachtet"-Angaben stammen aus eigenen HTTP-Abrufen (curl/Python urllib, ohne Login, ohne Cookies) am 29.09.2026; Holdings-Stichtag der Dateien jeweils 28.09.2026.

## 1. Welche Emittenten bieten einen direkten, maschinenlesbaren Download ohne Login? (URL-Muster, verifiziert)

### Takeaway
Die klassischen iShares-`.ajax?fileType=csv`-URLs sind **tot** (DE: 404; UK/US: HTTP 200, liefern aber HTML statt CSV). iShares lädt Holdings jetzt über eine neue JSON-API (`blackrock.com/varnish-api/.../get-product-data`), die ohne Login, ohne Cookie und ohne Browser-User-Agent funktioniert und ISIN plus Emittententicker liefert. **Deka** liefert pro Fonds eine XLSX, die sowohl die Fonds- als auch die **Index**zusammensetzung enthält (ISIN + WKN, kein Ticker). **Xtrackers** (DWS) liefert eine XLSX nur mit ISIN (kein Ticker), aber `robots.txt` sperrt den Pfad. Amundi habe ich nicht verifiziert.

### Cited Findings

**iShares – alter .ajax-CSV-Endpunkt (tot)**
- Beobachtet: `https://www.ishares.com/de/privatanleger/de/produkte/251464/ishares-core-dax-ucits-etf-de-fund/1478358465952.ajax?fileType=csv&fileName=EXS1_holdings&dataType=fund` → **HTTP 404**, Body "File not found." (mit und ohne Browser-UA). Dasselbe gilt für MDAX (Produkt-ID 251845). — [iShares Core DAX Produktseite](https://www.ishares.com/de/privatanleger/de/produkte/251464/)
- Beobachtet: UK-Variante `https://www.ishares.com/uk/individual/en/products/251464/ishares-core-dax-ucits-etf-de-fund/1506575576011.ajax?fileType=csv&fileName=EXS1_holdings&dataType=fund` → HTTP 200, `text/html`, ~418 KB, liefert die Produktseite (HTML) statt CSV. US-IVV-Variante (`/us/products/239726/.../1467271812596.ajax?fileType=csv...`) → HTTP 200, **`Content-Type: text/csv`**, aber Body ist HTML (~2,25 MB). — [iShares UK](https://www.ishares.com/uk/individual/en/products/251464/)
- Unabhängige Bestätigung: GitHub-Issue vom 23.09.2026 – iShares beantwortet Holdings-CSV-URLs (IJH, IJR, IWM, vermutlich IVV) mit der HTML-Produktseite, Status 200 und `Content-Type: text/csv`; Browser-UA, Accept- und Referer-Header ändern nichts, `fileType=json` liefert dasselbe HTML. Scraper, die jeden 2xx als Erfolg werten, erhalten stillschweigend leere Ergebnisse. — [kovagent/indexkit Issue #95](https://github.com/kovagent/indexkit/issues/95)
- Die neue iShares-Produktseite (eingebettet: `"productPageVersion":"2026.10.10"`) enthält keinen `.ajax`-Link mehr; die Holdings-Tabelle ist eine Client-Komponente (`componentkey="HoldingsTable"`) mit `apiHost: https://www.blackrock.com/varnish-api/uk-retail01-product-data/product-data/api/v2/get-product-data?` und einer Liste verfügbarer Stichtage (`initAsOfDateList: [20260928, 20260831, 20260630, 20251231]`). — beobachtet im HTML von [iShares Core DAX](https://www.ishares.com/de/privatanleger/de/produkte/251464/)

**iShares – neue JSON-API (funktioniert)**
- Funktionierendes Muster (beobachtet, HTTP 200, `application/json`):
  `https://www.blackrock.com/varnish-api/uk-retail01-product-data/product-data/api/v2/get-product-data?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=de-ishares-v2&locale=de_DE&portfolioId=<ID>&component=holdings&userType=individual`
  - `portfolioId=251464` = iShares Core DAX UCITS ETF (DE), EXS1 (Seitentitel zeigt Bloomberg-Ticker "DAXEX")
  - `portfolioId=251845` = iShares MDAX UCITS ETF (DE), EXS3
  - Optional `&asOfDate=YYYYMMDD` (mit 20260928 getestet, funktioniert).
  - Ohne User-Agent (curl default) und mit Python-`urllib`-Default-UA ebenfalls HTTP 200 (~445 KB bzw. ~60 KB gzip). Kein Cookie-/Consent-/Anlegertyp-Gate für die API beobachtet.
  - Minimal-Parameter (`portfolioId` + `component` allein) → HTTP 400 "No product data available with the provided input parameters." – die Kontextparameter (`targetSite`, `locale`, `userType`, `appType`, `appSubType`) sind Pflicht.
- JSON-Struktur (beobachtet): `componentsByNameMap.holdings.containersByNameMap.all.dataPointsByNameMap.<feld>.value` ist jeweils ein spaltenweises Array (Column-Store), parallel `formattedValue` in deutschem Format. Felder: `ticker` (Label "Emittententicker"), `isin`, `issueName`, `sectorName`, `assetClass`, `holdingPercent`, `marketValue`, `notionalValue`, `unitsHeld`, `unitPrice`, `countryOfRisk`, `exchange`, `marketCurrencyCode`, plus `asOfDate` (Skalar, 20260928) und `dateList`. — beobachtet, [API-Endpunkt EXS1](https://www.blackrock.com/varnish-api/uk-retail01-product-data/product-data/api/v2/get-product-data?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=de-ishares-v2&locale=de_DE&portfolioId=251464&component=holdings&userType=individual)
- Beobachtet EXS1 (DAX): 45 Zeilen = **40 Aktien** + EUR CASH, "CASH COLLATERAL EUR MLIFT", "ETD EUR BALANCE…", USD CASH, 1 Future ("DAX INDEX DEC 26", Ticker GXZ6, ISIN DE000F0GDWD2, Assetklasse "Futures").
- Beobachtet EXS3 (MDAX): 56 Zeilen = **50 Aktien** (alle Börse "Xetra") + 4× Geldmarkt/Cash (EUR, ETD_EUR, ZAR, USD) + 1 Cash Collateral + 1 Future ("MDAX MINI DEC 26", MFLZ6).
- Zusätzlich: Excel-Gesamtexport `https://www.blackrock.com/varnish-api/uk-retail01-product-data/product-data/api/v1/get-fund-document?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=de-ishares-v2&locale=de_DE&portfolioId=251464&component=fundDownloadV2&userType=individual` → HTTP 200, `application/vnd.ms-excel`, Dateiname `iShares-Core-DAX-UCITS-ETF-DE-EUR-Acc_fund.xls`, ~2,7 MB. **Achtung:** Das ist kein echtes XLS, sondern SpreadsheetML 2003 (XML, `<ss:Workbook>`), 9 Blätter inkl. "Holdings" und "Historical NAVs" – für pandas nur mit eigenem XML-Parsing lesbar. Die JSON-API ist einfacher.
- Frühere Beobachtungen (Hintergrund, veraltet): Mehrere GitHub-Projekte basieren auf den `.ajax`-CSV-URLs, z. B. [talsan/ishares](https://github.com/talsan/ishares), [nikulpatel3141/ETF-Scraper](https://github.com/nikulpatel3141/ETF-Scraper), [danielsteman/etf-constituents](https://github.com/danielsteman/etf-constituents). Bis ca. 2025 wurde das .ajax-Muster auch noch in Suchindizes geführt, z. B. [UK MAXJ .ajax-URL](https://www.ishares.com/uk/individual/en/products/342730/fund/1506575576011.ajax?fileType=csv&fileName=MAXJ_holdings&dataType=fund). Solcher Code ist mit Stand 09/2026 als **defekt** anzusehen.

**Deka – XLSX-Download (funktioniert, enthält Indexzusammensetzung)**
- Produktseite `https://www.deka-etf.de/etfs/Deka-MDAX-UCITS-ETF` verweist auf den Turbo-Frame `/etfs/Deka-MDAX-UCITS-ETF/composition_data` (HTML-Tabelle mit Name, WKN, ISIN, Gewichtung; Datums-Parameter `?date=YYYY-MM-DD`). — [Deka MDAX UCITS ETF](https://www.deka-etf.de/etfs/Deka-MDAX-UCITS-ETF)
- Beobachtet, Download-Muster: `https://www.deka-etf.de/etfs/<Slug>/composition_download?date=YYYY-MM-DD` (auch ohne `date` → neuester Stand) → HTTP 200, echtes XLSX (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`), Dateiname z. B. `Deka-ETF-Deka-MDAX-R--UCITS-ETF-Zusammensetzung.2026-09-28.xlsx`. Kein UA, kein Cookie nötig; der im HTML sichtbare "Akzeptieren"-Link blockierte den Abruf nicht.
  - Slugs getestet: `Deka-MDAX-UCITS-ETF` (MDAX, ISIN DE000ETFL441) und `Deka-DAX-UCITS-ETF` (DAX, DE000ETFL011).
- Beobachtet, Inhalt: 3 Blätter – **"Fondszusammensetzung"**, **"Indexzusammensetzung"**, "Lizenzhinweise" (enthält "Fondsname", "Indexname: DAX(R) Index", "Datum: 28.09.2026"). Spalten: `Holding Name, WKN, ISIN, Land, Branche, Gewichtung` (Gewichtung als Dezimalbruch, z. B. 0.1175). DAX: 40 Zeilen + Header; MDAX: 50 Zeilen + Header. **Kein Ticker.** Cash wird im Fondsblatt nicht als Zeile geführt (HTML-Ansicht zeigt Kasse 0,02 % separat).
- Deka `robots.txt` sperrt nur `/market_makers/*`. — [deka-etf.de/robots.txt](https://www.deka-etf.de/robots.txt)

**Xtrackers (DWS) – XLSX (funktioniert technisch, robots.txt sperrt)**
- Beobachtet: `https://etf.dws.com/etfdata/export/DEU/DEU/excel/product/constituent/LU0274211480/` → HTTP 200, XLSX (`Constituent_LU0274211480.xlsx`, ~8 KB). Englische Variante `/GBR/ENG/` ebenfalls 200. Die HTML-Produktseite ist eine Nuxt-SPA mit `ENTRY_GATE_ENABLED:true` (Anlegertyp-Gate), der Export-Endpunkt selbst verlangte aber kein Gate/Cookie. — [DWS-Export Xtrackers DAX 1C](https://etf.dws.com/etfdata/export/DEU/DEU/excel/product/constituent/LU0274211480/)
- Inhalt: Header ab Zeile 4: `Name, ISIN, Country, Currency, Exchange, Type of Security, Rating, Primary Listing, Industry Classification, Weighting`; 40 Aktien + EUR-/USD-Cash (`_CURRENCYEUR`) + ein Geldmarktfonds ("DEUTSCHE GLOBAL LIQUIDITY SERI", IE00BYQNZ507, "Mutual Fund"). **Kein Ticker.** Airbus hat hier Exchange "Euronext Paris". XML nutzt `x:`-Namespace-Präfix (einfache Regex-Parser scheitern; openpyxl/pandas sollten es lesen).
- `etf.dws.com/robots.txt` enthält `Disallow: /etfdata/*` und `Disallow: /export/*`. — [etf.dws.com/robots.txt](https://etf.dws.com/robots.txt)
- Ein physisch replizierender Xtrackers-MDAX-ETF taucht in der justETF-MDAX-Liste nicht auf (siehe Abschnitt 3).

**Amundi**
- Amundi verweist auf amundietf.com für die aktuelle Zusammensetzung; die Suchtreffer zeigten nur PDFs (Factsheets/KID), keinen direkten Holdings-Download. — [Amundi DAX Factsheet](https://www.amundietf.fr/pdfDocuments/monthly-factsheet/FR0010655712/ENG/FRA/INSTITUTIONNEL/ETF/20260131), [amundietf.de Produktseite FR0010655712](https://www.amundietf.de/de/professionell/products/equity/amundi-etf-dax-ucits-etf-dr/fr0010655712)

### Inferences
- Für DAX/MDAX gibt es zwei brauchbare, login-freie Quellen: **iShares-JSON-API** (mit Ticker) und **Deka-XLSX** (mit Indexzusammensetzung, nur ISIN/WKN). Beide zusammen ergeben eine robuste Primär-/Sekundärquelle mit unterschiedlicher Infrastruktur.
- Die neue iShares-API ist ein internes Frontend-Backend (kein dokumentiertes öffentliches API). Der Pfad enthält `uk-retail01` und die Seite `productPageVersion 2026.10.10` – das deutet auf ein kürzlich ausgerolltes Redesign hin; Parameter können sich wieder ändern.
- Response-Validierung ist Pflicht: `Content-Type` allein reicht nicht (iShares liefert HTML als `text/csv`). Prüfen: JSON parsebar, `asOfDate` vorhanden und nicht älter als X Tage, Anzahl Aktien = 40 bzw. 50.

### Gaps
- Amundi DAX/MDAX: kein direkter Holdings-Download verifiziert (Webseite vermutlich JS-basiert; nicht getestet).
- Invesco MDAX (IE00BHJYDV33): Holdings-Download nicht geprüft.
- Deka-Slug für die ausschüttende DAX-Klasse und DWS-Export für andere Xtrackers-Fonds nicht getestet.

## 2. Identifikatoren und Mapping auf Yahoo-Finance-Ticker; Quirks

### Takeaway
iShares liefert ISIN **und** Emittententicker; bei allen 90 DAX/MDAX-Aktien ergab `ticker + ".DE"` exakt die Symbolkonvention der bestehenden Fallback-CSV des Projekts. Deka und Xtrackers liefern nur ISIN (Deka zusätzlich WKN). Nicht-Aktien-Zeilen (Cash, Collateral, Futures) müssen über `assetClass == "Aktien"` gefiltert werden.

### Cited Findings
- Beobachtet, iShares-DAX-Ticker (Auszug): SIE, SAP, ALV, ENR, AIR, DTE, IFX, MUV2, DBK, DHL, DB1, BAYN, RHM, BAS, RWE, EOAN, MBG, ADS, DTG, MTX, FRE, BMW, HEI, MRK, CBK, HNR1, VOW3, SHL, VNA, SY1, HEN3, G1A, FME, QIA, CON, BEI, HOT, BNR, ZAL, G24. MDAX u. a. TKA, LHA, TLX, KBX, SRT3, P911, NDX1, HAG, AIXA, PAH3, 8TRA, R3NK, TKMS, AMV0, SHA0, AT1, RRTL, SAX, LXS. — [iShares API EXS1](https://www.blackrock.com/varnish-api/uk-retail01-product-data/product-data/api/v2/get-product-data?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=de-ishares-v2&locale=de_DE&portfolioId=251464&component=holdings&userType=individual), [iShares API EXS3](https://www.blackrock.com/varnish-api/uk-retail01-product-data/product-data/api/v2/get-product-data?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=de-ishares-v2&locale=de_DE&portfolioId=251845&component=holdings&userType=individual)
- Beobachtet, Abgleich mit `data/dax_mdax_fallback.csv` (Format `SAP.DE`): 90 vs. 90 Symbole; einzige Abweichung: ETF enthält **SAX.DE** (Ströer), Fallback-CSV enthält **BOSS.DE** (Hugo Boss). Alle anderen 89 Symbole identisch mit `ticker + ".DE"`.
- Beobachtete Quirks (iShares):
  - Nicht-deutsche ISINs: Airbus (NL0000235190, Exchange "Boerse Berlin"), Qiagen (NL0015002SN0, Exchange "Deutsche Börse AG"), Aroundtown (LU1673108939), RTL Group (LU0061462528). Die Ticker AIR/QIA/AT1/RRTL passen trotzdem auf `.DE`.
  - Ticker mit Ziffern/Vorzugsaktien-Suffix: VOW3, HEN3, SRT3, PAH3, MUV2, HNR1, 8TRA, P911, AMV0, SHA0 – Mapping bleibt `+ ".DE"`.
  - Cash-/Derivate-Zeilen: `ticker` = "EUR", "USD", "ZAR", "MLIFT"/"MSIFT", "ETD_EUR" (ISIN `None`), Futures mit echter ISIN (DE000F0GDWD2, DE000F3E21M2) – ein Filter nur auf "ISIN vorhanden" reicht also **nicht**; Filter auf `assetClass == "Aktien"` nötig.
  - `formattedValue` ist deutsch formatiert ("11,74", "1.000.789.954", Datum "28.Sept.2026", "30.Juni2026" ohne Leerzeichen) – stattdessen die numerischen `value`-Arrays nutzen.
  - Labels im JSON sind lokalisiert (z. B. "Börse", "Marktwährung" – bei falscher Decodierung Umlaut-Probleme); Feldschlüssel (`ticker`, `isin`, …) sind stabil englisch.
- Deka-XLSX: Spalten `Holding Name, WKN, ISIN, Land, Branche, Gewichtung`; Namen im Bloomberg-Stil ("SIEMENS AG-REG", "SARTORIUS AG-VORZUG", "FUCHS SE-PREF"). — [Deka MDAX composition_download](https://www.deka-etf.de/etfs/Deka-MDAX-UCITS-ETF/composition_download)
- Xtrackers-XLSX: nur ISIN, Disclaimer in Zeile 2, Header in Zeile 4, Gewichtung als Bruch; Zeilen "_CURRENCYEUR"/"Cash" und "Mutual Fund". — [DWS-Export](https://etf.dws.com/etfdata/export/DEU/DEU/excel/product/constituent/LU0274211480/)

### Inferences
- Bevorzugter Pfad für das Projekt: iShares-JSON → `ticker + ".DE"`; ISIN als Sekundärschlüssel zur Plausibilisierung/Join mit Deka.
- Bei ISIN-only-Quellen (Deka/Xtrackers) braucht man eine ISIN→Yahoo-Mapping-Tabelle (z. B. aus der iShares-Antwort oder der Fallback-CSV, wenn dort ISIN ergänzt würde). yfinance-Suche per ISIN ist möglich, aber ein weiterer fehleranfälliger externer Call.

### Gaps
- Nicht per yfinance verifiziert, dass jedes der 90 `.DE`-Symbole Daten liefert (nur Abgleich mit der bestehenden Fallback-CSV, die das Projekt bereits nutzt).
- Nicht geklärt, ob iShares-Ticker bei Neuaufnahmen immer dem Xetra-Kürzel entsprechen (bei Airbus liegt als Börse "Boerse Berlin" vor, Ticker trotzdem AIR).

## 3. Update-Frequenz, Verzögerung bei Indexänderungen, Replikationsmethode (Swap-ETFs identifizieren)

### Takeaway
iShares und Deka liefern tagesaktuelle Holdings (Stand T-1: am 29.09. lag der 28.09. vor). Alle DAX-ETFs replizieren laut justETF vollständig physisch; beim MDAX sind die **Amundi-MDAX-ETFs swap-basiert** und damit ungeeignet. Physische ETFs halten zusätzlich Cash und Index-Futures, die gefiltert werden müssen.

### Cited Findings
- Beobachtet: iShares `asOfDate=20260928` am Abruftag 29.09.2026; `dateList` bietet neben dem Tagesstand nur Monatsend-/Quartalsend-Stichtage (20260831, 20260630, 20251231). Deka-Datei: "Datum: 28.09.2026"; Datepicker in `composition_data` erlaubt beliebige Tage. — [iShares Core DAX](https://www.ishares.com/de/privatanleger/de/produkte/251464/), [Deka MDAX](https://www.deka-etf.de/etfs/Deka-MDAX-UCITS-ETF)
- Beobachtet: iShares-MDAX und Deka-MDAX enthalten beide Ströer (SAX, DE0007493991) und kein Hugo Boss; die projekteigene Fallback-CSV enthält noch BOSS.DE. Beide ETF-Quellen stimmen in den 50 MDAX-ISINs überein (Deka-Liste und iShares-Liste haben dieselben Werte, u. a. TKMS, AUMOVIO, Aroundtown, RTL). — eigene Abrufe (s. o.)
- Replikation DAX (justETF, 11 ETFs): alle "Full replication": iShares Core DAX (DE0005933931, 0,16 %, 8.446 Mio EUR), Xtrackers DAX 1C (LU0274211480, 0,09 %), Deka DAX (DE000ETFL011), Amundi Core DAX Dist (LU2611732046), Amundi ETF DAX DR (FR0010655712), Amundi DAX II Acc (LU0252633754), Deka DAX ausschüttend (DE000ETFL060), Xtrackers DAX 1D (LU1349386927), Amundi DAX II Dist (LU2090062436), iShares Core DAX Dist (DE000A2QP331), Amundi Core DAX Acc (LU3206583067). — [justETF DAX ETFs](https://www.justetf.com/en/how-to/dax-etfs.html)
- Replikation MDAX (justETF, 6 ETFs): iShares MDAX (DE0005933923, Full, 0,51 %, 1.423 Mio EUR), Invesco MDAX (IE00BHJYDV33, Full, 0,19 %), Deka MDAX (DE000ETFL441, Full, 0,30 %), iShares MDAX Dist (DE000A2QP349, Full), **Amundi MDAX Dist (FR0011857234, Swap)**, **Amundi MDAX Acc (FR0014015ZN2, Swap)**. — [justETF MDAX ETFs](https://www.justetf.com/en/how-to/mdax-etfs.html); Amundi MDAX als "unfunded swap" auch in [justETF FR0011857234](https://www.justetf.com/en/etf-profile.html?isin=FR0011857234)
- Amundi DAX II (LU0252633754): physisch, volle Replikation, Wertpapierleihe "Yes". — [justETF LU0252633754](https://www.justetf.com/en/etf-profile.html?isin=LU0252633754)
- Beobachtet: Physische ETFs halten neben den Aktien Cash, Cash-Collateral und Index-Futures (DAX-Future bei EXS1, MDAX-Mini-Future bei EXS3; Gewicht jeweils ~0 %), Xtrackers zusätzlich einen Geldmarktfonds.

### Inferences
- Physisch voll replizierende ETFs halten die Indexmitglieder 1:1; Abweichungen sind nur um den Umstellungstag herum zu erwarten (ETF baut am Effektivtag um). Da die Quellen T-1 liefern, liegt der Lag typischerweise bei 1 Handelstag nach dem Effektivtag – für einen wöchentlichen Batch irrelevant.
- Deka liefert mit dem Blatt "Indexzusammensetzung" sogar die Indexliste selbst, was das Problem "Fonds hält evtl. vorübergehend einen alten Wert" umgeht.
- Swap-ETFs (Amundi MDAX) sind ungeeignet, weil deren Holdings ein Substitute Basket sind, nicht die Indexmitglieder.

### Gaps
- Keine Primärquelle gefunden, die den genauen Veröffentlichungszeitpunkt/Lag der Holdings-Dateien (iShares, Deka) dokumentiert; Angabe T-1 basiert auf einer einzigen Beobachtung.
- Nicht überprüft, ob die Ströer-für-Hugo-Boss-Änderung ein tatsächlicher MDAX-Wechsel (Sept.-Review 2026) ist – wird von den zwei ETF-Quellen übereinstimmend gezeigt, aber nicht mit STOXX/Deutsche Börse abgeglichen.
- Verhalten bei Fast-Entry/Fast-Exit nicht beobachtet.

## 4. Historische Stabilität der URLs/Formate, Anti-Bot-Maßnahmen

### Takeaway
Die jahrelang genutzten iShares-`.ajax`-CSVs sind im September 2026 weltweit (US/UK/DE) weggebrochen – ein Musterbeispiel für die Fragilität solcher Quellen. Die Ersatz-API ist neu und undokumentiert. Deka und DWS liefern derzeit statische Download-Endpunkte ohne erkennbare Bot-Abwehr.

### Cited Findings
- Issue vom 23.09.2026: iShares liefert HTML für CSV-URLs an Nicht-Browser-Clients; Header-Spoofing hilft nicht; Folge sind stille Fehlschläge in Scrapern. — [kovagent/indexkit Issue #95](https://github.com/kovagent/indexkit/issues/95)
- Beobachtet: Deutsche iShares-.ajax-URL liefert 404 (nicht HTML), UK/US liefern HTML mit Status 200.
- Beobachtet: Die neue iShares-Produktseite lädt Holdings clientseitig über `blackrock.com/varnish-api/.../api/v2/get-product-data`; der Aufruf funktionierte ohne Browser-Header, Cookies oder Consent – derzeit also keine Bot-Abwehr auf der API. — [iShares Core DAX](https://www.ishares.com/de/privatanleger/de/produkte/251464/)
- Mehrere Open-Source-Projekte bauten auf dem alten .ajax-Muster auf ([talsan/ishares](https://github.com/talsan/ishares), [nikulpatel3141/ETF-Scraper](https://github.com/nikulpatel3141/ETF-Scraper), [danielsteman/etf-constituents](https://github.com/danielsteman/etf-constituents)) – deren Stand in Bezug auf die Umstellung nicht geprüft.

### Inferences
- Für den Batch: ETF-Holdings nur als eine von mehreren Quellen einsetzen, mit strikter Validierung (JSON/XLSX-Signatur, Zeilenzahl 40/50, Stichtag-Alter) und Fallback auf die CSV. Das entspricht dem Projektprinzip "Robustheit vor Performance".
- Zwei unabhängige Emittenten (BlackRock + Deka) senken das Risiko, dass beide gleichzeitig brechen.

### Gaps
- Keine Langzeit-Evidenz zur Stabilität der Deka-URL (`composition_download`) oder des DWS-Exports gefunden (keine GitHub-/Forenberichte).
- Keine Aussagen von BlackRock zur Absicht hinter der Umstellung (Anti-Scraping vs. reines Redesign).

## 5. Nutzungsbedingungen für automatisierten Download (private Nutzung)

### Takeaway
Keine der geprüften Seiten erlaubt automatisierten Abruf ausdrücklich. iShares-Bedingungen verbieten Vervielfältigung ohne Genehmigung; DWS sperrt den Export-Pfad per robots.txt; Deka sperrt ihn nicht. Für einen wöchentlichen privaten Abruf von 2–4 Dateien ist das Risiko praktisch gering, aber rechtlich eine Grauzone.

### Cited Findings
- iShares-Website-Bedingungen (laut Suchergebnis-Auszug): "Jegliche Vervielfältigung von Informationen oder Daten … erfordert die vorherige Genehmigung durch BNBV"; Nutzer dürfen keine Sekundärwerke aus den Informationen verkaufen, kopieren, publizieren, verbreiten … — [Suchtreffer iShares Deutschland/ETF-FAQ-Umfeld](https://www.ishares.com/de/professionelle-anleger/de/wissen-und-service/etf-faq) (Hinweis: der genaue Fundort der Bedingungen konnte nicht direkt verifiziert werden; "BNBV" deutet auf BlackRock (Netherlands) B.V.)
- Beobachtet, robots.txt: `www.ishares.com` und `www.blackrock.com` sperren u. a. `/*.dl$`, `?truepdf`, Sign-on-Pfade, aber **nicht** `/varnish-api/` bzw. `.ajax`. `etf.dws.com` sperrt `/etfdata/*` und `/export/*`. `www.deka-etf.de` sperrt nur `/market_makers/*`. — [ishares robots](https://www.ishares.com/robots.txt), [blackrock robots](https://www.blackrock.com/robots.txt), [DWS robots](https://etf.dws.com/robots.txt), [Deka robots](https://www.deka-etf.de/robots.txt)
- DWS-XLSX enthält einen Haftungsausschluss ("dient ausschließlich zu Informationszwecken…"), Deka-XLSX einen Blatt "Lizenzhinweise" mit Haftungsausschluss und STOXX-Markenhinweis ("DAX® Index ist das geistige Eigentum … der ISS STOXX Index GmbH"). — eigene Abrufe
- Justiziabler Hintergrund: Indexzusammensetzungen gehören lizenzrechtlich dem Indexanbieter (ISS STOXX); die Emittenten veröffentlichen Holdings aus Transparenzpflichten. — [Deka DAX composition_download, Blatt "Lizenzhinweise"](https://www.deka-etf.de/etfs/Deka-DAX-UCITS-ETF/composition_download)

### Inferences
- Private, nicht weiterverbreitete Nutzung eines wöchentlichen Abrufs ist mit hoher Wahrscheinlichkeit unproblematisch, sollte aber schonend erfolgen (1 Request pro Datei/Woche, ehrlicher User-Agent, keine Weiterveröffentlichung der Rohdaten). DWS-Export respektvollerweise meiden (robots.txt).
- Keine Rechtsberatung; die genauen AGB-Texte wurden nicht vollständig gelesen.

### Gaps
- iShares-/Deka-/DWS-Nutzungsbedingungen nicht im Volltext abgerufen; keine explizite Aussage zu automatisiertem Zugriff (Scraping-Klausel) gefunden.
- Keine Amundi- oder Invesco-Bedingungen geprüft.
