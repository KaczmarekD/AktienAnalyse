# Finanzportale als Scraping-Quelle für DAX/MDAX-Konstituenten (Stand: 29.09.2026)

Methodik-Hinweis: Alle "beobachteten" Status-Codes/Formate stammen aus eigenen Live-Abfragen am 29.09.2026 (~19:00 UTC) per `curl` mit Browser-User-Agent (Chrome 128, Windows) von einem privaten deutschen Anschluss aus, ohne Cookies, ohne JavaScript. Diese Beobachtungen haben keine externe URL als Beleg außer dem Endpoint selbst; sie sind als "[eigener Test]" markiert.

## Frage 1: Welche Portale bieten eine DAX/MDAX-Konstituentenseite oder einen JSON-Endpoint (mit ISIN/WKN/Symbol)? Exakte URLs, HTTP-Status, Format

### Takeaway
Zwei Quellen liefern heute ohne JavaScript, ohne Signatur-Header und ohne Cookies vollständige, maschinenlesbare Listen: (1) die onvista-JSON-API `GET https://api.onvista.de/api/v1/indices/{id}/constituents` (DAX-ID 20735, MDAX-ID 323547) mit ISIN, WKN **und Xetra-Symbol**, und (2) die interne Deutsche-Börse-API `POST https://api.boerse-frankfurt.de/v1/search/equity_search` mit Indexfilter, die ISIN und WKN (aber kein Ticker-Symbol) liefert. Beide gaben exakt 40 (DAX) bzw. 50 (MDAX) Werte zurück und stimmen inhaltlich überein. finanzen.net, investing.com, marketscreener und comdirect blockierten die Abfrage (403/401); TradingView ist JS-gerendert.

### Cited Findings

**onvista (api.onvista.de) – beste Einzelquelle**
- `GET https://api.onvista.de/api/v1/indices/20735/constituents` → HTTP 200, `application/json`, ~88 KB, `{"expires":…, "list":[…40 Einträge…], "total":40}` [eigener Test] — [Endpoint](https://api.onvista.de/api/v1/indices/20735/constituents)
- `GET https://api.onvista.de/api/v1/indices/323547/constituents` → HTTP 200, JSON, `total: 50`, `list` hat 50 Einträge (keine Paginierung nötig) [eigener Test] — [Endpoint](https://api.onvista.de/api/v1/indices/323547/constituents)
- Feldstruktur pro Eintrag (beobachtet): `instrument.name`, `instrument.isin`, `instrument.wkn`, `instrument.symbol`, `instrument.homeSymbol`, `instrument.entityType` ("STOCK"), `marketCapitalization` + `isoCurrencyMarketCapitalization` ("EUR"), `cnDivYield`, `cnPer`, `cnPeg`, `quote.market.name` ("Xetra"), `quote.market.codeExchangeGoogle` ("ETR"), `quote.isoCurrency` [eigener Test] — [Endpoint](https://api.onvista.de/api/v1/indices/20735/constituents)
- Alle 90 Einträge hatten ein nicht-leeres `symbol`/`homeSymbol` (z. B. ADS, AIR, ALV, SAP, AMV0, TKMS, R3NK, 8TRA, P911, FPE3, SHA0, G24) [eigener Test].
- Die HTML-Seiten `https://www.onvista.de/index/einzelwerte/DAX-Index-20735` und `…/MDAX-Index-323547` antworten ebenfalls mit HTTP 200 (~500 KB, ISINs im HTML enthalten, vermutlich eingebettetes Next.js-JSON) [eigener Test].
- Die Basis-URL `https://api.onvista.de/api/v1` wird auch vom Community-Wrapper pyOnvista verwendet — [pyOnvista api.py](https://github.com/cloasdata/pyOnvista/blob/master/src/pyonvista/api.py)

**Börse Frankfurt / Deutsche Börse (api.boerse-frankfurt.de)**
- `www.boerse-frankfurt.de/...` antwortet mit HTTP 308 (nginx) und leitet auf `https://live.deutsche-boerse.com/...` um; die Seite `https://live.deutsche-boerse.com/index/mdax/zugehoerige-werte` ist eine Angular-SPA (`<app-root>`, `ng-version="20.3.31"`, `main.*.js`) → Daten nicht ohne JS im HTML [eigener Test].
- Der Relaunch auf die neue Plattform live.deutsche-boerse.com erfolgte am 26.06.2024 — [Deutsche Börse Relaunch](https://live.deutsche-boerse.com/en/relaunch)
- Der API-Host heißt weiterhin `api.boerse-frankfurt.de` [eigener Test].
- **Funktionierender Aufruf:** `POST https://api.boerse-frankfurt.de/v1/search/equity_search`, `Content-Type: application/json`, Body `{"indices":["DE0008469008"],"lang":"de","offset":0,"limit":100}` → HTTP 200, `{"data":[…], "recordsTotal":40}`; mit MDAX-ISIN `DE0008467416` → `recordsTotal: 50` [eigener Test].
- Feldstruktur pro Eintrag: `isin`, `wkn`, `name.originalValue`, `slug`, `keyData` (u. a. `marketCapitalisation`, `priceBookRatio`, `priceEarningsRatio`, `dividendYield`), `overview` (u. a. `exchange: "XETR"`, `lastPrice`), `performance`, `sustainability`. **Kein Ticker/Xetra-Kürzel** [eigener Test].
- `GET` auf `equity_search` → HTTP 405 "Method 'GET' is not supported" [eigener Test].
- Mit Header `Origin: https://www.boerse-frankfurt.de` → HTTP 403 "Invalid CORS request"; ohne Origin-Header oder mit `Origin: https://live.deutsche-boerse.com` → 200 [eigener Test]. Wichtig für Implementierung: **keinen alten Origin setzen**.
- Der ältere Endpoint `GET /v1/data/index_constituents?isin=…&limit=50&offset=0` liefert HTTP 200 mit leerem Body `{}` – sowohl mit als auch ohne Signatur-Header, also faktisch tot [eigener Test].
- `GET /v1/data/price_information/single?isin=DE0007164600&mic=XETR` liefert Kursdaten mit HTTP 200 auch ohne Signatur-Header [eigener Test].
- Die Python-Bibliothek bf4py bietet eine Funktion `index_instruments(...)` im Modul `bf4py.general` — [bf4py GitHub](https://github.com/joqueka/bf4py). Ob sie noch mit dem aktuellen API-Stand funktioniert, wurde nicht getestet.

**finanzen.net**
- `https://www.finanzen.net/index/dax/werte` und `…/mdax/werte` → HTTP 403, ~390 Byte Body (Bot-Block auf Edge-Ebene, keine Cloudflare-Signatur im Body); `robots.txt` selbst lieferte 200 [eigener Test].

**ariva.de**
- `https://www.ariva.de/dax-index/kurse` → HTTP 200, ~275 KB statisches HTML, im ersten Abruf 12 eindeutige DE000-ISINs gefunden; ein zweiter Abruf wenige Minuten später lieferte 0 ISINs → inkonsistent/gedrosselt oder Paginierung [eigener Test]. Keine vollständige Liste mit ISIN für alle 40 verifiziert.

**comdirect**
- `https://www.comdirect.de/inf/indizes/werte/DE0008469008` → HTTP 401 (54 KB Fehlerseite) [eigener Test].

**boerse.de**
- `https://www.boerse.de/indizes/Dax/DE0008469008` → HTTP 200, statisches HTML, 18 ISINs; MDAX-Seite `…/indizes/MDax/DE0008467416` → 200 mit 18 ISINs → nur Teilliste im initialen HTML (nicht vollständig) [eigener Test].

**TradingView**
- `https://www.tradingview.com/symbols/XETR-DAX/components/` → HTTP 200, 254 KB, aber nur 1 ISIN im HTML, Treffer auf Cloudflare/Captcha-Strings → JS-gerendert, keine ISINs [eigener Test].

**investing.com**
- `https://www.investing.com/indices/germany-30-components` → HTTP 403, Cloudflare-Challenge-Seite [eigener Test].

**marketscreener**
- `https://www.marketscreener.com/quote/index/DAX-8905/components/` → HTTP 403 [eigener Test].

### Inferences
- Für einen Docker-Batch ohne Headless-Browser kommen realistisch nur onvista-API und Deutsche-Börse-API in Frage. onvista ist die bequemere Primärquelle, weil sie das Xetra-Symbol direkt mitliefert; die Deutsche-Börse-API ist die "autoritativere" Quelle (Indexanbieter-nahe) als Cross-Check über ISIN.
- Die onvista-Index-IDs (20735/323547) sind interne `entityValue`-IDs und kein offizieller Schlüssel; sie sind seit Jahren in den URL-Slugs stabil, sollten aber in `Settings` konfigurierbar sein.
- Plausibilitätsprüfung im Code sinnvoll: `total == 40` bzw. `== 50`, sonst Fallback auf CSV.

### Gaps
- Offizielle Stoxx/Qontigo-Komponentenlisten (stoxx.com, Composition-Files) wurden in diesem Teilauftrag nicht geprüft.
- ariva.de-Vollständigkeit und Paginierungsschema nicht geklärt.
- Ob bf4py `index_instruments` auf den heutigen (leeren) `index_constituents`-Endpoint oder auf `equity_search` zugreift, nicht verifiziert.

## Frage 2: Anti-Bot-Maßnahmen, Signatur-Header, Rate Limits, Consent-Walls

### Takeaway
Die historisch berüchtigten Börse-Frankfurt-Signaturheader (`Client-Date`, `X-Client-TraceId`, `X-Security`) sind im September 2026 für die getesteten Endpoints **nicht mehr erforderlich**; stattdessen prüft die API den `Origin`-Header (CORS). onvista-API und -HTML zeigten keinen Bot-Schutz; finanzen.net, investing.com (Cloudflare), marketscreener und comdirect blocken Skript-Zugriffe hart. Dokumentierte Rate-Limits wurden für keinen Anbieter gefunden.

### Cited Findings
- Das 2022 analysierte Schema der Börse-Frankfurt-API: `Client-Date` = aktuelle Zeit als ISO-String (`toISOString()`), `X-Security` = MD5 von lokaler Zeit im Format `YYYYMMDDHHmm`, `X-Client-TraceId` = MD5 aus Zeitstempel + vollständiger URL + fixem Salt `w4icATTGtnjAZMbkL3kJwxMfEAKDa3MN` (Stand Februar 2022) — [lwthiker: Analyzing a stock exchange's API](https://lwthiker.com/reversing/2022/02/12/analyzing-stock-exchange-api.html). **Veraltet** (vor dem Relaunch Juni 2024).
- Eigener Test: `price_information/single` und `equity_search` liefern ohne diese Header dieselben Daten wie mit ihnen (HTTP 200) [eigener Test].
- Eigener Test: Header `Origin: https://www.boerse-frankfurt.de` → 403 "Invalid CORS request" [eigener Test].
- Eigener Test: investing.com Response enthält Cloudflare-Challenge ("Just a moment"/cf-chl), HTTP 403 [eigener Test].
- onvista `robots.txt` enthält Kommentare: "Spidering is not allowed by our terms and conditions" / "Authorised spidering is subject to permission"; `https://api.onvista.de/robots.txt` enthält `User-agent: * / Disallow: /` [eigener Test] — [onvista robots.txt](https://www.onvista.de/robots.txt), [api.onvista.de robots.txt](https://api.onvista.de/robots.txt)
- `live.deutsche-boerse.com/robots.txt` bzw. `www.boerse-frankfurt.de/robots.txt` enthält nur einen Sitemap-Verweis, keine Disallow-Regeln [eigener Test].
- Der Relaunch-Text von Deutsche Börse erwähnt, das neue Angebot "meets growing requirements for security" — [Deutsche Börse Relaunch](https://live.deutsche-boerse.com/en/relaunch)
- Consent-Walls: Bei den API-Abrufen (onvista, Deutsche Börse) trat keine Consent-Seite auf; die HTML-Seiten wurden ohne Cookie-Consent ausgeliefert [eigener Test].

### Inferences
- Da die Signaturheader-Logik jederzeit reaktiviert werden könnte, lohnt es sich, sie optional (Feature-Flag) im Client vorzuhalten – Aufwand ~10 Zeilen `hashlib`.
- Bei einem wöchentlichen Batch mit 2–4 Requests ist das Rate-Limit-Risiko vernachlässigbar.
- finanzen.net/investing.com wären nur mit Headless-Browser/Stealth-Tricks nutzbar – unverhältnismäßig und rechtlich heikler (Umgehung technischer Schutzmaßnahmen).

### Gaps
- Keine offiziell dokumentierten Rate-Limits für api.onvista.de oder api.boerse-frankfurt.de gefunden.
- Ob die 403 bei finanzen.net IP-/Land-basiert (z. B. Rechenzentrums-IPs) oder UA-basiert ist, nicht untersucht; von einer Synology im Heimnetz evtl. anders.

## Frage 3: Stabilitätshistorie (GitHub-Projekte, Libraries, Breakage)

### Takeaway
Für beide APIs existieren mehrere inoffizielle Community-Wrapper (bf4py, boerse-frankfurt-api auf PyPI; pyOnvista, pyonvista-v2, vistafetch, gonvista). Die Börse-Frankfurt-API hat nachweislich einen Umbruch erlebt (Signaturheader 2022, Relaunch Juni 2024, Domainwechsel mit 308-Redirect, `index_constituents` inzwischen leer). onvista's `api/v1` ist seit Jahren der gleiche Pfad.

### Cited Findings
- bf4py: Python-Paket für "undocumented API" von boerse-frankfurt.de (Aktien, Unternehmensinfos, News, Anleihen, Fonds, Derivate); enthält `index_instruments(...)`; Hinweis, dass Daten meist 15 Minuten verzögert sind — [bf4py GitHub](https://github.com/joqueka/bf4py)
- PyPI-Paket `boerse-frankfurt-api` (Python >= 3.9) existiert — [PyPI boerse-frankfurt-api](https://pypi.org/project/boerse-frankfurt-api/)
- Ein Open-Source-Projekt (monize) hat per PR eine Deutsche-Börse-Anbindung für Wertpapiere ergänzt (Hinweis auf aktuelle Nutzung der API) — [kenlasko/monize PR #1437](https://github.com/kenlasko/monize/pull/1437) (Inhalt nicht im Detail geprüft)
- stocks_dl: Bibliothek zum Download von Börsendaten, u. a. Börse Frankfurt — [msrst/stocks_dl](https://github.com/msrst/stocks_dl)
- pyOnvista (cloasdata) nutzt Basis-URL `https://api.onvista.de/api/v1`; pyonvista-v2 erweitert es um Fundamentaldaten; weitere: bossenti/vistafetch, Go-Paket relusc/gonvista — [GitHub Topic onvista](https://github.com/topics/onvista), [pyonvista-v2 PyPI](https://pypi.org/project/pyonvista-v2/), [gonvista](https://pkg.go.dev/github.com/relusc/gonvista)
- Relaunch boerse-frankfurt.de → live.deutsche-boerse.com am 26./27.06.2024 — [Deutsche Börse Relaunch](https://live.deutsche-boerse.com/en/relaunch); ARIVA war Dienstleister des Relaunches — [ariva.ag Facelift](https://ariva.ag/facelift-fuer-die-boerse-frankfurt-ariva-begleitet-den-relaunch/)
- Eigener Test: `index_constituents` liefert `{}` (tot), Kursendpoints laufen weiterhin unter api.boerse-frankfurt.de [eigener Test].

### Inferences
- Die Existenz mehrerer aktiver Wrapper deutet darauf hin, dass beide APIs über Jahre einigermaßen stabil sind, aber ohne Vertrag jederzeit brechen können – exakt das Risikoprofil, das CLAUDE.md für yfinance bereits akzeptiert (Retry + Fallback-CSV).
- Zwei unabhängige Quellen parallel abzufragen und nur bei Übereinstimmung (oder mindestens Plausibilität 40/50) zu übernehmen, ist robuster als eine einzige.

### Gaps
- Keine konkreten Issue-Threads/Blogposts gefunden, die einen Ausfall von `api.onvista.de/api/v1/indices/.../constituents` dokumentieren (weder positiv noch negativ belegt).
- Letzte Commit-Daten von bf4py/pyOnvista konnten aus den abgerufenen Seiten nicht ermittelt werden.
- Foren (wertpapier-forum.de, Reddit) nicht durchsucht (Tool-Budget).

## Frage 4: Aktualität bei Indexänderungen

### Takeaway
Beide API-Quellen spiegelten am 29.09.2026 bereits die letzte reguläre Überprüfung (wirksam 21.09.2026: Ströer rein, Hugo Boss raus aus dem MDAX) sowie die Dezember-2025-Änderungen (Aumovio und TKMS rein) korrekt wider. Innerhalb von ≤ 8 Tagen nach Wirksamkeit waren beide aktuell.

### Cited Findings
- STOXX kündigte am 03.09.2026 die planmäßigen Anpassungen an; zum 21.09.2026 tauschen Ströer und Hugo Boss die Plätze in MDAX und SDAX — [STOXX Ankündigung Sep. 2026](https://stoxx.com/stoxx-announces-scheduled-adjustments-to-dax-blue-chip-indices-sep-3-2026/), [Deutsche Börse: Ströer steigt in den MDAX auf](https://live.deutsche-boerse.com/nachrichten/auswahlindizes-stroeer-steigt-in-den-mdax-auf), [finanzen.ch Überblick](https://www.finanzen.ch/nachrichten/aktien/ueberblick-anstehende-indexanderungen-zum-21-september-1036530895)
- Aumovio und TKMS ersetzten Gerresheimer und HelloFresh im MDAX, wirksam 22.12.2025 — [Deutsche Börse: Aumovio und TKMS steigen in den MDAX auf](https://live.deutsche-boerse.com/nachrichten/auswahlindizes-aumovio-und-tkms-steigen-in-den-mdax-auf), [Handelsblatt](https://www.handelsblatt.com/unternehmen/industrie/aktienindizes-boersenneulinge-tkms-und-aumovio-ziehen-in-mdax-ein/100180884.html)
- Eigener Test onvista MDAX (50): enthält Aumovio (DE000AUM0V10, AMV0), TKMS (DE000TKMS001, TKMS), RENK Group (R3NK), Ströer (SAX), kein Hugo Boss, kein Gerresheimer, kein HelloFresh [eigener Test].
- Eigener Test Deutsche-Börse-API MDAX (50): enthält AUMOVIO SE, TKMS AG & Co KGaA, RENK Group AG, Ströer SE & Co. KGaA, kein Hugo Boss; DAX (40): u. a. Scout24, Continental, Siemens Energy [eigener Test]. Beide Namenslisten deckungsgleich.
- Deutsche Börse erläutert den Ablauf der Indexanpassungen — [Der Ablauf bei Indexanpassungen](https://live.deutsche-boerse.com/wissen/wertpapiere/aktien/indexanpassungen)

### Inferences
- Für einen wöchentlichen Screener ist die Aktualität beider APIs mehr als ausreichend; die Wikipedia-Tabellen sind vermutlich die langsamere Quelle.
- Wegen Fast-Entry/Fast-Exit-Regeln und Spin-offs (z. B. Aumovio aus Continental) können Änderungen auch außerhalb der Quartalstermine auftreten – ein wöchentlicher Live-Abruf fängt das ab, die statische CSV nicht.

### Gaps
- Genauer Tag, an dem onvista/Deutsche Börse die Änderung vom 21.09.2026 übernommen haben (am Stichtag selbst oder später), nicht messbar – nur "spätestens 29.09.2026".
- Renks MDAX-Aufnahmedatum nicht recherchiert.

## Frage 5: Nutzungsbedingungen / Rechtliches

### Takeaway
onvista verbietet automatisierte Abfragen ausdrücklich (AGB Ziff. 3.3, Stand 02.09.2026) und sperrt `api.onvista.de` per robots.txt komplett. Deutsche Börse beansprucht Urheber-/Datenbankrechte an Website-Inhalten und verbietet Vervielfältigung ohne Zustimmung, ein explizites Scraping-Verbot für live.deutsche-boerse.com wurde nicht gefunden. Rechtlich (§ 87b UrhG) ist das wöchentliche Abrufen von 90 Namen+ISINs bei rein privater Nutzung ein "unwesentlicher Teil" mit geringem Risiko, ein AGB-Verstoß bleibt aber ein vertragliches (Sperr-)Risiko.

### Cited Findings
- onvista AGB Ziff. 3.3: "Eine automatisierte Abfrage des von onvista bereitgestellten Content oder von Teilen hieraus ist ohne ausdrückliche schriftliche Einwilligung von onvista in jeglicher Form unzulässig." Ziff. 3.1: Nutzung nur für eigene Zwecke, keine Weitergabe an Dritte. Ziff. 3.4: sofortige Sperrung bei Verstoß möglich. Versionsdatum 02.09.2026 — [onvista AGB](https://www.onvista.de/agb.html)
- Deutsche Börse: Website-Design inkl. Texte, Grafiken, Layout und Datenbanken sind urheberrechtlich geschützt; Inhalte dürfen ohne vorherige schriftliche Zustimmung nicht kopiert, reproduziert, veröffentlicht oder verbreitet werden — [Deutsche Börse: Intellectual Property Rights and Rights of use](https://www.deutsche-boerse.com/dbg-en/meta/intellectual-property-rights-and-rights-of-use); Haftungsausschluss für live.deutsche-boerse.com — [Disclaimer Börse Frankfurt](https://live.deutsche-boerse.com/en/disclaimer-en)
- § 87b UrhG: Datenbankhersteller hat ausschließliches Recht zur Vervielfältigung/Verbreitung der Datenbank insgesamt oder eines nach Art oder Umfang wesentlichen Teils; wiederholte und systematische Entnahme unwesentlicher Teile steht dem gleich, wenn sie der normalen Auswertung zuwiderläuft — [freiRecht § 87b UrhG](https://freirecht.de/g/UrhG:87b), [ratgeberrecht.eu Datenbankschutz](https://www.ratgeberrecht.eu/aktuell/urheberrechtlicher-schutz-von-datenbanken/)
- Screen-Scraping kann rechtswidrig sein, wenn durch viele kleine Abfragen nach und nach der gesamte Datenbankbestand ausgelesen wird; Privatpersonen dürfen Datenbanken für rein persönliche Zwecke nutzen — [WBS: Ist Screen Scraping legal?](https://www.wbs.legal/urheberrecht/ist-screen-scraping-legal-15081/), [dury.de Webscraping und Datenbankurheberrecht](https://www.dury.de/onlinerecht-blog-menue/731-webscraping-screenscraping-und-das-datenbankurheberrecht)
- § 44b UrhG (Text und Data Mining): Vervielfältigungen rechtmäßig zugänglicher Werke für TDM erlaubt, sofern kein maschinenlesbarer Nutzungsvorbehalt erklärt ist — [dejure § 44b UrhG](https://dejure.org/gesetze/UrhG/44b.html)

### Inferences
- Eine Liste von 40/50 Indexmitgliedern mit ISIN ist ein kleiner Ausschnitt des jeweiligen Datenbestands und zudem öffentlich bekannte Tatsache (vom Indexanbieter veröffentlicht) – § 87b-Risiko bei privater, nicht weiterverbreiteter Nutzung gering. Allerdings: Der Report wird per Mail verschickt – solange nur an sich selbst, bleibt es privat.
- Die robots.txt von api.onvista.de (`Disallow: /`) plus AGB 3.3 können als maschinenlesbarer TDM-Vorbehalt i. S. v. § 44b Abs. 3 gewertet werden – § 44b hilft bei onvista also nicht.
- Pragmatische Einordnung: Unter AGB-Gesichtspunkten ist die Deutsche-Börse-API etwas "sauberer" als onvista (kein explizites Automatisierungsverbot gefunden, robots ohne Disallow), aber keine der Quellen ist lizenziert. Keine Rechtsberatung.

### Gaps
- Die vollständigen Nutzungsbedingungen von live.deutsche-boerse.com konnten nicht abgerufen werden (`/nutzungsbedingungen` und `/en/terms-of-use` → 404).
- AGB von finanzen.net, ariva, comdirect, boerse.de, investing, marketscreener, TradingView nicht einzeln geprüft (für die Architektur irrelevant, da technisch geblockt bzw. unvollständig).
- Keine deutsche Rechtsprechung speziell zu privatem Scraping von Indexlisten gefunden.

## Frage 6: Mapping auf Yahoo-Finance-Ticker

### Takeaway
Das onvista-Feld `symbol`/`homeSymbol` entspricht dem Xetra-Kürzel; `symbol + ".DE"` ergab in allen Stichproben einen gültigen Yahoo-Ticker (z. B. AMV0.DE, P911.DE, AIXA.DE, AT1.DE). Eine Yahoo-Suche per ISIN liefert dagegen teils nicht den Xetra-Ticker (Airbus → AIR.PA, TKMS → TKMS.F) – für die Deutsche-Börse-API (nur ISIN/WKN) ist deshalb eine ISIN→Ticker-Auflösung mit Bevorzugung der `.DE`-Notierung nötig.

### Cited Findings
- Eigener Test Yahoo-Suche `https://query2.finance.yahoo.com/v1/finance/search?q=<ISIN>`: DE000AUM0V10 → AMV0.DE; DE000PAG9113 → P911.DE, P911.F; DE000A0WMPJ6 → AIXA.DE; LU1673108939 → AT1.DE; NL0000235190 → nur AIR.PA; DE000TKMS001 → nur TKMS.F [eigener Test].
- onvista liefert für alle 90 Werte das Xetra-Symbol (vollständige Liste beobachtet: DAX u. a. ADS AIR ALV BAS BAYN BEI BMW BNR CBK CON DTG DBK DB1 DHL DTE EOAN FRE FME G1A HNR1 HEI HEN3 HOT IFX MBG MRK MTX MUV2 QGEN RHM RWE SAP G24 SIE ENR SHL SY1 VOW3 VNA ZAL; MDAX u. a. AIXA AT1 AMV0 NDA AG1 BC8 GBF EVD DHER LHA DEZ DWS ELG EVK FTK FRA FNTN FPE3 HLE HAG IOS JEN SDF KGX KBX KRN LXS LEG NEM NDX1 P911 PAH3 PUM RAA R3NK RRTL SZG SRT3 SHA0 WAF SAX SMHN TEG TLX TKA TKMS 8TRA TUI1 UTDI WCH) [eigener Test] — [onvista DAX](https://api.onvista.de/api/v1/indices/20735/constituents), [onvista MDAX](https://api.onvista.de/api/v1/indices/323547/constituents)
- onvista liefert zusätzlich `quote.market.name = "Xetra"` / `codeExchangeGoogle = "ETR"`, d. h. das Symbol bezieht sich auf die Xetra-Notierung [eigener Test].

### Inferences
- Empfohlene Pipeline: onvista `symbol` → `f"{symbol}.DE"`; ISIN beibehalten als Primärschlüssel für Cross-Check mit der Deutsche-Börse-API und mit der bestehenden Fallback-CSV.
- Ausländische DAX/MDAX-Mitglieder (Airbus NL, Qiagen NL, Aroundtown LU, RTL LU) haben ebenfalls Xetra-Kürzel (AIR, QGEN, AT1, RRTL); `AIR.DE` existiert bei Yahoo, taucht aber in der ISIN-Suche nicht an erster Stelle auf – Symbol-basiertes Mapping ist daher zuverlässiger als ISIN-Suche.
- Ob jedes `.DE`-Symbol in yfinance Fundamentaldaten liefert (z. B. TKMS.DE, AMV0.DE bei Neulistings), ist separat zu prüfen; eine kurze Validierung (`yf.Ticker(t).fast_info`) mit Fallback auf die CSV-Zuordnung wäre sinnvoll.

### Gaps
- Nicht alle 90 `symbol + ".DE"`-Kombinationen gegen Yahoo verifiziert (nur 6 Stichproben per ISIN-Suche).
- TKMS.DE wurde von der Yahoo-ISIN-Suche nicht zurückgegeben – ob der Ticker in yfinance existiert, ist offen.
