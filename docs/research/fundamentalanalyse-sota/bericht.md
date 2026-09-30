# Langfristige Fundamentalanalyse: Stand der Forschung und was der Value-Analyzer übernehmen sollte

> Stand: 30.09.2026. Grundlage sind eine Literatur- und Webrecherche, eine eigene Auswertung der
> frei verfügbaren JKP-Faktordaten für Deutschland (Monatsdaten bis 12/2025) und Live-Tests von
> yfinance, filings.xbrl.org und weiteren Quellen. Tabellen, Skripte und die vollständige
> Quellenliste liegen unter [notizen/](notizen/). Keine Anlageberatung.
>
> **Umsetzungsstand (30.09.2026):**
> - Stufe 1 (Daten sichern) ist beschlossen:
>   [ADR-0010](../../adr/0010-stichtagsdaten-konsens-quartale-kurse.md), Pakete F1.1–F1.4.
> - Stufe 2 und Stufe 3 sind als
>   [ADR-0011](../../adr/0011-fundamentale-anker-und-belegte-faktoren.md) nur vorgeschlagen.
>   Zunächst werden Daten gesammelt, abgeleitet wird noch nichts.
> - Stufe 4 steht in der [Roadmap](../../architecture/roadmap.md) unter „Ideen“.

Einen einzelnen SOTA-Ansatz für die langfristige Aktienanalyse gibt es nicht. Die Forschung arbeitet
mit vier Werkzeugfamilien, die verschiedene Fragen beantworten.

- **Faktor-Composites** aus Bewertung, Profitabilität, Bilanzqualität und Momentum liefern ein
  robustes und erklärbares Querschnitts-Ranking.
- **Machine Learning** kombiniert Hunderte solcher Merkmale und prognostiziert in großen
  Querschnitten am besten. Sein Vorsprung stammt aber vor allem aus kleinen, schwer handelbaren
  Titeln und Monatshorizonten und schrumpft nach Handelskosten stark.
- **Bewertungsmodelle** wie Residualgewinn-Modell, DCF, Reverse DCF und Ertragskraftwert sind das
  Werkzeug für die Einzelaktie. Im Ranking schlagen sie einfache Multiples nicht.
- **LLMs** lesen Abschlüsse inzwischen auf Analystenniveau, rechnen aber unzuverlässig. Historische
  Tests mit ihnen sind durch Look-ahead-Bias verzerrt.

Reine Kursprognosen mit Deep Learning oder Time-Series-Foundation-Models gehören für lange Horizonte
nicht zum Stand der Technik, weil sie den Random Walk kaum schlagen.

Über Jahre folgt der Kurs einer Einzelaktie ihren Fundamentaldaten. Auf Unternehmensebene treiben
vor allem Nachrichten über künftige Cashflows die Renditen
([Vuolteenaho 2002](https://doi.org/10.1111/1540-6261.00421)). Die Grundlage einer Langfrist-Analyse
ist deshalb nicht der Kursverlauf selbst, sondern der **fundamentale Anker**, dem er folgt. Dieser
Bericht nutzt Fundamentaldaten darum zweimal: als Ranking-Faktoren im Querschnitt und als Anker, an
dem man den langfristigen Kurs einer einzelnen Aktie misst.

Für den Value-Analyzer mit 90 DAX/MDAX-Werten, einem Anlagehorizont von Jahren und einem
wöchentlichen Screener folgt daraus: Der Composite-Ansatz ist richtig, einzelne Bausteine sind aber
schwach belegt. Eine eigene Auswertung der JKP-Faktordaten für Deutschland seit 1989 zeigt:

- Am stärksten trugen **EV-Multiples, die Free-Cashflow-Rendite, cash-basierte Profitabilität, der
  Piotroski-F-Score, niedrige Accruals und Kursmomentum**.
- **Kurs-Buchwert, Ausschüttungsrendite, operative Marge, Gewinnstabilität und Verschuldung** trugen
  kaum oder gar nicht.

Der größte Engpass für Langfrist-Analysen ist die Datentiefe, nicht die Methode:

- yfinance liefert Kurse seit 1996/98, aber nur vier Geschäftsjahre an Abschlüssen.
- Eine freie, strukturierte Quelle für deutsche Abschlüsse gibt es nicht. filings.xbrl.org führt
  25.954 ESEF-Berichte, darunter keinen einzigen deutschen.
- Das EU-Portal ESAP soll erst bis Juli 2027 öffentlich werden.

Umso wertvoller ist die neue Postgres-Historie. Sie sollte ab sofort auch speichern, was sich später
nicht nachholen lässt: Konsensschätzungen, Quartalsabschlüsse und die Aktienanzahl.

## Vier Ansatzfamilien im Vergleich

| Ansatz | Leistet | Evidenz (Auswahl) | Datenbedarf | Eignung hier |
|---|---|---|---|---|
| **Faktor-Composites**: Value, Profitabilität, Investment und Emissionen, Accruals, Momentum | robustes, erklärbares Querschnitts-Ranking mit wenig Umschlag | Mehrheit von 153 Faktoren repliziert, auch in 93 Ländern ([Jensen/Kelly/Pedersen 2023](https://doi.org/10.1111/jofi.13249)); Quality in 24 Ländern ([Asness/Frazzini/Pedersen 2019](https://doi.org/10.1007/s11142-018-9470-2)) | Kennzahlen je Titel zum Stichtag | **hoch**: der heutige Ansatz, gezielt nachschärfen |
| **ML über viele Merkmale**: Boosting, neuronale Netze, IPCA, Transformer | nichtlineare Kombination Hunderter Merkmale | [Gu/Kelly/Xiu 2020](https://doi.org/10.1093/rfs/hhaa009) (USA), [Drobetz/Otto 2021](https://doi.org/10.1057/s41260-021-00237-x) (Europa); Grenzen: [Avramov/Cheng/Metzker 2023](https://doi.org/10.1287/mnsc.2022.4449), [Blitz et al. 2023](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4474637) | Point-in-Time-Panel über Jahrzehnte und Tausende Titel | **gering**: 90 Titel × 4 Jahre reichen nicht zum Trainieren |
| **Bewertungsmodelle**: Residualgewinn, DCF und Reverse DCF, Ertragskraftwert, implizite Kapitalkosten, statistischer Fair Value | Wert bzw. eingepreiste Erwartungen je Aktie | [Frankel/Lee 1998](https://doi.org/10.1016/S0165-4101(98)00026-3), [Lee/So/Wang 2021](https://doi.org/10.1093/rfs/hhaa066), [Bartram/Grinblatt 2021](https://ideas.repec.org/a/eee/jfinec/v139y2021i1p234-259.html), [Hanauer/Kononova/Rapp 2022](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3977872) | Prognosen oder mehrjährige Historie, Annahme zu den Kapitalkosten | **mittel**: als Anker für die Einzelaktie, nicht als Ranking-Faktor |
| **KI/LLM**: Abschlussanalyse, Textänderungen, Agenten | liest Berichte, extrahiert qualitative Risiken | [Kim/Muhn/Nikolaev 2024](https://arxiv.org/abs/2407.17866), [Cao/Jiang/Wang/Yang 2024](https://www.nber.org/papers/w28800), [Lazy Prices 2020](https://doi.org/10.1111/jofi.12885); Grenzen: [Lopez-Lira/Tang/Zhu 2025](https://arxiv.org/abs/2504.14765) | Geschäftsberichte, API-Zugang | **mittel**: Lesehilfe für die Top-Kandidaten, nicht im Score |
| *Kursprognose mit LSTM oder Time-Series-Foundation-Models* | – | [Rahimikia/Ni/Wang 2025](https://arxiv.org/abs/2511.18578), [Noguer i Alonso/Franklin 2026](https://arxiv.org/abs/2606.27100) | lange Kursreihen | **nein** für lange Horizonte |

## Fundamentaldaten als Anker für die langfristige Kursanalyse

Über Tage und Wochen ist ein Aktienkurs nahezu ein Random Walk. Über Jahre setzt sich seine Rendite
aus drei Teilen zusammen:

- Ausschüttungen
- Wachstum des Gewinns je Aktie
- Veränderung des Bewertungsmultiples

Die ersten beiden Teile sind fundamental verankert, der dritte nicht. Das Multiple pendelt um einen
Mittelwert, kann eine Rendite aber über viele Jahre dominieren. Eine Langfrist-Analyse stellt deshalb
immer zwei Fragen: Welcher fundamentale Wert trägt den Kurs? Und wie weit ist der Kurs davon
entfernt?

### Fünf Anker und ihre Grenzen

| Anker | Idee | Stärke | Grenze | Mit heutigen Daten |
|---|---|---|---|---|
| **Substanz**: Buchwert, NAV | Kurs gegen bilanziertes Eigenkapital je Aktie | Standard bei Banken und Versicherern (P/B gegen ROE, [Damodaran 2009](https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/finfirm09.pdf)) und bei Immobilien (NAV) | bei Industrie und Software durch nicht bilanzierte Intangibles verzerrt; in Deutschland der schwächste Value-Faktor | ja |
| **Ertragskraft**: Earnings Power Value | normalisierter operativer Gewinn nach Steuern, geteilt durch die Kapitalkosten, minus Nettoverschuldung; das ist der Wert ohne Wachstum (Greenwald et al., *Value Investing*, 2020) | zeigt, welcher Teil des Kurses für Wachstum bezahlt wird; Wachstum schafft nur Wert, wenn der ROIC über den Kapitalkosten liegt | Kapitalkosten sind eine Annahme; die Normalisierung braucht einen ganzen Zyklus | ja, mit 4 Jahren EBIT als Näherung |
| **Cashflow**: FCF-Rendite, Reverse DCF | Welches FCF-Wachstum unterstellt der heutige Unternehmenswert? (Mauboussin/Rappaport, *Expectations Investing*, 2021) | macht die Markterwartung ausdrücklich und mit Basisraten vergleichbar | der FCF schwankt, der Endwert dominiert | ja |
| **Residualgewinn** | Wert = Buchwert + Barwert der künftigen Übergewinne, (ROE − Kapitalkosten) × Buchwert ([Frankel/Lee 1998](https://doi.org/10.1016/S0165-4101(98)00026-3); Penman, *Accounting for Value*, 2011) | verbindet Substanz und Ertragskraft; Bilanzpolitik verschiebt Wert nur zwischen Buchwert und künftigen Gewinnen | braucht eine ROE-Prognose oder eine Fade-Annahme; als Ranking-Faktor in Deutschland schwach (3,1 %, t = 1,6) | ja, mit einer Fade-Regel |
| **Relativ**: eigene Historie, Querschnitt, statistischer Fair Value | Multiple gegen den eigenen Median, gegen andere Titel oder gegen eine Regression auf Bilanzgrößen ([Bartram/Grinblatt 2021](https://ideas.repec.org/a/eee/jfinec/v139y2021i1p234-259.html)) | einfach und datengetrieben | die eigene Historie braucht mindestens einen Zyklus, die Regression einen breiten Querschnitt | Querschnitt ja (das heutige Ranking); die Historie wächst in der DB |

Kein brauchbarer Anker sind Analysten-Kursziele. Nach zwölf Monaten sind nur 38 % erreicht, und der
absolute Fehler liegt im Mittel bei 45 %
([Bradshaw/Brown/Huang 2013](https://doi.org/10.1007/s11142-012-9216-5)).

### Vier Wege, Kurs und Anker zu verbinden

1. **Wertlinie im Langfrist-Chart.** Neben den Kurs wird ein fundamentaler Wert je Aktie gelegt:
   Gewinn oder FCF je Aktie mal einem „normalen“ Multiple, etwa dem Median der eigenen Historie. Bei
   Finanzwerten nimmt man den Buchwert je Aktie mal dem normalen P/B. Der prozentuale Abstand
   zwischen Kurs und Linie misst die Bewertung gegenüber der eigenen Geschichte. Zusammen mit dem
   heutigen Querschnittsrang ergibt das zwei unabhängige Blickwinkel.
2. **Renditezerlegung.** Die Gesamtrendite der letzten 5 bis 10 Jahre wird zerlegt in Ausschüttungen,
   Gewinnwachstum, Veränderung des Multiples und Veränderung der Aktienanzahl (Rückkäufe bzw.
   Verwässerung). Stammt ein großer Teil aus steigenden Multiples, ist der Kurs schwächer verankert
   und anfälliger für Rückschläge.
3. **Momentum nur mit fundamentaler Bestätigung.** Preis-Momentum ist im Kern Gewinn-Momentum.
   Gewinnüberraschungen erklären es vollständig ([Novy-Marx 2015](https://doi.org/10.3386/w20984)).
   Für Europa gilt: Momentum-Gewinne konzentrieren sich auf Titel, deren Kursverlauf zu den
   Fundamentaldaten (F-Score) passt, und fehlen dort, wo beides sich widerspricht
   ([Walkshäusl 2019](https://doi.org/10.1111/acfi.12462)). Für einen Value-Screener folgt daraus:
   - Fällt der Kurs und verschlechtern sich zugleich die Fundamentaldaten, ist das eine Warnung vor
     einer Value-Trap.
   - Fällt der Kurs, während die Fundamentaldaten stabil bleiben, kann das ein Kandidat sein.
4. **Fundamentaldaten prognostizieren statt Kurse.** Mehrere Studien zeigen, dass sich der Anker
   besser prognostizieren lässt als der Kurs:
   - Faktoren mit den tatsächlichen künftigen Fundamentaldaten wären klassischen Faktoren weit
     überlegen. Ein neuronales Netz, das nur die Fundamentaldaten prognostiziert, hob die simulierte
     Jahresrendite von 14,4 % auf 17,1 % (USA; [Alberg/Lipton 2017/18](https://arxiv.org/abs/1711.04837)).
   - ML-Gewinnprognosen sind genauer als der Analystenkonsens
     ([Cao/You 2024](https://rpc.cfainstitute.org/research/financial-analysts-journal/2024/fundamental-analysis-via-machine-learning)).
   - Ein LLM trifft die Richtung künftiger Gewinne häufiger als Analysten
     ([Kim/Muhn/Nikolaev 2024](https://arxiv.org/abs/2407.17866)).

   Wo ML oder LLMs zum Einsatz kommen, sollten sie deshalb Gewinne und Cashflows prognostizieren,
   nicht den Kurs.

### Basisraten gegen Extrapolation

Jeder Anker, der Wachstum enthält, muss dieses Wachstum auslaufen lassen:

- Profitabilität kehrt zum Mittelwert zurück, im einfachen Modell um etwa 38 % pro Jahr. Unter dem
  Mittel und weit davon entfernt geht es schneller
  ([Fama/French 2000](https://doi.org/10.1086/209638)).
- Hohe Wachstumsraten setzen sich kaum fort
  ([Chan/Karceski/Lakonishok 2003](https://doi.org/10.1111/1540-6261.00540)).
- Aktien mit den optimistischsten Langfrist-Wachstumsprognosen rentieren schlecht
  ([Bordalo et al. 2019](https://doi.org/10.1111/jofi.12833)).

Dazu kommt die extreme Schiefe langfristiger Einzelrenditen. Von 1990 bis 2020 schufen 2,4 % der
Unternehmen die gesamte Netto-Wertschöpfung der Weltbörsen, und 57,4 % der Nicht-US-Aktien lagen
hinter einmonatigen US-Treasury-Bills
([Bessembinder et al. 2023](https://doi.org/10.1080/0015198X.2023.2188870)). Anker schützen davor,
zu viel zu bezahlen. Die seltenen Extremgewinner finden sie nicht verlässlich. Streuung bleibt
deshalb Pflicht.

## Faktoren: robust, aber nicht jeder Baustein trägt

Die „Replikationskrise“ der Faktorforschung ist weitgehend aufgelöst, mit Einschränkungen:

- Die Mehrheit von 153 Faktoren lässt sich replizieren, bündelt sich in 13 Themes und wirkt
  out-of-sample in 93 Ländern ([Jensen/Kelly/Pedersen 2023](https://doi.org/10.1111/jofi.13249)).
- Kontrolliert man Micro-Caps, scheitert dagegen ein großer Teil von 452 Anomalien
  ([Hou/Xue/Zhang 2020](https://doi.org/10.1093/rfs/hhy131)).
- Nach der Veröffentlichung sinken die Prämien um gut die Hälfte
  ([McLean/Pontiff 2016](https://doi.org/10.1111/jofi.12365)).
- Wegen der vielen getesteten Faktoren sollte die Signifikanzhürde bei t > 3 liegen
  ([Harvey/Liu/Zhu 2016](https://doi.org/10.1093/rfs/hhv059)).

Daraus folgt: Belastbar sind Faktoren mit ökonomischer Begründung und internationaler Replikation.
Künftige Prämien werden niedriger ausfallen als historische.

Gut belegt sind vier Gruppen:

- **Bewertung:** Unternehmenswert-Multiples schlagen P/B
  ([Loughran/Wellman 2011](https://doi.org/10.1017/S0022109011000445),
  [Gray/Vogel 2012](https://doi.org/10.3905/jpm.2012.39.1.112)). Der Buchwert unterschätzt
  zunehmend selbst geschaffene Intangibles. Value mit aktivierter Forschung und
  Organisationskapital schneidet deutlich besser ab
  ([Arnott et al. 2021](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3488748),
  [Eisfeldt/Kim/Papanikolaou 2022](https://www.nowpublishers.com/article/Details/CFR-0113)).
- **Profitabilität:** Bruttogewinn je Bilanzsumme ([Novy-Marx 2013](https://doi.org/10.1016/j.jfineco.2013.01.003))
  und vor allem die cash-basierte operative Profitabilität, die Accruals als eigenes Signal
  überflüssig macht ([Ball et al. 2016](https://doi.org/10.1016/j.jfineco.2016.03.002)).
- **Bilanzqualität:** Niedrige Accruals ([Sloan 1996](https://doi.org/10.2308/tar-9608042309)) und
  der Piotroski-F-Score. Der F-Score trennt unter billigen Aktien Gewinner von Verlierern
  ([Piotroski 2000](https://doi.org/10.2307/2672906)) und wirkt international
  ([Walkshäusl 2020](https://doi.org/10.1057/s41260-020-00157-2)). In Deutschland verbesserte er alle
  zwölf untersuchten bilanzbasierten Long-only-Portfolios. Am besten schnitt die Kombination aus
  niedrigen Accruals und hohem F-Score ab, wenn man sie nur alle drei Jahre aktualisierte
  ([Pätäri/Leivo/Ahmed 2022](https://doi.org/10.1007/s11408-021-00400-9)).
- **Emissionen und Momentum:** Wer netto Aktien ausgibt, rentiert schlechter
  ([Pontiff/Woodgate 2008](https://doi.org/10.1111/j.1540-6261.2008.01335.x)). Value und Momentum
  sind negativ korreliert und ergänzen sich
  ([Asness/Moskowitz/Pedersen 2013](https://doi.org/10.1111/jofi.12021)).

Für ein Large-Cap-Universum gilt eine Einschränkung: Value- und Momentum-Prämien sind bei großen
Werten kleiner als bei kleinen, außer in Japan aber überall vorhanden
([Fama/French 2012](https://doi.org/10.1016/j.jfineco.2012.05.011)). Vor allem die Value-Prämie
schrumpft mit der Größe, Momentum kaum
([Israel/Moskowitz 2013](https://doi.org/10.1016/j.jfineco.2012.11.005)).

### Was in Deutschland trug: eigene Auswertung

Die [JKP-Faktordaten](https://jkpfactors.com/) enthalten für Deutschland Monatsrenditen von 153
Faktoren seit 1986. Es sind Long-short-Portfolios über alle Titel mit gekappter
Marktwert-Gewichtung, in USD und vor Kosten. Die Auswertung ist **keine Rückrechnung des
Screeners**. Sie zeigt, welche Merkmale in Deutschland und in den Developed Markets über lange
Zeit trugen. Zelle: annualisierte Rendite in % (t-Wert). Details, Definitionen und das Skript stehen in
[notizen/jkp-deutschland.md](notizen/jkp-deutschland.md).

| Faktor (Bezug im Screener) | DE ab Start (1987–2001) | DE 2010–2025 | Developed ab Start (1986–2001) | Developed 2010–2025 |
|---|---|---|---|---|
| EBITDA/EV (≈ EV/EBIT) | 7,6 (3,3) | 2,8 (1,2) | 5,6 (3,7) | 3,4 (2,4) |
| FCF/Marktwert (= 1 / P/FCF) | 7,5 (4,6) | 6,1 (2,9) | 4,9 (3,7) | 5,6 (4,6) |
| Buchwert/Marktwert (= 1 / P/B) | 3,0 (1,2) | 0,4 (0,2) | 5,0 (3,1) | 1,3 (0,6) |
| Netto-Ausschüttungsrendite (≈ Shareholder Yield)¹ | 2,6 (0,9) | −2,6 (−0,9) | 3,3 (2,2) | 1,4 (0,9) |
| EBIT/Buch-Unternehmenswert (≈ ROIC) | 4,9 (3,6) | 2,9 (1,5) | 1,9 (1,4) | 3,2 (2,5) |
| EBIT-Marge (= Operating Margin) | 0,1 (0,0) | −1,6 (−0,9) | 0,9 (0,8) | 0,7 (0,6) |
| niedrige Gewinnvariabilität (≈ Earnings Stability) | 0,0 (0,0) | −0,6 (−0,4) | −0,2 (−0,3) | 0,5 (0,6) |
| niedrige Nettoverschuldung/Marktwert (~ Net Debt/EBITDA) | 0,2 (0,1) | 0,0 (0,0) | 0,1 (0,0) | 1,7 (1,3) |
| Cash-basierte operative Profitabilität | 6,3 (4,3) | 2,6 (1,4) | 4,1 (3,8) | 3,3 (4,0) |
| Piotroski-F-Score | 7,2 (4,2) | 2,7 (1,2) | 3,3 (3,7) | 3,1 (3,0) |
| niedrige operative Accruals | 3,6 (2,3) | 3,5 (2,0) | 2,6 (3,4) | 2,0 (2,7) |
| niedrige Netto-Aktienemission (12 Monate) | 2,8 (1,4) | 4,9 (2,6) | 2,9 (3,3) | 2,6 (3,1) |
| Umsatzüberraschung | 4,9 (2,1) | 6,0 (2,8) | 3,9 (3,1) | 5,2 (3,9) |
| Kursmomentum 12-1 | 9,2 (3,7) | 9,2 (3,1) | 5,8 (3,2) | 6,9 (3,2) |

¹ In Deutschland deckt dieser Faktor nur rund 82 Titel je Monat ab, die übrigen 350 bis 680.

Daraus ergeben sich fünf Befunde:

1. **Value: EV und FCF tragen, P/B und Ausschüttung kaum.** Die FCF-Rendite ist die einzige
   Value-Kennzahl mit t > 2 auch in Deutschland 2010–2025. Buchwert/Marktwert korreliert mit
   EBITDA/EV zu 0,77 und bringt damit wenig Diversifikation. Mit Momentum korreliert es zu −0,57. Das
   KBV zieht also besonders „fallende Messer“ an. Eine gleichgewichtete Kombination aus EBITDA/EV
   und FCF erzielte seit 06/1995 7,7 % (t = 4,2), die Kombination aller vier heutigen Value-Bausteine
   5,3 % (2,6). Für 2010–2025 lauten die Werte 4,4 % (2,4) und 1,7 % (0,9).
2. **Quality: ROIC trägt, Marge, Stabilität und Verschuldung nicht.** Das gilt in Deutschland und in
   den Developed Markets gleichermaßen. Die Kombination der heutigen Quality-Proxys (ROIC, Marge,
   Stabilität) brachte 1,5 % (1,5). Die Kandidaten cash-basierte Profitabilität, F-Score und Accruals
   brachten 6,2 % (5,0), für 2010–2025 3,0 % (2,4) gegenüber 0,2 % (0,2). Operative Marge,
   Gewinnstabilität und Verschuldung können als Risikoindikatoren sinnvoll bleiben. Einen
   Renditebeitrag liefern sie nicht.
3. **Momentum ist in Deutschland der stärkste Einzelfaktor.** Es korreliert negativ mit Value
   (Themes: −0,29) und positiv mit dem F-Score (0,31). Das passt zum Anker-Befund oben: Tragfähige
   Kurstrends sind fundamental bestätigt.
4. **Die letzten 10 bis 15 Jahre waren für Value und Profitabilität schwach**, in Deutschland noch
   ausgeprägter als international. Robust blieben Momentum, Accruals, Emissionen und
   Umsatzüberraschungen.
5. **Auswahlverzerrung.** Die Kandidaten stammen vorab aus der Literatur, nicht aus dieser Tabelle,
   und die Developed-Markets-Spalten bestätigen sie. Trotzdem überzeichnen im Nachhinein gewählte
   Kombinationen ihre künftige Rendite ([Novy-Marx 2015](https://doi.org/10.3386/w21329)). Für
   einen Long-only-Screener über 90 große Werte zählen Richtung und Robustheit, nicht die Höhe der
   Zahlen.

## Machine Learning: stark im Querschnitt, schwach dort, wo dieses Projekt sucht

Im großen Querschnitt ist ML der Stand der Technik:

- Baum-Modelle und neuronale Netze prognostizieren US-Renditen besser als lineare Modelle
  ([Gu/Kelly/Xiu 2020](https://doi.org/10.1093/rfs/hhaa009)). Die wichtigsten Prädiktoren sind
  Kurstrends, Liquidität und Volatilität. Für Europa gilt dasselbe, dort mit Kurstrends und
  Bewertungskennzahlen vorn ([Drobetz/Otto 2021](https://doi.org/10.1057/s41260-021-00237-x)).
- Den Überblick gibt [Kelly/Xiu 2023](https://www.nber.org/papers/w31502). An der Forschungsfront
  stehen Transformer im stochastischen Diskontfaktor
  ([Kelly et al. 2025/26](https://www.nber.org/papers/w33351)) und ML, das Portfoliogewichte
  unter Handelskosten direkt optimiert
  ([Jensen/Kelly/Malamud/Pedersen 2026](https://doi.org/10.1093/rfs/hhag022)).

Drei Befunde begrenzen den Nutzen für dieses Projekt:

- **Die Gewinne liegen bei den kleinen Titeln.** Deep-Learning-Signale verdienen vor allem an schwer
  handelbaren Titeln. Ohne Micro-Caps und angeschlagene Titel und nach Handelskosten sinkt die
  Rendite deutlich ([Avramov/Cheng/Metzker 2023](https://doi.org/10.1287/mnsc.2022.4449)).
- **Der Horizont ist zu kurz.** Auf Monatsrenditen trainierte Modelle verdienen nach Kosten seit 2004
  fast nichts. Erst längere Zielhorizonte und effiziente Handelsregeln bringen positive
  Nettorenditen, und diese Modelle laden dann stärker auf die klassischen Faktoren
  ([Blitz et al. 2023](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4474637)).
- **Vorsicht bei scheinbarer Vorhersagekraft.** Adaptive Modellsuche erzeugt signifikante Backtests
  sogar auf Daten ohne jede Vorhersagbarkeit
  ([Nikolopoulos 2026](https://arxiv.org/abs/2604.15531)). Die RFS hat im März 2026 eine
  „Expression of Concern“ zu einer vielzitierten ML-Studie über Gewinnprognosen veröffentlicht
  ([RFS 2026](https://doi.org/10.1093/rfs/hhag017)). Diese Studie wird hier deshalb nicht als Beleg
  verwendet.

Ein eigenes Renditemodell auf 90 Titeln mit vier Jahren Historie wäre reines Overfitting. Wenn ML,
dann in einer der beiden Formen, die zum Anker-Gedanken passen:

- ML prognostiziert Fundamentaldaten (siehe oben).
- ML schätzt einen „agnostischen“ Fair Value aus Bilanzgrößen. Mit 21 Bilanzgrößen und
  Baum-Modellen erzielten Hanauer, Kononova und Rapp in Europa 48 bis 66 Basispunkte Alpha pro
  Monat, lineare Modelle 11 bis 36
  ([Hanauer/Kononova/Rapp 2022](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3977872)).

Beides braucht einen breiten Querschnitt, etwa den STOXX Europe 600, und Point-in-Time-Daten. Laut
CLAUDE.md gehört das in eine separate Pipeline. Nebenbei: Fehlende Fundamentaldaten betreffen über
70 % der Firmen und fehlen nicht zufällig
([Bryzgalova et al. 2025](https://doi.org/10.1093/rfs/hhae036)). Die heutige NaN-tolerante
Mittelung mit Mindestanteil ist pragmatisch. Ein Hinweis auf die Abdeckung je Titel im Report wäre
ehrlicher.

## KI und LLMs: gute Leser, unzuverlässige Rechner

Die stärkste Evidenz betrifft das Lesen und Einordnen:

- GPT-4 sagte aus anonymisierten Abschlüssen die Richtung künftiger Gewinne zu 60,35 % richtig
  voraus, Analysten lagen etwa 7 Prozentpunkte darunter
  ([Kim/Muhn/Nikolaev 2024](https://arxiv.org/abs/2407.17866)).
- Ein KI-Analyst schlägt die Mehrheit der menschlichen Analysten. Menschen bleiben besser, wo
  institutionelles Wissen zählt, etwa bei Intangibles. **Mensch plus Maschine** liefert die besten
  Prognosen ([Cao/Jiang/Wang/Yang 2024](https://www.nber.org/papers/w28800)). Das entspricht dem
  Disclaimer dieses Projekts: quantitative Vorauswahl, danach qualitative Prüfung.
- Für lange Horizonte interessant sind Veränderungen im Text von Geschäftsberichten. Firmen, die ihre
  10-Ks stark ändern, rentieren später deutlich schlechter. Der Markt reagiert erst, wenn die
  Information über Nachrichten oder Zahlen ankommt
  ([Lazy Prices, Cohen/Malloy/Nguyen 2020](https://doi.org/10.1111/jofi.12885)). Für deutsche Berichte
  ist das nicht untersucht.

Agenten sind die Front von 2026, aber mit kurzem Horizont:

- LLM-Agenten screenen Fundamentaldaten und Nachrichten und einigen sich auf Kauf- und
  Verkaufssignale ([Caner et al. 2026](https://arxiv.org/abs/2603.23300)).
- Ein autonomer Such-Agent sagt Tagesrenditen im Russell 1000 voraus, live seit 04/2025
  ([Chen/Pu 2026](https://arxiv.org/abs/2601.11958)).
- Alpha-Mining-Agenten erzeugen vor allem kurzfristige Formelfaktoren
  ([AlphaAgent](https://arxiv.org/abs/2502.16789), [R&D-Agent-Quant](https://arxiv.org/abs/2505.15155)).
  Bei solchen Systemen ordnet keine einzelne Kennzahl die Systeme konsistent
  ([Pan/Ding/Giesecke 2026](https://arxiv.org/abs/2609.00731)).

Zwei Grenzen sind entscheidend:

- **Zuverlässigkeit.** Im Finance Agent Benchmark v2 erreicht das beste Modell 61,44 %. In den
  Kategorien Financial Modeling und Precedents liegen die Besten bei 34,52 % und 36,37 %
  ([Vals AI, Stand 29.09.2026](https://www.vals.ai/benchmarks/fabv2)). Mehrstufige Rechnungen mit
  exakten Zahlen sind die Schwachstelle.
- **Look-ahead-Bias.** LLMs geben historische Kurse und Kennzahlen aus ihrem Trainingszeitraum fast
  wörtlich wieder ([Lopez-Lira/Tang/Zhu 2025](https://arxiv.org/abs/2504.14765)). Backtests über
  diesen Zeitraum überschätzen die Vorhersagekraft. Abhilfe schaffen Tests zur Erkennung
  ([Gao/Jiang/Yan 2025](https://arxiv.org/abs/2512.23847)) und Point-in-Time-Modelle wie ChronoGPT
  ([He et al. 2025](https://arxiv.org/abs/2502.21206)). Im Live-Betrieb, also mit Daten nach dem
  Trainingsstichtag, besteht das Problem nicht.

Time-Series-Foundation-Models (Chronos, TimesFM, Moirai u. a.) prognostizieren Renditen mit ihren
Standardgewichten schwach. Erst ein Pretraining auf Finanzdaten hilft
([Rahimikia/Ni/Wang 2025](https://arxiv.org/abs/2511.18578)). Auch dann sind die Gewinne gegenüber dem
Random Walk „klein und vereinzelt“ ([Noguer i Alonso/Franklin 2026](https://arxiv.org/abs/2606.27100)).
Für Langfrist-Analysen sind sie kein Werkzeug.

## Daten: Die Tiefe der Fundamentalhistorie ist der Engpass

Ergebnisse der Live-Tests vom 30.09.2026; Details in
[notizen/datenquellen-live-tests.md](notizen/datenquellen-live-tests.md):

| Quelle | Befund | Tiefe | Kosten | Bewertung |
|---|---|---|---|---|
| **yfinance 0.2.66** (8 DAX/MDAX-Titel) | Kurse mit Dividenden; Abschlüsse 4, vereinzelt 5 Jahre; 5 bis 7 Quartale; Aktienanzahl meist seit 2015/16; Konsensdaten (`eps_trend`, `eps_revisions`, Schätzungen) bei 8 von 8; Insiderdaten leer | Kurse 1996–2000 bzw. seit dem Börsengang; Fundamentaldaten 4 Jahre | 0 € | reicht für den Querschnitt, ist zu kurz für Langfrist-Anker |
| **filings.xbrl.org** (ESEF) | 25.954 Berichte, **0 aus Deutschland**; SAP, Siemens und Allianz ohne Filings; laut Betreiber ist das deutsche Unternehmensregister nicht abrufbar | andere Länder ab GJ 2020 | 0 € | für DAX/MDAX unbrauchbar |
| **ESAP** (ESMA) | sammelt seit 10.07.2026 Pflichtberichte, öffentlich bis Juli 2027, API vorgesehen | ab 2026; ob ältere Berichte nachgeladen werden, ist unklar | 0 € | beobachten |
| **EODHD** Fundamentals | Nicht-US-Werte laut Doku ab 2000, kleine Werte nur 6 Jahre | rund 25 Jahre | 59,99 €/Monat bzw. 49,99 € bei Jahreszahlung | die einzige bezahlbare Quelle für sofort verfügbare lange Historie |
| **BaFin** Directors' Dealings | Meldungen nach Art. 19 MAR, 12 Monate vorgehalten | 12 Monate | 0 € | lange Historie nur durch eigenes Sammeln; Nutzungsbedingungen ungeprüft |
| **JKP, AQR** Faktordaten | Deutschland ab 1986, frei (JKP: CC BY-NC 4.0) | 40 Jahre | 0 € | zum Kalibrieren der Methodik, nicht für den Wochenlauf |

Die Postgres-Historie ist damit der strategisch wichtigste Datenbestand des Projekts. Einiges
sammelt sie schon:

- `market_data.raw_info` sichert jede Woche die komplette `info`-Antwort. Darin stecken unter anderem
  `forwardEps`, `targetMeanPrice` und die Zahl der Analysten. Die DB baut also bereits eine
  Konsenshistorie auf.
- `statement_value` hält Restatements fest.

Andere Daten lassen sich später nicht mehr nachholen und fehlen bisher:

- `eps_trend`, `eps_revisions` und die Schätztabellen
- die Quartalsabschlüsse (`statement_value` kennt heute nur `annual`)
- die Historie der Aktienanzahl

## Empfehlungen für den Value-Analyzer

Die Reihenfolge passt zum [Implementierungsplan](../../architecture/implementierungsplan.md):

- Neue Kennzahlen entstehen als reine Funktionen (P1.3).
- Gewichte ändert man über die Scoring-Profile (P2b).
- Die Anker gehören ins Titel-Detail des UI (P3.7).
- Für jeden neuen Faktor gilt der Ablauf „Neuer Scoring-Faktor“ aus [CLAUDE.md](../../../CLAUDE.md).

Änderungen an der Composite-Methodik verändern die Samstags-Mail. Sie brauchen deshalb ein eigenes
ADR und gehören hinter den Golden-Master (P0.1).

### Stufe 1: Daten sichern, die sich nicht nachholen lassen

Sofort umsetzbar und ohne Einfluss auf das Ranking:

1. **Konsens-Snapshots** wöchentlich speichern: `eps_trend`, `eps_revisions`, `earnings_estimate`,
   `revenue_estimate` und `growth_estimates`. Die Daten sind für DAX und MDAX vorhanden.
2. **Quartalsabschlüsse** in `statement_value` aufnehmen. Das Datenmodell sieht die Frequenz bereits
   vor. Sie sind Voraussetzung für Gewinnüberraschungen und TTM-Kennzahlen.
3. **Aktienanzahl** aus `get_shares_full` speichern, als Grundlage für Netto-Emission und Verwässerung.

### Stufe 2: Scoring nachschärfen

Je Faktor ein Arbeitspaket, gebündelt in einem ADR:

4. **Quality:** Der Piotroski-F-Score (neun Binärsignale aus zwei aufeinanderfolgenden Abschlüssen),
   die operativen Accruals, also (Jahresüberschuss − operativer Cashflow) / Bilanzsumme mit „niedrig
   ist gut“, und der operative Cashflow je Bilanzsumme als einfacher Proxy für die cash-basierte
   Profitabilität kommen hinzu. `op_cash`, `net_income` und `total_assets` stehen schon in
   `FIELD_MAP`. Operative Marge, Gewinnstabilität und Net Debt/EBITDA bleiben als Risikoindikatoren
   erhalten, im Composite bekommen sie aber weniger Gewicht.
5. **Value:** EV/EBIT und P/FCF bleiben der Kern. P/B wird für Nicht-Finanzwerte gestrichen oder um
   aktivierte Forschungsausgaben bereinigt. Eine F&E-Zeile liefert yfinance allerdings nur bei
   F&E-intensiven Titeln, im Test bei 3 von 8. Die Shareholder Yield wird um die Netto-Emission
   ergänzt oder durch sie ersetzt: Eine sinkende Aktienanzahl ist ein guter Wert.
6. **Anwendbarkeit je Branche**, ausdrücklich ohne sektorrelatives Ranking:
   - Bei Banken und Versicherern sind EV/EBIT, P/FCF, FCF-Marge und Net Debt/EBITDA sinnlos
     ([Damodaran 2009](https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/finfirm09.pdf)).
     Stattdessen zählen P/B, P/E und ROE. Das betrifft Allianz, Commerzbank, Deutsche Bank,
     Hannover Rück, Münchener Rück und Talanx.
   - Bei Immobilien nach IAS 40 kann das EBIT Bewertungsergebnisse enthalten. Der Anker ist dort
     der NAV bzw. die FFO-Rendite. Das betrifft Vonovia, Aroundtown, LEG und TAG.
   - Zusammen sind das 10 der 90 Titel. Grenzfälle wie flatexDEGIRO sind einzeln zu entscheiden.
     Heute rechnet `score()` alle Faktoren für alle Titel.
7. **Momentum als Anker-Filter im Value-Trap-Flag.** Das Flag wird zusätzlich gesetzt, wenn ein
   hoher Value-Score mit schwachem 12-1-Momentum und schwachem F-Score zusammenfällt. Das ist das
   „fallende Messer ohne fundamentale Stütze“. Die Kurshistorie liegt über yfinance ohnehin vor, die
   Schwellen gehören ins Profil. Später kann Revisionsmomentum (Veränderung der Konsens-EPS über 90
   Tage) hinzukommen. Belege: Walkshäusl 2019, Novy-Marx 2015,
   [Capstaff/Paudyal/Rees 2001](https://pureportal.strath.ac.uk/en/publications/revisions-of-earnings-forecasts-and-security-returns-evidence-fro/)
   für Deutschland, Frankreich und Großbritannien.

### Stufe 3: Fundamentale Anker je Titel

Für das Titel-Detail im UI, optional auch als Spalten der Mail:

8. **Ertragskraftwert (EPV) und Preis/EPV:** mittlerer EBIT der verfügbaren Jahre × (1 −
   effektive Steuerquote) / Kapitalkosten − Nettoverschuldung, je Aktie. Das Verhältnis zeigt die
   eingepreiste Wachstumsprämie. Die Logik für die effektive Steuerquote steckt bereits in
   `_roic()`. Die Kapitalkosten werden ein Profil-Parameter, die Anzeige zeigt die Sensitivität bei
   ±1 Prozentpunkt.
9. **Implizites Wachstum per Reverse DCF:** Welches FCF-Wachstum über 10 Jahre mit anschließendem
   Auslaufen rechtfertigt den heutigen Unternehmenswert? Daneben stehen das eigene
   Vergangenheitswachstum und die Basisraten (Fama/French 2000, Chan/Karceski/Lakonishok 2003).
10. **Langfrist-Chart mit Wertlinie und Renditezerlegung:** Kurse seit 1996/98 aus yfinance, dazu
    Gewinn und FCF je Aktie mal dem Median-Multiple der eigenen Historie, bei Finanzwerten der
    Buchwert. Mit den heutigen Daten reicht die Linie nur vier Jahre zurück. Sie wächst mit der DB
    oder sofort mit einer längeren Quelle (Stufe 4).
11. **Normalisierte Gewinne für Zykliker:** den EBIT über alle verfügbaren Jahre mitteln, damit ein
    Zykliker auf dem Gewinnhoch nicht billig aussieht. Die Idee geht auf Graham und Dodd zurück und
    steckt auch im Shiller-KGV (CAPE).

### Stufe 4: optional

12. **EODHD-Adapter**, wenn die Langfrist-Anker sofort 20 Jahre zurückreichen sollen. Das steht in
    der Roadmap schon als Idee. ESAP ab Juli 2027 prüfen.
13. **LLM-Lesehilfe für die Top-Kandidaten**, mit eigenem ADR:
    - Das Modell liest je Titel den Geschäftsbericht und den Risikobericht und füllt eine
      strukturierte Checkliste mit Seitenbelegen: Geschäftsmodell, Kapitalallokation, Warnsignale,
      Änderungen im Risikobericht gegenüber dem Vorjahr (Lazy-Prices-Idee).
    - Die Ergebnisse werden versioniert gespeichert, mit Modell- und Prompt-Version, und fließen nie
      in den Score. Auf der NAS läuft dabei nur ein API-Aufruf.
14. **Directors' Dealings sammeln**, wenn die BaFin-Bedingungen das erlauben. Insiderkäufe gehen in
    Deutschland mit +3,6 % Überrendite in 20 Tagen einher
    ([Betzer/Theissen 2009](https://doi.org/10.1111/j.1468-036X.2007.00422.x)). Für
    Langfrist-Anleger ist das ein qualitativer Hinweis und kein Faktor.

### Nicht empfohlen

- ein eigenes ML-Renditemodell auf 90 Titeln
- Kursprognosen mit LSTM oder Time-Series-Foundation-Models
- Backtests mit LLMs über deren Trainingszeitraum
- LLM-Agenten als Entscheider
- Analysten-Kursziele als Anker

## Grenzen dieser Recherche

- Die JKP-Daten für Deutschland bilden Long-short-Portfolios über alle Titel ab, in USD und vor
  Kosten. Eine Large-Cap-Teilmenge gibt es nur für die USA. Die Definitionen weichen vom Screener ab,
  für die FCF-Marge gibt es keine Entsprechung. Teilperioden ab 2010 sind kurz, und t-Werte unter 2
  beweisen keine Prämie von null.
- Pätäri et al. (2022), Walkshäusl (2019/2020) und Bradshaw et al. (2013) wurden wegen Paywalls nur
  über Abstracts und Sekundärquellen geprüft.
- Nicht live geprüft sind die BaFin-Nutzungsbedingungen, die Frage, ob ESAP ältere Berichte
  nachlädt, die EODHD-Abdeckung aller 90 Titel (der Demo-Key reicht nicht) und FMP (HTTP 403).
- LLM-Benchmarks und Agenten-Studien ändern sich monatlich. Die Zahlen gelten für Ende September
  2026.

## Fazit

Die Forschung liefert kein neues Wundermodell. Sie verschiebt die Gewichte. Für einen langfristigen
Anleger mit großen deutschen Werten liegt der Stand der Technik nicht in komplexeren
Prognosemodellen, sondern in drei Dingen:

- in besser belegten Bausteinen: Cashflow statt Buchwert, Bilanzqualität statt Marge, Emission
  statt bloßer Ausschüttung
- in fundamentalen Ankern, an denen man den Kurs einer Aktie über Jahre misst
- in der Disziplin, Wachstum nicht fortzuschreiben

Machine Learning und LLMs helfen dort, wo sie den Anker prognostizieren oder Berichte lesen. Beim
Vorhersagen von Kursen helfen sie nicht.

Der Value-Analyzer steht dafür gut da. Sein Composite ist im Kern richtig, die Datenhaltung speichert
Stichtage unwiderruflich, und die geplanten Scoring-Profile machen Methodikänderungen versionierbar.
Die wichtigste Maßnahme kostet fast nichts und eilt am meisten: Konsensdaten, Quartalsabschlüsse und
die Aktienanzahl ab sofort mitschreiben. Jede Woche ohne diese Daten fehlt später unwiderruflich in
der Langfrist-Historie, auf der alle Anker aufbauen.
