# Datenquellen für Langfrist-Fundamentaldaten: Live-Tests vom 30.09.2026

## yfinance 0.2.66

Getestet wurde die Version aus dem Projekt-Lockfile in einer frischen venv mit pandas 3.0.6, am
30.09.2026 gegen 22 Uhr. Die Stichprobe umfasst acht Titel, sechs aus dem DAX und zwei aus dem MDAX.
Das Skript steht am Ende dieser Notiz.

| Symbol | Index | Kurse ab | Jahre | Ausschüttungen | Jahresabschlüsse (GuV/Bilanz/CF) | Quartale | Aktienanzahl ab | F&E-Zeile | Analysten | Yahoo-Branche |
|---|---|---|---|---|---|---|---|---|---|---|
| SAP.DE | DAX | 09.04.1998 | 28,5 | 28 | 4/4/4 | 6 | 04/2015 | ja | 26 | Software – Application |
| SIE.DE | DAX | 08.11.1996 | 29,9 | 30 | 4/4/4 | 5 | 12/2015 | ja | 22 | Specialty Industrial Machinery |
| ALV.DE | DAX | 16.12.1996 | 29,8 | 27 | 4/5/4 | 7 | 03/2015 | nein | 16 | Insurance – Diversified |
| DBK.DE | DAX | 18.11.1996 | 29,9 | 31 | 4/4/4 | 6 | 10/2015 | nein | 18 | Banks – Regional |
| RHM.DE | DAX | 05.08.1998 | 28,2 | 27 | 4/4/5 | 6 | 11/2015 | nein | 21 | Aerospace & Defense |
| HNR1.DE | DAX | 23.10.2000 | 25,9 | 23 | 5/5/5 | 6 | 10/2003 | nein | 15 | Insurance – Reinsurance |
| KGX.DE | MDAX | 08.07.2013 | 13,2 | 13 | 4/4/4 | 5 | 07/2016 | ja | 15 | Farm & Heavy Construction Machinery |
| LEG.DE | MDAX | 08.07.2013 | 13,2 | 13 | 4/4/4 | 6 | 11/2015 | nein | 14 | Real Estate Services |

„Jahresabschlüsse“ zählt die Geschäftsjahre mit mehr als drei befüllten Zeilen. Kion und LEG notieren
erst seit dem Börsengang 2013.

**Konsensdaten sind für alle acht Titel vorhanden**, auch für die beiden MDAX-Werte. Dazu gehören
`earnings_estimate`, `revenue_estimate`, `eps_trend` (4×5), `eps_revisions` (4×4),
`growth_estimates` und `analyst_price_targets`. `eps_trend` zeigt die Konsens-EPS heute sowie vor 7,
30, 60 und 90 Tagen, jeweils für das laufende und das nächste Quartal und Geschäftsjahr.
`eps_revisions` zählt die Erhöhungen und Senkungen der letzten 7 und 30 Tage. Ein Beispiel für
KGX.DE: Die EPS-Schätzung für das nächste Geschäftsjahr liegt bei 4,548 gegenüber 4,718 vor 90 Tagen,
also bei −3,6 %. In den letzten 30 Tagen gab es 7 Senkungen und 1 Erhöhung. Die Zeile für das
langfristige Wachstum (LTG) in `growth_estimates` war bei KGX leer.

**Insiderdaten fehlen.** `insider_transactions` war bei allen acht Titeln leer. `insider_purchases`
enthält nur eine Platzhaltertabelle mit null Käufen. Yahoo hat also keine deutschen Directors'
Dealings. `upgrades_downgrades` war nur bei DBK befüllt (79 Zeilen). Bei sieben Titeln meldete Yahoo
für eines der leeren Zusatzmodule HTTP 404 („No fundamentals data found“).

**Die DB sammelt bereits eine Konsenshistorie.** `info` wird jede Woche vollständig in
`market_data.raw_info` gespeichert und enthält unter anderem `forwardEps`, `targetMeanPrice`,
`numberOfAnalystOpinions` (14 bis 26) und `recommendationMean`. Nicht gespeichert werden `eps_trend`,
`eps_revisions`, die Schätztabellen und die Quartalsabschlüsse. `statement_value` führt heute nur
`frequency = annual`.

**Hinweis zur Testumgebung:** Unter Windows ließ sich `curl_cffi`, eine Abhängigkeit von yfinance,
im langen Scratchpad-Pfad nicht laden („Der Dateiname oder die Erweiterung ist zu lang“). Über den
8.3-Kurzpfad lief der Test. Für die NAS spielt das keine Rolle.

## filings.xbrl.org (ESEF-Berichte)

- Die API `https://filings.xbrl.org/api/filings` folgt JSON:API. Sie führte am 30.09.2026
  **25.954 Filings**, der jüngste Eintrag war vom 24.09.2026.
- Mit `filter[country]=DE` liefert sie **0** Treffer. Zum Vergleich: FR 1.179, NL 657, AT 601.
- SAP SE (LEI `529900D6BF99LW9R2E68`), Siemens (`W38RGI023J3WT1HWRP32`) und Allianz
  (`529900K9B0N5BT694847`) existieren als Entitäten, haben aber jeweils **0 Filings**.
- Die [About-Seite](https://filings.xbrl.org/docs/about) nennt Deutschland und Irland ausdrücklich als
  Länder, deren ESEF-Berichte sich nicht zuverlässig finden und laden lassen. Das deutsche OAM ist das
  Unternehmensregister. Die Nutzung der Daten ist dort nach eigener Aussage nicht eingeschränkt.

```bash
curl -s "https://filings.xbrl.org/api/filings?filter%5Bcountry%5D=DE&page%5Bsize%5D=3"
curl -s "https://filings.xbrl.org/api/entities/529900D6BF99LW9R2E68/filings"
```

## ESAP (European Single Access Point)

Die ESMA betreibt das Portal ([ESMA](https://esma.europa.eu/esmas-activities/data/european-single-access-point-esap),
[AMF](https://www.amf-france.org/en/news-publications/news/european-single-access-point-financial-and-non-financial-information-european-entities-esap-enters)).

- Seit dem 10.07.2026 sammelt ESAP Informationen nach der Transparenzrichtlinie (Jahresfinanzberichte
  börsennotierter Emittenten), der Prospekt-Verordnung und der Leerverkaufs-Verordnung.
- Öffentlich zugänglich wird ESAP bis Juli 2027. Art. 7 der Verordnung (EU) 2023/2859 sieht eine API,
  einen Download- und einen Benachrichtigungsdienst vor. Phase 2 folgt ab Januar 2028.
- Offen ist, ob Berichte aus der Zeit vor dem 10.07.2026 nachgeladen werden. Das ließ sich nicht
  klären.

## EODHD Fundamentals

- Die Fundamentals-API gehört zum Tarif **Equity Analyst**: 59,99 €/Monat oder 599,90 €/Jahr
  (49,99 €/Monat), Stand 30.09.2026 ([Preise](https://eodhd.com/pricing)). Die günstigeren Tarife
  enthalten keine Fundamentaldaten.
- Laut Dokumentation reichen die Daten für Nicht-US-Werte bis 2000 zurück. Kleine Werte haben nur 6
  Jahre bzw. 20 Quartale, Bulk-Abrufe nur 4 Jahre bzw. 4 Quartale
  ([Fundamentals-Doku](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds)).
- Ob das für alle 90 DAX/MDAX-Werte in voller Tiefe gilt, wurde nicht live geprüft, weil der
  Demo-Key nicht reicht (siehe [DAX/MDAX-Datenquellen](../../dax-mdax-datenquellen/bericht.md)).
- FMP ließ sich nicht prüfen: Die Preisseite antwortete mit HTTP 403.

## BaFin: Eigengeschäfte von Führungskräften (Art. 19 MAR)

- Vollständige Meldungen stehen etwa 1 bis 2 Arbeitstage nach Abschluss des Verfahrens in der
  Datenbank, und zwar **12 Monate lang**
  ([BaFin](https://www.bafin.de/EN/PublikationenDaten/Datenbanken/DirectorsDealings/directorsdealings_node_en.html)).
- Eine lange Historie entsteht deshalb nur, wenn man selbst sammelt. Ob die Nutzungsbedingungen
  einen automatisierten Abruf erlauben, wurde nicht geprüft.

## Forschungsdatensätze

- **JKP Global Factor Data:** 153 Faktoren, 13 Themes und 93 Länder, Deutschland ab 1986, Update
  04/2026 mit Daten bis 12/2025. Die Faktorrenditen sind frei (CC BY-NC 4.0), Merkmale je Titel gibt es
  nur über WRDS. Die Auswertung steht in [jkp-deutschland.md](jkp-deutschland.md).
- **AQR Quality Minus Junk:** monatliche Faktoren für die USA und 23 weitere Länder einschließlich
  Deutschland (DEU), global ab 1986
  ([AQR](https://www.aqr.com/Insights/Datasets/Quality-Minus-Junk-Factors-Monthly)).

Beide eignen sich zum Kalibrieren und Prüfen der Methodik, nicht für den Wochenlauf.

## Probe-Skript yfinance

```python
"""Live-Probe: Welche Langfrist- und Zusatzdaten liefert yfinance für DAX/MDAX-Titel?"""

import json
import time

import pandas as pd
import yfinance as yf

TICKERS = ["SAP.DE", "SIE.DE", "ALV.DE", "DBK.DE", "RHM.DE", "KGX.DE", "LEG.DE", "HNR1.DE"]
EXTRAS = ("earnings_estimate", "revenue_estimate", "eps_trend", "eps_revisions", "growth_estimates",
          "analyst_price_targets", "upgrades_downgrades", "insider_transactions",
          "insider_purchases", "institutional_holders")


def filled_cols(df):
    if df is None or getattr(df, "empty", True):
        return 0
    return int(sum(df[c].notna().sum() > 3 for c in df.columns))


def shape(obj):
    if isinstance(obj, (pd.DataFrame, pd.Series)):
        return f"{obj.shape}" if not obj.empty else "leer"
    return f"dict[{len(obj)}]" if isinstance(obj, dict) else type(obj).__name__


def safe(fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return f"ERR {type(e).__name__}: {str(e)[:60]}"


out = {}
for sym in TICKERS:
    yt = yf.Ticker(sym)
    r = {}
    hist = safe(lambda: yt.history(period="max", auto_adjust=False, actions=True))
    if isinstance(hist, pd.DataFrame) and not hist.empty:
        r["kurse_ab"] = str(hist.index[0].date())
        r["jahre"] = round((hist.index[-1] - hist.index[0]).days / 365.25, 1)
        r["ausschuettungen"] = int((hist["Dividends"] > 0).sum())
    inc, bal, cf = (safe(lambda a=a: getattr(yt, a)) for a in ("income_stmt", "balance_sheet", "cashflow"))
    r["jahre_guv_bilanz_cf"] = [filled_cols(x) if isinstance(x, pd.DataFrame) else x for x in (inc, bal, cf)]
    r["quartale"] = filled_cols(safe(lambda: yt.quarterly_income_stmt))
    if isinstance(inc, pd.DataFrame):
        r["fue_zeile"] = any("Research" in str(i) for i in inc.index)
    shares = safe(lambda: yt.get_shares_full(start="2000-01-01"))
    if isinstance(shares, pd.Series) and not shares.empty:
        r["aktienanzahl_ab"] = str(shares.index[0].date())
    for attr in EXTRAS:
        v = safe(lambda a=attr: getattr(yt, a))
        r[attr] = shape(v) if not isinstance(v, str) else v
    info = safe(lambda: yt.info)
    if isinstance(info, dict):
        r["info"] = {k: info.get(k) for k in ("numberOfAnalystOpinions", "recommendationMean",
                                              "forwardEps", "targetMeanPrice", "industry")}
    out[sym] = r
    time.sleep(1.0)

print(json.dumps(out, indent=1, ensure_ascii=False, default=str))
```
