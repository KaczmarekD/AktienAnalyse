"""J4125-Pruefung: laeuft im App-Image unter QEMU mit einem CPU-Modell ohne AVX (ADR-0008).

Braucht ein Paket AVX/AVX2 (x86-64-v3), stuerzt Python mit "Illegal instruction" ab und
der Container endet mit Exit-Code 132. Vorher prueft run.sh per Gegenprobe, dass die
Emulation AVX2 wirklich abfaengt. Ablauf hier:

1. Sicherstellen, dass die Emulation greift (kein AVX/AVX2, aber SSE4.2) - sonst waere ein
   gruenes Ergebnis wertlos.
2. Jede native Erweiterung im Image importieren; jeder Fehler bricht ab. Sie werden
   automatisch gefunden, es gibt keine Liste, die veralten kann. Danach den Importgraph der
   App ueber src.main laden.
3. Rechnen wie im Wochenlauf: Scoring, Mail-Report (Jinja2/MarkupSafe), Parquet-Rundlauf.

Aufruf: make check-j4125 (Stufe j4125-check im Dockerfile)
"""

from __future__ import annotations

import importlib
import sys
import sysconfig
from datetime import datetime
from pathlib import Path
from typing import NoReturn


def fail(message: str) -> NoReturn:
    sys.exit(f"FEHLER: {message}")


def cpu_features() -> dict[str, bool]:
    # Private numpy-API: Zieht sie bei einem numpy-Upgrade um, soll das klar gemeldet werden
    try:
        from numpy._core._multiarray_umath import __cpu_features__  # noqa: PLC0415
    except ImportError:
        fail("numpy-CPU-Features nicht gefunden (numpy-API geaendert?) - Pruefskript anpassen")
    return dict(__cpu_features__)


def native_extension_modules(site_packages: Path) -> list[str]:
    """Alle kompilierten Python-Erweiterungen (.so) unter site-packages als Modulnamen."""
    names = []
    for path in sorted(site_packages.rglob("*.so")):
        # Mitgelieferte C-Bibliotheken (z. B. numpy.libs/libopenblas*.so) sind keine Module
        if ".cpython-" not in path.name and ".abi3." not in path.name:
            continue
        rel = path.relative_to(site_packages)
        names.append(".".join((*rel.parts[:-1], rel.name.split(".", 1)[0])))
    return names


# 1. Emulation greift?
cpu = cpu_features()
if cpu.get("AVX") or cpu.get("AVX2"):
    fail("CPU zeigt AVX/AVX2 - laeuft die Pruefung wirklich unter QEMU (-cpu Denverton)?")
if not cpu.get("SSE42"):
    fail("SSE4.2 fehlt - das CPU-Modell ist schwaecher als der J4125")
print("CPU-Modell ok: SSE4.2 ja, AVX nein, AVX2 nein")

# 2. Alle nativen Erweiterungen und die App laden
# psycopg_binary laesst sich erst nach psycopg importieren. Die App braucht die
# C-Implementierung: Die reine Python-Variante faende im Image keine libpq.
import psycopg  # noqa: E402

if psycopg.pq.__impl__ != "binary":
    fail(f"psycopg laeuft als {psycopg.pq.__impl__!r} statt 'binary' - psycopg[binary] im Lock?")

site_packages = Path(sysconfig.get_paths()["platlib"])
modules = native_extension_modules(site_packages)
if len(modules) < 50:
    fail(f"nur {len(modules)} Erweiterungen gefunden - Suche nach .so kaputt?")
failed: list[str] = []
for name in modules:
    try:
        importlib.import_module(name)
    except (
        Exception
    ) as exc:  # jeder Fehler zaehlt: numpy meldet fehlende CPU-Features per RuntimeError
        failed.append(f"{name}: {type(exc).__name__}: {exc}")
if failed:
    fail("Import fehlgeschlagen:\n  " + "\n  ".join(failed))
print(
    f"Native Erweiterungen: alle {len(modules)} geladen, psycopg binary (libpq {psycopg.pq.version()})"
)

sys.path.insert(0, "/app")
importlib.import_module("src.main")  # kompletter Importgraph der App
print("App-Importgraph (src.main) geladen")

# 3. Rechnen wie im Wochenlauf
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from src.fundamentals import (  # noqa: E402
    Fundamentals,
    Identity,
    MarketData,
    QualityMetrics,
    ValueMetrics,
)
from src.reporting import build_report  # noqa: E402
from src.scoring import ScoringConfig, score  # noqa: E402

# Zufaellige Titel ueber die Dataclass wie in fetch_all: So hat der Frame immer genau
# die Spalten, die Scoring und Mail-Template erwarten, auch wenn Felder dazukommen.
rng = np.random.default_rng(0)
n = 90
records = []
for i in range(n):
    dividend_yield = float(rng.uniform(0, 0.06))
    buyback_yield = float(rng.uniform(0, 0.03))
    fund = Fundamentals(
        identity=Identity(
            symbol=f"T{i}.DE",
            name=f"Titel {i}",
            index="DAX" if i < 40 else "MDAX",
            sector="Industrials",
            currency="EUR",
            financial_currency="EUR",
        ),
        market=MarketData(
            price=float(rng.uniform(5, 500)), market_cap=float(rng.uniform(3e8, 2e11))
        ),
        value=ValueMetrics(
            ev_ebit=float(rng.normal(15, 8)),
            pe_ratio=float(rng.normal(18, 9)),
            pb_ratio=float(rng.uniform(0.3, 8)),
            p_fcf=float(rng.normal(18, 10)),
            dividend_yield=dividend_yield,
            buyback_yield=buyback_yield,
            shareholder_yield=dividend_yield + buyback_yield,
        ),
        quality=QualityMetrics(
            roic=float(rng.normal(0.1, 0.08)),
            fcf_margin=float(rng.normal(0.08, 0.06)),
            operating_margin=float(rng.normal(0.12, 0.08)),
            net_debt_ebitda=float(rng.normal(1.5, 1.2)),
            earnings_stability=float(rng.uniform(0, 1)),
        ),
    )
    records.append(fund.to_flat_dict())
scored = score(pd.DataFrame(records), ScoringConfig())
for column in ("value_score", "quality_score", "composite_score"):
    if int(scored[column].notna().sum()) < 80:
        fail(f"{column}: zu wenige Werte - Ranking unter Emulation fehlerhaft")

report = build_report(scored, universe_size=n, now=datetime(2026, 1, 1, 7, 30))
if "Value-Screening" not in report.html or not report.csv_bytes:
    fail("Report unvollstaendig")

buffer = pa.BufferOutputStream()
pq.write_table(pa.Table.from_pandas(scored), buffer)
if pq.read_table(pa.BufferReader(buffer.getvalue())).num_rows != len(scored):
    fail("Parquet-Rundlauf fehlerhaft")

print(
    f"J4125-Pruefung bestanden (Python {sys.version.split()[0]}, numpy {np.__version__}, "
    f"pandas {pd.__version__}, pyarrow {pa.__version__})"
)
