"""Schema ``batch``: Start, Abschluss und Log-Zeilen eines Laufs (``BatchStore``).

Seit P1.8 speichern die Module ihre Daten selbst (``adapters/postgres/store.py``); hier
bleibt nur die Ablaufsteuerung. Jede Methode ist eine eigene, sofort committete
Transaktion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tenacity import retry, stop_after_attempt, wait_exponential

from va_platform.db import session_scope

from .. import __version__
from .repositories.runs import RunRepository

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Engine

    from .log_handler import LogEntry


class BatchRecorder:
    def __init__(self, engine: Engine, app_version: str = __version__) -> None:
        self._engine = engine
        self._app_version = app_version

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=2, max=15),
        reraise=True,
    )
    def start_run(
        self,
        *,
        kind: str,
        dry_run: bool,
        force_refresh: bool,
        universe_mode: str | None,
        settings: dict[str, Any] | None,
    ) -> int:
        with session_scope(self._engine) as s:
            return RunRepository(s).write_run_start(
                kind=kind,
                app_version=self._app_version,
                dry_run=dry_run,
                force_refresh=force_refresh,
                universe_mode=universe_mode,
                settings=settings,
            )

    def finish_run(self, run_id: int, **kwargs: Any) -> None:
        with session_scope(self._engine) as s:
            RunRepository(s).write_run_finish(run_id, **kwargs)

    def record_logs(self, run_id: int, entries: Sequence[LogEntry]) -> None:
        with session_scope(self._engine) as s:
            RunRepository(s).write_logs(run_id, entries)
