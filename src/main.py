"""Orchestriert den Batch: Universum -> Daten -> Scoring -> Report -> Mail."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback

from pydantic import ValidationError

from . import __version__
from .config import Settings, load_settings
from .data_fetcher import FetcherConfig, fetch_all
from .healthcheck import ping
from .logging_setup import setup_logging
from .mailer import send_report
from .reporting import build_report
from .scoring import ScoringConfig, score
from .universe import load_universe


def _run(settings: Settings, *, force_refresh: bool, dry_run: bool) -> int:
    log = logging.getLogger("main")
    log.info("=== value-analyzer v%s START ===", __version__)

    try:
        tickers = load_universe()
        if settings.universe == "DAX_ONLY":
            tickers = [t for t in tickers if t.index == "DAX"]
        universe_size = len(tickers)

        fetcher_cfg = FetcherConfig(default_tax_rate=settings.default_tax_rate)
        df = fetch_all(
            tickers,
            cache_dir=settings.data_dir,
            force_refresh=force_refresh,
            cfg=fetcher_cfg,
        )

        scoring_cfg = ScoringConfig(
            min_market_cap=settings.min_market_cap,
            value_weight=settings.value_weight,
            quality_weight=settings.quality_weight,
        )
        scored = score(df, scoring_cfg)

        if scored.empty or int(scored["composite_score"].notna().sum()) == 0:
            log.error("Keine bewertbaren Datenpunkte - Abbruch.")
            ping(settings.healthcheck_url, success=False, message="no scoreable data")
            return 3

        report = build_report(
            scored,
            output_dir=settings.data_dir,
            top_n=settings.top_n,
            bottom_n=settings.bottom_n,
            value_weight=settings.value_weight,
            quality_weight=settings.quality_weight,
            version=__version__,
            universe_size=universe_size,
        )

        if dry_run:
            preview = settings.data_dir / "preview_latest.html"
            preview.write_text(report.html, encoding="utf-8")
            log.info("DRY-RUN: HTML-Preview -> %s", preview)
            log.info("DRY-RUN: CSV -> %s", report.csv_path)
            log.info("DRY-RUN: Subject ware -> %s", report.subject)
            return 0

        send_report(settings, report.subject, report.html, attachment=report.csv_path)
        log.info("=== Run erfolgreich (scored %d/%d) ===", report.scored, report.universe_size)
        ping(
            settings.healthcheck_url,
            success=True,
            message=f"scored {report.scored}/{report.universe_size}",
        )
    except Exception as e:
        log.exception("Unerwarteter Fehler im Run")
        ping(settings.healthcheck_url, success=False, message=str(e))
        if not dry_run:
            _try_send_error_mail(settings, traceback.format_exc())
        return 1
    return 0


def _try_send_error_mail(settings: Settings, trace: str) -> None:
    try:
        html = f"<h2>Fehler im wochentlichen Batch-Run</h2><pre>{trace}</pre>"
        send_report(settings, "FEHLER beim Batch-Run", html, attachment=None)
    except Exception as inner:
        logging.getLogger("main").error("Auch Fehler-Mail fehlgeschlagen: %s", inner)


def run(force_refresh: bool = False, dry_run: bool = False) -> int:
    try:
        settings = load_settings()
    except ValidationError as e:
        # Logging ist hier noch nicht initialisiert - direkt auf stderr
        sys.stderr.write("Konfigurationsfehler:\n")
        sys.stderr.write(str(e) + "\n")
        return 2

    setup_logging(settings.logs_dir)
    return _run(settings, force_refresh=force_refresh, dry_run=dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description="DAX/MDAX Value-Aktien Batch-Analyse")
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Cache ignorieren und Daten neu von yfinance laden",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Kein Mailversand, nur HTML/CSV erzeugen",
    )
    args = parser.parse_args()
    return run(force_refresh=args.force_refresh, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
