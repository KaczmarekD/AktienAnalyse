# ADR-0011: Fundamentale Anker und belegte Faktoren im Scoring

- **Status:** vorgeschlagen
- **Datum:** 2026-09-30
- **Grundlage:** [Recherche: Langfristige Fundamentalanalyse](../research/fundamentalanalyse-sota/bericht.md)
- **Setzt voraus:** [ADR-0010](0010-stichtagsdaten-konsens-quartale-kurse.md), also die
  Datensammlung aus F1
- **Würde ändern (bei Annahme):**
  - die Methodik in [CLAUDE.md](../../CLAUDE.md): Faktorkatalog, Value-Trap-Flag, Umgang mit
    Finanzwerten
  - die Parameter in [scoring-profile.md](../architecture/scoring-profile.md)

## Warum noch „vorgeschlagen“

Zuerst werden nur Daten gesammelt (ADR-0010), abgeleitet wird noch nichts. Die Rohdaten werden
gespeichert, also kann jede spätere Methodik rückwirkend auf alle Abrufe angewendet werden. Durch
Warten geht deshalb nichts verloren. Umsetzbar wäre dieses ADR ohnehin erst nach P1.3, P1.5 und
P2b.2.

**Entschieden wird**, sobald P1.5 und P2b.2 erledigt sind. Vorher kommt auf den bis dahin
gespeicherten Abrufen:

1. ein Vergleich der Rankings v1 und v2 per Rescore, ohne Backtest (CLAUDE.md schließt Backtesting
   aus)
2. die Prüfung, ob das EBIT der Immobilienwerte Bewertungsergebnisse enthält (siehe Punkt 4 der
   Entscheidung)
3. bei Bedarf eine aktualisierte JKP-Auswertung

Mit 90 Titeln lässt sich eine Faktorprämie auch nach Jahren nicht statistisch nachweisen. Die
Entscheidung wird sich deshalb weiter vor allem auf die externe Evidenz stützen. Bis zur Annahme
gilt die Methodik aus CLAUDE.md unverändert.

## Kontext

- **Heutiges Scoring:** Der Screener rankt im Querschnitt 0,6 × Value und 0,4 × Quality.
  - Value: EV/EBIT, P/B, P/FCF, Shareholder Yield
  - Quality: ROIC, FCF-Marge, operative Marge, Net Debt/EBITDA, Gewinnstabilität
- **Stand der Forschung:** Faktor-Composites sind der richtige Ansatz. Nicht zu 90 Titeln mit vier
  Jahren Abschlusshistorie passen:
  - eigene ML-Renditemodelle
  - Kursprognosen mit LSTM oder Time-Series-Foundation-Models
  - Backtests mit LLMs

  Über Jahre folgt der Kurs einer Aktie ihren Fundamentaldaten. Für die Langfrist-Analyse zählt
  deshalb der fundamentale Anker.
- **JKP-Faktordaten für Deutschland seit 1989:**
  - ohne Prämie: P/B, Ausschüttungsrendite, operative Marge, Gewinnstabilität, Verschuldung
  - mit Prämie: F-Score, operative Accruals, cash-basierte Profitabilität, niedrige
    Netto-Emission und Kursmomentum, auch in den Developed Markets

  Die Daten stammen aus Long-short-Portfolios über alle Titel. Für 90 große Werte, long-only,
  belegen sie die Richtung, nicht die Rendite.
- **Finanzwerte:** EV-, FCF- und Margen-Kennzahlen sind für Banken und Versicherer sinnlos. Trotzdem
  rechnet `score()` heute alle Faktoren für alle Titel.
- **Wunsch des Users:** langfristige Kursanalysen mit Fundamentaldaten als Anker.

## Entscheidung (vorgeschlagen)

1. **Neue Faktoren im Katalog.** Bestehende Faktoren behalten ihre Definition, damit die Historie
   vergleichbar bleibt.
   - Quality: `f_score` (0 bis 9 nach Piotroski, hoch ist gut), `operating_accruals`
     ((Jahresüberschuss − operativer Cashflow) / Bilanzsumme, niedrig ist gut) und `cfo_assets`
     (operativer Cashflow / Bilanzsumme, hoch ist gut)
   - Value: `net_share_issuance`, die Veränderung der Aktienanzahl über 12 Monate, bereinigt um
     Splits (niedrig ist gut). Das ist kein Multiple. Negative Werte (Rückkäufe) sind gültig und
     fallen nicht unter den Ausschluss negativer Multiples.
2. **Standardprofil v2.** Es ist eine neue Version des Profils „Standard“ nach
   [ADR-0009](0009-scoring-profile-in-der-db.md). v1 bleibt für Vergleich und Rollback erhalten.
   - Value aktiv: `ev_ebit`, `p_fcf`, `net_share_issuance`. Abgeschaltet: `pb`,
     `shareholder_yield`.
   - Quality aktiv: `roic`, `fcf_margin`, `f_score`, `operating_accruals`, `cfo_assets`.
     Abgeschaltet: `operating_margin`, `earnings_stability`, `net_debt_ebitda`.
   - Abgeschaltete Faktoren werden weiter berechnet und gespeichert. Der Report zeigt sie als
     Risikoindikatoren. Profile kennen nur „an“ und „aus“, „weniger Gewicht“ heißt hier also
     Gewicht null bei voller Sichtbarkeit.
   - Die Gewichtung 0,6/0,4 und alle übrigen Schwellen bleiben.
3. **Branchenregeln statt sektorrelativem Ranking.**
   - Banken und Versicherer sind Titel, deren Yahoo-`industry` mit „Banks“ bzw. „Insurance“
     beginnt. Für sie werden EV/EBIT, P/FCF, FCF-Marge, Net Debt/EBITDA, operative Marge, ROIC,
     F-Score, Accruals und CFO/Bilanzsumme nicht berechnet.
   - Wer dadurch unter den Mindestanteil vorhandener Faktoren fällt, bekommt keinen
     Composite-Score. Diese Titel erscheinen in einem eigenen Abschnitt „Finanzwerte“ mit P/B, P/E,
     ROE und dem gerechtfertigten P/B, also (ROE − g) / (r − g).
   - Alle Ränge bleiben global. Innerhalb einer Branche wird nicht gerankt.
4. **Immobilien** („Real Estate“, „REIT“) folgen denselben Regeln, falls ihr EBIT
   Bewertungsergebnisse nach IAS 40 enthält. Das wird vor der Annahme an Vonovia, LEG, TAG und
   Aroundtown geprüft.
5. **Momentum dient als Anker-Prüfung, nicht als Renditefaktor.**
   - `market-data` berechnet das 12-1-Monats-Momentum aus der gespeicherten Kurshistorie.
   - Das Value-Trap-Flag wird zusätzlich gesetzt, wenn drei Bedingungen zusammentreffen: Der
     Value-Score liegt bei mindestens `value_trap_value_threshold`, der Momentum-Rang bei höchstens
     `trap_momentum_max_rank` (Standard 0,30), und der F-Score bei höchstens `trap_fscore_max`
     (Standard 3). Das ist ein fallendes Messer ohne fundamentale Stütze.
   - Das Ergebnis speichert, welche Regel das Flag ausgelöst hat.
   - Momentum geht nicht in den Composite ein.
6. **Fundamentale Anker je Titel.** `scoring` berechnet in jedem Lauf:
   - den Ertragskraftwert (EPV) je Aktie: Mittelwert der verfügbaren EBIT-Jahre × (1 −
     effektive Steuerquote) / `cost_of_capital` − Nettoverschuldung
   - Preis/EPV
   - das implizite FCF-Wachstum per Reverse DCF: `dcf_years` Jahre Wachstum, danach
     `terminal_growth`
   - Neue Profil-Parameter: `cost_of_capital` (Standard 0,08), `terminal_growth` (0,02) und
     `dcf_years` (10).
   - Die Anker gehen nicht in den Composite ein. Sie stehen in der CSV und im Titel-Detail.
   - Das Titel-Detail zeigt zusätzlich die Wertlinie: Kurs gegen Gewinn bzw. FCF je Aktie mal dem
     Median-Multiple der eigenen Historie, bei Finanzwerten gegen den Buchwert je Aktie. Dazu kommt
     die Zerlegung der Rendite in Ausschüttungen, Gewinnwachstum, Bewertungsänderung und
     Aktienanzahl.
7. **Bewusst nicht Teil dieses Vorschlags:**
   - Kein eigenes ML-Renditemodell, keine Kursprognosen mit LSTM oder TSFM, keine Backtests mit
     LLMs, keine LLM-Agenten als Entscheider und keine Analysten-Kursziele als Anker.
   - Eine LLM-Lesehilfe für Geschäftsberichte, das Sammeln von Directors' Dealings und ein Wechsel
     zu EODHD brauchen jeweils ein eigenes ADR.

**Umsetzung nach Annahme:** die Pakete F2.1 bis F3.2 im
[Implementierungsplan](../architecture/implementierungsplan.md). Alle Faktoren und Regeln kommen
zunächst abgeschaltet. Erst F2.5 aktiviert v2 und aktualisiert die Golden-Files bewusst.

## Konsequenzen (bei Annahme)

- ✅ Das Scoring stützt sich auf Signale, die in Deutschland und international belegt sind.
  Finanzwerte werden nicht mehr mit ungeeigneten Kennzahlen bewertet.
- ✅ Jede Änderung ist über Profil-Versionen umkehrbar. Rankings mit v1 bleiben reproduzierbar.
- ✅ Der Anlagehorizont bleibt lang und der Screener fundamental. Momentum dient nur als Filter.
- ⚠️ Rund 10 der 90 Titel verlassen das Composite-Ranking und stehen im Abschnitt „Finanzwerte“.
  Die Top- und Flop-Listen ändern sich mit v2 spürbar.
- ⚠️ Auswahlverzerrung bleibt möglich: Faktoren, die im Nachhinein gewählt werden, überzeichnen
  ihre Wirkung.
- ⚠️ Die Anker hängen an Annahmen (Kapitalkosten, Endwachstum). Das UI zeigt deshalb die
  Sensitivität bei ±1 Prozentpunkt.
- ⚠️ Ab Phase 5 darf `scoring` nicht mehr aus `market_data` lesen
  ([ADR-0003](0003-postgresql-schema-pro-service.md)). Momentum und die neuen Kennzahlen reisen
  deshalb als Felder im Snapshot-Event, die Contracts werden additiv erweitert. Die Wertlinie im
  web-api braucht dann eine Projektion.

## Verworfene Alternativen

- **Eigenes ML-Renditemodell:** Dafür gibt es zu wenig Daten. Der Vorsprung solcher Modelle stammt
  aus Small Caps und kurzen Horizonten und schrumpft nach Kosten.
- **Kursprognosen mit LSTM oder TSFM:** Sie schlagen den Random Walk kaum und sagen nichts über den
  fundamentalen Wert.
- **Sektorrelatives Ranking:** Dafür gibt es zu wenige Titel je Sektor, siehe CLAUDE.md.
- **Finanzwerte weiter mit allen Faktoren:** EV- und FCF-Kennzahlen sind dort sinnlos und verzerren
  die globalen Ränge.
- **Gewichte je Faktor im Profil:** Das würde das Parametermodell aus ADR-0009 deutlich
  verkomplizieren. Für diesen Vorschlag reicht an/aus.
- **Bestehende Faktoren umdefinieren**, etwa die Shareholder Yield netto um Emissionen: Das bricht
  die Vergleichbarkeit der gespeicherten Historie.
- **Sofort umstellen, ohne Profil-Version:** nicht umkehrbar und ein Widerspruch zu ADR-0009.
