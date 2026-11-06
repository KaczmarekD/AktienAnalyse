# Vorprüfung zu ADR-0011

> **Stand:** 06.11.2026. Vorarbeit für die Entscheidung über
> [ADR-0011](../../adr/0011-fundamentale-anker-und-belegte-faktoren.md), wie dort unter „Warum
> noch vorgeschlagen“ verlangt: (1) Vergleich der Rankings v1 und v2 per Rescore, (2) Prüfung des
> Immobilien-EBIT. Punkt (3), eine neue JKP-Auswertung, entfällt: Seit der
> [Recherche](../fundamentalanalyse-sota/bericht.md) vom September gibt es keine neuen Daten, die
> sie ändern würden.
>
> Nichts davon ändert Ranking oder Mail. Die Skripte unter [skripte/](skripte/) sind Prototypen
> für diese Prüfung, kein Produktcode; die Ergebnisse liegen unter [notizen/](notizen/).

## Kurzfassung

- **Immobilien-EBIT:** Die Zeile „EBIT“ von Yahoo enthält bei Vonovia, LEG, TAG und Aroundtown
  die Bewertungsergebnisse nach IAS 40. Die Bedingung aus Punkt 4 des ADR ist damit erfüllt:
  Immobilien gehören unter dieselbe Branchenregel wie Banken und Versicherer.
- **Das verzerrt schon heute:** Die Aufwertungen von 2025 machen die Immobilienwerte im
  v1-Ranking billig. Alle vier stehen in den Top 20 (LEG 8, Aroundtown 11, TAG 17, Vonovia 18).
- **v1 gegen v2:** v2 ändert das Ranking deutlich. Von den Top 20 bleiben 9. Die Rangfolge der
  Titel, die in beiden bewertet sind, korreliert mit 0,69 (Spearman). Ohne Composite und im
  Abschnitt „Finanzwerte“ stehen 6 Titel (Banken und Versicherer) oder 10 mit Immobilien, wie
  im ADR geschätzt.
- **Richtung:** v2 bevorzugt Titel mit starkem Cashflow und hoher Bilanzqualität (Ionos,
  Nemetschek, Knorr-Bremse, DHL). Bilanzlastige und nach Buchwert billige Titel rutschen ab
  (Versicherer, Immobilien, Porsche SE, Lufthansa). Das ist eine Aussage über die
  Zusammensetzung, nicht über künftige Renditen: Einen Backtest schließt CLAUDE.md aus.
- **Lücken der Regel:** flatexDEGIRO ist eine Bank, heißt bei Yahoo aber „Capital Markets“ und
  fällt durch die Branchenregel. TKMS ist erst seit 2025 eigenständig und hat noch keinen
  F-Score.

## 1. Enthält das EBIT der Immobilienwerte Bewertungsergebnisse?

**Methode:** Die Jahresabschlüsse der vier Titel von Yahoo (Abruf 06.11.2026,
[realestate.py](skripte/realestate.py), Daten in [realestate.json](notizen/realestate.json)),
verglichen mit den Bewertungsergebnissen aus den Geschäftsberichten.

Werte in Mrd. €:

| Titel | Jahr | EBIT | Operating Income | Jahresergebnis |
|---|---|---:|---:|---:|
| Vonovia | 2025 | 3,44 | 0,47 | 3,72 |
| Vonovia | 2024 | 0,27 | 1,00 | −0,90 |
| Vonovia | 2023 | −8,37 | 1,05 | −6,29 |
| Vonovia | 2022 | −0,02 | −2,10 | −0,64 |
| LEG Immobilien | 2025 | 1,30 | 0,68 | 1,46 |
| LEG Immobilien | 2024 | 0,32 | 0,55 | 0,07 |
| LEG Immobilien | 2023 | −1,82 | 0,56 | −1,57 |
| LEG Immobilien | 2022 | 0,65 | 0,25 | 0,23 |
| TAG Immobilien | 2025 | 0,53 | 0,29 | 0,09 |
| TAG Immobilien | 2024 | 0,19 | 0,29 | 0,12 |
| TAG Immobilien | 2023 | −0,43 | 0,29 | −0,40 |
| TAG Immobilien | 2022 | 0,20 | 0,24 | 0,11 |
| Aroundtown | 2025 | 1,04 | 0,93 | 0,87 |
| Aroundtown | 2024 | 0,68 | 0,93 | 0,26 |
| Aroundtown | 2023 | −2,62 | 0,90 | −1,83 |
| Aroundtown | 2022 | −0,24 | 0,85 | −0,53 |

**Belege aus den Geschäftsberichten 2023**, dem Jahr der großen Abwertungen:

- Vonovia: Ergebnis aus der Bewertung der Investment Properties −10,65 Mrd. €
  ([Geschäftsbericht 2023](https://report.vonovia.com/2023/q4/en/?p=12526)).
- LEG: Wertminderung des Bestands um 11,9 %
  ([Präsentation FY 2023](https://irpages2.eqs.com/Download/Companies/legimmobilien/Presentations/LEG_FY_2023_Presentation.pdf)),
  Jahresfehlbetrag rund 1,57 Mrd. €
  ([Simply Wall St](https://simplywall.st/stocks/de/real-estate-management-and-development/etr-leg/leg-immobilien-shares/news/leg-immobilien-full-year-2023-earnings-eps-beats-expectation)).
- TAG: Bewertungsergebnis −705,2 Mio. € ([Pressemitteilung FY 2023](https://www.tag-ag.com/news/pressemitteilungen/meldung/operationally-successful-fy-2023-for-tag-sales-results-in-poland-exceed-guidance-significantly-increased-net-liquidity-from-disposals-in-germany-ltv-stable-despite-portfolio-devaluation-2721883)).
  Operating Income 0,29 minus 0,71 ergibt fast genau Yahoos EBIT von −0,43.
- Aroundtown: Neubewertungen rund −3,2 Mrd. €
  ([IPE Real Assets](https://realassets.ipe.com/propertyeu/germanys-aroundtown-portfolio-devalued-by-32bn-for-2023-makes-an-annual-loss-of-24b/10082522.article)).

**Ergebnis:** Yahoos „EBIT“ folgt den Bewertungsergebnissen: tief negativ 2023, über dem Operating
Income 2025, als die Werte wieder stiegen. Unser `FIELD_MAP` nimmt für `ebit` zuerst die Zeile
„EBIT“. Damit hängen EV/EBIT und ROIC bei Immobilien am Bewertungszyklus statt am Mietgeschäft.

**Auch „Operating Income“ ist kein sauberer Ersatz:** Bei Vonovia schwankt es zwischen −2,10
(2022) und 0,47 (2025), obwohl sich das Mietgeschäft kaum ändert. Ein Tausch der Zeile löst das
Problem also nicht. Das stützt den Weg des ADR, für Immobilien die EV- und Ertragskennzahlen gar
nicht zu rechnen.

**Wirkung heute (v1, Woche vom 30.10.2026):** Mit Operating Income statt EBIT fielen die
Immobilienwerte so (nur zur Größenordnung, siehe oben):

| Titel | EV/EBIT heute | mit Operating Income | Rang v1 heute | Rang mit Operating Income |
|---|---:|---:|---:|---:|
| Vonovia | 17,3 | 125,9 | 18 | 33 |
| LEG Immobilien | 9,9 | 18,8 | 8 | 16 |
| TAG Immobilien | 11,0 | 19,9 | 17 | 28 |
| Aroundtown | 14,6 | 16,4 | 11 | 10 |

## 2. Rescore v1 gegen v2

**Grundlage:** die echte Woche vom 30.10.2026 aus der Replay-Fixture
(`tests/fixtures/replay/2026-10-30_scoring-run-1.json`, 90 Titel). Gespeicherte Wochen von der
NAS gibt es noch nicht. Die neuen Kennzahlen stammen deshalb aus einem Abruf bei Yahoo vom
06.11.2026 ([fetch_raw.py](skripte/fetch_raw.py)): Jahresabschlüsse, Aktienanzahl, Splits und
400 Tage Kurse. Die Abschlüsse sind in beiden Fällen dieselben (Geschäftsjahr 2025).

**Methode** ([rescore.py](skripte/rescore.py)):

- v1 rechnet mit der Konfiguration der Fixture über `va_scoring.domain.scoring.score` und
  reproduziert die gespeicherten Scores exakt (größte Abweichung 1e−16).
- v2 nimmt dieselbe Funktion mit dem Katalog aus ADR-0011, Punkt 2: Value `ev_ebit`, `p_fcf`,
  `net_share_issuance`; Quality `roic`, `fcf_margin`, `f_score`, `operating_accruals`,
  `cfo_assets`. Gewichte und Schwellen bleiben.
- **Variante A:** Banken und Versicherer (Yahoo-`industry` beginnt mit „Banks“ oder
  „Insurance“) ohne die Kennzahlen aus Punkt 3. **Variante B:** dazu Immobilien („Real
  Estate“, „REIT“), wie es Teil 1 nahelegt.
- Momentum-Regel aus Punkt 5 im Value-Trap-Flag (Value ≥ 0,70, Momentum-Rang ≤ 0,30, F-Score ≤ 3).

**Vereinfachungen des Prototyps**, die F2.1 bis F2.3 im Produkt genauer machen:

- F-Score und Kapitalumschlag mit der Bilanzsumme am Jahresende statt am Jahresanfang; fehlt
  eines der neun Signale, gibt es keinen F-Score.
- Netto-Emission: Bei 22 Titeln aus der Aktienserie von Yahoo (12 Monate, um Splits bereinigt),
  bei 67 aus der Bilanz (Jahresende gegen Vorjahr), bei einem gar nicht. Im Produkt kommt sie aus
  der gespeicherten Serie (F1.3).
- Momentum aus bereinigten Schlusskursen von Yahoo, im Produkt aus `close`, `dividend` und
  `split` (F2.3).

**Abdeckung** bei den 84 Titeln über der Größenschwelle, die keine Banken oder Versicherer sind:
F-Score 82, Accruals 84, CFO/Bilanzsumme 84, Netto-Emission 83, Momentum 84. Ohne F-Score
bleiben Porsche SE (eine Holding ohne Bruttomarge) und TKMS (kein Vorjahr), ohne Netto-Emission
TKMS.

**Ergebnis:**

| | Variante A | Variante B |
|---|---:|---:|
| Titel mit Composite (v1: 88) | 79 | 75 |
| davon in den Top 20 von v1 und v2 | 9 | 9 |
| davon in den Flop 10 von v1 und v2 | 5 | 5 |
| Rangkorrelation (Spearman) der gemeinsamen Titel | 0,69 | 0,73 |
| Value-Trap über Quality | BMW | BMW |
| Value-Trap über Momentum | keiner | keiner |

Top 20 (fett: neu gegenüber v1):

| Rang | v1 (heute) | v2, Variante A | v2, Variante B |
|---:|---|---|---|
| 1 | Allianz | Fresenius Medical Care | Deutsche Telekom |
| 2 | Porsche SE | Deutsche Telekom | Fresenius Medical Care |
| 3 | freenet | Bilfinger | **TUI** |
| 4 | Talanx | **TUI** | Bilfinger |
| 5 | Hannover Rück | freenet | **DHL** |
| 6 | Münchener Rück | **DHL** | freenet |
| 7 | Bilfinger | **Ionos Group** | **Ionos Group** |
| 8 | LEG Immobilien | **Zalando** | **Zalando** |
| 9 | Fresenius Medical Care | Ströer | Ströer |
| 10 | Deutsche Telekom | Henkel | Henkel |
| 11 | Aroundtown | Heidelberg Materials | Heidelberg Materials |
| 12 | Heidelberg Materials | **TKMS** | **TKMS** |
| 13 | Krones | **flatexDEGIRO** | **flatexDEGIRO** |
| 14 | Henkel | **Nemetschek** | **Nemetschek** |
| 15 | Deutsche Lufthansa | Krones | Krones |
| 16 | BMW | **Nordex** | **Nordex** |
| 17 | TAG Immobilien | **United Internet** | **United Internet** |
| 18 | Vonovia | Fuchs | **Knorr-Bremse** |
| 19 | Ströer | **Knorr-Bremse** | Fuchs |
| 20 | Fuchs | **Mercedes-Benz Group** | **GEA Group** |

**Größte Bewegungen** (Variante A, Rang v1 → v2):

- hoch: TKMS 51 → 12, Nordex 54 → 16, Nemetschek 52 → 14, Zalando 45 → 8, Ionos 43 → 7,
  Bayer 70 → 37, Adidas 78 → 46, MTU 61 → 29
- runter: RWE 26 → 70, LEG 8 → 42, Vonovia 18 → 50, RTL 35 → 66, Aroundtown 11 → 39,
  Traton 41 → 68, TAG 17 → 41, Porsche SE 2 → 24

Die Immobilienwerte fallen schon in Variante A aus den Top 20, weil v2 KBV und Shareholder Yield
abschaltet, bei denen sie vorn lagen.

**Abschnitt „Finanzwerte“** (Variante A, gerechtfertigtes KBV = (ROE − 2 %) / (8 % − 2 %),
Standardwerte aus ADR-0011, Punkt 6):

| Titel | Branche (Yahoo) | KBV | KGV | ROE | gerechtf. KBV |
|---|---|---:|---:|---:|---:|
| Allianz | Insurance - Diversified | 2,64 | 14,4 | 17,2 % | 2,53 |
| Commerzbank | Banks - Regional | 1,21 | 14,5 | 7,8 % | 0,96 |
| Deutsche Bank | Banks - Regional | 0,71 | 9,4 | 8,8 % | 1,14 |
| Hannover Rück | Insurance - Reinsurance | 2,64 | 12,8 | 20,4 % | 3,07 |
| Münchener Rück | Insurance - Reinsurance | 2,13 | 10,7 | 18,4 % | 2,73 |
| Talanx | Insurance - Diversified | 2,30 | 12,7 | 18,4 % | 2,74 |

Heute stehen vier dieser sechs in den Top 6 von v1, getragen von EV/EBIT und P/FCF, die bei
Versicherern nichts aussagen (Allianz: EV/EBIT 4,2, P/FCF 5,4). Commerzbank und Deutsche Bank
haben seit M1 schon heute keinen Composite.

**Auffälligkeiten:**

- **flatexDEGIRO** (Rang 13 in v2) ist eine Bank, Yahoo führt es als „Capital Markets“. Der
  Unternehmenswert ist durch Kundengelder negativ (EV/EBIT −7,6, fällt aus dem Ranking), der Free
  Cashflow enthält Kundeneinlagen. Die Präfixliste der Branchenregel sollte „Capital Markets“
  enthalten. Deutsche Börse und DWS (auch „Financial Services“) haben schon heute kein EV/EBIT
  und bleiben, wie sie sind.
- **TKMS** (Rang 12 in v2) ist seit Oktober 2025 eigenständig: ein Geschäftsjahr, also kein
  F-Score und keine Netto-Emission. Die FCF-Marge von 36 % kommt vermutlich von Anzahlungen auf
  Marineaufträge. Das gilt in v1 genauso, nur wiegt FCF in v2 schwerer.
- **Momentum-Regel:** In dieser Woche erfüllt kein Titel alle drei Bedingungen. Sie ist eine
  Sicherung für fallende Messer, kein Filter, der wöchentlich greift.

## 3. Was das für die Entscheidung heißt

Die Prüfungen bestätigen den Vorschlag in zwei Punkten und zeigen eine Lücke:

1. **Branchenregeln** beheben eine Verzerrung, die heute wirkt: Versicherer auf den Plätzen 1 und
   4 bis 6, Immobilien mit Aufwertungsgewinnen in den Top 20. Das spricht dafür, sie zuerst
   umzusetzen.
2. **Immobilien** gehören dazu (Punkt 4 ist erfüllt).
3. **Lücke:** Die Präfixliste braucht „Capital Markets“ für flatexDEGIRO.

Die neuen Faktoren verschieben das Ranking spürbar zu Cashflow und Bilanzqualität. Ob das besser
ist, kann der Rescore nicht zeigen; dafür steht weiter die externe Evidenz aus der Recherche
(JKP-Faktordaten für Deutschland). Jede Änderung bleibt über Profil-Versionen umkehrbar.

Möglichkeiten:

- **Annehmen mit Ergänzungen:** Immobilien und „Capital Markets“ fest in der Branchenregel, die
  Branchenregeln (F2.4) als erstes Paket von Track F2. Danach F2.1 bis F2.3 und F2.5.
- **Teilweise annehmen:** nur die Branchenregeln jetzt, die neuen Faktoren und das Profil v2
  nach einigen Wochen gespeicherter Daten von der NAS.
- **Zurückstellen**, bis die NAS mehrere Wochen gesammelt hat, und den Rescore dann auf diesen
  Wochen wiederholen.

## Grenzen

- Eine Woche, kein Zeitverlauf. Mit gespeicherten Wochen von der NAS lässt sich der Vergleich mit
  denselben Skripten wiederholen; `fetch_raw.py` wäre dann durch die Daten aus F1 zu ersetzen.
- Die Rohdaten von Yahoo sind der Stand vom 06.11.2026, die Kurse der Fixture der vom 30.10.2026.
- Der Prototyp rechnet die neuen Kennzahlen vereinfacht (siehe Methode). Die Pakete F2.1 bis F2.3
  legen sie mit Tests gegen von Hand nachgerechnete Werte fest.
