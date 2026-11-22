"""Alle Daten einer Person loeschen, auf ihren ausdruecklichen Wunsch (ADR-0012, seit D3.1).

Persoenliche Daten liegen in zwei Schemas: das Konto in ``identity`` (web-api), die Depots in
``portfolio``. Dieses Kommando loescht beides, die Depots zuerst (dafuer braucht es die ID des
Kontos), dann das Konto; ``identity.erasure_log`` haelt die Zeilenzahlen beider fest, ohne Inhalte.
Es braucht die Rolle des Besitzers und laeuft deshalb im Container ``value-analyzer``::

    docker compose run --rm value-analyzer python -m src.erase_user anna --by dennis --yes

Scheitert das Loeschen des Kontos nach dem der Depots, reicht ein zweiter Aufruf: Depots gibt es
dann keine mehr, das Konto ist noch da. Ohne ``--yes`` loescht es nichts. Exit-Code: 0 geloescht,
1 Konto unbekannt, 2 nicht bestaetigt oder nicht eingerichtet.

``python -m va_web_api.admin erase-user`` (D1.6) loescht nur das Konto und laesst die Depots stehen.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from va_platform.db import create_db_engine
from va_portfolio.adapters.postgres.erasure import erase_user as erase_portfolio
from va_web_api.adapters.postgres.identity_erasure import UnknownAccount, erase_user, user_id_of


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.erase_user")
    parser.add_argument("username")
    parser.add_argument("--by", required=True, help="der Admin, der loescht (fuer das Protokoll)")
    parser.add_argument(
        "--yes", action="store_true", help="bestaetigt: unwiderruflich, nur auf Wunsch der Person"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    name = args.username.strip().lower()
    if not args.yes:
        print(
            f"Loescht alle Daten von {name} (Konto und Depots), unwiderruflich (Backups "
            "ausgenommen). Nur auf ausdruecklichen Wunsch der Person; mit --yes bestaetigen.",
            file=sys.stderr,
        )
        return 2
    url = os.environ.get("DATABASE_OWNER_URL")
    if not url:
        print("DATABASE_OWNER_URL muss gesetzt sein (Container value-analyzer)", file=sys.stderr)
        return 2
    engine = create_db_engine(url)
    try:
        user_id = user_id_of(engine, name)
        if user_id is None:
            print(f"Den Benutzer {name} gibt es nicht", file=sys.stderr)
            return 1
        depots = erase_portfolio(engine, user_id)
        report = erase_user(
            engine, name, by=args.by.strip().lower(), at=datetime.now(UTC), extra_rows=depots
        )
    except UnknownAccount:
        print(f"Den Benutzer {name} gibt es nicht", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"Daten von {name} geloescht, Protokoll in identity.erasure_log:")
    for table, count in report.rows.items():
        print(f"  {table}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
