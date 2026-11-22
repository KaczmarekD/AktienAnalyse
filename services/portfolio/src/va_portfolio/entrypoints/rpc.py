"""Request/Reply von portfolio (D3.1): Depots lesen und aendern fuer das web-api; seit D3.2
auch der Datenexport aller eigenen Depots (``portfolio.depots.export``).

Fehler gehen als Antwort zurueck: ``not_found`` (kein Depot dieses Nutzers), ``archived``,
``invalid`` (Eingabe), ``conflict`` mit der neuesten Version. Ein unerwarteter Fehler wird beim
Transport zu ``internal`` (``va_platform.nats.answer_request``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from va_contracts.portfolio import (
    CashLineV1,
    DepotExportV1,
    DepotV1,
    HistoryEntryV1,
    HoldingLineV1,
    HoldingsV1,
)
from va_contracts.rpc.v1 import (
    DEPOTS_ARCHIVE,
    DEPOTS_CREATE,
    DEPOTS_EXPORT,
    DEPOTS_GET,
    DEPOTS_LIST,
    DEPOTS_RESTORE,
    DEPOTS_UPDATE,
    HOLDINGS_GET,
    HOLDINGS_HISTORY,
    HOLDINGS_SAVE,
    DepotExportReplyV1,
    DepotListReplyV1,
    DepotReplyV1,
    HistoryReplyV1,
    HoldingsReplyV1,
    RpcErrorV1,
)

from ..application.depots import ArchivedDepot, DepotNotFound
from ..domain.depots import CashLine, DepotError, HoldingLine, VersionConflict

if TYPE_CHECKING:
    from va_contracts.rpc.v1 import (
        DepotCreateRequestV1,
        DepotExportRequestV1,
        DepotListRequestV1,
        DepotRefRequestV1,
        DepotUpdateRequestV1,
        HoldingsGetRequestV1,
        HoldingsSaveRequestV1,
        RpcReplyV1,
        RpcSpec,
    )

    from ..application.depots import DepotService, DepotSummary, HistoryEntry
    from ..domain.depots import Snapshot


def _depot(summary: DepotSummary) -> DepotV1:
    depot = summary.depot
    return DepotV1(
        id=depot.id,
        kind=depot.kind,
        name=depot.name,
        description=depot.description,
        status=depot.status,
        created_at=depot.created_at,
        version=summary.version,
        positions=summary.positions,
    )


def _holdings(snapshot: Snapshot) -> HoldingsV1:
    return HoldingsV1(
        depot_id=snapshot.depot_id,
        version=snapshot.version,
        source=snapshot.source,
        created_at=snapshot.created_at,
        created_by=snapshot.created_by,
        lines=[
            HoldingLineV1(
                isin=line.isin,
                quantity=line.quantity,
                unit=line.unit,
                cost_basis_eur=line.cost_basis_eur,
                note=line.note,
            )
            for line in snapshot.lines
        ],
        cash=[CashLineV1(currency="EUR", amount=c.amount) for c in snapshot.cash],
    )


def _entry(entry: HistoryEntry) -> HistoryEntryV1:
    return HistoryEntryV1(
        version=entry.version,
        source=entry.source,
        created_at=entry.created_at,
        created_by=entry.created_by,
        positions=entry.positions,
        added=entry.diff.added,
        changed=entry.diff.changed,
        removed=entry.diff.removed,
    )


def _guarded[R: RpcReplyV1](reply: type[R], work: Callable[[], R]) -> R:
    """Die erwartbaren Fehler des Anwendungsfalls als Antwort."""
    try:
        return work()
    except DepotNotFound as e:
        return reply(error=RpcErrorV1(code="not_found", message=str(e)))
    except ArchivedDepot as e:
        return reply(error=RpcErrorV1(code="archived", message=str(e)))
    except VersionConflict as e:
        return reply(error=RpcErrorV1(code="conflict", message=str(e), newest=e.newest))
    except DepotError as e:
        return reply(error=RpcErrorV1(code="invalid", message=str(e)))


def handlers(service: DepotService) -> dict[RpcSpec[Any, Any], Callable[[Any], RpcReplyV1]]:
    def list_depots(request: DepotListRequestV1) -> DepotListReplyV1:
        summaries = service.list(request.user_id, include_archived=request.include_archived)
        return DepotListReplyV1(depots=[_depot(s) for s in summaries])

    def create(request: DepotCreateRequestV1) -> DepotReplyV1:
        return _guarded(
            DepotReplyV1,
            lambda: DepotReplyV1(
                depot=_depot(
                    service.create(request.user_id, request.kind, request.name, request.description)
                )
            ),
        )

    def get(request: DepotRefRequestV1) -> DepotReplyV1:
        return _guarded(
            DepotReplyV1,
            lambda: DepotReplyV1(depot=_depot(service.get(request.user_id, request.depot_id))),
        )

    def update(request: DepotUpdateRequestV1) -> DepotReplyV1:
        return _guarded(
            DepotReplyV1,
            lambda: DepotReplyV1(
                depot=_depot(
                    service.update(
                        request.user_id, request.depot_id, request.name, request.description
                    )
                )
            ),
        )

    def archive(request: DepotRefRequestV1) -> DepotReplyV1:
        return _guarded(
            DepotReplyV1,
            lambda: DepotReplyV1(depot=_depot(service.archive(request.user_id, request.depot_id))),
        )

    def restore(request: DepotRefRequestV1) -> DepotReplyV1:
        return _guarded(
            DepotReplyV1,
            lambda: DepotReplyV1(depot=_depot(service.restore(request.user_id, request.depot_id))),
        )

    def holdings(request: HoldingsGetRequestV1) -> HoldingsReplyV1:
        return _guarded(
            HoldingsReplyV1,
            lambda: HoldingsReplyV1(
                holdings=_holdings(
                    service.holdings(request.user_id, request.depot_id, request.version)
                )
            ),
        )

    def save(request: HoldingsSaveRequestV1) -> HoldingsReplyV1:
        lines = [
            HoldingLine(line.isin, line.quantity, line.unit, line.cost_basis_eur, line.note)
            for line in request.lines
        ]
        cash = [CashLine(c.amount, c.currency) for c in request.cash]
        return _guarded(
            HoldingsReplyV1,
            lambda: HoldingsReplyV1(
                holdings=_holdings(
                    service.save(
                        request.user_id,
                        request.depot_id,
                        request.base_version,
                        lines,
                        cash,
                        source=request.source,
                    )
                )
            ),
        )

    def export(request: DepotExportRequestV1) -> DepotExportReplyV1:
        return DepotExportReplyV1(
            depots=[
                DepotExportV1(depot=_depot(summary), versions=[_holdings(s) for s in snapshots])
                for summary, snapshots in service.export(request.user_id)
            ]
        )

    def history(request: DepotRefRequestV1) -> HistoryReplyV1:
        return _guarded(
            HistoryReplyV1,
            lambda: HistoryReplyV1(
                entries=[_entry(e) for e in service.history(request.user_id, request.depot_id)]
            ),
        )

    return {
        DEPOTS_LIST: list_depots,
        DEPOTS_CREATE: create,
        DEPOTS_GET: get,
        DEPOTS_UPDATE: update,
        DEPOTS_ARCHIVE: archive,
        DEPOTS_RESTORE: restore,
        HOLDINGS_GET: holdings,
        HOLDINGS_SAVE: save,
        HOLDINGS_HISTORY: history,
        DEPOTS_EXPORT: export,
    }
