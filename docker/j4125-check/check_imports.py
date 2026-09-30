"""J4125-Pruefung: laeuft im App-Image unter QEMU mit einem CPU-Modell ohne AVX (ADR-0008).

Braucht ein Paket AVX/AVX2 (x86-64-v3), stuerzt der Import mit "Illegal instruction" ab
und der Container endet mit einem Fehlercode. Zusaetzlich prueft das Skript, dass die
Emulation wirklich greift - sonst waere ein gruenes Ergebnis wertlos.
"""

from __future__ import annotations

import sys

import numpy as np
from numpy._core._multiarray_umath import __cpu_features__ as cpu

if cpu.get("AVX") or cpu.get("AVX2"):
    sys.exit("FEHLER: CPU zeigt AVX/AVX2 - laeuft die Pruefung wirklich unter QEMU (-cpu Denverton)?")
if not cpu.get("SSE42"):
    sys.exit("FEHLER: SSE4.2 fehlt - das CPU-Modell ist schwaecher als der J4125")
print(f"CPU-Modell ok: SSE4.2 ja, AVX nein, AVX2 nein (numpy {np.__version__})")

# Alle nativen Abhaengigkeiten laden, die im Wochenlauf gebraucht werden
import curl_cffi  # noqa: E402
import lxml.etree  # noqa: E402
import openpyxl  # noqa: E402
import pandas as pd  # noqa: E402
import psycopg  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import pydantic  # noqa: E402
import sqlalchemy  # noqa: E402
import yfinance  # noqa: E402

sys.path.insert(0, "/app")
from src.scoring import ScoringConfig, score  # noqa: E402

# Rechnen wie im Wochenlauf: Perzentil-Ranking und ein Parquet-Rundlauf (Altdaten-Import)
rng = np.random.default_rng(0)
n = 90
df = pd.DataFrame(
    {
        "symbol": [f"T{i}.DE" for i in range(n)],
        "market_cap": rng.uniform(3e8, 2e11, n),
        "ev_ebit": rng.normal(15, 8, n),
        "pb_ratio": rng.uniform(0.3, 8, n),
        "p_fcf": rng.normal(18, 10, n),
        "shareholder_yield": rng.uniform(0, 0.08, n),
        "roic": rng.normal(0.1, 0.08, n),
        "fcf_margin": rng.normal(0.08, 0.06, n),
        "operating_margin": rng.normal(0.12, 0.08, n),
        "net_debt_ebitda": rng.normal(1.5, 1.2, n),
        "earnings_stability": rng.uniform(0, 1, n),
    }
)
scored = score(df, ScoringConfig())
assert scored["composite_score"].notna().sum() > 80

buffer = pa.BufferOutputStream()
pq.write_table(pa.Table.from_pandas(scored), buffer)
roundtrip = pq.read_table(pa.BufferReader(buffer.getvalue())).to_pandas()
assert len(roundtrip) == len(scored)

versions = {
    "pandas": pd.__version__,
    "pyarrow": pa.__version__,
    "psycopg": psycopg.__version__,
    "sqlalchemy": sqlalchemy.__version__,
    "yfinance": yfinance.__version__,
    "curl_cffi": curl_cffi.__version__,
    "lxml": ".".join(map(str, lxml.etree.LXML_VERSION)),
    "openpyxl": openpyxl.__version__,
    "pydantic": pydantic.VERSION,
}
print("J4125-Pruefung bestanden:", ", ".join(f"{k} {v}" for k, v in versions.items()))
