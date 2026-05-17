"""Zentrales Logging-Setup mit Rotation."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    """Konfiguriert Root-Logger mit RotatingFileHandler + StreamHandler.

    Ein einziger Logfile (``value-analyzer.log``) bis 5 MB, danach Rotation
    mit 10 Backups. So entstehen ueber Jahre maximal 50 MB Logs statt
    ein File pro Run.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "value-analyzer.log"

    formatter = logging.Formatter(LOG_FORMAT)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    root = logging.getLogger()
    # Bestehende Handler entfernen (relevant fuer Tests / Re-Runs im selben Prozess)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    # Drittanbieter zaehmen
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("peewee").setLevel(logging.WARNING)
