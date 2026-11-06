"""ADR-0011, Vorprüfung 2: Enthält das EBIT von Yahoo bei Immobilienwerten Bewertungsergebnisse
nach IAS 40? Gibt die relevanten Zeilen der Jahresabschlüsse aus und speichert sie als JSON."""

import json
import sys
from pathlib import Path

import yfinance as yf

OUT = Path(sys.argv[1])
TICKERS = {
    "VNA.DE": "Vonovia",
    "LEG.DE": "LEG Immobilien",
    "TEG.DE": "TAG Immobilien",
    "AT1.DE": "Aroundtown",
}
ROWS = [
    "Total Revenue",
    "Operating Revenue",
    "Gross Profit",
    "Operating Income",
    "EBIT",
    "EBITDA",
    "Normalized EBITDA",
    "Normalized Income",
    "Total Unusual Items",
    "Total Unusual Items Excluding Goodwill",
    "Special Income Charges",
    "Gain On Sale Of Ppe",
    "Gain On Sale Of Business",
    "Other Special Charges",
    "Write Off",
    "Impairment Of Capital Assets",
    "Other Non Operating Income Expenses",
    "Net Non Operating Interest Income Expense",
    "Pretax Income",
    "Tax Provision",
    "Net Income",
    "Net Income Common Stockholders",
]

result = {}
for symbol, name in TICKERS.items():
    ticker = yf.Ticker(symbol)
    stmt = ticker.income_stmt
    info = ticker.info
    result[symbol] = {
        "name": name,
        "industry": info.get("industry"),
        "sector": info.get("sector"),
        "rows_available": [str(i) for i in stmt.index],
        "years": {},
    }
    for column in stmt.columns:
        year = str(column.date())
        result[symbol]["years"][year] = {
            row: (
                None
                if row not in stmt.index or stmt.loc[row, column] != stmt.loc[row, column]
                else float(stmt.loc[row, column])
            )
            for row in ROWS
        }
    print(f"\n=== {symbol} {name} ({info.get('industry')})")
    for year, values in result[symbol]["years"].items():

        def mrd(key, values=values):
            v = values.get(key)
            return "-" if v is None else f"{v / 1e9:7.2f}"

        print(
            f"{year}: Umsatz {mrd('Total Revenue')} | OpInc {mrd('Operating Income')} | "
            f"EBIT {mrd('EBIT')} | EBITDA {mrd('EBITDA')} | NormEBITDA {mrd('Normalized EBITDA')} | "
            f"Unusual {mrd('Total Unusual Items')} | Pretax {mrd('Pretax Income')} | "
            f"NetInc {mrd('Net Income')}"
        )

OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
print("\ngespeichert:", OUT)
