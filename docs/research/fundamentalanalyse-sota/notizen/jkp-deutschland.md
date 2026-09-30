# JKP-Faktordaten: Was trug in Deutschland? (Auswertung vom 30.09.2026)

Die Auswertung soll die Faktorwahl des Screeners mit veröffentlichten Faktorrenditen belegen. Sie ist
**keine Rückrechnung des Screeners**, denn Backtesting gehört laut [CLAUDE.md](../../../../CLAUDE.md)
nicht in dieses Projekt.

## Daten

- **Quelle:** Global Factor Data von Jensen, Kelly und Pedersen ([jkpfactors.com](https://jkpfactors.com/)).
  Das Update vom April 2026 enthält Monatsdaten bis 12/2025. Wer die Daten nutzt, muss
  [Jensen/Kelly/Pedersen (2023)](https://doi.org/10.1111/jofi.13249) zitieren.
- **Lizenz:** Die Daten stehen unter CC BY-NC 4.0, der Code unter MIT. Diese Auswertung ist privat
  und nicht kommerziell. Die Rohdaten liegen nicht im Repo.
- **Abruf am 30.09.2026, ohne Login:**
  `https://jkpfactors-data.s3.amazonaws.com/public/[<region>]_[<theme>]_[monthly]_[vw_cap].zip`.
  Die eckigen Klammern werden als `%5B`/`%5D` kodiert. Verwendet wurden die Regionen `deu` und
  `developed` sowie die Themes `all_factors`, `all_themes` und `mkt`. Welche Kombinationen es gibt,
  steht in `public/availability.json`. Auswertungen nach Größenklassen (`public/factor/…`) gibt es
  nur für die USA, für Deutschland also keine Large-Cap-Teilmenge.
- **Konstruktion** laut [Dokumentation](https://jkpfactors-data.s3.amazonaws.com/documents/Documentation.pdf),
  Abschnitt 2:
  - Terzile je Land und Monat. Die Grenzen stammen aus den Nicht-Micro-Caps (größer als das
    20. NYSE-Perzentil), die Micro-Caps werden danach einsortiert.
  - Gewichtung nach Marktwert, gekappt beim 80. NYSE-Perzentil („capped value weight“).
  - Der Faktor ist das Terzil mit der laut Originalstudie höchsten erwarteten Rendite minus das
    Terzil mit der niedrigsten (long-short).
  - Bilanzdaten fließen erst vier Monate nach Geschäftsjahresende ein.
  - Ein Theme ist der gleichgewichtete Durchschnitt seiner vorzeichenbereinigten Faktoren.
  - Alle Renditen sind in USD.

## Lesehilfe

- Jede Zelle zeigt die annualisierte mittlere Monatsrendite in % mit dem t-Wert in Klammern.
  „ab Start“ reicht vom ersten Monat mit Daten (Spalte „DE Start“) bis 12/2025.
- Die Renditen sind long-short über alle deutschen Titel und vor Kosten. Je Faktor fließen im
  Median 80 bis 680 Titel ein. Für einen Long-only-Screener mit 90 großen Werten zählen Richtung und
  Robustheit, nicht die Höhe.
- „(niedrig)“ heißt: Der Faktor kauft die Titel mit niedrigem Wert.
- Die Definitionen weichen vom Screener ab, etwa EBITDA/EV statt EV/EBIT oder die
  Netto-Ausschüttung einschließlich Emissionen. Für die FCF-Marge gibt es keine direkte
  Entsprechung.
- Ein t-Wert unter 2 heißt: Die Prämie ist statistisch nicht von null zu unterscheiden. Bewiesen
  ist damit nicht, dass sie null ist.

## Themes Deutschland

| Theme | Start | ab Start | 2000–2025 | 2010–2025 | 2016–2025 |
|---|---|---|---|---|---|
| accruals | 02/1991 | 2,4 (2,0) | 3,0 (2,2) | 1,8 (1,5) | 1,9 (1,3) |
| debt_issuance | 05/1990 | 1,2 (1,5) | 2,9 (3,6) | 1,5 (2,0) | 2,6 (2,5) |
| investment | 05/1990 | 3,4 (2,7) | 4,6 (2,9) | 0,7 (0,5) | 1,4 (0,7) |
| low_leverage | 01/1986 | −2,6 (−1,3) | −2,7 (−1,6) | −0,5 (−0,4) | −1,3 (−0,7) |
| low_risk | 02/1986 | 2,8 (1,5) | 3,8 (1,3) | 0,3 (0,1) | −0,3 (−0,1) |
| momentum | 04/1986 | 6,5 (3,4) | 8,7 (3,4) | 6,6 (3,1) | 7,1 (2,5) |
| profit_growth | 01/1987 | 2,7 (3,3) | 2,0 (2,0) | 2,1 (2,2) | 0,9 (0,7) |
| profitability | 05/1989 | 3,8 (4,4) | 3,6 (3,4) | 1,7 (1,5) | 0,6 (0,3) |
| quality | 01/1987 | 2,5 (2,4) | 2,9 (2,7) | 1,7 (1,4) | −0,5 (−0,3) |
| seasonality | 02/1986 | 0,8 (1,4) | 1,3 (2,1) | 0,3 (0,5) | 0,4 (0,6) |
| short_term_reversal | 02/1986 | 0,8 (0,7) | 0,5 (0,4) | 1,5 (1,3) | 1,2 (0,8) |
| size | 01/1986 | 0,9 (0,8) | 0,7 (0,6) | −0,1 (−0,1) | −1,0 (−0,7) |
| value | 12/1986 | 4,1 (2,6) | 5,7 (2,7) | 0,9 (0,6) | 0,7 (0,3) |

Zum Vergleich der deutsche Markt als Überrendite in USD: ab 1986 6,8 % (2,2), 2000–2025 6,6 % (1,7),
2010–2025 7,4 % (1,6), 2016–2025 7,0 % (1,2).

## Einzelfaktoren Deutschland und Developed Markets

| Faktor | JKP | Bezug im Screener | Titel DE (Median) | DE Start | DE ab Start | DE 2010–2025 | DE 2016–2025 | Dev. ab Start | Dev. 2010–2025 |
|---|---|---|---|---|---|---|---|---|---|
| EBITDA/EV | `ebitda_mev` | ≈ EV/EBIT | 460 | 05/1989 | 7,6 (3,3) | 2,8 (1,2) | 3,1 (0,9) | 5,6 (3,7) | 3,4 (2,4) |
| FCF/Marktwert | `fcf_me` | = 1 / P/FCF | 373 | 05/1995 | 7,5 (4,6) | 6,1 (2,9) | 3,8 (1,3) | 4,9 (3,7) | 5,6 (4,6) |
| Operativer CF/Marktwert | `ocf_me` | – | 489 | 05/1989 | 7,9 (3,3) | 3,9 (1,6) | 3,7 (1,1) | 4,3 (3,2) | 3,9 (2,4) |
| Buchwert/Marktwert | `be_me` | = 1 / P/B | 428 | 05/1989 | 3,0 (1,2) | 0,4 (0,2) | 1,7 (0,5) | 5,0 (3,1) | 1,3 (0,6) |
| Gewinnrendite (E/P) | `ni_me` | bewusst nicht im Composite | 501 | 05/1989 | 4,5 (2,0) | −0,9 (−0,4) | −1,9 (−0,7) | 5,0 (3,4) | 3,5 (2,3) |
| Umsatz/Marktwert | `sale_me` | – | 460 | 05/1989 | 4,9 (1,9) | 2,6 (0,9) | 3,8 (1,0) | 5,4 (3,6) | 2,8 (1,6) |
| Netto-Ausschüttungsrendite | `eqnpo_me` | ≈ Shareholder Yield | 82 | 05/1995 | 2,6 (0,9) | −2,6 (−0,9) | −5,3 (−1,3) | 3,3 (2,2) | 1,4 (0,9) |
| Dividendenrendite | `div12m_me` | Teil der Shareholder Yield | 211 | 12/1986 | 2,6 (1,6) | −2,1 (−0,9) | −1,8 (−0,5) | 5,1 (4,4) | 2,0 (1,3) |
| Residualgewinn-Wert/Marktwert (Frankel/Lee) | `ival_me` | – | 192 | 05/1990 | 3,1 (1,6) | −1,9 (−0,7) | −1,6 (−0,4) | 5,1 (3,4) | 2,7 (1,7) |
| EBIT/Buch-Unternehmenswert | `ebit_bev` | ≈ ROIC | 477 | 05/1989 | 4,9 (3,6) | 2,9 (1,5) | 1,7 (0,6) | 1,9 (1,4) | 3,2 (2,5) |
| EBIT-Marge | `ebit_sale` | = Operating Margin | 485 | 05/1989 | 0,1 (0,0) | −1,6 (−0,9) | −3,2 (−1,3) | 0,9 (0,8) | 0,7 (0,6) |
| Gewinnvariabilität (niedrig) | `earnings_variability` | ≈ Earnings Stability | 365 | 05/1994 | 0,0 (0,0) | −0,6 (−0,4) | −2,2 (−1,0) | −0,2 (−0,3) | 0,5 (0,6) |
| Nettoverschuldung/Marktwert (niedrig) | `netdebt_me` | ~ Net Debt/EBITDA | 455 | 05/1989 | 0,2 (0,1) | 0,0 (0,0) | −0,1 (0,0) | 0,1 (0,0) | 1,7 (1,3) |
| Bruttogewinn/Bilanzsumme | `gp_at` | – | 379 | 02/1990 | 1,6 (1,2) | 2,6 (1,4) | −0,8 (−0,3) | 1,3 (1,1) | 3,1 (2,7) |
| Cash-basierte operative Profitabilität | `cop_at` | Kandidat | 371 | 02/1991 | 6,3 (4,3) | 2,6 (1,4) | −1,0 (−0,4) | 4,1 (3,8) | 3,3 (4,0) |
| Operativer CF/Bilanzsumme | `ocf_at` | Kandidat (einfacher Proxy) | 487 | 05/1989 | 5,0 (3,4) | 1,4 (0,7) | −2,5 (−1,0) | 3,7 (4,0) | 2,3 (1,7) |
| Operativer Gewinn/Bilanzsumme | `op_at` | – | 471 | 05/1989 | 4,7 (3,3) | 1,2 (0,6) | −3,5 (−1,3) | 2,1 (1,9) | 1,6 (1,2) |
| Eigenkapitalrendite | `ni_be` | Finanzwerte | 473 | 05/1989 | 3,3 (2,2) | 0,8 (0,4) | −0,9 (−0,3) | 2,2 (2,1) | 3,3 (2,6) |
| Quality minus Junk | `qmj` | – | 407 | 05/1994 | 3,3 (1,7) | 3,3 (1,4) | 1,4 (0,5) | 3,8 (3,2) | 4,1 (2,5) |
| QMJ Safety | `qmj_safety` | – | 471 | 03/1989 | 0,4 (0,2) | 0,1 (0,0) | 0,6 (0,2) | 0,7 (0,5) | 2,2 (1,4) |
| Piotroski F-Score | `f_score` | Kandidat | 341 | 02/1992 | 7,2 (4,2) | 2,7 (1,2) | 2,5 (0,9) | 3,3 (3,7) | 3,1 (3,0) |
| Ohlson O-Score (niedrig) | `o_score` | Distress-Filter | 384 | 02/1991 | 4,7 (3,1) | 0,0 (0,0) | 4,1 (1,7) | 2,8 (2,1) | 3,1 (3,6) |
| Altman Z-Score | `z_score` | Distress-Filter | 342 | 02/1990 | −3,6 (−1,6) | −1,9 (−0,8) | −4,3 (−1,3) | −1,7 (−1,3) | 0,1 (0,1) |
| Operative Accruals (niedrig) | `oaccruals_at` | Kandidat | 380 | 02/1991 | 3,6 (2,3) | 3,5 (2,0) | 3,5 (1,5) | 2,6 (3,4) | 2,0 (2,7) |
| Gesamt-Accruals (niedrig) | `taccruals_at` | – | 369 | 02/1991 | 0,9 (0,6) | −1,1 (−0,7) | −2,4 (−1,1) | 0,5 (0,5) | −1,3 (−1,9) |
| Bilanzwachstum (niedrig) | `at_gr1` | – | 486 | 05/1990 | 4,0 (2,1) | 0,4 (0,2) | 2,4 (0,8) | 0,7 (0,7) | 0,5 (0,4) |
| Netto-Aktienemission 12 M (niedrig) | `chcsho_12m` | Kandidat | 680 | 01/1987 | 2,8 (1,4) | 4,9 (2,6) | 2,5 (1,1) | 2,9 (3,3) | 2,6 (3,1) |
| Netto-Gesamtemission/Bilanzsumme (niedrig) | `netis_at` | – | 145 | 05/1995 | 7,3 (3,1) | 3,0 (1,2) | 4,4 (1,3) | 5,7 (4,4) | 3,7 (4,5) |
| F&E-Kapital/Bilanzsumme | `rd5_at` | Intangibles | 102 | 05/1994 | 5,5 (2,3) | 5,1 (2,5) | 2,7 (0,9) | 3,0 (2,2) | 4,3 (3,0) |
| Gewinnüberraschung (SUE) | `niq_su` | Fundamental-Momentum | 362 | 02/2002 | 2,3 (1,0) | 2,1 (1,3) | 2,0 (0,9) | 3,3 (2,1) | 4,6 (4,7) |
| Umsatzüberraschung | `saleq_su` | Fundamental-Momentum | 266 | 08/2001 | 4,9 (2,1) | 6,0 (2,8) | 5,2 (1,8) | 3,9 (3,1) | 5,2 (3,9) |
| Kursmomentum 12-1 | `ret_12_1` | Kandidat (Anker-Filter) | 513 | 01/1987 | 9,2 (3,7) | 9,2 (3,1) | 7,5 (1,9) | 5,8 (3,2) | 6,9 (3,2) |
| Residuales Momentum 12-1 | `resff3_12_1` | – | 433 | 05/1992 | 9,1 (5,3) | 6,0 (3,0) | 6,0 (2,2) | 5,9 (6,9) | 4,7 (4,6) |
| Langfrist-Reversal | `ret_60_12` | – | 428 | 01/1991 | −0,8 (−0,5) | −2,5 (−1,0) | −2,5 (−0,7) | 1,4 (1,1) | −0,9 (−0,5) |
| Mispricing Management (Stambaugh/Yuan) | `mispricing_mgmt` | Komposit | 445 | 05/1990 | 5,9 (3,2) | 5,4 (2,8) | 7,2 (2,7) | 4,8 (4,8) | 4,6 (3,8) |
| Mispricing Performance (Stambaugh/Yuan) | `mispricing_perf` | Komposit | 549 | 01/1987 | 7,4 (3,9) | 5,5 (2,3) | 4,1 (1,2) | 4,9 (3,3) | 6,2 (3,5) |

## Korrelationen

Themes Deutschland, Monatsrenditen 01/1991–12/2025:

| | value | momentum | quality | profitability | investment | accruals | low_risk |
|---|---|---|---|---|---|---|---|
| value | 1,00 | −0,29 | −0,24 | 0,14 | 0,59 | 0,47 | 0,36 |
| momentum | −0,29 | 1,00 | 0,34 | −0,04 | 0,24 | −0,07 | 0,46 |
| quality | −0,24 | 0,34 | 1,00 | 0,64 | −0,13 | −0,10 | 0,32 |
| profitability | 0,14 | −0,04 | 0,64 | 1,00 | −0,14 | 0,07 | 0,13 |
| investment | 0,59 | 0,24 | −0,13 | −0,14 | 1,00 | 0,43 | 0,59 |
| accruals | 0,47 | −0,07 | −0,10 | 0,07 | 0,43 | 1,00 | 0,18 |
| low_risk | 0,36 | 0,46 | 0,32 | 0,13 | 0,59 | 0,18 | 1,00 |

Ausgewählte Faktoren Deutschland, 06/1995–12/2025:

| | `ebitda_mev` | `fcf_me` | `be_me` | `eqnpo_me` | `ebit_bev` | `ebit_sale` | `cop_at` | `f_score` | `oaccruals_at` | `ret_12_1` |
|---|---|---|---|---|---|---|---|---|---|---|
| `ebitda_mev` | 1,00 | 0,39 | 0,77 | 0,67 | 0,04 | −0,11 | 0,23 | 0,23 | 0,30 | −0,29 |
| `fcf_me` | 0,39 | 1,00 | 0,32 | 0,27 | −0,09 | 0,05 | 0,26 | 0,22 | 0,43 | −0,04 |
| `be_me` | 0,77 | 0,32 | 1,00 | 0,50 | −0,36 | −0,11 | 0,09 | −0,02 | 0,33 | −0,57 |
| `eqnpo_me` | 0,67 | 0,27 | 0,50 | 1,00 | 0,04 | 0,00 | 0,17 | 0,20 | 0,15 | −0,12 |
| `ebit_bev` | 0,04 | −0,09 | −0,36 | 0,04 | 1,00 | 0,41 | 0,36 | 0,26 | −0,10 | 0,18 |
| `ebit_sale` | −0,11 | 0,05 | −0,11 | 0,00 | 0,41 | 1,00 | 0,27 | 0,20 | −0,20 | 0,12 |
| `cop_at` | 0,23 | 0,26 | 0,09 | 0,17 | 0,36 | 0,27 | 1,00 | 0,27 | 0,48 | −0,05 |
| `f_score` | 0,23 | 0,22 | −0,02 | 0,20 | 0,26 | 0,20 | 0,27 | 1,00 | 0,09 | 0,31 |
| `oaccruals_at` | 0,30 | 0,43 | 0,33 | 0,15 | −0,10 | −0,20 | 0,48 | 0,09 | 1,00 | −0,18 |
| `ret_12_1` | −0,29 | −0,04 | −0,57 | −0,12 | 0,18 | 0,12 | −0,05 | 0,31 | −0,18 | 1,00 |

## Gleichgewichtete Kombinationen Deutschland

Alle Kombinationen beginnen im gemeinsamen Startmonat 06/1995. Die FCF-Marge hat keine
JKP-Entsprechung. Net Debt/EBITDA ist nur grob über `netdebt_me` abbildbar und fehlt deshalb in der
Kombination „Quality-Proxys heute“.

| Kombination | 06/1995–2025 | 2000–2025 | 2010–2025 | 2016–2025 |
|---|---|---|---|---|
| Value heute: EBITDA/EV, FCF, B/M, Netto-Ausschüttung | 5,3 (2,6) | 6,5 (2,9) | 1,7 (0,9) | 0,8 (0,3) |
| Value schlank: EBITDA/EV, FCF | 7,7 (4,2) | 8,8 (4,4) | 4,4 (2,4) | 3,4 (1,2) |
| Quality-Proxys heute: ROIC, EBIT-Marge, Gewinnvariabilität | 1,5 (1,5) | 1,7 (1,5) | 0,2 (0,2) | −1,3 (−0,7) |
| Quality-Kandidaten: CbOP, F-Score, operative Accruals | 6,2 (5,0) | 5,8 (4,3) | 3,0 (2,4) | 1,7 (1,0) |
| Kursmomentum 12-1 | 11,1 (3,8) | 10,6 (3,1) | 9,2 (3,1) | 7,5 (1,9) |

## Beobachtungen

1. **Value:** Am stärksten und stabilsten war die FCF-Rendite. Sie ist die einzige Value-Kennzahl,
   die auch 2010–2025 in Deutschland einen t-Wert über 2 hat. Das EV-Multiple folgt knapp dahinter.
   Buchwert/Marktwert ist der schwächste Value-Faktor und korreliert mit EBITDA/EV zu 0,77, bringt
   also kaum Diversifikation. Die Netto-Ausschüttungsrendite deckt nur rund 82 deutsche Titel ab und
   ist seit 2010 negativ, die Dividendenrendite ebenso.
2. **Quality:** Der ROIC-Proxy trägt, die operative Marge, die Gewinnvariabilität und die
   Nettoverschuldung tragen in Deutschland und in den Developed Markets nicht. Cash-basierte
   Profitabilität, F-Score und operative Accruals zeigen über 30 Jahre t-Werte von 2,3 bis 4,3,
   auch international.
3. **Momentum** ist in Deutschland der stärkste Einzelfaktor und korreliert negativ mit Value
   (Themes −0,29, mit B/M −0,57). Der F-Score korreliert positiv mit Momentum (0,31). Er erfasst also
   die „fundamentale Bestätigung“ eines Kurstrends.
4. **Die letzten 10 bis 15 Jahre** waren für Value und Profitabilität in Deutschland schwach. Robust
   blieben Momentum, Accruals, Emissionen (Aktien und Schulden) und Umsatzüberraschungen. Das deckt
   sich mit dem Rückgang von Prämien nach ihrer Veröffentlichung
   ([McLean/Pontiff 2016](https://doi.org/10.1111/jofi.12365)).
5. **Auswahlverzerrung:** Die Kandidaten (CbOP, F-Score, Accruals, Netto-Emission) stammen vorab aus
   der Literatur und nicht aus dieser Tabelle, und die Developed-Spalten bestätigen sie. Trotzdem
   überschätzen im Nachhinein gewählte Kombinationen ihre künftige Rendite
   ([Novy-Marx 2015](https://doi.org/10.3386/w21329)).

## Reproduktion

Die Daten werden in einen Arbeitsordner geladen. Die Zip-Dateien entpackt man in Unterordner mit
demselben Namen:

```bash
B="https://jkpfactors-data.s3.amazonaws.com/public"
for r in deu developed; do
  for t in all_factors all_themes mkt; do
    curl -s -o "${r}_${t}.zip" "$B/%5B${r}%5D_%5B${t}%5D_%5Bmonthly%5D_%5Bvw_cap%5D.zip"
    unzip -o -q "${r}_${t}.zip" -d "${r}_${t}"
  done
done
```

Das Auswertungsskript (pandas 3.0.6, NumPy) erwartet diese Ordner unter `jkp/` neben sich und gibt
die obigen Tabellen als Markdown aus:

```python
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).parent / "jkp"
PERIODS = {
    "ab Start": ("1900-01-01", "2025-12-31"),
    "2000–2025": ("2000-01-01", "2025-12-31"),
    "2010–2025": ("2010-01-01", "2025-12-31"),
    "2016–2025": ("2016-01-01", "2025-12-31"),
}
FACTORS = ["ebitda_mev", "fcf_me", "ocf_me", "be_me", "ni_me", "sale_me", "eqnpo_me", "div12m_me",
           "ival_me", "ebit_bev", "ebit_sale", "earnings_variability", "netdebt_me", "gp_at",
           "cop_at", "ocf_at", "op_at", "ni_be", "qmj", "qmj_safety", "f_score", "o_score",
           "z_score", "oaccruals_at", "taccruals_at", "at_gr1", "chcsho_12m", "netis_at", "rd5_at",
           "niq_su", "saleq_su", "ret_12_1", "resff3_12_1", "ret_60_12", "mispricing_mgmt",
           "mispricing_perf"]


def stats(r: pd.Series) -> tuple[float, float]:
    """Annualisierte mittlere Monatsrendite und t-Wert."""
    r = r.dropna()
    if len(r) < 24:
        return np.nan, np.nan
    m, s = r.mean(), r.std(ddof=1)
    return m * 12, m / (s / np.sqrt(len(r)))


def fmt(x: float, t: float) -> str:
    return "–" if np.isnan(x) else f"{x * 100:.1f} ({t:.1f})".replace(".", ",")


def load(pattern: str) -> pd.DataFrame:
    return pd.read_csv(next(BASE.glob(pattern)), parse_dates=["date"])


def series(df: pd.DataFrame, name: str) -> pd.Series:
    return df[df["name"] == name].set_index("date")["ret"].sort_index()


themes = load("deu_all_themes/*.csv")
de = load("deu_all_factors/*.csv")
dev = load("developed_all_factors/*.csv")

for name in sorted(themes["name"].unique()):
    s = series(themes, name)
    print(name, *(fmt(*stats(s.loc[a:b])) for a, b in PERIODS.values()), sep=" | ")

for key in FACTORS:
    s_de, s_dev = series(de, key), series(dev, key)
    n = int(de.loc[de["name"] == key, "n_stocks"].median())
    print(key, n, f"{s_de.index.min():%m/%Y}", fmt(*stats(s_de)),
          fmt(*stats(s_de.loc["2010":"2025"])), fmt(*stats(s_de.loc["2016":"2025"])),
          fmt(*stats(s_dev)), fmt(*stats(s_dev.loc["2010":"2025"])), sep=" | ")

wide = de.pivot(index="date", columns="name", values="ret").loc["1995-06":"2025-12"]
combos = {
    "value_heute": ["ebitda_mev", "fcf_me", "be_me", "eqnpo_me"],
    "value_schlank": ["ebitda_mev", "fcf_me"],
    "quality_heute": ["ebit_bev", "ebit_sale", "earnings_variability"],
    "quality_kandidaten": ["cop_at", "f_score", "oaccruals_at"],
    "momentum": ["ret_12_1"],
}
for label, members in combos.items():
    s = wide[members].mean(axis=1, skipna=False)
    print(label, fmt(*stats(s)), fmt(*stats(s.loc["2000":"2025"])),
          fmt(*stats(s.loc["2010":"2025"])), fmt(*stats(s.loc["2016":"2025"])), sep=" | ")
```
