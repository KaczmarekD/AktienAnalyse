"""Abgleich, Uebernahme und Export einer Datei ueber Request/Reply (D3.5, DEP-05).

- Der Abgleich speichert nichts und nennt neu, geaendert, gleich, entfaellt, nicht erkannt und
  "wird geprueft" (ohne Stammdaten).
- Uebernommen wird nur eine Datei ohne abgelehnte Zeilen, auf die aktuelle Version, als
  Depotstand mit Herkunft ``import`` und dem SHA-256 der Datei; die Kasse bleibt.
- Fehlt die Einheit: die bisherige der ISIN, sonst ``nominal`` fuer Anleihen, sonst Stueck.
- Der Export ist dasselbe Format; der Dateiname enthaelt nur Zahlen.
- Fremde Depots: ``not_found``; archiviert: ``archived``; kaputte Datei: ``invalid``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from va_contracts.rpc.v1 import (
    HOLDINGS_FILE,
    HOLDINGS_GET,
    HOLDINGS_IMPORT,
    HOLDINGS_IMPORT_PREVIEW,
    HoldingsFileRequestV1,
    HoldingsGetRequestV1,
    HoldingsImportRequestV1,
)
from va_portfolio.adapters.memory import MemoryDepotStore, MemoryMarketStore
from va_portfolio.application.depots import DepotService
from va_portfolio.application.market import SecurityCopy
from va_portfolio.domain.depots import CashLine, HoldingLine
from va_portfolio.domain.valuation import SecurityInfo
from va_portfolio.entrypoints.rpc import handlers

ANNA, BEN = 1, 2
SAP = "DE0007164600"
APPLE = "US0378331005"
BUND = "DE0001102580"
T0 = datetime(2026, 11, 22, 10, 0, tzinfo=UTC)


@pytest.fixture
def market() -> MemoryMarketStore:
    market = MemoryMarketStore()
    market.record_securities(
        [
            SecurityCopy(SecurityInfo(SAP, "SAP SE", "equity", "EUR"), {}),
            SecurityCopy(SecurityInfo(BUND, "Bund 2033", "bond", "EUR"), {}),
        ],
        as_of=date(2026, 11, 21),
        at=T0,
    )
    return market


@pytest.fixture
def service(market) -> DepotService:
    return DepotService(MemoryDepotStore(), market=market, clock=lambda: T0)


@pytest.fixture
def rpc(service) -> dict[Any, Any]:
    return handlers(service)


def _depot(service: DepotService) -> int:
    depot = service.create(ANNA, "depot", "DKB", None).depot
    service.save(
        ANNA,
        depot.id,
        0,
        [HoldingLine(SAP, Decimal(10)), HoldingLine(APPLE, Decimal(3))],
        [CashLine(Decimal(100))],
    )
    return depot.id


def _isin(n: int) -> str:
    from va_contracts.securities import valid_isin

    body = f"DE000{n:06d}"
    return next(body + d for d in "0123456789" if valid_isin(body + d))


def _file(*rows: str) -> bytes:
    return ("isin;menge;einstand;notiz\n" + "".join(f"{r}\n" for r in rows)).encode()


def _preview(rpc, depot_id: int, content: bytes, user: int = ANNA):
    return rpc[HOLDINGS_IMPORT_PREVIEW](
        HoldingsFileRequestV1(user_id=user, depot_id=depot_id, content=content)
    )


def _import(rpc, depot_id: int, content: bytes, base: int = 1, user: int = ANNA):
    return rpc[HOLDINGS_IMPORT](
        HoldingsImportRequestV1(user_id=user, depot_id=depot_id, base_version=base, content=content)
    )


class TestPreview:
    def test_new_changed_unchanged_removed_rejected(self, service, rpc):
        depot_id = _depot(service)
        content = _file(f"{SAP};10", f"{BUND};5000", "XX123;1", "IE00B4L5Y983;2")
        preview = _preview(rpc, depot_id, content).preview
        assert preview.base_version == 1
        assert [(e.isin, e.status, e.pending) for e in preview.entries] == [
            (SAP, "unchanged", False),
            (BUND, "new", False),
            ("IE00B4L5Y983", "new", True),  # ohne Stammdaten: wird geprueft
            (APPLE, "removed", False),
        ]
        assert preview.entries[1].after.unit == "nominal"  # Anleihe laut Stammdaten
        [rejected] = preview.rejected
        assert rejected.line == 4
        assert service.holdings(ANNA, depot_id).version == 1  # nichts gespeichert

    def test_the_unit_stays_as_it_was(self, service, rpc):
        depot = service.create(ANNA, "depot", "DKB", None).depot
        other = "DE000A383J95"  # eine Anleihe ohne Stammdaten
        service.save(ANNA, depot.id, 0, [HoldingLine(other, Decimal(1000), "nominal")], [])
        entry = _preview(rpc, depot.id, _file(f"{other};2000")).preview.entries[0]
        assert (entry.status, entry.after.unit) == ("changed", "nominal")

    def test_the_largest_preview_fits_through_nats(self, service, rpc):
        """1000 Positionen, alle geaendert, Notizen mit 500 Zeichen vorher und nachher."""
        depot = service.create(ANNA, "depot", "DKB", None).depot
        isins = [_isin(n) for n in range(1000)]
        before = [HoldingLine(i, Decimal(1), note="v" * 500) for i in isins]
        service.save(ANNA, depot.id, 0, before, [])
        content = "".join(f"{i};2;123456,78;{'n' * 500}\n" for i in isins).encode()
        reply = _preview(rpc, depot.id, content)
        assert len(reply.preview.entries) == 1000
        assert len(reply.model_dump_json()) < 900_000  # NATS: max_payload 1 MB
        assert reply.preview.entries[0].after.note.endswith("\u2026")

    def test_a_broken_file_is_invalid(self, service, rpc):
        depot_id = _depot(service)
        reply = _preview(rpc, depot_id, b"\x81\x8d\x8f;1\n")
        assert (reply.preview, reply.error.code) == (None, "invalid")

    def test_foreign_depot_is_not_found(self, service, rpc):
        depot_id = _depot(service)
        assert _preview(rpc, depot_id, _file(f"{SAP};1"), user=BEN).error.code == "not_found"


class TestImport:
    def test_a_new_snapshot_with_source_and_hash(self, service, rpc):
        depot_id = _depot(service)
        content = _file(f"{SAP};12,5;2000;Nachkauf")
        holdings = _import(rpc, depot_id, content).holdings
        assert (holdings.version, holdings.source) == (2, "import")
        [line] = holdings.lines
        assert (line.isin, line.quantity, line.cost_basis_eur, line.note) == (
            SAP,
            Decimal("12.5"),
            Decimal(2000),
            "Nachkauf",
        )
        assert [c.amount for c in holdings.cash] == [Decimal(100)]  # Kasse bleibt
        snapshot = service.holdings(ANNA, depot_id)
        assert snapshot.source_ref == hashlib.sha256(content).hexdigest()

    def test_rejected_rows_refuse_the_import(self, service, rpc):
        depot_id = _depot(service)
        reply = _import(rpc, depot_id, _file(f"{SAP};10", f"{APPLE};zehn"))
        assert reply.error.code == "invalid"
        assert "Zeile 3" in reply.error.message
        assert service.holdings(ANNA, depot_id).version == 1

    def test_an_old_base_is_a_conflict(self, service, rpc):
        depot_id = _depot(service)
        reply = _import(rpc, depot_id, _file(f"{SAP};1"), base=0)
        assert (reply.error.code, reply.error.newest) == ("conflict", 1)

    def test_archived_depot(self, service, rpc):
        depot_id = _depot(service)
        service.archive(ANNA, depot_id)
        assert _import(rpc, depot_id, _file(f"{SAP};1")).error.code == "archived"


class TestExport:
    def test_same_format_with_a_safe_name(self, service, rpc):
        depot_id = _depot(service)
        service.update(ANNA, depot_id, 'Depot "a"/../b', None)
        reply = rpc[HOLDINGS_FILE](HoldingsGetRequestV1(user_id=ANNA, depot_id=depot_id))
        assert reply.filename == f"depot-{depot_id}-v1.csv"
        assert reply.content.decode("utf-8-sig").splitlines()[1] == f"{SAP};10;;;stueck"

    def test_round_trip_changes_nothing(self, service, rpc):
        depot_id = _depot(service)
        content = rpc[HOLDINGS_FILE](HoldingsGetRequestV1(user_id=ANNA, depot_id=depot_id)).content
        preview = _preview(rpc, depot_id, content).preview
        assert {e.status for e in preview.entries} == {"unchanged"}

    def test_in_json_as_base64(self, service, rpc):
        depot_id = _depot(service)
        reply = rpc[HOLDINGS_FILE](HoldingsGetRequestV1(user_id=ANNA, depot_id=depot_id))
        assert isinstance(json.loads(reply.model_dump_json())["content"], str)

    def test_an_old_version(self, service, rpc):
        depot_id = _depot(service)
        _import(rpc, depot_id, _file(f"{SAP};1"))
        request = HoldingsGetRequestV1(user_id=ANNA, depot_id=depot_id, version=1)
        assert rpc[HOLDINGS_FILE](request).filename == f"depot-{depot_id}-v1.csv"
        assert rpc[HOLDINGS_GET](request).holdings.version == 1
