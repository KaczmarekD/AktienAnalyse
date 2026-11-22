"""Request/Reply von portfolio (D3.1): Depots fuer das web-api.

Die Handler bilden den Anwendungsfall auf die Contracts ab. Fehler gehen als Antwort zurueck:
``not_found`` (fremdes oder unbekanntes Depot), ``archived``, ``invalid``, ``conflict`` (mit der
neuesten Version). Mengen reisen als ``Decimal``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from va_contracts.portfolio import CashLineV1, HoldingLineV1
from va_contracts.rpc.v1 import (
    DEPOTS_ARCHIVE,
    DEPOTS_CREATE,
    DEPOTS_GET,
    DEPOTS_LIST,
    DEPOTS_RESTORE,
    DEPOTS_UPDATE,
    HOLDINGS_GET,
    HOLDINGS_HISTORY,
    HOLDINGS_SAVE,
    RPCS,
    DepotCreateRequestV1,
    DepotListRequestV1,
    DepotRefRequestV1,
    DepotUpdateRequestV1,
    HoldingsGetRequestV1,
    HoldingsSaveRequestV1,
)
from va_portfolio.adapters.memory import MemoryDepotStore
from va_portfolio.application.depots import DepotService
from va_portfolio.entrypoints.rpc import handlers

ANNA, BEN = 1, 2
SAP = "DE0007164600"
T0 = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)


@pytest.fixture
def call():
    rpc = handlers(DepotService(MemoryDepotStore(), clock=lambda: T0))

    def _call(spec, request):
        reply = rpc[spec](request)
        assert isinstance(reply, spec.reply)
        return reply

    return _call


def _create(call, user=ANNA):
    reply = call(DEPOTS_CREATE, DepotCreateRequestV1(user_id=user, kind="depot", name="DKB"))
    return reply.depot.id


def test_every_portfolio_command_has_a_handler():
    portfolio = {spec for name, spec in RPCS.items() if name.startswith("portfolio.")}
    assert set(handlers(DepotService(MemoryDepotStore()))) == portfolio


def test_create_list_get(call):
    depot_id = _create(call)
    [listed] = call(DEPOTS_LIST, DepotListRequestV1(user_id=ANNA)).depots
    assert (listed.id, listed.name, listed.kind, listed.status, listed.version) == (
        depot_id,
        "DKB",
        "depot",
        "active",
        0,
    )
    got = call(DEPOTS_GET, DepotRefRequestV1(user_id=ANNA, depot_id=depot_id)).depot
    assert got == listed


def test_a_foreign_depot_is_not_found(call):
    depot_id = _create(call, user=BEN)
    for spec, request in (
        (DEPOTS_GET, DepotRefRequestV1(user_id=ANNA, depot_id=depot_id)),
        (DEPOTS_ARCHIVE, DepotRefRequestV1(user_id=ANNA, depot_id=depot_id)),
        (HOLDINGS_GET, HoldingsGetRequestV1(user_id=ANNA, depot_id=depot_id)),
        (HOLDINGS_HISTORY, DepotRefRequestV1(user_id=ANNA, depot_id=depot_id)),
        (DEPOTS_UPDATE, DepotUpdateRequestV1(user_id=ANNA, depot_id=depot_id, name="x")),
        (HOLDINGS_SAVE, HoldingsSaveRequestV1(user_id=ANNA, depot_id=depot_id, base_version=0)),
    ):
        reply = call(spec, request)
        assert reply.error is not None, spec.name
        assert reply.error.code == "not_found", spec.name
    assert call(DEPOTS_LIST, DepotListRequestV1(user_id=ANNA)).depots == []


def test_save_and_read_holdings(call):
    depot_id = _create(call)
    saved = call(
        HOLDINGS_SAVE,
        HoldingsSaveRequestV1(
            user_id=ANNA,
            depot_id=depot_id,
            base_version=0,
            lines=[
                HoldingLineV1(
                    isin=SAP, quantity=Decimal("12.5"), cost_basis_eur=Decimal("1500"), note="x"
                )
            ],
            cash=[CashLineV1(amount=Decimal("250.10"))],
        ),
    ).holdings
    assert (saved.version, saved.source, saved.created_by) == (1, "manual", ANNA)
    current = call(HOLDINGS_GET, HoldingsGetRequestV1(user_id=ANNA, depot_id=depot_id)).holdings
    assert current == saved
    assert current.lines[0].quantity == Decimal("12.5")
    assert current.cash[0].amount == Decimal("250.10")
    # Mengen als Zahl im String, nie als float
    assert '"quantity":"12.5"' in current.model_dump_json()


def test_a_conflict_names_the_newest_version(call):
    depot_id = _create(call)
    request = HoldingsSaveRequestV1(user_id=ANNA, depot_id=depot_id, base_version=0)
    call(HOLDINGS_SAVE, request)
    reply = call(HOLDINGS_SAVE, request)
    assert reply.error is not None
    assert (reply.error.code, reply.error.newest) == ("conflict", 1)


def test_invalid_lines(call):
    depot_id = _create(call)
    line = HoldingLineV1(isin=SAP, quantity=Decimal("1"))
    reply = call(
        HOLDINGS_SAVE,
        HoldingsSaveRequestV1(user_id=ANNA, depot_id=depot_id, base_version=0, lines=[line, line]),
    )
    assert reply.error is not None
    assert reply.error.code == "invalid"
    assert "doppelt" in reply.error.message


def test_an_archived_depot_is_read_only(call):
    depot_id = _create(call)
    archived = call(DEPOTS_ARCHIVE, DepotRefRequestV1(user_id=ANNA, depot_id=depot_id)).depot
    assert archived.status == "archived"
    reply = call(DEPOTS_UPDATE, DepotUpdateRequestV1(user_id=ANNA, depot_id=depot_id, name="x"))
    assert reply.error is not None
    assert reply.error.code == "archived"
    assert call(DEPOTS_LIST, DepotListRequestV1(user_id=ANNA, include_archived=True)).depots
    restored = call(DEPOTS_RESTORE, DepotRefRequestV1(user_id=ANNA, depot_id=depot_id)).depot
    assert restored.status == "active"


def test_history(call):
    depot_id = _create(call)
    call(
        HOLDINGS_SAVE,
        HoldingsSaveRequestV1(
            user_id=ANNA,
            depot_id=depot_id,
            base_version=0,
            lines=[HoldingLineV1(isin=SAP, quantity=Decimal("1"))],
        ),
    )
    [entry] = call(HOLDINGS_HISTORY, DepotRefRequestV1(user_id=ANNA, depot_id=depot_id)).entries
    assert (entry.version, entry.added, entry.positions, entry.source) == (1, 1, 1, "manual")


def test_an_unknown_version_is_not_found(call):
    depot_id = _create(call)
    reply = call(HOLDINGS_GET, HoldingsGetRequestV1(user_id=ANNA, depot_id=depot_id, version=3))
    assert reply.error is not None
    assert reply.error.code == "not_found"
