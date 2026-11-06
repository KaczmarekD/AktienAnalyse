"""Report-Generierung: HTML-Mail-Body + CSV-Anhang.

Subject-Tag traegt eine Erfolgsstatistik (``ok 102/110`` oder
``partial 60/110``), damit der Posteingang als Health-Check dient.

Die CSV entsteht nur im Speicher: Sie geht als Mail-Anhang raus und wird mit
dem Report in der Datenbank abgelegt. Dateien schreibt nur der Dry-Run.
"""

from __future__ import annotations

import logging
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from importlib import resources
from typing import Any

import numpy as np
import pandas as pd
from jinja2 import Template

from va_contracts.profile import ProfileParamsV1

# Name der Fallback-Quelle wie in market-data (Import verboten, ein Test vergleicht beide)
FALLBACK_SOURCE = "Fallback-CSV"

log = logging.getLogger(__name__)


# Das Template liegt als Datei im Paket (auch installiert im Image in site-packages)
TEMPLATE_NAME = "report.html.j2"
HTML_TEMPLATE = Template(
    resources.files("va_notification")
    .joinpath("templates", TEMPLATE_NAME)
    .read_text(encoding="utf-8"),
    autoescape=True,
)


def render_html(**context: Any) -> str:
    """Das HTML der Mail aus dem Template."""
    return HTML_TEMPLATE.render(**context)


# Textspalten, die das Template mit "or '-'" o. ae. auswertet. Zahlen bleiben NaN (das
# Template prueft sie mit x == x bzw. fmt_*).
_TEXT_COLUMNS = ("symbol", "name", "index", "sector", "industry", "currency", "financial_currency")


def _template_rows(frame: pd.DataFrame) -> list[dict[Hashable, Any]]:
    """Zeilen fuers Template: fehlende Texte als None.

    Seit pandas 3 sind fehlende Werte in Textspalten NaN (truthy) statt None - im
    Template stuende sonst "nan" statt "-".
    """
    rows = frame.to_dict(orient="records")
    for row in rows:
        for col in _TEXT_COLUMNS:
            value = row.get(col)
            if value is not None and not isinstance(value, str) and pd.isna(value):
                row[col] = None
    return rows


def _numbers(frame: pd.DataFrame, column: str) -> pd.Series:
    """Spalte als Zahlen; fehlt sie, NaN."""
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").astype(float)


def _financial_rows(
    scored: pd.DataFrame, cost_of_capital: float, terminal_growth: float
) -> list[dict[Hashable, Any]]:
    """Titel unter der Branchenregel (F2.4) fuer den Abschnitt "Finanzwerte", nach Symbol.

    ROE = KBV / KGV (Gewinn je Buchwert), nur mit positivem KBV und KGV. Gerechtfertigtes KBV
    nach ADR-0011, Punkt 3: (ROE - g) / (r - g).
    """
    if "industry_rule" not in scored.columns:
        return []
    rows = scored[scored["industry_rule"].fillna(value=False).astype(bool)].copy()
    if rows.empty:
        return []
    pb, pe = _numbers(rows, "pb_ratio"), _numbers(rows, "pe_ratio")
    roe = (pb / pe).where((pb > 0) & (pe > 0), np.nan)
    rows["roe"] = roe
    rows["justified_pb"] = (roe - terminal_growth) / (cost_of_capital - terminal_growth)
    return _template_rows(rows.sort_values("symbol", kind="stable"))


def _fmt_num(v: Any) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{v:,.2f}".replace(",", ".")


def _fmt_pct(v: Any) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"{v * 100:.1f} %"


@dataclass
class ReportArtifacts:
    html: str
    csv_bytes: bytes
    csv_filename: str
    subject: str
    top_count: int
    bottom_count: int
    scored: int
    failed: int
    universe_size: int


def _build_subject(
    *,
    scored: int,
    universe_size: int,
    top_name: str,
    timestamp: datetime,
) -> str:
    tag = "ok" if scored == universe_size else "partial"
    return (
        f"[{tag} {scored}/{universe_size}] "
        f"DAX/MDAX Value-Screening {timestamp.strftime('%Y-%m-%d')} "
        f"- Top: {top_name}"
    )


def build_report(
    scored: pd.DataFrame,
    top_n: int = 20,
    bottom_n: int = 10,
    value_weight: float = 0.6,
    quality_weight: float = 0.4,
    version: str = "dev",  # im Betrieb die App-Version aus NotificationConfig
    profile: str | None = None,  # z. B. "Standard v1" (P2b.3), fehlt ohne Profil
    universe_size: int | None = None,
    universe_source: str | None = None,
    universe_as_of: date | None = None,
    universe_added: Sequence[str] = (),
    universe_removed: Sequence[str] = (),
    now: datetime | None = None,
    # Gerechtfertigtes KBV im Abschnitt "Finanzwerte" (F2.4): aus den Parametern des Laufs,
    # ohne sie die Standardwerte des Contracts
    cost_of_capital: float | None = None,
    terminal_growth: float | None = None,
) -> ReportArtifacts:
    # Injizierbar, damit Tests (Golden-Master) deterministisch sind. Lokale Zeit:
    # Dockerfile und Compose setzen TZ=Europe/Berlin.
    if now is None:
        now = datetime.now()

    valid = scored[scored["composite_score"].notna()].copy()
    top_rows = _template_rows(valid.head(top_n))
    bottom_rows = _template_rows(valid.tail(bottom_n).iloc[::-1])

    defaults = ProfileParamsV1()
    rate = cost_of_capital if cost_of_capital is not None else defaults.cost_of_capital
    growth = terminal_growth if terminal_growth is not None else defaults.terminal_growth
    financial_rows = _financial_rows(scored, rate, growth)

    scored_count = int(valid.shape[0])
    universe = universe_size if universe_size is not None else len(scored)
    failed = max(0, universe - scored_count)

    html = render_html(
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        top_n=top_n,
        bottom_n=bottom_n,
        top_rows=top_rows,
        bottom_rows=bottom_rows,
        financial_rows=financial_rows,
        financial_params={"r": rate, "g": growth},
        weights={"value": value_weight, "quality": quality_weight},
        version=version,
        profile=profile,
        universe_source=universe_source,
        universe_as_of=universe_as_of.isoformat() if universe_as_of else None,
        is_fallback=universe_source == FALLBACK_SOURCE,
        universe_added=list(universe_added),
        universe_removed=list(universe_removed),
        fmt_num=_fmt_num,
        fmt_pct=_fmt_pct,
        stats={
            "universe_size": universe,
            "scored": scored_count,
            "failed": failed,
        },
    )

    csv_filename = f"value_ranking_{now.strftime('%Y%m%d')}.csv"
    cols_order = [
        "rank_overall",
        "symbol",
        "name",
        "index",
        "sector",
        "industry",
        "composite_score",
        "value_score",
        "quality_score",
        "value_trap_flag",
        "market_cap",
        "price",
        "currency",
        "financial_currency",
        "ev_ebit",
        "pe_ratio",
        "pb_ratio",
        "p_fcf",
        "dividend_yield",
        "buyback_yield",
        "shareholder_yield",
        "roic",
        "roa",
        "fcf_margin",
        "gross_margin",
        "operating_margin",
        "net_debt_ebitda",
        "debt_to_equity",
        "earnings_stability",
        "revenue_growth_5y",
        "eps_growth_5y",
        "errors",
    ]
    export = scored.reindex(columns=[c for c in cols_order if c in scored.columns])
    # utf-8-sig (BOM), damit Excel Umlaute korrekt erkennt. LF fest, sonst haengt das
    # Zeilenende vom Betriebssystem ab (pandas nimmt os.linesep).
    csv_bytes = export.to_csv(index=False, sep=";", decimal=",", lineterminator="\n").encode(
        "utf-8-sig"
    )

    top_name = top_rows[0]["name"] if top_rows else "?"
    subject = _build_subject(
        scored=scored_count,
        universe_size=universe,
        top_name=top_name,
        timestamp=now,
    )

    log.info("Report erstellt: HTML %d Zeichen, CSV %s", len(html), csv_filename)
    return ReportArtifacts(
        html=html,
        csv_bytes=csv_bytes,
        csv_filename=csv_filename,
        subject=subject,
        top_count=len(top_rows),
        bottom_count=len(bottom_rows),
        scored=scored_count,
        failed=failed,
        universe_size=universe,
    )
