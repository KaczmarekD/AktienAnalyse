"""Ein gespeicherter Bewertungslauf als Testfall: die Snapshots seines Abrufs und sein Ergebnis.

Aus der Datenbank (nur lesend) oder aus einer Fixture-Datei (JSON). Beide Wege ergeben
dieselben Spalten wie die Repositories, damit Replay und Vergleich nicht wissen, woher der
Fall kommt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import pandas as pd

from va_market_data.adapters.postgres import MarketDataRepository
from va_notification.adapters.postgres import ReportingRepository
from va_platform.db import session_scope
from va_platform.serialization import json_safe, to_python
from va_scoring.adapters.postgres import ScoringRepository

if TYPE_CHECKING:
    from collections.abc import Collection

    from sqlalchemy import Engine

    from va_scoring.adapters.postgres.models import ScoringRun

    from .replay import ReplayResult

SCORE_COLUMNS = (
    "symbol",
    "passed_filter",
    "value_score",
    "quality_score",
    "composite_score",
    "value_trap_flag",
    "rank_overall",
)
FACTOR_COLUMNS = (
    "symbol",
    "factor_key",
    "category",
    "source_column",
    "direction",
    "raw_value",
    "percentile_rank",
)
# Ohne Auswahl: alle Laeufe ausser Rescores (die bewerten absichtlich anders)
DEFAULT_ORIGINS = ("live", "import")
FORMAT = 1


@dataclass(frozen=True)
class ReplayCase:
    scoring_run_id: int
    fetch_run_id: int
    origin: str  # live / import / rescore
    fetched_on: date  # Tag des Abrufs (lokale Zeit)
    universe_source: str | None
    universe_as_of: date | None
    universe_size: int  # Titel des Bewertungslaufs, vor dem Groessenfilter
    config: dict[str, Any] | None  # gespeicherte Konfiguration (Import: keine)
    generated_at: datetime | None  # Zeitpunkt des gespeicherten Reports
    snapshots: pd.DataFrame  # Spalten wie MarketDataRepository.get_snapshots_df
    scores: pd.DataFrame  # erwartet, SCORE_COLUMNS
    factor_scores: pd.DataFrame  # erwartet, FACTOR_COLUMNS; leer, wenn nicht gespeichert
    csv: bytes | None  # CSV des gespeicherten Reports

    @property
    def file_name(self) -> str:
        return f"{self.fetched_on.isoformat()}_scoring-run-{self.scoring_run_id}.json"

    def with_expected(self, result: ReplayResult) -> ReplayCase:
        """Dieselben Snapshots, die Ergebnisse aus einem Replay (``--update-golden``)."""
        return replace(
            self, scores=result.scores, factor_scores=result.factor_scores, csv=result.csv
        )

    def to_json(self) -> str:
        """Tabellen mit einer Kopfzeile ``columns`` und einer Zeile je Datensatz, die CSV mit
        einer Zeile je CSV-Zeile: kompakt, und ein Review sieht genau, was sich aendert."""
        head = {
            "format": FORMAT,
            "scoring_run_id": self.scoring_run_id,
            "fetch_run_id": self.fetch_run_id,
            "origin": self.origin,
            "fetched_on": self.fetched_on,
            "universe": {
                "source": self.universe_source,
                "as_of": self.universe_as_of,
                "size": self.universe_size,
            },
            "config": self.config,
            "generated_at": self.generated_at,
        }
        # Feste Reihenfolge, damit ein neu geschriebener Fall nur echte Aenderungen zeigt
        # (Postgres sortiert z. B. "p_fcf" und "pb" anders als Python)
        tables = {
            "snapshots": _table(self.snapshots, ["symbol"]),
            "scores": _table(self.scores, ["rank_overall", "symbol"]),
            "factor_scores": _table(self.factor_scores, ["symbol", "factor_key"]),
        }
        parts = [f" {_dump(key)}: {_dump(value)}" for key, value in head.items()]
        for key, (columns, rows) in tables.items():
            parts.append(
                f' {_dump(key)}: {{\n  "columns": {_dump(columns)},\n  "rows": {_lines(rows)}\n }}'
            )
        csv = None if self.csv is None else self.csv.decode("utf-8-sig").splitlines()
        parts.append(f' "csv": {_dump(None) if csv is None else _lines(csv)}')
        return "{\n" + ",\n".join(parts) + "\n}\n"

    @classmethod
    def from_json(cls, text: str) -> ReplayCase:
        data = json.loads(text)
        if data.get("format") != FORMAT:
            msg = f"unbekanntes Fixture-Format {data.get('format')!r}, erwartet {FORMAT}"
            raise ValueError(msg)
        universe = data["universe"]
        return cls(
            scoring_run_id=int(data["scoring_run_id"]),
            fetch_run_id=int(data["fetch_run_id"]),
            origin=str(data["origin"]),
            fetched_on=date.fromisoformat(data["fetched_on"]),
            universe_source=universe["source"],
            universe_as_of=_date(universe["as_of"]),
            universe_size=int(universe["size"]),
            config=data["config"],
            generated_at=_datetime(data["generated_at"]),
            snapshots=_frame(data["snapshots"]),
            scores=_frame(data["scores"]).reindex(columns=list(SCORE_COLUMNS)),
            factor_scores=_frame(data["factor_scores"]).reindex(columns=list(FACTOR_COLUMNS)),
            csv=None if data["csv"] is None else _csv_bytes(data["csv"]),
        )


@dataclass(frozen=True)
class Skipped:
    """Ein Bewertungslauf, der sich nicht nachspielen laesst, mit Grund."""

    scoring_run_id: int
    reason: str


def load_cases(
    engine: Engine,
    *,
    scoring_run_ids: Collection[int] = (),
    fetch_run_ids: Collection[int] = (),
) -> list[ReplayCase | Skipped]:
    """Die gewaehlten Bewertungslaeufe, ohne Auswahl alle ausser Rescores.

    Ein ausdruecklich genannter Bewertungslauf zaehlt auch, wenn er ein Rescore ist.
    """
    with session_scope(engine) as s:
        scoring = ScoringRepository(s)
        runs: dict[int, ScoringRun] = {}
        if fetch_run_ids or not scoring_run_ids:
            found = scoring.get_scoring_runs(fetch_run_ids=fetch_run_ids, origins=DEFAULT_ORIGINS)
            runs |= {r.id: r for r in found}
        if scoring_run_ids:
            runs |= {r.id: r for r in scoring.get_scoring_runs(scoring_run_ids=scoring_run_ids)}
        market, reporting = MarketDataRepository(s), ReportingRepository(s)
        return [_load(runs[i], scoring, market, reporting) for i in sorted(runs)]


def _load(
    run: ScoringRun,
    scoring: ScoringRepository,
    market: MarketDataRepository,
    reporting: ReportingRepository,
) -> ReplayCase | Skipped:
    if run.fetch_run_id is None:
        return Skipped(run.id, "ohne Abruf")
    fetch_run = market.get_fetch_run(run.fetch_run_id)
    if fetch_run is None:
        return Skipped(run.id, f"Abruf #{run.fetch_run_id} fehlt")
    scores = scoring.get_scores_df(run.id)
    if scores.empty:
        return Skipped(run.id, "ohne Ergebnisse")
    # Nur die Titel dieses Laufs: z. B. DAX_ONLY auf einem Vollabruf, beim Import fehlen
    # die gefilterten Titel
    symbols = [str(s) for s in scores["symbol"]]
    snapshots = market.get_snapshots_df(run.fetch_run_id, symbols)
    missing = sorted(set(symbols) - {str(s) for s in snapshots["symbol"]})
    if missing:
        return Skipped(run.id, f"Snapshots fehlen fuer {', '.join(missing)}")
    report = reporting.get_report_for_scoring_run(run.id)
    return ReplayCase(
        scoring_run_id=run.id,
        fetch_run_id=run.fetch_run_id,
        origin=run.origin,
        fetched_on=fetch_run.started_at.astimezone().date(),
        universe_source=fetch_run.universe_source,
        universe_as_of=fetch_run.universe_as_of,
        universe_size=len(scores),
        config=run.config,
        generated_at=None if report is None else report.generated_at,
        snapshots=snapshots,
        scores=scores.reindex(columns=list(SCORE_COLUMNS)),
        factor_scores=scoring.get_factor_scores_df(run.id).reindex(columns=list(FACTOR_COLUMNS)),
        csv=None if report is None else bytes(report.csv_bytes),
    )


def _table(frame: pd.DataFrame, order: list[str]) -> tuple[list[str], list[list[Any]]]:
    """Spaltennamen und Zeilen, sortiert nach ``order``."""
    columns = [str(c) for c in frame.columns]
    ordered = frame.sort_values(order, na_position="last", kind="stable") if len(frame) else frame
    rows = []
    for record in ordered.itertuples(index=False, name=None):
        row = [to_python(v) for v in record]
        if "rank_overall" in columns:
            i = columns.index("rank_overall")
            if isinstance(row[i], float):  # NaN in der Spalte macht aus Raengen Gleitkommazahlen
                row[i] = int(row[i])
        rows.append(row)
    return columns, rows


def _frame(table: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(table["rows"], columns=table["columns"])


def _dump(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False)


def _lines(items: list[Any]) -> str:
    """JSON-Liste mit einem Eintrag je Zeile."""
    if not items:
        return "[]"
    return "[\n" + ",\n".join(f"   {_dump(item)}" for item in items) + "\n  ]"


def _csv_bytes(lines: list[str]) -> bytes:
    # Wie build_report: BOM, LF, Zeilenende auch nach der letzten Zeile
    return ("\n".join(lines) + "\n").encode("utf-8-sig")


def _date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _datetime(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)
