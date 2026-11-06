"""ADR-0011, Vorprüfung 1: Rohdaten für die Faktoren aus v2 je Titel der Replay-Woche.

Holt von Yahoo die Jahresabschlüsse (GuV, Bilanz, Cashflow), die Aktienanzahl der letzten
14 Monate, Splits und 400 Tage Kurse. Jeder Titel landet als JSON im Cache-Ordner; schon
geholte Titel werden übersprungen. Nur Prototyp für die Entscheidung, kein Produktcode.
"""

import datetime as dt
import json
import sys
import time
from pathlib import Path

import yfinance as yf

FIXTURE = Path(sys.argv[1])
CACHE = Path(sys.argv[2])
CACHE.mkdir(parents=True, exist_ok=True)

fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
columns = fixture["snapshots"]["columns"]
symbols = [row[columns.index("symbol")] for row in fixture["snapshots"]["rows"]]


def frame(df):
    """DataFrame (Zeilen = Posten, Spalten = Stichtage) als {Stichtag: {Posten: Wert}}."""
    out = {}
    if df is None or df.empty:
        return out
    for column in df.columns:
        key = str(column.date()) if hasattr(column, "date") else str(column)
        out[key] = {
            str(row): float(df.loc[row, column])
            for row in df.index
            if df.loc[row, column] == df.loc[row, column]  # ohne NaN
        }
    return out


today = dt.date.today()
for number, symbol in enumerate(symbols, 1):
    target = CACHE / f"{symbol}.json"
    if target.exists():
        continue
    for attempt in range(3):
        try:
            ticker = yf.Ticker(symbol)
            shares = ticker.get_shares_full(start=today - dt.timedelta(days=430), end=today)
            history = ticker.history(period="400d", auto_adjust=True, actions=True)
            data = {
                "symbol": symbol,
                "fetched": str(today),
                "income": frame(ticker.income_stmt),
                "balance": frame(ticker.balance_sheet),
                "cashflow": frame(ticker.cashflow),
                "shares": (
                    {}
                    if shares is None or shares.empty
                    else {str(index.date()): float(value) for index, value in shares.items()}
                ),
                "close": {
                    str(index.date()): float(value) for index, value in history["Close"].items()
                },
                "splits": {
                    str(index.date()): float(value)
                    for index, value in history.get("Stock Splits", {}).items()
                    if value
                },
            }
            target.write_text(json.dumps(data), encoding="utf-8")
            print(
                f"{number:3d}/{len(symbols)} {symbol}: GuV {len(data['income'])} J, "
                f"Aktien {len(data['shares'])}, Kurse {len(data['close'])}",
                flush=True,
            )
            break
        except Exception as error:
            print(f"{symbol}: Versuch {attempt + 1} gescheitert: {error}", flush=True)
            time.sleep(10 * (attempt + 1))
    time.sleep(1.0)
print("fertig", flush=True)
