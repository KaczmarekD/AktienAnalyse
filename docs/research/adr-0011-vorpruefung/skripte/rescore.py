"""ADR-0011, Vorprüfung 1: Rescore v1 gegen v2 auf der echten Woche vom 30.10.2026.

v1 rechnet mit der Konfiguration aus der Replay-Fixture und muss deren gespeicherte Scores
reproduzieren. v2 nimmt die Faktoren und Regeln aus ADR-0011: neue Kennzahlen aus den Rohdaten
von Yahoo (fetch_raw.py), Profil v2, Branchenregel für Banken und Versicherer (Variante A) und
zusätzlich für Immobilien (Variante B), Momentum-Regel im Value-Trap-Flag.

Prototyp für die Entscheidung, kein Produktcode. Vereinfachungen stehen im Bericht.
"""

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from va_scoring.domain.scoring import ScoringConfig, score

FIXTURE, RAW, OUT = (Path(arg) for arg in sys.argv[1:4])
OUT.mkdir(parents=True, exist_ok=True)
TOP, FLOP = 20, 10
COST_OF_CAPITAL, TERMINAL_GROWTH = 0.08, 0.02  # Standardwerte aus ADR-0011, Punkt 6

fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
snap = pd.DataFrame(fixture["snapshots"]["rows"], columns=fixture["snapshots"]["columns"])


def config(raw: dict) -> ScoringConfig:
    values = dict(raw)
    values["value_factors"] = {k: tuple(v) for k, v in raw["value_factors"].items()}
    values["quality_factors"] = {k: tuple(v) for k, v in raw["quality_factors"].items()}
    return ScoringConfig(**values)


CFG_V1 = config(fixture["config"])

# --- Rohdaten -> Kennzahlen aus ADR-0011 -------------------------------------------------------

NAMES = {
    "net_income": ("Net Income", "Net Income Common Stockholders"),
    "revenue": ("Total Revenue", "Operating Revenue"),
    "gross_profit": ("Gross Profit",),
    "total_assets": ("Total Assets",),
    "long_term_debt": ("Long Term Debt", "Long Term Debt And Capital Lease Obligation"),
    "current_assets": ("Current Assets",),
    "current_liabilities": ("Current Liabilities",),
    "shares": ("Ordinary Shares Number", "Share Issued"),
    "equity": ("Stockholders Equity", "Common Stock Equity"),
    "cfo": ("Operating Cash Flow",),
}


def pick(block: dict, year: str, key: str):
    for name in NAMES[key]:
        value = block.get(year, {}).get(name)
        if value is not None and math.isfinite(value):
            return value
    return None


def years(raw: dict) -> list[str]:
    """Geschäftsjahre mit Bilanzsumme, neuestes zuerst."""
    return sorted(
        (y for y in raw["balance"] if pick(raw["balance"], y, "total_assets")), reverse=True
    )


def gt(a, b):
    return None if a is None or b is None else int(a > b)


def f_score(raw: dict):
    """Piotroski (2000), neun Signale aus den letzten zwei Geschäftsjahren. Vereinfachung: ROA und
    Kapitalumschlag mit der Bilanzsumme am Jahresende statt am Jahresanfang. Fehlt ein Signal,
    gibt es keinen F-Score (None), wie im Implementierungsplan F2.1 verlangt."""
    ys = years(raw)
    if len(ys) < 2:
        return None, None
    t, p = ys[0], ys[1]
    inc, bal, cf = raw["income"], raw["balance"], raw["cashflow"]
    ni_t, ni_p = pick(inc, t, "net_income"), pick(inc, p, "net_income")
    ta_t, ta_p = pick(bal, t, "total_assets"), pick(bal, p, "total_assets")
    cfo_t = pick(cf, t, "cfo")
    rev_t, rev_p = pick(inc, t, "revenue"), pick(inc, p, "revenue")
    gp_t, gp_p = pick(inc, t, "gross_profit"), pick(inc, p, "gross_profit")
    ltd_t, ltd_p = pick(bal, t, "long_term_debt") or 0.0, pick(bal, p, "long_term_debt") or 0.0
    ca_t, ca_p = pick(bal, t, "current_assets"), pick(bal, p, "current_assets")
    cl_t, cl_p = pick(bal, t, "current_liabilities"), pick(bal, p, "current_liabilities")
    sh_t, sh_p = pick(bal, t, "shares"), pick(bal, p, "shares")

    def ratio(a, b):
        return None if a is None or not b else a / b

    roa_t, roa_p = ratio(ni_t, ta_t), ratio(ni_p, ta_p)
    signals = {
        "roa_positive": gt(roa_t, 0),
        "cfo_positive": gt(cfo_t, 0),
        "roa_up": gt(roa_t, roa_p),
        "cfo_above_ni": gt(ratio(cfo_t, ta_t), roa_t),
        "leverage_down": (
            1 if ltd_t == 0 and ltd_p == 0 else gt(ratio(ltd_p, ta_p), ratio(ltd_t, ta_t))
        ),
        "liquidity_up": gt(ratio(ca_t, cl_t), ratio(ca_p, cl_p)),
        "no_issuance": None if sh_t is None or sh_p is None else int(sh_t <= sh_p * 1.001),
        "margin_up": gt(ratio(gp_t, rev_t), ratio(gp_p, rev_p)),
        "turnover_up": gt(ratio(rev_t, ta_t), ratio(rev_p, ta_p)),
    }
    missing = [k for k, v in signals.items() if v is None]
    return (None if missing else sum(signals.values())), missing


def accruals(raw: dict):
    ys = years(raw)
    if not ys:
        return None, None, None
    t = ys[0]
    ni, cfo = pick(raw["income"], t, "net_income"), pick(raw["cashflow"], t, "cfo")
    ta = pick(raw["balance"], t, "total_assets")
    equity = pick(raw["balance"], t, "equity")
    acc = None if ni is None or cfo is None or not ta else (ni - cfo) / ta
    cfoa = None if cfo is None or not ta else cfo / ta
    roe = None if ni is None or not equity or equity <= 0 else ni / equity
    return acc, cfoa, roe


def net_share_issuance(raw: dict):
    """Veränderung der Aktienanzahl über 12 Monate, um Splits bereinigt. Robust gegen Ausreißer
    der Yahoo-Serie: Median der letzten zehn Werte gegen den Median um den Stichtag vor einem Jahr
    (±20 Tage). Ohne Serie: Bilanzposten Jahresende gegen Vorjahr."""
    series = pd.Series(raw["shares"], dtype=float)
    if len(series) >= 5:
        series.index = pd.to_datetime(series.index)
        series = series.sort_index()
        end = series.index.max()
        then = end - pd.Timedelta(days=365)
        around = series[
            (series.index >= then - pd.Timedelta(days=20))
            & (series.index <= then + pd.Timedelta(days=20))
        ]
        if not around.empty:
            now_value = series.iloc[-10:].median()
            then_value = around.median()
            factor = 1.0
            for day, split in raw["splits"].items():
                if pd.Timestamp(day) > then:
                    factor *= split
            if then_value > 0:
                return now_value / (then_value * factor) - 1.0, "serie"
    ys = years(raw)
    if len(ys) >= 2:
        sh_t, sh_p = pick(raw["balance"], ys[0], "shares"), pick(raw["balance"], ys[1], "shares")
        if sh_t and sh_p:
            return sh_t / sh_p - 1.0, "bilanz"
    return None, None


def momentum(raw: dict):
    """12-1-Monats-Momentum aus bereinigten Schlusskursen: der letzte Monat ausgelassen."""
    closes = pd.Series(raw["close"], dtype=float).sort_index()
    if len(closes) < 253:
        return None
    return closes.iloc[-22] / closes.iloc[-253] - 1.0


extra_rows, notes = [], {}
for symbol in snap["symbol"]:
    path = RAW / f"{symbol}.json"
    if not path.exists():
        notes[symbol] = "keine Rohdaten"
        extra_rows.append({"symbol": symbol})
        continue
    raw = json.loads(path.read_text(encoding="utf-8"))
    fs, fs_missing = f_score(raw)
    acc, cfoa, roe = accruals(raw)
    nsi, nsi_source = net_share_issuance(raw)
    extra_rows.append(
        {
            "symbol": symbol,
            "f_score": fs,
            "f_score_missing": ",".join(fs_missing or []),
            "operating_accruals": acc,
            "cfo_assets": cfoa,
            "net_share_issuance": nsi,
            "nsi_source": nsi_source,
            "momentum_12_1": momentum(raw),
            "roe": roe,
            "fiscal_year": (years(raw) or [None])[0],
        }
    )
extra = pd.DataFrame(extra_rows)
df = snap.merge(extra, on="symbol", how="left")
df["neg_issuance"] = -df["net_share_issuance"]  # Rückkauf hoch = gut; kein Multiple (ADR Punkt 1)

# --- Profile ------------------------------------------------------------------------------------

FINANCIAL_EXCLUDED = [
    "ev_ebit",
    "p_fcf",
    "fcf_margin",
    "net_debt_ebitda",
    "operating_margin",
    "roic",
    "f_score",
    "operating_accruals",
    "cfo_assets",
]


def is_financial(industry) -> bool:
    text = str(industry or "")
    return text.startswith("Banks") or text.startswith("Insurance")


def is_real_estate(industry) -> bool:
    text = str(industry or "")
    return text.startswith("Real Estate") or "REIT" in text


CFG_V2 = ScoringConfig(
    min_market_cap=CFG_V1.min_market_cap,
    value_weight=CFG_V1.value_weight,
    quality_weight=CFG_V1.quality_weight,
    min_value_factor_share=CFG_V1.min_value_factor_share,
    min_quality_factor_share=CFG_V1.min_quality_factor_share,
    min_factor_count=CFG_V1.min_factor_count,
    value_trap_value_threshold=CFG_V1.value_trap_value_threshold,
    value_trap_quality_threshold=CFG_V1.value_trap_quality_threshold,
    drop_negative_value_metrics=CFG_V1.drop_negative_value_metrics,
    value_factors={
        "ev_ebit": ("ev_ebit", "low"),
        "p_fcf": ("p_fcf", "low"),
        "net_share_issuance": ("neg_issuance", "high"),
    },
    quality_factors={
        "roic": ("roic", "high"),
        "fcf_margin": ("fcf_margin", "high"),
        "f_score": ("f_score", "high"),
        "operating_accruals": ("operating_accruals", "low"),
        "cfo_assets": ("cfo_assets", "high"),
    },
)


def run_v2(frame: pd.DataFrame, rule) -> pd.DataFrame:
    data = frame.copy()
    mask = data["industry"].map(rule)
    data.loc[mask, FINANCIAL_EXCLUDED] = np.nan
    result = score(data, CFG_V2)
    # Momentum-Regel (ADR Punkt 5): Rang im bewerteten Querschnitt
    result["momentum_rank"] = result["momentum_12_1"].rank(pct=True)
    result["trap_momentum"] = (
        (result["value_score"].fillna(0) >= CFG_V2.value_trap_value_threshold)
        & (result["momentum_rank"].fillna(1) <= 0.30)
        & (result["f_score"].fillna(9) <= 3)
    )
    result["trap_quality"] = result["value_trap_flag"]
    result["value_trap_flag"] = result["trap_quality"] | result["trap_momentum"]
    result["finanzwert"] = result["industry"].map(rule)
    return result


v1 = score(df, CFG_V1)
stored = pd.DataFrame(fixture["scores"]["rows"], columns=fixture["scores"]["columns"])
check = v1.merge(stored, on="symbol", suffixes=("", "_stored"))
reproduced = float(
    (check["composite_score"].fillna(-1) - check["composite_score_stored"].fillna(-1)).abs().max()
)
v2a = run_v2(df, is_financial)
v2b = run_v2(df, lambda industry: is_financial(industry) or is_real_estate(industry))

# --- Vergleich ----------------------------------------------------------------------------------


def ranked(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[frame["composite_score"].notna()].copy()
    out["rank"] = np.arange(1, len(out) + 1)
    return out.set_index("symbol")


r1, ra, rb = ranked(v1), ranked(v2a), ranked(v2b)


def top(frame, n):
    return list(frame.index[:n])


def compare(name: str, other: pd.DataFrame) -> dict:
    t1, t2 = top(r1, TOP), top(other, TOP)
    f1, f2 = list(r1.index[-FLOP:]), list(other.index[-FLOP:])
    both = r1.index.intersection(other.index)
    # Spearman = Pearson auf den Rängen (ohne scipy)
    rho = float(r1.loc[both, "rank"].rank().corr(other.loc[both, "rank"].rank()))
    moves = (r1.loc[both, "rank"] - other.loc[both, "rank"]).sort_values()
    return {
        "variant": name,
        "ranked_v1": len(r1),
        "ranked_v2": len(other),
        "top_overlap": len(set(t1) & set(t2)),
        "top_entered": [s for s in t2 if s not in t1],
        "top_left": [s for s in t1 if s not in t2],
        "flop_overlap": len(set(f1) & set(f2)),
        "spearman_common": rho,
        "common": len(both),
        "biggest_up": [
            (s, int(r1.loc[s, "rank"]), int(other.loc[s, "rank"])) for s in moves.index[-8:][::-1]
        ],
        "biggest_down": [
            (s, int(r1.loc[s, "rank"]), int(other.loc[s, "rank"])) for s in moves.index[:8]
        ],
        "traps_v1": sorted(r1.index[r1["value_trap_flag"]]),
        "traps_v2_quality": sorted(other.index[other["trap_quality"]]),
        "traps_v2_momentum": sorted(other.index[other["trap_momentum"]]),
    }


passing = df[df["market_cap"].fillna(0) >= CFG_V1.min_market_cap]
nonfin = passing[~passing["industry"].map(is_financial)]
coverage = {
    key: f"{int(nonfin[key].notna().sum())}/{len(nonfin)}"
    for key in [
        "f_score",
        "operating_accruals",
        "cfo_assets",
        "net_share_issuance",
        "momentum_12_1",
    ]
}

fin = v2a[v2a["finanzwert"]].copy()
fin["justified_pb"] = (fin["roe"] - TERMINAL_GROWTH) / (COST_OF_CAPITAL - TERMINAL_GROWTH)
finanzwerte = fin[["symbol", "name", "industry", "pb_ratio", "pe_ratio", "roe", "justified_pb"]]

summary = {
    "reproduced_v1_max_abs_diff": reproduced,
    "coverage_non_financials": coverage,
    "f_score_missing_signals": extra["f_score_missing"]
    .replace("", np.nan)
    .dropna()
    .str.split(",")
    .explode()
    .value_counts()
    .to_dict(),
    "nsi_sources": extra["nsi_source"].value_counts(dropna=False).to_dict(),
    "notes": notes,
    "compare_a": compare("A: Banken und Versicherer", ra),
    "compare_b": compare("B: dazu Immobilien", rb),
    "finanzwerte_a": finanzwerte.round(4).to_dict(orient="records"),
}
(OUT / "summary.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
)

names = df.set_index("symbol")["name"].to_dict()
cols = ["rank", "composite_score", "value_score", "quality_score", "value_trap_flag"]
table = pd.DataFrame(
    {"v1": pd.Series(r1["rank"]), "v2A": pd.Series(ra["rank"]), "v2B": pd.Series(rb["rank"])}
)
table.insert(0, "name", [names.get(s) for s in table.index])
table = table.sort_values(["v1", "v2A"], na_position="last")
table.to_csv(OUT / "raenge.csv", sep=";", decimal=",", encoding="utf-8-sig")
df.to_csv(OUT / "faktoren.csv", sep=";", decimal=",", encoding="utf-8-sig", index=False)

print(
    json.dumps(
        {
            k: summary[k]
            for k in [
                "reproduced_v1_max_abs_diff",
                "coverage_non_financials",
                "f_score_missing_signals",
                "nsi_sources",
            ]
        },
        indent=1,
        default=str,
    )
)
for key in ["compare_a", "compare_b"]:
    c = summary[key]
    print(
        f"\n{c['variant']}: bewertet v1 {c['ranked_v1']}, v2 {c['ranked_v2']}; "
        f"Top {TOP} gemeinsam {c['top_overlap']}, Flop {FLOP} gemeinsam {c['flop_overlap']}, "
        f"Spearman (gemeinsame {c['common']}) {c['spearman_common']:.2f}"
    )
    print("  neu in Top:", [names[s] for s in c["top_entered"]])
    print("  raus aus Top:", [names[s] for s in c["top_left"]])
    print("  hoch:", [(names[s], a, b) for s, a, b in c["biggest_up"][:5]])
    print("  runter:", [(names[s], a, b) for s, a, b in c["biggest_down"][:5]])
    print("  Traps v1:", [names[s] for s in c["traps_v1"]])
    print(
        "  Traps v2 Quality:",
        [names[s] for s in c["traps_v2_quality"]],
        "Momentum:",
        [names[s] for s in c["traps_v2_momentum"]],
    )
print("\nFinanzwerte (A):")
print(finanzwerte.round(3).to_string(index=False))
