"""Einmal-Import der Altdateien aus der Zeit vor der Datenbank.

    python -m src.db.import_legacy /app/data

Liest ``fundamentals_YYYY-MM-DD.parquet`` (Kennzahlen aller Titel) und
``value_ranking_YYYYMMDD.csv`` (Scores der gefilterten Titel, auch aus Mails
gespeicherte Anhaenge). Je Datum entsteht ein Lauf vom Typ ``import``.

Mehrfach ausfuehrbar: jede Datei wird ueber ihren SHA-256 genau einmal
importiert. Die Dateien selbst bleiben unangetastet.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from ..config import DatabaseSettings
from ..fundamentals import ERRORS_SEPARATOR
from .engine import create_db_engine, session_scope
from .recorder import snapshot_row
from .repositories.market_data import MarketDataRepository
from .repositories.runs import RunRepository
from .repositories.scoring import ScoreRow, ScoringRepository
from .serialization import to_python

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

PATTERNS: dict[str, tuple[re.Pattern[str], str]] = {
    "fundamentals_parquet": (
        re.compile(r"^fundamentals_(\d{4}-\d{2}-\d{2})\.parquet$"),
        "%Y-%m-%d",
    ),
    "ranking_csv": (re.compile(r"^value_ranking_(\d{8})\.csv$"), "%Y%m%d"),
}
LEGACY_VERSION = "legacy"
# Ab hier enthalten Altdateien die Fixes 9265460 (Dividendenrendite) und 8e55e7f (FX)
FIXES_EFFECTIVE = date(2026, 9, 30)
SCORE_COLUMNS = {
    "rank_overall",
    "composite_score",
    "value_score",
    "quality_score",
    "value_trap_flag",
}


@dataclass
class ImportSummary:
    imported: int = 0
    skipped: int = 0
    files: list[str] = field(default_factory=list)


@dataclass
class _DayFiles:
    parquet: Path | None = None
    csv: Path | None = None


def _note(day: date, files: list[str]) -> str:
    note = f"Import aus Altdateien ({', '.join(files)}); Rohdaten und Einzelraenge fehlen."
    if day < FIXES_EFFECTIVE:
        note += (
            " Vor den Fixes 9265460 (Dividendenrendite < 1 % x100) und 8e55e7f "
            "(Multiples bei abweichender Berichtswaehrung) koennen dividend_yield, "
            "shareholder_yield, Bewertungs-Multiples und Scores verzerrt sein."
        )
    return note


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scan(directory: Path) -> dict[date, _DayFiles]:
    days: dict[date, _DayFiles] = defaultdict(_DayFiles)
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        for kind, (pattern, fmt) in PATTERNS.items():
            match = pattern.match(path.name)
            if not match:
                continue
            try:
                day = datetime.strptime(match.group(1), fmt).date()
            except ValueError:
                continue
            if kind == "fundamentals_parquet":
                days[day].parquet = path
            else:
                days[day].csv = path
    return dict(days)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", decimal=",", encoding="utf-8-sig")


def _snapshot_values(row: Mapping[Any, Any]) -> dict[str, Any]:
    errors = to_python(row.get("errors"))
    return snapshot_row(
        row, str(errors).split(ERRORS_SEPARATOR) if errors else [], drop_unknown=True
    )


def _write_snapshots(repo: MarketDataRepository, fetch_run_id: int, df: pd.DataFrame) -> None:
    ids = repo.get_or_create_instruments(str(s) for s in df["symbol"])
    for row in df.to_dict("records"):
        repo.write_snapshot(fetch_run_id, ids[str(row["symbol"])], _snapshot_values(row))


def _import_day(
    session: Session,
    day: date,
    parquet: Path | None,
    csv: Path | None,
    known_parquet_run: int | None,
) -> None:
    runs = RunRepository(session)
    market = MarketDataRepository(session)
    started_at = datetime.combine(day, time.min).astimezone()
    names = [p.name for p in (parquet, csv) if p is not None]
    note = _note(day, names)

    run_id = runs.write_run_start(
        kind="import",
        app_version=LEGACY_VERSION,
        dry_run=False,
        force_refresh=False,
        universe_mode=None,
        settings=None,
        started_at=started_at,
    )
    fundamentals = pd.read_parquet(parquet) if parquet else None
    ranking = _read_csv(csv) if csv else None

    fetch_run_id: int | None = None
    if known_parquet_run is not None:
        fetch_run_id = runs.get_run(known_parquet_run).fetch_run_id  # type: ignore[union-attr]
    source = fundamentals if fundamentals is not None else ranking
    if fetch_run_id is None and source is not None:
        snapshot_df = source.drop(columns=[c for c in SCORE_COLUMNS if c in source.columns])
        fetch_run_id = market.write_fetch_run_start(
            provider="yfinance",
            provider_version=None,
            universe_source=None,
            universe_size=len(snapshot_df),
            origin="import",
            started_at=started_at,
            note=note,
        )
        _write_snapshots(market, fetch_run_id, snapshot_df)
        ok = int(snapshot_df["market_cap"].notna().sum()) if "market_cap" in snapshot_df else 0
        market.write_fetch_run_finish(
            fetch_run_id,
            ok_count=ok,
            success_share=ok / max(len(snapshot_df), 1),
            finished_at=started_at,
        )

    scoring_run_id: int | None = None
    if ranking is not None:
        scoring = ScoringRepository(session)
        scoring_run_id = scoring.write_scoring_run(
            fetch_run_id=fetch_run_id,
            config=None,
            app_version=LEGACY_VERSION,
            origin="import",
            note=note,
            created_at=started_at,
        )
        ids = market.get_or_create_instruments(str(s) for s in ranking["symbol"])
        scoring.write_score_results(
            scoring_run_id,
            [
                ScoreRow(
                    instrument_id=ids[str(r["symbol"])],
                    passed_filter=True,
                    value_score=to_python(r.get("value_score")),
                    quality_score=to_python(r.get("quality_score")),
                    composite_score=to_python(r.get("composite_score")),
                    value_trap_flag=_bool(r.get("value_trap_flag")),
                    rank_overall=_int(r.get("rank_overall")),
                )
                for r in ranking.to_dict("records")
            ],
        )

    # Universumsgroesse immer vom Abruf - eine Ranking-CSV enthaelt nur gefilterte Titel
    fetch_run = market.get_fetch_run(fetch_run_id) if fetch_run_id is not None else None
    universe = fetch_run.universe_size if fetch_run is not None else None
    scored = int(ranking["composite_score"].notna().sum()) if ranking is not None else None
    runs.write_run_finish(
        run_id,
        status="success",
        exit_code=0,
        fetch_run_id=fetch_run_id,
        scoring_run_id=scoring_run_id,
        universe_size=universe,
        scored_count=scored,
        finished_at=started_at,
    )
    for path, kind in ((parquet, "fundamentals_parquet"), (csv, "ranking_csv")):
        if path is not None:
            runs.write_import_file(
                file_name=path.name, sha256=_sha256(path), kind=kind, run_id=run_id
            )


def _bool(value: Any) -> bool | None:
    value = to_python(value)
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "wahr"}
    return bool(value)


def _int(value: Any) -> int | None:
    value = to_python(value)
    return None if value is None else int(value)


def import_directory(directory: Path, database_url: str) -> ImportSummary:
    summary = ImportSummary()
    engine = create_db_engine(database_url)
    try:
        for day, files in sorted(_scan(directory).items()):
            new: dict[str, Path | None] = {"parquet": None, "csv": None}
            known_parquet_run: int | None = None
            with session_scope(engine) as s:
                runs = RunRepository(s)
                for slot, path in (("parquet", files.parquet), ("csv", files.csv)):
                    if path is None:
                        continue
                    known = runs.get_import_file(_sha256(path))
                    if known is None:
                        new[slot] = path
                        continue
                    summary.skipped += 1
                    if slot == "parquet":
                        known_parquet_run = known.run_id
            if new["parquet"] is None and new["csv"] is None:
                continue
            with session_scope(engine) as s:
                _import_day(s, day, new["parquet"], new["csv"], known_parquet_run)
            for path in (new["parquet"], new["csv"]):
                if path is not None:
                    summary.imported += 1
                    summary.files.append(path.name)
                    log.info("Importiert: %s", path.name)
    finally:
        engine.dispose()
    return summary


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    parser = argparse.ArgumentParser(description="Altdateien (Parquet/CSV) in die DB importieren")
    parser.add_argument("directory", type=Path, help="Ordner mit fundamentals_*/value_ranking_*")
    args = parser.parse_args()
    settings = DatabaseSettings()
    if settings.database_url is None:
        log.error("DATABASE_URL fehlt")
        return 1
    summary = import_directory(args.directory, settings.database_url.get_secret_value())
    log.info(
        "Fertig: %d Dateien importiert, %d bereits vorhanden", summary.imported, summary.skipped
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
