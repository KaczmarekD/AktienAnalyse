# Recherche: Depot-Daten und Bankzugang (04.11.2026, Live-Prüfung 06.11.2026)

Notizen zur Recherche für die [Depot-Spezifikation](../architecture/depot/README.md). Geprüft am
04.11.2026 per Websuche, auf den Seiten der Anbieter und im Quellcode von yfinance und
python-fints. Am 06.11.2026 folgten Live-Abrufe von yfinance 1.8, OpenFIGI und dem ESMA-Register
([Live-Prüfung](#live-prüfung-06112026)). Der DKB-Zugang ist noch nicht live geprüft.

Kennzeichnung: **[B]** belegt durch eine Quelle, **[A]** Annahme oder Schluss daraus. Vor der
Umsetzung eines Pakets die betroffenen Punkte erneut prüfen, vor allem die mit [A].

## Anlass

Der Nutzer wünscht (04.11.2026):

- mehrere Nutzer im UI, je Nutzer Depots,
- beliebige Aktien, ETFs und Anleihen, deren Analyse und News,
- Berichte mit eigenem Intervall, Hinweise zur Verbesserung des Depots,
- später einen nur lesenden Zugang zu den Beständen über eine Depot-API, generisch über Ports,
  zuerst für die DKB.

## DKB-Zugangswege

| Weg | Machbar | Bestand | Anmeldung | Risiko |
|---|---|---|---|---|
| FinTS 3.0 (PIN/TAN) | ja, mit Person am Gerät | ja (HKWPD) | PIN plus Freigabe in der DKB-App bei jedem Abruf | Umzug der Depotabwicklung zu Upvest 2026/27 |
| PSD2 / XS2A | nein | nein | – | – |
| Web-API der Banking-Seite (dkb-robo) | nein | technisch ja | Captcha seit 11/2025 | Umgehung des Bot-Schutzes, GPL-3.0 |
| Exportdatei | nur Teile | kein Bestandsexport | – | – |
| Aggregatoren (finAPI u. a.) | technisch ja | ja | Freigabe bei jedem Abruf | ab 60–200 EUR im Monat |

### FinTS

- [B] Adresse seit 25.11.2024 `https://fints.dkb.de/fints`, vorher
  `banking-dkb.s-fints-pt-dkb.de/fints30`. Benutzerkennung ist der Anmeldename, die Kunden-ID
  bleibt leer.
  Quellen: [ifun.de, 18.11.2024](https://www.ifun.de/dkb-neue-freigabemethoden-und-serverwechsel-fuer-finanzsoftware-243660/),
  [teltarif, 18.11.2024](https://www.teltarif.de/arch/2024/kw47/s97127.html).
- [B] Die DKB erklärte im August 2024, FinTS bleibe, empfahl Drittsoftware aber XS2A
  ([ifun.de](https://www.ifun.de/mac-banking-mit-moneymoney-wird-fuer-dkb-kunden-umstaendlich-238119/)).
- [B] TAN-Verfahren: DKB-App (entkoppelt, Code 940), chipTAN manuell und QR. TAN2go endete am
  22.11.2024 ([python-fints #178](https://github.com/raphaelm/python-fints/issues/178),
  [#183](https://github.com/raphaelm/python-fints/issues/183)).
- [B] Bestand über HKWPD funktioniert auf dem neuen Server. Ein Nutzer zitiert im September 2025
  eine MT535-Zeile der DKB mit Kaufdatum und Kaufkurs je Posten. Der reguläre Ausdruck in
  python-fints erkennt sie nicht, der Einstand geht verloren. Das Issue ist offen
  ([#195](https://github.com/raphaelm/python-fints/issues/195)). [A] Wir brauchen einen eigenen
  Parser für MT535.
- [B] Depotumsätze (HKWDU) kennt python-fints nicht, es gibt nur HKWPD5/6
  ([depot.py](https://github.com/raphaelm/python-fints/blob/master/fints/segments/depot.py)).
  [A] Ob die DKB HKWDU anbietet, zeigt ihr Parameterteil (HIWDUS in der BPD).
- [B] Freigabe nötig „bei jedem Login und jedem Umsatzabruf“
  ([Lexware-Hilfe](https://help.lexware.de/de-form/articles/548915-lexware-office-dkb-bank-anbinden)),
  ein Nutzer von python-fints bestätigt das (#183). [A] Die DKB nutzt die 90/180-Tage-Ausnahme
  für direkten FinTS-Zugang nicht. Ein Abruf ohne Person am Gerät, etwa im Wochenlauf, geht nicht.
- [B] python-fints 5.0.0 (06.01.2026) und 5.0.1 (09.10.2026), LGPL-3.0
  ([PyPI](https://pypi.org/project/fints/)). Der Fehler mit dem entkoppelten Verfahren bei der DKB
  ist behoben, im Mai 2026 lief es mit 5.0.0 (#183). Offen: #212 (TAN-Verfahren bleibt auf „999“).
- [B] Die DKB verlagert die Wertpapierabwicklung von dwpbank zu Upvest, Neukunden ab 2026,
  Bestandskunden ab 2027 ([finanz-szene, 08.09.2025](https://finanz-szene.de/digital-banking/dkb-verlagert-wertpapier-abwicklung-auf-upvest-und-trennt-sich-von-dwp-bank/)).
  [A] Ob HKWPD danach bleibt, sagt niemand.
- [B] Lesende Zugänge oder eingeschränkte Rechte bietet die DKB nicht an (gesucht, nichts
  gefunden). Die PIN erlaubt technisch auch Aufträge. Jeder Auftrag bräuchte aber eine eigene
  Freigabe in der App mit seinen Details.

### FinTS-Produktregistrierung

- [B] Seit 01.08.2019 lassen Banken nur registrierte Produkte zu. Die Nummer kommt nach
  vollständigem Formular meist in 10–15 Arbeitstagen
  ([fints.org](https://www.fints.org/de/hersteller/produktregistrierung)).
- [B] Kostenlos, auch für „Privatanwender-Software“
  ([SWEN-Doku](https://maltewinckler.github.io/swen/concepts/fints/)).
- [B] Im Mai 2026 scheiterte eine frisch registrierte Nummer zunächst bei der DKB, eine zufällige
  Nummer ergibt „Could not find system_id“ (#183). [A] Die Liste der Bank hinkte hinterher. Fremde
  Nummern nicht nutzen.

### PSD2, Web-API, Exporte, Aggregatoren

- [B] PSD2 regelt nur Zahlungskonten (Art. 4 Nr. 12, Art. 67). Der EuGH (C-191/17, 04.10.2018)
  versteht darunter Konten, von denen direkt gezahlt werden kann
  ([Bird & Bird](https://www.twobirds.com/en/insights/2018/global/the-cjeu-provides-clarity-on-the-definition-of-a-payment-account)).
  [A] Ein Depot fällt nicht darunter. XS2A verlangt außerdem eine BaFin-Erlaubnis und ein
  eIDAS-Zertifikat.
- [B] dkb-robo liest Depotpositionen (ISIN/WKN, Menge, Kurs, Börse, Währung), letzte Version
  0.31.2 vom 05.08.2025. Seit 01.11.2025 schützen Friendly Captcha und Myra-Bot-Erkennung den
  Login, die veröffentlichte Version funktioniert nicht mehr
  ([Issue #92](https://github.com/grindsa/dkb-robo/issues/92)).
- [B] Kein CSV- oder Excel-Export des Bestands, nur die Ansicht
  ([Acutic, 14.08.2026](https://acutic.io/de/blog/dkb-depot-export), Blog eines Anbieters). Im
  Postfach liegen PDFs: Abrechnungen, Jahressteuerbescheinigung, Erträgnisaufstellung
  ([DKB-FAQ](https://www.dkb.de/fragen-antworten/was-kann-das-postfach-im-banking)). CSV gibt es
  nur für Umsätze des Girokontos. [A] Ein Depotauszug als PDF existiert wegen MiFID II
  wahrscheinlich, sein Aufbau ist nicht dokumentiert.
- [B] Portfolio Performance importiert DKB-PDFs (Kauf, Verkauf, Ausschüttung, Sparplan)
  ([Forum](https://forum.portfolio-performance.info/t/pdf-import-von-dkb/4449)).
- [B] finAPI liest DKB-Depots über FinTS/XS2A. „Access for own use“ (bis 10 eigene Konten) kostet
  200 EUR im Monat ([Preise](https://www.finapi.io/en/prices/)). Tink: Investments-API vorhanden,
  DKB nicht bestätigt, nur B2B. GoCardless: nur Zahlungskonten. Plaid: Investments nur USA/Kanada.

### Umgang mit der PIN

- [B] Der Zustand, den python-fints mit `deconstruct()` liefert, enthält die PIN nicht
  ([Doku](https://python-fints.readthedocs.io/en/latest/client.html)). Zu speichern sind nur
  System-ID, Bankparameter und gewähltes TAN-Verfahren.
- [A] Weil die DKB ohnehin bei jedem Abruf eine Freigabe verlangt, bringt eine gespeicherte PIN
  nichts. Die PIN wird je Abruf eingegeben und bleibt im Speicher.
- [A] Der Logger `fints` darf nie auf DEBUG stehen. Ohne HTTPS ginge die PIN im LAN im Klartext
  über Port 8080.

## News

| Quelle | Abdeckung | Grenzen | Einschätzung |
|---|---|---|---|
| yfinance `get_news` | Symbole bei Yahoo | 1.7.0 nutzt `/xhr/ncp`, laut Kommentar in 1.8.0 abgeschaltet | nach Upgrade auf 1.8 erste Quelle |
| EQS News (DGAP) | Ad-hoc, Directors' Dealings, Stimmrechte | kein öffentlicher RSS-Feed, keine API | nur über Mail-Alarme |
| Google News RSS | alles | robots.txt sperrt `/rss`, Nutzungsbedingungen verbieten Roboter | nicht abrufen, nur als Link im UI |
| GDELT DOC 2.0 | weltweit, mit Sprachfilter | Abgleich über Firmennamen, etwa 1 Anfrage je 5 s | Ersatzquelle |
| Finnhub | nur Nordamerika | Free Tier | für US-Titel |
| Marketaux | auch deutsche Titel | 100 Anfragen am Tag, 3 Artikel je Anfrage | Ersatz, Nutzungsbedingungen unklar |
| NewsAPI | – | Free Tier nur für Entwicklung | ausgeschlossen |
| Alpha Vantage | USA | 25 Anfragen am Tag | kaum nützlich |
| EODHD | weltweit | Free Tier etwa 2 News-Anfragen am Tag | nur bezahlt sinnvoll |

- [B] yfinance 1.8.0 erschien am 03.11.2026 ([PyPI](https://pypi.org/project/yfinance/)). `get_news`
  nutzt dort einen neuen GraphQL-Endpunkt
  ([base.py 1.8.0](https://raw.githubusercontent.com/ranaroussi/yfinance/1.8.0/yfinance/base.py)),
  1.7.0 noch `/xhr/ncp`. 1.8.0 verlangt `curl_cffi>=0.17`. [A] Upgrade nach einigen Wochen
  Wartezeit und mit `make check-j4125`.
- [B] `get_news(count, tab="news"|"all"|"press releases")`, neueste zuerst. Die Nachrichten folgen
  `yf.config.locale`, laut Doku hat Yahoo nur für manche Locales News
  ([Doku](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_news.html)).
  [A] Für `.DE`-Symbole eher wenig, oft englisch.
- [B] Yahoo hat keine deutschen Directors' Dealings (`insider_transactions` leer bei 8 Testtiteln,
  [Live-Test 30.09.2026](fundamentalanalyse-sota/notizen/datenquellen-live-tests.md)).
- [B] EQS News bietet nur Watchlist-Alarme per Mail oder Push
  ([eqs-news.com](https://www.eqs-news.com/)). [A] Ein eigenes Postfach für diese Alarme ließe sich
  per IMAP lesen. EQS ist nicht der einzige Verbreiter (dpa-AFX, pressetext).
- [B] BaFin-Datenbank der Directors' Dealings hält Einträge nur 12 Monate
  ([BaFin](https://www.bafin.de/EN/PublikationenDaten/Datenbanken/DirectorsDealings/directorsdealings_node_en.html)).
  Bundesanzeiger und Unternehmensregister haben keine API. ESAP kommt mit API ab Juli 2027.
- [B] Google News: [robots.txt](https://news.google.com/robots.txt) und
  [Nutzungsbedingungen](https://www.google.com/intl/en_us/terms_google_news.html).
- [B] GDELT: „unlimited and unrestricted use“ mit Quellenangabe
  ([about](https://www.gdeltproject.org/about.html), [DOC 2.0](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)).
- [B] Marketaux [Preise](https://marketaux.com/pricing), [Bedingungen](https://marketaux.com/tos);
  NewsAPI [Preise](https://newsapi.org/pricing); EODHD [News-API](https://eodhd.com/financial-apis/financial-news-api).

**Speichern (keine Rechtsberatung):** [B] Das Leistungsschutzrecht der Presseverleger
([§ 87g UrhG](https://www.gesetze-im-internet.de/urhg/__87g.html)) erfasst nicht: Tatsachen,
private oder nicht kommerzielle Nutzung durch einzelne Nutzer, Links, einzelne Wörter oder sehr
kurze Auszüge. [A] Schlagzeile, Link, Zeitpunkt, Quelle und höchstens ein bis zwei Sätze sind
unbedenklich. Volltexte nicht speichern. Die Bedingungen einer API können strenger sein als das
Gesetz.

## ETFs

- [B] yfinance `funds_data` liest `quoteType`, `summaryProfile`, `topHoldings` und `fundProfile`
  ([funds.py 1.8.0](https://raw.githubusercontent.com/ranaroussi/yfinance/1.8.0/yfinance/scrapers/funds.py)):
  Überblick, Kosten (`annualReportExpenseRatio`), Fondsvolumen, Anlageklassen, Sektoren,
  **nur die 10 größten Positionen**, bei Renten-ETFs Duration und Laufzeit.
  [A] TER und Rentenfelder fehlen bei UCITS-ETFs oft, Live-Test steht aus.
- [B] Vollständige Bestände: iShares über die JSON-API, die wir schon nutzen (ISIN, Gewicht,
  Sektor, Land), Deka als XLSX. Xtrackers technisch als XLSX, robots.txt sperrt aber `/etfdata/*`.
  Amundi, Vanguard, SPDR: nichts Maschinenlesbares geprüft
  ([Notizen 29.09.2026](dax-mdax-datenquellen/notizen/etf_holdings.md)).
- [A] Swap-ETFs halten einen Ersatzkorb. Für die Durchschau zählt dort der Index.
- [B] justETF hat keine API.

## Wertpapiere und Kennungen

- [B] OpenFIGI ohne Schlüssel 25 Anfragen pro Minute mit je 10 Aufträgen, mit kostenlosem
  Schlüssel 250 pro Minute mit je 100. Liefert FIGI, Ticker, Börse, Wertpapierart, Name
  ([Doku](https://www.openfigi.com/api/documentation)).
- [B] Die Deutsche Börse veröffentlicht täglich eine CSV aller handelbaren Instrumente für Xetra
  und Frankfurt (ISIN, WKN, Kürzel, Art, Währung)
  ([Seite](https://www.deutsche-boerse-cash-market.com/dbcm-en/instruments-statistics/all-tradable-instruments/boersefrankfurt)).
  [A] Die aktuelle Download-Adresse ist nicht geprüft.
- [B] `yf.Ticker("<ISIN>")` löst die ISIN über `Search` auf und nimmt den ersten Treffer.
- [B] Unser Adapter rechnet Berichts- in Handelswährung um (`_statement_fx`).
  [A] London notiert in `GBp` (Pence), dafür braucht es eine Regel „/100“. Ausländische Aktien
  auf Xetra (z. B. `APC.DE`) haben EUR-Kurse, aber teils lückenhaftere Daten als das
  Heimat-Listing. Fundamentaldaten dann vom Heimat-Listing, Kurs von Xetra.
- [B] EZB-Referenzkurse täglich ([eurofxref-daily.xml](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml)).

## Anleihen

- [B] Bundesbank: tägliche Kurs- und Renditeliste der börsennotierten Bundeswertpapiere als XLSX
  (ISIN, Kupon, Fälligkeit, Kurs, Rendite, Stückzinsen)
  ([Liste](https://bundesbank.de/action/de/810554/bbksearch)).
- [B] Bundesbank SDMX-REST liefert CSV, z. B. die 10-jährige Nullkuponrendite
  ([Abruf](https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZAR.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?lastNObservations=3&format=csv)),
  dazu die täglichen Svensson-Parameter. Die Zinskurve lässt sich lokal berechnen.
- [B] ESMA FIRDS: wöchentliche Voll- und tägliche Änderungsdateien als XML mit Fälligkeit und Zins
  ([Spezifikation](https://www.esma.europa.eu/sites/default/files/library/esma65-8-9568_-_firds_reference_data_functional_specifications_v2.10.pdf)).
  [A] Große Dateien, eine Abfrage je ISIN ist nicht geprüft.
- [B] Für Unternehmensanleihen gibt es keine freie offizielle Kurs-API. [A] Yahoo hat praktisch
  keine europäischen Einzelanleihen.
- [A] Rendite, Duration, Stückzinsen und Abstand zur Bundkurve lassen sich in reinem Python
  rechnen. Typische Lücken: Zinsmethode, unregelmäßige Kuponperioden, Clean/Dirty, Kündigungsrechte,
  Floater und Inflationsanleihen, Rating.

## Live-Prüfung (06.11.2026)

Abgerufen mit yfinance 1.8.0 in einer Wegwerf-Umgebung, dazu OpenFIGI und das ESMA-Register
direkt. Alle Punkte hier sind **[B]** durch eigenen Abruf.

**yfinance-News (1.8.0):**

- `get_news(count=10, tab="news")` liefert für SAP.DE, ALV.DE, HNR1.DE und AAPL je 10 Meldungen.
  Felder je Meldung: `title`, `summary`, `description`, `pubDate`, `provider.displayName`,
  `canonicalUrl.url`, `contentType`, `finance`.
- Alle Meldungen sind **englisch**, die Anbieter meist US-Portale (Simply Wall St., Motley Fool,
  Zacks, Investing.com). Mit Locale `de-DE` kommt **nichts**.
- Für ETFs (EUNL.DE) gibt es keine Meldungen.
- `finance.stockTickers` nennt die Titel einer Meldung. SAP erscheint dort als US-Symbol `SAP`,
  Allianz als `ALV.DE`. Getaggt heißt nur „erwähnt“: Bei SAP.DE waren 3 von 10 Meldungen
  Vergleichsartikel mit bis zu 10 Tickern (z. B. „DocuSign vs. Monday.com“), bei ALV.DE ging es
  einmal um Medicare.

**yfinance `funds_data`:**

| Feld | EUNL.DE (MSCI World) | EUNH.DE (Euro-Staatsanleihen) |
|---|---|---|
| TER (`Annual Report Expense Ratio`) | 0,0020, plausibel | 0,0009, plausibel |
| Fondsvolumen (`Total Net Assets`) | 308.088,2, Einheit unklar | 0,0, fehlt |
| Top-Positionen | 10 (NVIDIA, Apple, Microsoft …) | keine |
| Sektoren | ja | leer |
| Anlageklassen | ja (99,6 % Aktien) | ja (99,9 % Anleihen) |
| Länder | gibt es nicht | gibt es nicht |
| Duration, Laufzeit | leer | 2,73 und 9,08 Jahre; die Duration ist für diesen Fonds unplausibel |
| Kategorie | leer | leer |

**OpenFIGI ohne Schlüssel** (`/v3/mapping`, HTTP 200):

| ISIN | Treffer | Beispiel |
|---|---|---|
| DE0001102580 (Bund 0 % 2032) | 1 | `DBR 0 02/15/32`, `securityType2 = Govt` |
| DE000A383J95 (Deutsche Bank 4 % 2028, kündbar) | 1 | `DB V4 07/12/28 EMTN`, `Corp` |
| US0378331005 (Apple) | 303 | ein Listing je Börse, ohne `exchCode`-Filter unbrauchbar |
| IE00B4L5Y983 (iShares Core MSCI World) | 198 | `securityType2 = Mutual Fund` |

`securityType2` trennt Staatsanleihe, Unternehmensanleihe, Aktie und Fonds. Für die Auflösung
braucht die Anfrage den `exchCode` (Xetra: `GY`).

**ESMA FIRDS je ISIN** (Suche des Registers,
`registers.esma.europa.eu/solr/esma_registers_firds/select?q=isin:…`, ohne Schlüssel):

| ISIN | CFI | Kupon | Fälligkeit | Stückelung | LEI |
|---|---|---|---|---|---|
| DE0001102580 | DBFTFB | 0 | 2032-02-15 | 0,01 | 529900AQBND3S6YJLY83 |
| DE000A383J95 | DTVUGB | 4 | 2028-07-12 | 100.000 | 7LTWFZYICNSX8D621K86 |
| DE0007164600 (SAP) | ESVUFB | – | – | – | 529900D6BF99LW9R2E68 |
| IE00B4L5Y983 | CEOGES | – | – | – | 549300QS4Q1IT6XCA514 |

- Ein Datensatz je Handelsplatz (22 bis 96). Maßgeblich ist der mit `latest_received_flag = 1`.
- Der CFI-Code gibt die Anlageklasse (E Aktie, D Schuldtitel, C Fonds) und bei Anleihen die
  Zinsart (dritte Stelle: F fest, V variabel). Die Deutsche-Bank-Anleihe ist trotz Kupon 4 als
  variabel markiert und laut Name ab 2027 kündbar: eine Sonderform.
- Die LEI gibt es für Anleihen, Aktien und Fonds. Damit lassen sich Aktie und Anleihe desselben
  Emittenten zusammenführen.
- [A] Die Solr-Suche ist nicht als API dokumentiert. Dokumentierter Rückfallweg sind die
  FIRDS-Dateien.

**Yahoo und Anleihen:** `yf.Ticker("DE0001102580")` bricht mit „Invalid ISIN number“ ab. Yahoo
kennt die Bundesanleihe nicht.

## Empfehlungen

Stand nach der Live-Prüfung vom 06.11.2026.

| Bereich | Erste Quelle | Ersatz |
|---|---|---|
| Bestand DKB | FinTS mit Person am Gerät (PIN je Abruf, Freigabe in der App) | eigene CSV; CSV von Portfolio Performance |
| News allgemein | yfinance ab 1.8 (englisch, mit Relevanzregel) | GDELT DOC (Name plus `sourcelang:german`) für deutsche Meldungen |
| News USA | Finnhub | Marketaux |
| Pflichtmitteilungen | EQS-Mail-Alarme in eigenem Postfach, per IMAP gelesen | BaFin-Datenbank, ab 2027 ESAP |
| ETF: TER, Sektoren, Anlageklassen | yfinance `funds_data` | Anbieterdateien |
| ETF: Bestände, Länder, Volumen, Renten-Kennzahlen | Anbieterdateien (iShares JSON, Deka XLSX) | yfinance nur Top 10, ohne Länder |
| ISIN → Listing, Anlageklasse | OpenFIGI (mit `exchCode`, ohne Schlüssel möglich) | yfinance-Suche, CSV der Deutschen Börse |
| Anleihen, Stammdaten | ESMA FIRDS je ISIN (Kupon, Fälligkeit, Stückelung, Rang, LEI, CFI) | Bankabruf, Hand |
| Emittent (LEI) | ESMA FIRDS | – |
| Bundesanleihen, Kurse | Bundesbank XLSX und SDMX | Hand |
| andere Anleihen, Kurse | Bankabruf | Hand, Renten-ETF als Näherung |
| Währungen | EZB-Referenzkurse | yfinance `=X` |

**Nicht bauen:** dkb-robo bzw. Scraping der Banking-Seite, PSD2, Aggregatoren, Google-News-RSS
im Abruf, Bundesanzeiger-Scraping, Speichern von Volltexten.

**Live prüfen:**

1. ✅ yfinance 1.8 `get_news` für `.DE`-Symbole mit Locale `de-DE` und `en-US` (06.11.2026)
2. ✅ `funds_data` für EUNL.DE und einen Renten-ETF (06.11.2026)
3. ✅ OpenFIGI für eine Bundesanleihe und eine Unternehmensanleihe (06.11.2026)
4. ✅ FIRDS-Abfrage je ISIN (06.11.2026)
5. ⏳ FinTS bei der DKB mit eigener Produktnummer: BPD auf HIWPDS und HIWDUS prüfen, MT535 mit
   Einstand. Braucht die Produktnummer und den User am Gerät (Spike am Anfang von D9).
