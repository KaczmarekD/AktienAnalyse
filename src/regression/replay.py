"""Replay: ein gespeicherter Abruf durch die echten Handler von scoring und notification.

Derselbe Weg wie ein Lauf, der einen Abruf vom selben Tag wiederverwendet: Snapshots ->
``FundamentalsV1`` -> ``marketdata.snapshot.completed`` auf einem eigenen Bus im Prozess. Die
Speicher, der Versand und der Healthcheck sind Attrappen, die das Ergebnis nur festhalten.
Es wird nichts gespeichert und nichts verschickt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import TYPE_CHECKING, Any

import pandas as pd

from va_contracts.envelope import new_envelope
from va_contracts.events.v1 import (
    RUN_FAILED,
    SNAPSHOT_COMPLETED,
    FundamentalsV1,
    RunOptionsV1,
    SnapshotCompletedV1,
    UniverseInfoV1,
)
from va_market_data.application.fetch import success_share
from va_notification.entrypoints.handlers import NotificationConfig, NotificationHandler
from va_platform.bus import InProcessBus
from va_platform.serialization import json_safe
from va_scoring.adapters.postgres.store import factor_rows, score_rows, scoring_symbols
from va_scoring.entrypoints.handlers import SnapshotCompletedHandler

from .case import FACTOR_COLUMNS, SCORE_COLUMNS
from .compare import (
    ABSENT,
    PRESENT,
    Difference,
    compare_csv,
    compare_factor_scores,
    compare_scores,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from va_contracts import Envelope
    from va_contracts.events.v1 import RunFailedV1
    from va_notification.domain.report import ReportArtifacts
    from va_platform.bus import DeadLetter
    from va_scoring.domain.profile import ProfileVersionRef
    from va_scoring.domain.scoring import ScoringConfig

    from .case import ReplayCase

SOURCE = "va/regression"
CONSUMER = "regression"


class ReplayError(RuntimeError):
    """Die Event-Kette lief nicht durch: Ein Handler ist trotz Wiederholung gescheitert."""


@dataclass(frozen=True)
class ReplayResult:
    scores: pd.DataFrame  # SCORE_COLUMNS
    factor_scores: pd.DataFrame  # FACTOR_COLUMNS
    csv: bytes | None  # None: kein Report (z. B. keine bewertbaren Titel)
    failure: str | None  # reason aus screening.run.failed


@dataclass(frozen=True)
class CaseOutcome:
    case: ReplayCase
    differences: tuple[Difference, ...]
    checked: tuple[str, ...]  # verglichene Bereiche: scores, factors, csv
    failure: str | None = None
    # Schluessel, in denen die aktuelle Konfiguration von der gespeicherten abweicht;
    # None: keine gespeichert (Import)
    config_changes: tuple[str, ...] | None = None

    @property
    def equal(self) -> bool:
        return not self.differences and self.failure is None


def check(case: ReplayCase, config: ScoringConfig) -> CaseOutcome:
    """Replay und Vergleich mit allem, was zu diesem Lauf gespeichert ist."""
    result = replay(case, config)
    differences = compare_scores(case.scores, result.scores)
    checked = ["scores"]
    if not case.factor_scores.empty:
        checked.append("factors")
        differences += compare_factor_scores(case.factor_scores, result.factor_scores)
    if case.csv is not None:
        checked.append("csv")
        if result.csv is None:
            differences.append(Difference("csv", "", "report", PRESENT, ABSENT))
        else:
            differences += compare_csv(case.csv, result.csv)
    return CaseOutcome(
        case=case,
        differences=tuple(differences),
        checked=tuple(checked),
        failure=result.failure,
        config_changes=_config_changes(case.config, config),
    )


def replay(case: ReplayCase, config: ScoringConfig) -> ReplayResult:
    scoring = _ScoringCapture(case.scoring_run_id)
    reporting = _ReportCapture()
    failures: list[RunFailedV1] = []
    dead: list[DeadLetter] = []

    bus = InProcessBus(on_dead_letter=dead.append)
    SnapshotCompletedHandler(bus, store=scoring, config=config).subscribe()
    NotificationHandler(
        bus,
        sender=_NoSender(),
        heartbeat=_NoHeartbeat(),
        store=reporting,
        config=NotificationConfig(clock=lambda: _report_time(case)),
    ).subscribe()

    def on_failed(env: Envelope[RunFailedV1]) -> None:
        failures.append(env.data)

    bus.subscribe(RUN_FAILED, CONSUMER, on_failed)
    bus.publish(
        new_envelope(
            SNAPSHOT_COMPLETED,
            _snapshot_completed(case),
            source=SOURCE,
            correlationid=f"replay-{case.scoring_run_id}",
        )
    )
    if dead:
        letter = dead[0]
        msg = f"{letter.consumer}: {letter.error}"
        raise ReplayError(msg) from letter.error
    return ReplayResult(
        scores=scoring.scores,
        factor_scores=scoring.factor_scores,
        csv=None if reporting.report is None else reporting.report.csv_bytes,
        failure=failures[0].reason if failures else None,
    )


def _snapshot_completed(case: ReplayCase) -> SnapshotCompletedV1:
    frame = case.snapshots
    return SnapshotCompletedV1(
        # Platzhalter: Der Replay hat keinen eigenen Lauf in batch.run
        run_id=case.scoring_run_id,
        trigger="manual",
        # dry_run und notify=False: notification baut den Report, verschickt aber nichts
        options=RunOptionsV1(dry_run=True, notify=False),
        fetch_run_id=case.fetch_run_id,
        as_of=case.fetched_on,
        success_share=success_share(frame),
        universe=UniverseInfoV1(
            source=case.universe_source, as_of=case.universe_as_of, size=case.universe_size
        ),
        fundamentals=[FundamentalsV1.from_flat(row) for row in frame.to_dict("records")],
    )


def _report_time(case: ReplayCase) -> datetime:
    if case.generated_at is not None:
        return case.generated_at
    return datetime.combine(case.fetched_on, time())


def _config_changes(stored: dict[str, Any] | None, config: ScoringConfig) -> tuple[str, ...] | None:
    if stored is None:
        return None
    current = json_safe(asdict(config))
    old = json_safe(stored)
    return tuple(sorted(k for k in current.keys() | old.keys() if current.get(k) != old.get(k)))


def _frame(rows: list[Any], columns: tuple[str, ...], symbols: dict[int, str]) -> pd.DataFrame:
    # instrument_id faellt ueber ``columns`` weg, das Symbol tritt an seine Stelle
    records = [{"symbol": symbols[row.instrument_id], **asdict(row)} for row in rows]
    return pd.DataFrame(records, columns=list(columns))


@dataclass
class _ScoringCapture:
    """``ScoringStore``: bildet die Zeilen wie der Speicher, schreibt sie aber nicht."""

    scoring_run_id: int
    scores: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=list(SCORE_COLUMNS)))
    factor_scores: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(columns=list(FACTOR_COLUMNS))
    )

    def record_scoring(
        self,
        fetch_run_id: int,  # noqa: ARG002 - Signatur des Ports
        df_all: pd.DataFrame,
        scored: pd.DataFrame,
        cfg: ScoringConfig,
    ) -> int:
        # Kuenstliche IDs je Titel, damit dieselben Funktionen wie im Speicher greifen
        ids = {symbol: i for i, symbol in enumerate(scoring_symbols(df_all, scored), start=1)}
        symbols = {i: symbol for symbol, i in ids.items()}
        scores = _frame(score_rows(df_all, scored, ids), SCORE_COLUMNS, symbols)
        self.scores = scores.sort_values(
            ["rank_overall", "symbol"], na_position="last", ignore_index=True
        )
        factors = _frame(factor_rows(scored, ids, cfg), FACTOR_COLUMNS, symbols)
        self.factor_scores = factors.sort_values(["symbol", "factor_key"], ignore_index=True)
        return self.scoring_run_id

    def ensure_default_profile(self, params: Mapping[str, Any]) -> ProfileVersionRef:
        msg = "Das Replay legt keine Profile an"
        raise NotImplementedError(msg)


@dataclass
class _ReportCapture:
    """``ReportStore``: haelt den Report fest, Versandprotokolle entfallen."""

    report: ReportArtifacts | None = None

    def record_report(
        self,
        run_id: int | None,  # noqa: ARG002 - Signatur des Ports
        scoring_run_id: int | None,  # noqa: ARG002
        report: ReportArtifacts,
    ) -> int:
        self.report = report
        return 1

    def record_delivery(self, **kwargs: Any) -> None:  # noqa: ARG002 - Signatur des Ports
        return None


class _NoSender:
    def send(
        self,
        subject: str,  # noqa: ARG002 - Signatur des Ports
        html_body: str,  # noqa: ARG002
        attachment: tuple[str, bytes] | None = None,  # noqa: ARG002
    ) -> None:
        msg = "Ein Replay verschickt nichts"
        raise RuntimeError(msg)


class _NoHeartbeat:
    def ping(self, success: bool, message: str | None = None) -> bool | None:  # noqa: ARG002
        return None
