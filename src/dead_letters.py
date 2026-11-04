"""Aus einem Dead Letter wird ``screening.run.failed`` (P1.8, fuer den Worker aus P4.7 geteilt).

Ein Handler ist trotz Wiederholung gescheitert, das ist ein Bug. Der Run endet dann wie jeder
Fehlschlag: notification schickt die Fehlermail (und bei ``scheduled`` den Ping auf ``/fail``),
die Run-Verwaltung schliesst ihn ab. Run, Trigger und Optionen stehen im gescheiterten Event.
Ein gescheitertes Fehler-Event loest keines mehr aus, ein Event ohne Run (Profile) auch nicht.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Any, get_args

from va_contracts.events.v1 import RUN_FAILED, RunFailedV1, Stage
from va_platform.bus import follow_up

if TYPE_CHECKING:
    from va_contracts import Envelope
    from va_platform.bus import DeadLetter


def run_failure(dead: DeadLetter, *, source: str) -> Envelope[RunFailedV1] | None:
    """``screening.run.failed`` fuer den Run des gescheiterten Events, sonst ``None``."""
    if dead.envelope.type == RUN_FAILED.type:
        return None
    data: Any = dead.envelope.data
    if not all(hasattr(data, field) for field in ("run_id", "trigger", "options")):
        return None
    failure = RunFailedV1(
        run_id=data.run_id,
        trigger=data.trigger,
        options=data.options,
        stage=stage_of(dead.consumer),
        reason=f"{dead.consumer}: {dead.error}",
        detail="".join(traceback.format_exception(dead.error)),
    )
    return follow_up(dead.envelope, RUN_FAILED, failure, source=source)


def stage_of(consumer: str) -> Stage:
    """Stufe fuer screening.run.failed; was keinem Modul gehoert, meldet der Watchdog."""
    return consumer if consumer in get_args(Stage) else "watchdog"  # type: ignore[return-value]
