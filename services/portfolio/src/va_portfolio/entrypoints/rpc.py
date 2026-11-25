"""Request/Reply von portfolio (D3.1): Depots lesen und aendern fuer das web-api; seit D3.2
auch der Datenexport aller eigenen Depots (``portfolio.depots.export``).

Seit D3.5 Datei im eigenen Format: Abgleich (``holdings.import.preview``), Uebernahme
(``holdings.import``) und die Positionen als Datei (``holdings.file``). Im Abgleich sind Notizen
auf ``PREVIEW_NOTE`` Zeichen gekuerzt: 1000 geaenderte Positionen mit langen Notizen vorher und
nachher passten sonst nicht durch NATS (1 MB). Uebernommen wird die volle Notiz.

Seit D3.4 traegt jedes Depot seine Bewertung (``DepotValuationV1``), ``depots.get`` dazu jede
Position; der Export nicht.

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
    DepotValuationV1,
    HistoryEntryV1,
    HoldingLineV1,
    HoldingsV1,
    ImportEntryV1,
    ImportPreviewV1,
    PositionValueV1,
    RejectedRowV1,
)
from va_contracts.rpc.v1 import (
    DEPOTS_ARCHIVE,
    DEPOTS_CREATE,
    DEPOTS_EXPORT,
    DEPOTS_GET,
    DEPOTS_LIST,
    DEPOTS_RESTORE,
    DEPOTS_UPDATE,
    HOLDINGS_FILE,
    HOLDINGS_GET,
    HOLDINGS_HISTORY,
    HOLDINGS_IMPORT,
    HOLDINGS_IMPORT_PREVIEW,
    HOLDINGS_SAVE,
    DepotExportReplyV1,
    DepotListReplyV1,
    DepotReplyV1,
    HistoryReplyV1,
    HoldingsFileReplyV1,
    HoldingsReplyV1,
    ImportPreviewReplyV1,
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
        HoldingsFileRequestV1,
        HoldingsGetRequestV1,
        HoldingsImportRequestV1,
        HoldingsSaveRequestV1,
        RpcReplyV1,
        RpcSpec,
    )

    from ..application.depots import DepotService, DepotSummary, HistoryEntry, ImportPreview
    from ..domain.depots import Snapshot
    from ..domain.valuation import DepotValue, PositionValue


def _position(position: PositionValue) -> PositionValueV1:
    line, security, quote = position.line, position.security, position.quote
    return PositionValueV1(
        isin=line.isin,
        name=security.name if security else None,
        asset_class=security.asset_class if security else None,  # type: ignore[arg-type]
        pending=position.pending,
        quantity=line.quantity,
        unit=line.unit,
        price=quote.close if quote else None,
        price_currency=quote.currency if quote else None,
        price_date=quote.trade_date if quote else None,
        price_source=quote.source if quote else None,
        percent_of_par=quote.percent_of_par if quote else False,
        fx_rate=position.fx_rate,
        value_eur=position.value_eur,
        cost_basis_eur=line.cost_basis_eur,
        difference_eur=position.difference_eur,
        missing=position.missing,
    )


def _valuation(value: DepotValue, *, positions: bool) -> DepotValuationV1:
    return DepotValuationV1(
        value_eur=value.value_eur,
        positions_eur=value.positions_eur,
        cash_eur=value.cash_eur,
        complete=value.complete,
        unvalued=value.unvalued,
        pending=value.pending,
        cost_basis_eur=value.cost_basis_eur,
        difference_eur=value.difference_eur,
        price_date=value.price_date,
        positions=[_position(p) for p in value.positions] if positions else [],
    )


def _depot(summary: DepotSummary, *, positions: bool = False) -> DepotV1:
    depot = summary.depot
    valuation = summary.valuation
    return DepotV1(
        id=depot.id,
        kind=depot.kind,
        name=depot.name,
        description=depot.description,
        status=depot.status,
        created_at=depot.created_at,
        version=summary.version,
        positions=summary.positions,
        valuation=None if valuation is None else _valuation(valuation, positions=positions),
    )


PREVIEW_NOTE = 120


def _line(line: HoldingLine, *, note_limit: int | None = None) -> HoldingLineV1:
    note = line.note
    if note is not None and note_limit is not None and len(note) > note_limit:
        note = note[: note_limit - 1] + "\u2026"
    return HoldingLineV1(
        isin=line.isin,
        quantity=line.quantity,
        unit=line.unit,
        cost_basis_eur=line.cost_basis_eur,
        note=note,
    )


def _preview(preview: ImportPreview) -> ImportPreviewV1:
    return ImportPreviewV1(
        base_version=preview.base_version,
        entries=[
            ImportEntryV1(
                isin=e.isin,
                status=e.status,
                before=None if e.before is None else _line(e.before, note_limit=PREVIEW_NOTE),
                after=None if e.after is None else _line(e.after, note_limit=PREVIEW_NOTE),
                pending=e.after is not None and e.isin in preview.pending,
            )
            for e in preview.entries
        ],
        rejected=[RejectedRowV1(line=r.line, reason=r.reason) for r in preview.rejected],
    )


def _holdings(snapshot: Snapshot) -> HoldingsV1:
    return HoldingsV1(
        depot_id=snapshot.depot_id,
        version=snapshot.version,
        source=snapshot.source,
        created_at=snapshot.created_at,
        created_by=snapshot.created_by,
        lines=[_line(line) for line in snapshot.lines],
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
            lambda: DepotReplyV1(
                depot=_depot(service.get(request.user_id, request.depot_id), positions=True)
            ),
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

    def import_preview(request: HoldingsFileRequestV1) -> ImportPreviewReplyV1:
        return _guarded(
            ImportPreviewReplyV1,
            lambda: ImportPreviewReplyV1(
                preview=_preview(
                    service.preview_import(request.user_id, request.depot_id, request.content)
                )
            ),
        )

    def import_file(request: HoldingsImportRequestV1) -> HoldingsReplyV1:
        return _guarded(
            HoldingsReplyV1,
            lambda: HoldingsReplyV1(
                holdings=_holdings(
                    service.import_file(
                        request.user_id, request.depot_id, request.base_version, request.content
                    )
                )
            ),
        )

    def holdings_file(request: HoldingsGetRequestV1) -> HoldingsFileReplyV1:
        def work() -> HoldingsFileReplyV1:
            filename, content = service.export_file(
                request.user_id, request.depot_id, request.version
            )
            return HoldingsFileReplyV1(filename=filename, content=content)

        return _guarded(HoldingsFileReplyV1, work)

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
        HOLDINGS_IMPORT_PREVIEW: import_preview,
        HOLDINGS_IMPORT: import_file,
        HOLDINGS_FILE: holdings_file,
    }
