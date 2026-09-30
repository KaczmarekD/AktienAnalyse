"""Orchestriert den Batch: Universum -> Daten -> Scoring -> Report -> Mail.

Jeder Schritt landet ueber den ``BatchRecorder`` in PostgreSQL - nichts wird
geloescht oder ueberschrieben. Ist die Datenbank nicht erreichbar, bricht der
Lauf ab (Exit 4): ohne Speicherung kein Report, ein manueller Nachlauf reicht.

Exit-Codes: 0 ok, 1 Fehler im Lauf, 2 Konfiguration, 3 keine bewertbaren
Daten, 4 Datenbank nicht erreichbar.
"""

from __future__ import annotations

import argparse
import html
import logging
import sys
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from . import __version__
from .config import Settings, load_settings
from .data_fetcher import FetcherConfig, fetch_all
from .db.engine import create_db_engine
from .db.log_handler import BufferingLogHandler
from .db.recorder import BatchRecorder
from .healthcheck import ping, ping_target
from .logging_setup import setup_logging
from .mailer import send_report
from .reporting import ReportArtifacts, build_report
from .scoring import ScoringConfig, score
from .universe import Ticker, load_universe

if TYPE_CHECKING:
    import pandas as pd

    from .fundamentals import Fundamentals

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2
EXIT_NO_DATA = 3
EXIT_DB_UNAVAILABLE = 4

# Nie in die Datenbank: Passwoerter, Verbindungs-URLs, Healthcheck-UUID
_SECRET_SETTINGS = {"smtp_password", "database_url", "database_owner_url", "healthcheck_url"}

log = logging.getLogger("main")


def _open_recorder(settings: Settings) -> BatchRecorder:
    return BatchRecorder(create_db_engine(settings.database_url.get_secret_value()))


def _settings_snapshot(settings: Settings) -> dict[str, Any]:
    return settings.model_dump(mode="json", exclude=_SECRET_SETTINGS)


@contextmanager
def _capture_logs() -> Iterator[BufferingLogHandler]:
    """Sammelt die Log-Zeilen des Laufs fuer ``batch.run_log``."""
    root = logging.getLogger()
    handler = BufferingLogHandler()
    previous_level = root.level
    if root.level > logging.INFO:
        root.setLevel(logging.INFO)
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


def _safely(what: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Protokoll-Schreibzugriffe, die den Lauf nicht mehr kippen duerfen."""
    try:
        fn(*args, **kwargs)
    except Exception:
        log.warning("%s konnte nicht gespeichert werden", what, exc_info=True)


def _run(settings: Settings, *, force_refresh: bool, dry_run: bool) -> int:
    with _capture_logs() as captured:
        log.info("=== value-analyzer v%s START ===", __version__)
        try:
            recorder = _open_recorder(settings)
            run_id = recorder.start_run(
                kind="batch",
                dry_run=dry_run,
                force_refresh=force_refresh,
                universe_mode=settings.universe,
                settings=_settings_snapshot(settings),
            )
        except Exception:
            log.exception("Datenbank nicht erreichbar - Lauf abgebrochen")
            ping(settings.healthcheck_url, success=False, message="database unreachable")
            if not dry_run:
                _try_send_error_mail(settings, traceback.format_exc())
            return EXIT_DB_UNAVAILABLE

        try:
            return _execute(
                settings, recorder, run_id, force_refresh=force_refresh, dry_run=dry_run
            )
        finally:
            _safely("Log-Zeilen", recorder.record_logs, run_id, captured.entries)


def _execute(
    settings: Settings, recorder: BatchRecorder, run_id: int, *, force_refresh: bool, dry_run: bool
) -> int:
    ids: dict[str, int | None] = {"fetch_run_id": None, "scoring_run_id": None, "report_id": None}
    universe_size: int | None = None
    try:
        universe = load_universe()
        tickers = universe.tickers
        if settings.universe == "DAX_ONLY":
            tickers = [t for t in tickers if t.index == "DAX"]
        universe_size = len(tickers)

        symbols = [t.symbol for t in tickers]
        fetch_run_id = (
            None if force_refresh else recorder.find_reusable_fetch(date.today(), symbols)
        )
        if fetch_run_id is not None:
            log.info("Nutze Abruf #%d von heute aus der Datenbank", fetch_run_id)
            df = recorder.load_snapshots(fetch_run_id, symbols)
        else:
            fetch_run_id = recorder.start_fetch(tickers, universe.source, universe.as_of)
            ids["fetch_run_id"] = fetch_run_id
            df = _fetch_and_store(settings, recorder, fetch_run_id, tickers)
        ids["fetch_run_id"] = fetch_run_id

        scoring_cfg = ScoringConfig(
            min_market_cap=settings.min_market_cap,
            value_weight=settings.value_weight,
            quality_weight=settings.quality_weight,
        )
        scored = score(df, scoring_cfg)
        ids["scoring_run_id"] = recorder.record_scoring(fetch_run_id, df, scored, scoring_cfg)

        if scored.empty or int(scored["composite_score"].notna().sum()) == 0:
            log.error("Keine bewertbaren Datenpunkte - Abbruch.")
            recorder.finish_run(
                run_id,
                status="no_data",
                exit_code=EXIT_NO_DATA,
                universe_size=universe_size,
                scored_count=0,
                failed_count=universe_size,
                **ids,
            )
            _ping(settings, recorder, run_id, success=False, message="no scoreable data")
            return EXIT_NO_DATA

        report = build_report(
            scored,
            top_n=settings.top_n,
            bottom_n=settings.bottom_n,
            value_weight=settings.value_weight,
            quality_weight=settings.quality_weight,
            version=__version__,
            universe_size=universe_size,
            universe_source=universe.source,
            universe_as_of=universe.as_of,
            universe_added=[_ticker_label(t) for t in universe.added],
            universe_removed=[_ticker_label(t) for t in universe.removed],
        )
        ids["report_id"] = recorder.record_report(run_id, ids["scoring_run_id"], report)
        counts = {
            "universe_size": report.universe_size,
            "scored_count": report.scored,
            "failed_count": report.failed,
        }
        status = "success" if report.failed == 0 else "partial"

        if dry_run:
            _write_preview(settings, report)
            recorder.finish_run(run_id, status=status, exit_code=EXIT_OK, **counts, **ids)
            return EXIT_OK

        _send_and_record(settings, recorder, run_id, ids["report_id"], report)
        log.info("=== Run erfolgreich (scored %d/%d) ===", report.scored, report.universe_size)
        # Die Mail ist raus: ein DB-Fehler beim Abschluss darf keinen Fehlalarm ausloesen
        _safely(
            "Laufabschluss",
            recorder.finish_run,
            run_id,
            status=status,
            exit_code=EXIT_OK,
            **counts,
            **ids,
        )
        _ping(
            settings,
            recorder,
            run_id,
            success=True,
            message=f"scored {report.scored}/{report.universe_size}",
        )
    except Exception as e:
        trace = traceback.format_exc()
        log.exception("Unerwarteter Fehler im Run")
        _safely(
            "Laufabschluss",
            recorder.finish_run,
            run_id,
            status="failed",
            exit_code=EXIT_FAILED,
            error=trace,
            universe_size=universe_size,
            **ids,
        )
        _ping(settings, recorder, run_id, success=False, message=str(e))
        if not dry_run:
            _try_send_error_mail(settings, trace, recorder=recorder, run_id=run_id)
        return EXIT_FAILED
    return EXIT_OK


def _fetch_and_store(
    settings: Settings, recorder: BatchRecorder, fetch_run_id: int, tickers: list[Ticker]
) -> pd.DataFrame:
    """Ruft alle Titel ab und speichert jeden sofort.

    Laesst sich ein Titel auch nach Retries nicht speichern, faellt nur er aus dem
    Lauf - Report und Datenbank bleiben deckungsgleich.
    """
    unsaved: set[str] = set()

    def store(fund: Fundamentals) -> None:
        try:
            recorder.record_fundamentals(fetch_run_id, fund)
        except Exception:
            log.exception("%s konnte nicht gespeichert werden - Titel entfaellt", fund.symbol)
            unsaved.add(fund.symbol)

    df = fetch_all(
        tickers,
        cfg=FetcherConfig(default_tax_rate=settings.default_tax_rate),
        on_result=store,
    )
    if unsaved and "symbol" in df.columns:
        df = df[~df["symbol"].isin(unsaved)].reset_index(drop=True)
    recorder.finish_fetch(fetch_run_id, df)
    return df


def _ticker_label(t: Ticker) -> str:
    return f"{t.name} ({t.symbol}, {t.index})"


def _write_preview(settings: Settings, report: ReportArtifacts) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    preview = settings.data_dir / "preview_latest.html"
    preview.write_text(report.html, encoding="utf-8")
    # Praefix: Der Altdaten-Import greift nur value_ranking_*.csv auf
    csv_path = settings.data_dir / f"preview_{report.csv_filename}"
    csv_path.write_bytes(report.csv_bytes)
    log.info("DRY-RUN: HTML-Preview -> %s", preview)
    log.info("DRY-RUN: CSV -> %s", csv_path)
    log.info("DRY-RUN: Subject waere -> %s", report.subject)


def _send_and_record(
    settings: Settings,
    recorder: BatchRecorder,
    run_id: int,
    report_id: int | None,
    report: ReportArtifacts,
) -> None:
    delivery = {
        "run_id": run_id,
        "report_id": report_id,
        "channel": "mail",
        "kind": "report",
        "recipient": str(settings.mail_to),
        "subject": report.subject,
    }
    try:
        send_report(
            settings,
            report.subject,
            report.html,
            attachment=(report.csv_filename, report.csv_bytes),
        )
    except Exception as e:
        _safely(
            "Versandprotokoll", recorder.record_delivery, **delivery, success=False, error=str(e)
        )
        raise
    _safely("Versandprotokoll", recorder.record_delivery, **delivery, success=True)


def _ping(
    settings: Settings, recorder: BatchRecorder, run_id: int, *, success: bool, message: str
) -> None:
    result = ping(settings.healthcheck_url, success=success, message=message)
    if result is None:
        return
    _safely(
        "Healthcheck-Protokoll",
        recorder.record_delivery,
        run_id=run_id,
        report_id=None,
        channel="healthcheck",
        kind="ping_ok" if success else "ping_fail",
        recipient=ping_target(settings.healthcheck_url),
        subject=None,
        success=result,
        error=None if result else "Ping fehlgeschlagen",
    )


def _try_send_error_mail(
    settings: Settings,
    trace: str,
    *,
    recorder: BatchRecorder | None = None,
    run_id: int | None = None,
) -> None:
    subject = "FEHLER beim Batch-Run"
    error: str | None = None
    try:
        body = f"<h2>Fehler im woechentlichen Batch-Run</h2><pre>{html.escape(trace)}</pre>"
        send_report(settings, subject, body, attachment=None)
    except Exception as inner:
        log.error("Auch Fehler-Mail fehlgeschlagen: %s", inner)
        error = str(inner)
    if recorder is not None:
        _safely(
            "Versandprotokoll",
            recorder.record_delivery,
            run_id=run_id,
            report_id=None,
            channel="mail",
            kind="error",
            recipient=str(settings.mail_to),
            subject=subject,
            success=error is None,
            error=error,
        )


def run(force_refresh: bool = False, dry_run: bool = False) -> int:
    try:
        settings = load_settings()
    except ValidationError as e:
        # Logging ist hier noch nicht initialisiert - direkt auf stderr
        sys.stderr.write("Konfigurationsfehler:\n")
        sys.stderr.write(str(e) + "\n")
        return EXIT_CONFIG

    setup_logging(settings.logs_dir)
    return _run(settings, force_refresh=force_refresh, dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description="DAX/MDAX Value-Aktien Batch-Analyse")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Abruf von heute in der Datenbank ignorieren und neu von yfinance laden",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Kein Mailversand; Vorschau-HTML und CSV zusaetzlich nach DATA_DIR schreiben",
    )
    args = parser.parse_args()
    return run(force_refresh=args.force_refresh, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
