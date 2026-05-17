"""Report-Generierung: HTML-Mail-Body + CSV-Anhang.

Subject-Tag traegt eine Erfolgsstatistik (``ok 102/110`` oder
``partial 60/110``), damit der Posteingang als Health-Check dient.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Template

log = logging.getLogger(__name__)


HTML_TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Value-Screening DAX/MDAX</title>
<style>
  body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         color: #222; max-width: 980px; margin: 0 auto; padding: 16px; }
  h1 { color: #1a4d8c; border-bottom: 2px solid #1a4d8c; padding-bottom: 6px; }
  h2 { color: #1a4d8c; margin-top: 28px; }
  table { border-collapse: collapse; width: 100%; margin-top: 10px; font-size: 13px; }
  th, td { border: 1px solid #ccd6e0; padding: 6px 8px; text-align: right; }
  th { background: #eef3f9; text-align: center; }
  td.text { text-align: left; }
  tr:nth-child(even) { background: #fafcff; }
  .meta { color: #666; font-size: 12px; margin-bottom: 16px; }
  .flag { background: #fff3cd; color: #7a5d00; padding: 2px 6px; border-radius: 3px; font-size: 11px; }
  .footer { color: #888; font-size: 11px; margin-top: 32px; border-top: 1px solid #eee; padding-top: 10px; }
  .ok { color: #1f7a3a; }
  .warn { color: #b07000; }
</style>
</head>
<body>
<h1>Value-Screening DAX &amp; MDAX</h1>
<div class="meta">
  Stand: {{ generated_at }} &middot;
  Universum: {{ stats.universe_size }} Werte gescannt,
  <span class="{{ 'ok' if stats.failed == 0 else 'warn' }}">{{ stats.scored }} bewertet</span>,
  {{ stats.failed }} fehlgeschlagen &middot;
  Datenquelle: yfinance
</div>

<h2>Top {{ top_n }} Value-Kandidaten</h2>
<p>Sortiert nach Composite Score (Gewichtung: {{ "%.0f" | format(weights.value*100) }} %% Value, {{ "%.0f" | format(weights.quality*100) }} %% Quality).</p>
<table>
  <thead>
    <tr>
      <th>#</th><th class="text">Unternehmen</th><th>Index</th><th class="text">Sektor</th>
      <th>Score</th><th>Value</th><th>Quality</th>
      <th>EV/EBIT</th><th>P/B</th><th>P/FCF</th><th>Div.-Yld</th>
      <th>ROIC</th><th>FCF-Marge</th><th>NetDebt/EBITDA</th>
    </tr>
  </thead>
  <tbody>
  {% for r in top_rows %}
    <tr>
      <td>{{ r.rank_overall }}</td>
      <td class="text"><b>{{ r.name }}</b><br><span style="color:#888;font-size:11px">{{ r.symbol }}</span>
        {% if r.value_trap_flag %} <span class="flag">Value-Trap?</span>{% endif %}
      </td>
      <td>{{ r.index }}</td>
      <td class="text">{{ r.sector or "-" }}</td>
      <td><b>{{ "%.2f" | format(r.composite_score) }}</b></td>
      <td>{{ "%.2f" | format(r.value_score) if r.value_score == r.value_score else "-" }}</td>
      <td>{{ "%.2f" | format(r.quality_score) if r.quality_score == r.quality_score else "-" }}</td>
      <td>{{ fmt_num(r.ev_ebit) }}</td>
      <td>{{ fmt_num(r.pb_ratio) }}</td>
      <td>{{ fmt_num(r.p_fcf) }}</td>
      <td>{{ fmt_pct(r.dividend_yield) }}</td>
      <td>{{ fmt_pct(r.roic) }}</td>
      <td>{{ fmt_pct(r.fcf_margin) }}</td>
      <td>{{ fmt_num(r.net_debt_ebitda) }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<h2>Watchlist: Bottom {{ bottom_n }}</h2>
<p>Schwaechste Composite-Werte - dienen als Kontrast und ggf. als Short-/Avoid-Ideen.</p>
<table>
  <thead>
    <tr>
      <th>#</th><th class="text">Unternehmen</th><th>Index</th><th class="text">Sektor</th>
      <th>Score</th><th>Value</th><th>Quality</th>
      <th>EV/EBIT</th><th>P/B</th><th>Verschuldung D/E</th>
    </tr>
  </thead>
  <tbody>
  {% for r in bottom_rows %}
    <tr>
      <td>{{ r.rank_overall }}</td>
      <td class="text"><b>{{ r.name }}</b><br><span style="color:#888;font-size:11px">{{ r.symbol }}</span></td>
      <td>{{ r.index }}</td>
      <td class="text">{{ r.sector or "-" }}</td>
      <td>{{ "%.2f" | format(r.composite_score) if r.composite_score == r.composite_score else "-" }}</td>
      <td>{{ "%.2f" | format(r.value_score) if r.value_score == r.value_score else "-" }}</td>
      <td>{{ "%.2f" | format(r.quality_score) if r.quality_score == r.quality_score else "-" }}</td>
      <td>{{ fmt_num(r.ev_ebit) }}</td>
      <td>{{ fmt_num(r.pb_ratio) }}</td>
      <td>{{ fmt_num(r.debt_to_equity) }}</td>
    </tr>
  {% endfor %}
  </tbody>
</table>

<h2>Methodik (kurz)</h2>
<p style="font-size:13px">
Composite Value Score: Perzentilrang ueber EV/EBIT, P/B, P/FCF und Shareholder Yield (Cross-Sektional auf das gefilterte Universum). Niedrige Bewertungs-Multiples und hohe Yields ergeben hohe Ranks.
<br>Quality Score: Perzentilrang ueber ROIC, FCF-Marge, operative Marge, Net Debt / EBITDA (invertiert) und Earnings-Stabilitaet.
<br>Composite = {{ "%.0f" | format(weights.value*100) }} %% Value + {{ "%.0f" | format(weights.quality*100) }} %% Quality. Negative Bewertungs-Multiples (Verluste) werden aus dem Value-Ranking ausgeschlossen, nicht mit 0 bestraft.
<br>"Value-Trap"-Flag: oberes Value-Quartil + unteres Quality-Quartil.
</p>

<div class="footer">
  Automatisch generiert durch value-analyzer v{{ version }} &middot;
  Daten via yfinance &middot; CSV-Vollranking liegt als Anhang bei.
  <br>Keine Anlageempfehlung. Eigene Pruefung erforderlich.
</div>
</body>
</html>
""")


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
    csv_path: Path
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
    output_dir: Path,
    top_n: int = 20,
    bottom_n: int = 10,
    value_weight: float = 0.6,
    quality_weight: float = 0.4,
    version: str = "0.2.0",
    universe_size: int | None = None,
) -> ReportArtifacts:
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()

    valid = scored[scored["composite_score"].notna()].copy()
    top_rows = valid.head(top_n).to_dict(orient="records")
    bottom_rows = valid.tail(bottom_n).iloc[::-1].to_dict(orient="records")

    scored_count = int(valid.shape[0])
    universe = universe_size if universe_size is not None else len(scored)
    failed = max(0, universe - scored_count)

    html = HTML_TEMPLATE.render(
        generated_at=now.strftime("%Y-%m-%d %H:%M"),
        top_n=top_n,
        bottom_n=bottom_n,
        top_rows=top_rows,
        bottom_rows=bottom_rows,
        weights={"value": value_weight, "quality": quality_weight},
        version=version,
        fmt_num=_fmt_num,
        fmt_pct=_fmt_pct,
        stats={
            "universe_size": universe,
            "scored": scored_count,
            "failed": failed,
        },
    )

    csv_path = output_dir / f"value_ranking_{now.strftime('%Y%m%d')}.csv"
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
    export.to_csv(csv_path, index=False, sep=";", decimal=",", encoding="utf-8-sig")

    top_name = top_rows[0]["name"] if top_rows else "?"
    subject = _build_subject(
        scored=scored_count,
        universe_size=universe,
        top_name=top_name,
        timestamp=now,
    )

    log.info("Report erstellt: HTML %d Zeichen, CSV %s", len(html), csv_path.name)
    return ReportArtifacts(
        html=html,
        csv_path=csv_path,
        subject=subject,
        top_count=len(top_rows),
        bottom_count=len(bottom_rows),
        scored=scored_count,
        failed=failed,
        universe_size=universe,
    )
