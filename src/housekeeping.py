"""Aufraeumen alter Laufartefakte im Data-Verzeichnis.

Jeder Run legt einen Parquet-Cache und eine Ranking-CSV an. Ohne Rotation
waechst ``data/`` auf der Synology unbegrenzt. Das Alter wird aus dem Datum
im Dateinamen gelesen (nicht aus mtime), damit Kopien/Restores das Ergebnis
nicht verfaelschen. Die Fallback-CSV passt auf keines der Muster.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

# (Regex auf den Dateinamen, strptime-Format des Datums-Gruppe)
ARTIFACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^fundamentals_(\d{4}-\d{2}-\d{2})\.parquet$"), "%Y-%m-%d"),
    (re.compile(r"^value_ranking_(\d{8})\.csv$"), "%Y%m%d"),
)


def _artifact_date(name: str) -> date | None:
    for pattern, fmt in ARTIFACT_PATTERNS:
        m = pattern.match(name)
        if m:
            try:
                return datetime.strptime(m.group(1), fmt).date()
            except ValueError:
                return None
    return None


def cleanup_old_artifacts(
    data_dir: Path,
    retention_days: int,
    today: date | None = None,
) -> list[Path]:
    """Loescht Caches/Rankings, die aelter als ``retention_days`` sind.

    Fehler beim Loeschen werden geloggt, nie geworfen - Housekeeping darf
    den Run nicht abbrechen. Liefert die geloeschten Pfade.
    """
    if retention_days <= 0 or not data_dir.is_dir():
        return []
    cutoff = (today or date.today()) - timedelta(days=retention_days)

    removed: list[Path] = []
    for path in data_dir.iterdir():
        if not path.is_file():
            continue
        artifact_date = _artifact_date(path.name)
        if artifact_date is None or artifact_date >= cutoff:
            continue
        try:
            path.unlink()
            removed.append(path)
        except OSError as e:
            log.warning("Konnte %s nicht loeschen: %s", path, e)

    if removed:
        log.info(
            "Housekeeping: %d Dateien aelter als %d Tage entfernt", len(removed), retention_days
        )
    return removed
