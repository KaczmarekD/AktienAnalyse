"""Die Abdeckung von Hand pflegen (D2.2), bis portfolio sie meldet (D3).

Im Container von market-data (dort steht ``DATABASE_URL`` mit der Rolle des Dienstes)::

    docker compose exec market-data python -m va_market_data.coverage set US0378331005 \\
        IE00B4L5Y983=EUNL.DE
    docker compose exec market-data python -m va_market_data.coverage show

``set`` ersetzt die ganze Menge, ``clear`` leert sie. Jede ISIN wird aufgeloest (ESMA FIRDS, OpenFIGI); ``ISIN=SYMBOL``
waehlt das Listing fuer die Kurse. Ist eine ISIN unbekannt oder ungueltig, aendert sich nichts.
Der naechste Wochenlauf ruft die Aktien darin zusaetzlich ab (``covered[]``).

Exit-Code: 0 gespeichert oder gezeigt, 1 ISIN unbekannt oder ungueltig, 2 nicht eingerichtet.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from va_platform.db import create_db_engine

from .adapters.postgres.store import PostgresSnapshotStore
from .application.securities import ResolvedSecurity
from .domain.coverage import CoverageItem, coverage_symbols
from .entrypoints.service import securities

SOURCE = "command"

type Resolve = Callable[[str, str | None], ResolvedSecurity | None]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m va_market_data.coverage")
    commands = parser.add_subparsers(dest="command", required=True)
    replace = commands.add_parser("set", help="Abdeckung ersetzen")
    replace.add_argument("entries", nargs="+", metavar="ISIN[=SYMBOL]")
    commands.add_parser("show", help="Abdeckung zeigen")
    # Leeren nur ausdruecklich: Ein vergessenes Argument bei set soll nichts entfernen
    commands.add_parser("clear", help="Abdeckung leeren")
    return parser


def _item(resolved: ResolvedSecurity, symbol: str | None) -> CoverageItem:
    master = resolved.master
    fundamentals, price = coverage_symbols(master.isin, master.asset_class, resolved.listings)
    return CoverageItem(
        isin=master.isin,
        asset_class=master.asset_class,
        fundamentals_symbol=fundamentals,
        price_symbol=symbol or price,
        name=master.name,
    )


def _resolve_all(entries: Sequence[str], resolve: Resolve) -> list[CoverageItem] | None:
    items: list[CoverageItem] = []
    for entry in entries:
        isin, _, symbol = entry.partition("=")
        isin = isin.strip().upper()
        try:
            resolved = resolve(isin, symbol.strip() or None)
        except ValueError as e:
            print(f"{isin}: {e}", file=sys.stderr)
            return None
        if resolved is None:
            print(f"{isin}: unbekannt (weder ESMA FIRDS noch OpenFIGI kennen sie)", file=sys.stderr)
            return None
        items.append(_item(resolved, symbol.strip() or None))
    return items


def _show(items: Sequence[CoverageItem]) -> None:
    if not items:
        print("Abdeckung ist leer")
    for item in items:
        print(
            f"{item.isin}  {item.asset_class:<6}  Kennzahlen {item.fundamentals_symbol or '-':<10}"
            f"  Kurs {item.price_symbol or '-':<10}  {item.name or ''}"
        )


def main(argv: Sequence[str] | None = None, *, resolve: Resolve | None = None) -> int:
    args = _parser().parse_args(argv)
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL muss gesetzt sein (Container market-data)", file=sys.stderr)
        return 2
    engine = create_db_engine(url)
    try:
        store = PostgresSnapshotStore(engine, provider="command", provider_version=None)
        if args.command == "show":
            _show(store.coverage())
            return 0
        if args.command == "clear":
            items: list[CoverageItem] | None = []
        else:
            items = _resolve_all(args.entries, resolve or securities(engine).resolve)
        if items is None:
            return 1
        changed = store.write_coverage(items, source=SOURCE, at=datetime.now(UTC))
        print("Neue Fassung der Abdeckung:" if changed else "Abdeckung unveraendert:")
        _show(store.coverage())
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
