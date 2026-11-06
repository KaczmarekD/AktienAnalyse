# Analyse und Hinweise

> **Status:** Spezifikation, Entwurf vom 04.11.2026. Teil der
> [Depot-Spezifikation](README.md), Stufen D4 (Analyse) und D5 (Hinweise). Grundsatzentscheidung:
> [ADR-0013](../../adr/0013-depots-im-service-portfolio.md) (vorgeschlagen).

## Grundsatz: bewertet wird gegen ein Referenzuniversum

Das Scoring arbeitet mit Perzentilrängen: Ein Titel ist so gut, wie er im Vergleich zu den
anderen dasteht ([CLAUDE.md](../../../CLAUDE.md#methodik-entscheidungen)). Ein Depot mit zehn
Aktien eignet sich nicht als Vergleichsgruppe. Der beste von zehn mittelmäßigen Titeln bekäme
sonst 1,0.

Deshalb bleibt DAX/MDAX das **Referenzuniversum**. Die Aktien eines Depots werden darin
**eingeordnet**:

- Ein Titel aus dem Referenzuniversum behält seine Werte aus dem Ranking.
- Jeder andere Titel bekommt den Perzentilrang, den er hätte, wenn man ihn allein dem
  Referenzuniversum hinzufügte. Die Ränge der Referenztitel ändern sich dadurch nicht.

So ist ein Score im Depot mit einem Score im Ranking vergleichbar, bis auf den kleinen Unterschied
zwischen n und n+1 Vergleichswerten. Das Ranking und die Samstags-Mail bleiben unverändert, der
Golden-Master auch.

**Composite-Perzentil:** Der Composite ist kein Perzentil, sondern ein gewichtetes Mittel aus
Mitteln von Rängen. Er streut eng um 0,5. Für Aussagen wie „unteres Fünftel“ zählt deshalb das
**Composite-Perzentil**: der Rang des Composite unter allen Referenztiteln mit Composite (für
eingeordnete Titel wieder „Referenz plus dieser eine Titel“). Schwellen der Hinweise nutzen es.

Weitere Referenzuniversen (z. B. STOXX Europe 600 für europäische Titel) sind möglich. Sie folgen
dem Rezept „Neues Universum“ aus CLAUDE.md. Welches für welchen Titel gilt, ist eine offene Frage
([README](README.md#offene-fragen)).

## Anforderungen

| ID | Prio | Anforderung |
|---|---|---|
| ANA-01 | Muss | Jede Aktie im Depot bekommt Value-, Quality- und Composite-Score, Composite-Perzentil, Faktor-Ränge und Value-Trap-Flag nach dem aktiven Scoring-Profil, eingeordnet ins Referenzuniversum. |
| ANA-02 | Muss | Die Regeln des Rankings gelten auch bei der Einordnung: negative Multiples zählen nicht, Composite nur mit beiden Teilscores (M1). |
| ANA-03 | Muss | Der Größenfilter (`min_market_cap`) schließt Depot-Titel nicht aus. Eingeordnet werden Aktien außerhalb des Universums und auch Universumstitel unter dem Filter, wenn sie in einem Depot stehen. Der Filter wird zum Hinweis HIN-Q06. |
| ANA-04 | Muss | Score-Verlauf je Position über alle Bewertungsläufe, wie im Titel-Detail. |
| ANA-05 | Muss | ETFs: Kosten (TER, laufende Kosten in EUR pro Jahr), Fondsvolumen, Struktur nach Sektor, Land und Anlageklasse, soweit die Quelle sie liefert, jeweils mit Stand. |
| ANA-06 | Soll | ETFs: Durchschau auf die Bestände (Look-through), daraus Überschneidungen und ein Look-through-Score (siehe unten). |
| ANA-07 | Muss | Anleihen: Restlaufzeit, Rendite bis Fälligkeit, modifizierte Duration, Kupontermine, aus Kupon, Fälligkeit und Kurs. |
| ANA-08 | Muss | Depot: Wert, Allokation nach Anlageklasse, Sektor, Land und Währung, Konzentration, Kosten, wertgewichtete Scores, Datenabdeckung. |
| ANA-09 | Muss | Jede Zahl zeigt ihren Datenstand. Fehlt eine Größe, steht „keine Daten“ da, kein Ersatzwert. |
| ANA-10 | Muss | Die Analyse wird neu gerechnet bei neuem Depotstand, neuen Kursen, neuem Bewertungslauf und neuen Stammdaten. |

## Aktien: Einordnung

Neue reine Funktion in `va_scoring.domain` neben `score()`:

```python
def place(
    reference: pd.DataFrame,   # das bewertete Referenzuniversum (Ergebnis von score(): Rohwerte,
                               # Ränge, nur Titel, die den Größenfilter passieren)
    candidates: pd.DataFrame,  # Kennzahlen der einzuordnenden Aktien (siehe ANA-03)
    cfg: ScoringConfig,        # aus dem aktiven Profil
) -> pd.DataFrame:             # je Kandidat: rank_<faktor>, value_score, quality_score,
                               # composite, composite_percentile, value_trap, reason
    ...
```

- Je Faktor gelten Richtung und Ausschlüsse wie in `_percentile_rank`. Der Rang eines
  Kandidaten ist sein Perzentilrang in „Referenz plus dieser eine Kandidat“, mit
  `method="average"` wie heute.
- Value-, Quality- und Composite-Score sowie das Flag folgen denselben Regeln und Gewichten wie im
  Ranking (`_composite_mean`, Mindestanteil der Faktoren). Ohne Score nennt `reason` den Grund
  (`no_quality`, `no_value`, `no_data`).
- **Wann eingeordnet wird:**
  - im Bewertungslauf: `scoring.run.completed` bekommt das optionale Feld `placements[]`
    (additiv, `PlacementV1` in [wertpapiere.md](wertpapiere.md#contracts-additiv)). notification
    ignoriert es, die Mail bleibt gleich.
  - beim Rescore nach einer Profil-Aktivierung ebenso. Die Kandidaten liegen dafür getrennt in
    `scoring.input_snapshot`.
  - bei neuer Abdeckung sofort gegen den letzten Bewertungslauf (`scoring.placements.updated`),
    damit eine neue Position nicht bis Samstag ohne Score bleibt.
- Woher die Kandidaten kommen: market-data ruft die Aktien aus den Depots mit ab und schickt sie
  im optionalen Feld `covered[]` mit ([wertpapiere.md](wertpapiere.md#abdeckung-und-abrufe)).
  Universumstitel unter dem Größenfilter nimmt scoring aus `fundamentals[]`, wenn sie in der
  Abdeckung stehen.
- Gespeichert wird in `scoring.placement` (scoring_run_id, isin, symbol, Scores, Faktor-Ränge,
  Flag, reason), nur zum Anfügen.

Test-Eigenschaften:
- Ein Kandidat mit denselben Kennzahlen wie ein Referenztitel landet direkt neben ihm.
- Ein Kandidat, der in jedem Faktor besser ist als alle Referenztitel, bekommt je Faktor den
  höchsten Rang, der bei n+1 Werten möglich ist: 1,0 bei „hoch ist gut“, 1 − 1/(n+1) bei
  „niedrig ist gut“ (dort gilt `1 − rank(pct)`). Für „schlechter als alle“ entsprechend den
  niedrigsten.
- Die Ränge der Referenztitel sind mit und ohne Kandidaten gleich.
- Ranking, Report-CSV, Backfill der Projektionen und Replay-Regression sind mit und ohne
  Kandidaten gleich.

## ETFs

| Größe | Rechnung | Quelle |
|---|---|---|
| Laufende Kosten | Positionswert × TER | TER aus den ETF-Stammdaten |
| Struktur | Gewichte nach Sektor, Land, Anlageklasse | ETF-Stammdaten, mit Stand. Länder nur aus Anbieterdateien, yfinance liefert keine. |
| Look-through | Einzeltitel-Gewicht im Depot = direkt gehalten + Σ (ETF-Gewicht × Anteil des Titels im ETF) | Bestandsliste des ETF |
| Überschneidung zweier ETFs | Σ min(Gewicht in A, Gewicht in B) über gemeinsame Titel | Bestandslisten |
| Look-through-Score | Σ (Anteil × Composite) über die bewerteten Titel, geteilt durch ihren Anteil | Bestandsliste und Scores |

Grenzen, die das UI offen zeigt:

- Liefert die Quelle nur die größten Positionen (z. B. Top 10), sind Look-through und
  Überschneidung **Untergrenzen**. Das UI schreibt dann „mindestens“.
- Der Look-through-Score erscheint nur, wenn mindestens 50 % des ETF-Gewichts bewertet sind
  (Schwelle einstellbar). Bei einem Welt-ETF ist das mit DAX/MDAX als Referenz selten der Fall.
- Die Währung eines ETF ist seine Fondswährung, nicht das Währungsrisiko seiner Bestände.

## Anleihen

- **Rendite bis Fälligkeit:** interner Zinsfuß der Zahlungen aus Kupon und Rückzahlung, gemessen
  am aktuellen Dirty-Preis (Kurs in % plus Stückzinsen). Stückzinsen und Perioden folgen der
  Zinsmethode aus den Stammdaten (z. B. ACT/ACT ICMA bei Bundesanleihen). Gelöst mit Bisektion,
  ohne neue Abhängigkeit.
- **Modifizierte Duration** aus denselben Zahlungen.
- **Kupontermine** und **Fälligkeitsprofil** (Wert je Fälligkeitsjahr).
- Nicht berechnet: Floater, inflationsindexierte und ewige Anleihen, Wandelanleihen. Sie stehen
  im Bestand mit Hinweis „Sonderform, keine Rendite“.
- Ein Rating gibt es frei nicht. Es ist kein Teil der ersten Stufe.

## Depot

Reine Funktion in `va_portfolio.domain.analysis`:

```python
@dataclass(frozen=True)
class AnalysisInput:
    holdings: HoldingSnapshot
    securities: Mapping[Isin, Security]       # Stammdaten inkl. ETF- und Anleihedaten
    prices: Mapping[Isin, Price]
    fx: FxRates
    scores: Mapping[Isin, PlacedScore]        # aktueller Bewertungslauf
    previous_scores: Mapping[Isin, PlacedScore]  # vorheriger Bewertungslauf (HIN-Q03)
    news: Sequence[NewsRef]                   # HIN-N01, HIN-N02
    target: TargetAllocation | None           # HIN-A01
    params: HintParams
    previous: DepotAnalysis | None            # Status neu/besteht/erledigt (HIN-03)
    acks: Sequence[HintAck]                   # zur Kenntnis genommen (HIN-05)
    today: date


def analyze(data: AnalysisInput) -> DepotAnalysis: ...
```

| Bereich | Inhalt |
|---|---|
| Wert | je Position Wert in EUR und Gewicht; Summe; Anteil mit Kurs |
| Allokation | nach Anlageklasse, Sektor, Land, Währung; Sektor und Land mit Durchschau durch ETFs, sonst „ohne Durchschau“ |
| Konzentration | größter Einzeltitel und Top 5 (mit Durchschau), effektive Zahl der Titel (1 / Σ Gewicht²) |
| Qualität | wertgewichteter Composite, Value und Quality über den bewerteten Aktienanteil; Abdeckung; Zahl der Value-Trap-Flags; Verteilung der Aktien auf die Fünftel des Referenzuniversums (nach Composite-Perzentil) |
| Kosten | gewichtete TER, laufende Kosten in EUR pro Jahr |
| Anleihen | gewichtete Rendite und Duration, Fälligkeitsprofil |
| Datenlage | Anteil des Werts mit Kurs, mit Score, mit Durchschau; älteste Daten |

Keine Renditeberechnung, keine Wertentwicklung, kein Benchmark-Vergleich. Das bleibt draußen
([README](README.md#nicht-ziele)). Einstand und Differenz zum Wert zeigt das Depot als reine Anzeige
(DEP-13).

## Hinweise

Hinweise sind regelbasierte Beobachtungen am Depot. Jede Regel ist eine reine Funktion mit
Katalogeintrag (ID, Titel, Begründung, Ansatzpunkt), so wie `FACTOR_INFO` für die Faktoren.

### Leitplanken

- Ein Hinweis nennt **Messwert, Schwelle und Datenstand**, dazu eine Begründung, warum das
  relevant sein kann, und einen **Ansatzpunkt** zum Prüfen.
- Ein Hinweis sagt nie „kaufen“, „verkaufen“ oder nennt ein Kursziel. Das Werkzeug liefert eine
  quantitative Vorauswahl, keine Anlageempfehlung (siehe Disclaimer in CLAUDE.md). UI und Bericht
  zeigen den Disclaimer.
- Es gibt keine Funktion, die Aufträge erteilt.

### Anforderungen

| ID | Prio | Anforderung |
|---|---|---|
| HIN-01 | Muss | Hinweise entstehen bei jeder Analyse aus dem Katalog unten. |
| HIN-02 | Muss | Drei Schweregrade: Info, Warnung, Kritisch. |
| HIN-03 | Muss | Status je Hinweis im Vergleich zur vorherigen Analyse: neu, besteht, erledigt. |
| HIN-04 | Muss | Schwellen je Depot einstellbar, in Grenzen, versioniert wie die Scoring-Profile (`HintParamsV1` mit Standardwerten). Jede Regel lässt sich abschalten. |
| HIN-05 | Soll | „Zur Kenntnis genommen“: Der Hinweis verschwindet, bis er schwerer wird oder sich der Messwert um eine regelabhängige Spanne verschlechtert. |
| HIN-06 | Soll | Prüfkandidaten (siehe unten), abschaltbar, standardmäßig aus. |

### Katalog (erste Fassung)

| ID | Regel | Standard | Schwere | Ansatzpunkt |
|---|---|---|---|---|
| **Konzentration** | | | | |
| HIN-K01 | Einzeltitel-Anteil (direkt plus über ETFs) | > 10 % / > 20 % | Warnung / Kritisch | Gewicht und Doppelung über ETFs prüfen |
| HIN-K02 | Anteil der fünf größten Einzeltitel | > 50 % | Info | Streuung prüfen |
| HIN-K03 | Anteil eines Sektors (mit Durchschau) | > 30 % | Warnung | Abhängigkeit von einer Branche prüfen |
| HIN-K04 | Anteil eines Landes (mit Durchschau) | > 50 % | Info | Heimatmarkt-Übergewicht prüfen |
| HIN-K05 | Anteil Fremdwährung | > 50 % | Info | Währungsrisiko prüfen |
| HIN-K06 | Anteil eines Emittenten (Aktien und Anleihen zusammen), zusammengeführt über die LEI aus FIRDS | > 10 % | Warnung | Emittentenrisiko prüfen |
| **Allokation** | | | | |
| HIN-A01 | Abweichung einer Anlageklasse von der Zielallokation | > 5 Prozentpunkte | Info | Zielallokation und Gewichte prüfen |
| HIN-A02 | Anteil Kasse | > 10 % | Info | Liquiditätsbedarf prüfen |
| **Qualität (Aktien)** | | | | |
| HIN-Q01 | Value-Trap-Flag | – | Warnung | Geschäftsbericht, Ursache der niedrigen Quality prüfen |
| HIN-Q02 | Composite im unteren Fünftel des Referenzuniversums | Composite-Perzentil ≤ 20 % | Info | Kennzahlen im Titel-Detail prüfen |
| HIN-Q03 | Composite-Perzentil gefallen seit dem vorherigen Bewertungslauf | ≥ 20 Prozentpunkte | Info | Welche Faktoren sich verschlechtert haben |
| HIN-Q04 | Quality-Score niedrig | ≤ 0,3 | Info | Profitabilität, Verschuldung prüfen |
| HIN-Q05 | Keine Bewertung möglich (Daten fehlen, z. B. Banken ohne Quality) | – | Info | Qualitativ beurteilen |
| HIN-Q06 | Vergleich eingeschränkt: außerhalb des Referenzmarkts oder unter dem Größenfilter | – | Info | Score nur als grobe Einordnung lesen |
| **ETFs** | | | | |
| HIN-E01 | TER | > 0,5 % | Info | Kosten prüfen |
| HIN-E02 | Überschneidung zweier ETFs | ≥ 50 % | Info | Doppelte Abdeckung prüfen |
| HIN-E03 | Fondsvolumen (nur aus Anbieterdateien, yfinance ist dafür unzuverlässig) | < 100 Mio. EUR | Info | Schließungsrisiko prüfen |
| **Anleihen** | | | | |
| HIN-B01 | Fälligkeit | < 90 Tage | Info | Wiederanlage planen |
| HIN-B02 | Kurs | < 80 % | Warnung | Bonität des Emittenten prüfen |
| HIN-B03 | Anteil eines Fälligkeitsjahrs am Anleihenwert | > 50 % | Info | Laufzeitenstruktur prüfen |
| **News** | | | | |
| HIN-N01 | Ad-hoc-Mitteilung zu einer Position | letzte 7 Tage | Warnung | Mitteilung lesen |
| HIN-N02 | Eigengeschäfte von Führungskräften gemeldet | letzte 30 Tage | Info | Meldung lesen |
| **Datenlage** | | | | |
| HIN-D01 | Kurs fehlt oder älter als 5 Handelstage | – | Warnung | Depotwert ist unvollständig |
| HIN-D02 | Bankstand älter als | 30 Tage | Info | Bestand neu abrufen |
| HIN-D03 | Wertpapier nicht erkannt (ISIN ohne Stammdaten) | – | Warnung | ISIN prüfen |

Der Katalog wächst mit der Spezifikation. Eine neue Regel braucht ID, Standardschwelle in
`HintParamsV1`, Katalogtext und Test.

### Prüfkandidaten

Zu einer Aktie mit HIN-Q01 oder HIN-Q02 zeigt das UI auf Wunsch bis zu drei Titel **zum
Vergleich**: aus dem Referenzuniversum, aus demselben Sektor, mit höherem Composite, ohne
Value-Trap-Flag und nicht schon im Depot. Die Überschrift lautet „Zum Vergleich im selben
Sektor“, nicht „Ersetzen durch“. Das ist dieselbe Information wie das Ranking, nur gefiltert.

### Lebenszyklus

```
Analyse n-1        Analyse n           Status
HIN-K01:SAP  ───►  HIN-K01:SAP     →   besteht (Schwere kann steigen)
             ───►  HIN-Q01:XYZ     →   neu
HIN-B01:DE…  ───►  (fehlt)         →   erledigt
```

Schlüssel eines Hinweises: Regel und Gegenstand (`HIN-K01:<ISIN>` oder `HIN-A02:depot`).

## Datenmodell (Schema `portfolio`)

| Tabelle | Inhalt | Schreibweise |
|---|---|---|
| `analysis_run` | id, depot_id, snapshot_version, scoring_run_id, prices_as_of, trigger, result (JSONB), computed_at | anfügen |
| `hint` | analysis_run_id, key, rule_id, severity, subject_isin, measured, threshold, status, payload (JSONB) | anfügen |
| `hint_params` | depot_id, version, params (JSONB), created_at | anfügen, gültig ist die jüngste Zeile |
| `hint_ack` | depot_id, key, user_id, measured_at_ack, severity_at_ack, at | anfügen |

## Events

| Subject | Sender → Empfänger | Inhalt |
|---|---|---|
| `va.portfolio.analysis.completed` | portfolio → web-api | depot_id, analysis_run_id, Zahl der Hinweise nach Schwere, Zahl der neuen Hinweise. Keine Schlüssel, ISINs oder Beträge: das Event liegt 30 Tage im Stream. |
| `va.portfolio.alert.raised` | portfolio → web-api | depot_id, Zahl neuer kritischer Hinweise und Ad-hoc-Mitteilungen, für die Sofortmeldung ([berichte.md](berichte.md#ablauf)) |

Das web-api meldet es auf dem Topic `depot:<id>` an die Tabs des Besitzers, die dann per REST
nachladen.

## API

| Methode und Pfad | Zweck |
|---|---|
| `GET /api/v1/depots/{id}/analysis` | jüngste Analyse |
| `GET /api/v1/depots/{id}/hints?status=` | Hinweise |
| `POST /api/v1/depots/{id}/hints/{key}/ack` | zur Kenntnis nehmen |
| `GET`/`PUT /api/v1/depots/{id}/hint-params` | Schwellen (mit `If-Match`) |
| `GET /api/v1/hints/catalog` | Katalog mit Texten für das UI |
| `GET /api/v1/depots/{id}/positions/{isin}/comparison` | Prüfkandidaten |

## Tests und Abnahme

- `place()`: die Eigenschaften oben, dazu Golden-File mit einem eingefrorenen Universum und drei
  Kandidaten (deutscher Titel, US-Titel, Bank).
- `analyze()`: Beispieldepots als JSON-Fixtures (nur Aktien, Aktien plus Welt-ETF, mit Anleihen,
  mit fehlenden Kursen), Golden-Files der Analyse.
- Jede Regel: ein Test knapp unter und knapp über der Schwelle.
- Lebenszyklus: neu, besteht, erledigt, zur Kenntnis genommen und wieder sichtbar.
- Ranking und Mail-Golden-Master bleiben unverändert, ebenso die Replay-Fixtures.
