"""Kommandozeile der Replay-Regression.

    python -m src.regression [--scoring-run N ...] [--fetch-run N ...] [--export DIR]

Ohne Auswahl werden alle Bewertungslaeufe ausser Rescores nachgespielt. Exit 0: alles
gleich, 1: Abweichungen, 2: nichts zu vergleichen oder Fehler (z. B. Datenbank nicht
erreichbar).
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from va_platform.db import create_db_engine

from ..composition import scoring_config
from ..config import Settings
from .case import ReplayCase, Skipped, load_cases
from .replay import check

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .compare import Difference
    from .replay import CaseOutcome

EXIT_EQUAL = 0
EXIT_DIFFERENT = 1
EXIT_ERROR = 2

AREAS = {"scores": "Scores", "factors": "Faktor-Raenge", "csv": "CSV"}
MAX_LISTED = 20  # je Bereich, der Rest wird nur gezaehlt


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = settings or Settings()  # type: ignore[call-arg]
    engine = create_db_engine(settings.database_url.get_secret_value(), read_only=True)
    try:
        cases = load_cases(engine, scoring_run_ids=args.scoring_run, fetch_run_ids=args.fetch_run)
    except SQLAlchemyError as e:
        print(f"Datenbank nicht lesbar: {getattr(e, 'orig', None) or e}")
        return EXIT_ERROR
    finally:
        engine.dispose()

    config = scoring_config(settings)
    outcomes: list[CaseOutcome] = []
    failed = 0
    for case in cases:
        if isinstance(case, Skipped):
            print(f"Bewertungslauf #{case.scoring_run_id}: uebersprungen ({case.reason})")
            continue
        if args.export is not None:
            _export(case, args.export)
        try:
            outcome = check(case, config)
        except Exception as e:  # ein kaputter Lauf stoppt die anderen nicht
            print(f"{_title(case)}: Replay gescheitert ({type(e).__name__}: {e})")
            failed += 1
            continue
        outcomes.append(outcome)
        print(format_outcome(outcome))

    if not outcomes and not failed:
        print("Ergebnis: nichts zu vergleichen")
        return EXIT_ERROR
    equal = sum(o.equal for o in outcomes)
    print(f"Ergebnis: {equal} von {len(outcomes) + failed} Bewertungslaeufen gleich")
    if failed:
        return EXIT_ERROR
    return EXIT_EQUAL if equal == len(outcomes) else EXIT_DIFFERENT


def format_outcome(outcome: CaseOutcome) -> str:
    areas = ", ".join(AREAS[a] for a in outcome.checked)
    count = len(outcome.differences)
    verdict = "gleich" if outcome.equal else f"{count} Abweichung{'en' if count != 1 else ''}"
    lines = [f"{_title(outcome.case)}: {verdict} ({areas})"]
    if outcome.config_changes:
        changed = ", ".join(outcome.config_changes)
        lines.append(f"  Konfiguration weicht vom gespeicherten Lauf ab: {changed}")
    if outcome.failure is not None:
        lines.append(f"  Replay endete mit screening.run.failed: {outcome.failure}")
    by_area: dict[str, list[Difference]] = defaultdict(list)
    for difference in outcome.differences:
        by_area[difference.area].append(difference)
    for area, found in by_area.items():
        lines.append(f"  {AREAS[area]}:")
        lines += [f"    {d}" for d in found[:MAX_LISTED]]
        if len(found) > MAX_LISTED:
            lines.append(f"    ... und {len(found) - MAX_LISTED} weitere")
    return "\n".join(lines)


def _title(case: ReplayCase) -> str:
    return (
        f"Bewertungslauf #{case.scoring_run_id} (Abruf #{case.fetch_run_id} vom "
        f"{case.fetched_on:%d.%m.%Y}, {case.origin})"
    )


def _export(case: ReplayCase, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / case.file_name
    path.write_text(case.to_json(), encoding="utf-8", newline="\n")
    print(f"Exportiert: {path}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.regression",
        description=(
            "Gespeicherte Bewertungslaeufe mit dem aktuellen Code nachspielen und vergleichen. "
            "Schreibt nichts in die Datenbank."
        ),
    )
    parser.add_argument(
        "--scoring-run", type=int, action="append", default=[], metavar="N",
        help="Bewertungslauf scoring.scoring_run.id (mehrfach moeglich)",
    )  # fmt: skip
    parser.add_argument(
        "--fetch-run", type=int, action="append", default=[], metavar="N",
        help="alle Bewertungslaeufe dieses Abrufs ausser Rescores (mehrfach moeglich)",
    )  # fmt: skip
    parser.add_argument(
        "--export", type=Path, default=None, metavar="DIR",
        help="je Lauf eine Fixture-Datei fuer tests/fixtures/replay/ schreiben",
    )  # fmt: skip
    return parser
