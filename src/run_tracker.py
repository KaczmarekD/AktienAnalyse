"""Abschluss eines Laufs aus den Events - Vorlaeufer der Run-Projektion im web-api (P1.8).

Der Tracker liest nur Events, keine Tabellen der Module. Am Ende der Kette steht genau ein
Ergebnis: ``notification.report.sent`` (Erfolg) oder ``screening.run.failed``. Ein
Fehlschlag gewinnt immer, auch gegen ein spaeteres Erfolgs-Event.
"""

from __future__ import annotations

import functools
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from va_contracts.events.v1 import (
    REASON_NO_DATA,
    REPORT_SENT,
    RUN_FAILED,
    SCORING_RUN_COMPLETED,
    SNAPSHOT_COMPLETED,
)

if TYPE_CHECKING:
    from va_contracts import Envelope
    from va_contracts.events.v1 import (
        ReportSentV1,
        RunFailedV1,
        ScoringRunCompletedV1,
        SnapshotCompletedV1,
    )
    from va_platform.bus import DeadLetter, EventBus

CONSUMER = "batch"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_DATA = 3


@dataclass
class RunOutcome:
    """Felder fuer ``batch.run`` beim Abschluss (``RunRepository.write_run_finish``)."""

    status: str
    exit_code: int
    fetch_run_id: int | None = None
    scoring_run_id: int | None = None
    report_id: int | None = None
    universe_size: int | None = None
    scored_count: int | None = None
    failed_count: int | None = None
    error: str | None = None

    def finish_kwargs(self) -> dict[str, Any]:
        return asdict(self)


def _locked[**P, R](method: Callable[P, R]) -> Callable[P, R]:
    """Ueber NATS laufen die Handler in Threads (P4.3): immer nur einer zur Zeit."""

    @functools.wraps(method)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        tracker = args[0]
        assert isinstance(tracker, RunTracker)
        with tracker._lock:
            return method(*args, **kwargs)

    return wrapper


class RunTracker:
    def __init__(self, run_id: int) -> None:
        self._run_id = run_id
        self._fetch_run_id: int | None = None
        self._scoring_run_id: int | None = None
        self._universe_size: int | None = None
        self._scored: int | None = None
        self._result: RunOutcome | None = None
        self._lock = threading.RLock()
        self._decided = threading.Event()

    @property
    def outcome(self) -> RunOutcome | None:
        return self._result

    @outcome.setter
    def outcome(self, value: RunOutcome | None) -> None:
        self._result = value
        if value is not None:
            self._decided.set()

    def wait(self, timeout: float) -> bool:
        """``True``, sobald ein Ergebnis feststeht (P4.3: ueber NATS kehrt publish sofort
        zurueck). Ein spaeterer Fehlschlag kann ein Erfolgs-Ergebnis noch ersetzen."""
        return self._decided.wait(timeout)

    def subscribe(self, bus: EventBus) -> None:
        bus.subscribe(SNAPSHOT_COMPLETED, CONSUMER, self._on_snapshot)
        bus.subscribe(SCORING_RUN_COMPLETED, CONSUMER, self._on_scoring)
        bus.subscribe(REPORT_SENT, CONSUMER, self._on_report_sent)
        bus.subscribe(RUN_FAILED, CONSUMER, self._on_failed)

    @_locked
    def _on_snapshot(self, env: Envelope[SnapshotCompletedV1]) -> None:
        if env.data.run_id == self._run_id:
            self._fetch_run_id = env.data.fetch_run_id
            self._universe_size = env.data.universe.size

    @_locked
    def _on_scoring(self, env: Envelope[ScoringRunCompletedV1]) -> None:
        event = env.data
        if event.run_id != self._run_id:
            return
        self._fetch_run_id = event.fetch_run_id
        self._scoring_run_id = event.scoring_run_id
        self._universe_size = event.universe.size
        self._scored = sum(row.composite_score is not None for row in event.ranking)

    @_locked
    def _on_report_sent(self, env: Envelope[ReportSentV1]) -> None:
        if env.data.run_id != self._run_id or self._failed:
            return
        universe = self._universe_size or 0
        scored = self._scored or 0
        failed = max(0, universe - scored)
        self.outcome = self._outcome(
            "success" if failed == 0 else "partial",
            EXIT_OK,
            report_id=env.data.report_id,
            scored_count=scored,
            failed_count=failed,
        )

    @_locked
    def _on_failed(self, env: Envelope[RunFailedV1]) -> None:
        event = env.data
        if event.run_id != self._run_id or self._failed:
            return
        if event.scoring_run_id is not None:
            self._scoring_run_id = event.scoring_run_id
        if event.reason == REASON_NO_DATA:
            self.outcome = self._outcome(
                "no_data", EXIT_NO_DATA, scored_count=0, failed_count=self._universe_size
            )
        else:
            self.outcome = self._outcome("failed", EXIT_FAILED, error=event.detail or event.reason)

    @_locked
    def on_dead_letter(self, dead: DeadLetter) -> None:
        """Ein Handler ist trotz Wiederholung gescheitert (ein Bug): Der Lauf ist gescheitert."""
        if self._failed:
            return
        self.outcome = self._outcome(
            "failed",
            EXIT_FAILED,
            error=f"{dead.consumer}: {dead.envelope.type} nicht verarbeitet ({dead.error!r})",
        )

    @property
    def _failed(self) -> bool:
        return self.outcome is not None and self.outcome.exit_code != EXIT_OK

    def _outcome(
        self,
        status: str,
        exit_code: int,
        *,
        report_id: int | None = None,
        scored_count: int | None = None,
        failed_count: int | None = None,
        error: str | None = None,
    ) -> RunOutcome:
        return RunOutcome(
            status=status,
            exit_code=exit_code,
            fetch_run_id=self._fetch_run_id,
            scoring_run_id=self._scoring_run_id,
            report_id=report_id,
            universe_size=self._universe_size,
            scored_count=scored_count,
            failed_count=failed_count,
            error=error,
        )
