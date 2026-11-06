"""Verwaltung der Konten auf der Kommandozeile (D1.1, NUT-04).

Den ersten Admin legt dieses Kommando an, im Container des web-api::

    docker compose exec web-api python -m va_web_api.admin create-user dennis --admin

Es gibt kein Standardpasswort und keinen Admin aus einer ENV-Variable. Ohne ``--password-stdin``
fragt das Kommando das Passwort zweimal ab (``getpass``, ohne Echo). Es braucht
``WEB_API_IDENTITY_DATABASE_URL`` (Rolle ``va_identity``).

Exit-Code: 0 angelegt, 1 abgelehnt (Name, Passwort, Rolle, Mail, schon vorhanden), 2 nicht
eingerichtet.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Sequence
from typing import TextIO

from pydantic import ValidationError

from va_platform.db import create_db_engine

from .adapters.postgres.identity_store import PostgresIdentityStore
from .identity.ports import UserExists
from .identity.service import IdentityService, WeakPassword
from .settings import WebApiSettings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m va_web_api.admin")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="Konto anlegen")
    create.add_argument("username")
    create.add_argument("--admin", action="store_true", help="Rolle admin statt user")
    create.add_argument("--email")
    create.add_argument("--display-name")
    create.add_argument(
        "--password-stdin", action="store_true", help="Passwort als erste Zeile von stdin"
    )
    return parser


def _password(from_stdin: bool, stdin: TextIO) -> str | None:
    if from_stdin:
        return stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Passwort: ")
    if first != getpass.getpass("Passwort wiederholen: "):
        return None
    return first


def _identity_url() -> str | None:
    try:
        settings = WebApiSettings()  # type: ignore[call-arg]
    except ValidationError:
        return None
    url = settings.identity_database_url
    return None if url is None else url.get_secret_value()


def main(argv: Sequence[str] | None = None, *, stdin: TextIO = sys.stdin) -> int:
    args = _parser().parse_args(argv)
    url = _identity_url()
    if url is None:
        print(
            "WEB_API_IDENTITY_DATABASE_URL (und WEB_API_DATABASE_URL) muessen gesetzt sein",
            file=sys.stderr,
        )
        return 2
    password = _password(args.password_stdin, stdin)
    if password is None:
        print("Die Passwoerter stimmen nicht ueberein", file=sys.stderr)
        return 1
    engine = create_db_engine(url)
    try:
        service = IdentityService(PostgresIdentityStore(engine))
        user = service.create_user(
            args.username,
            password,
            role="admin" if args.admin else "user",
            display_name=args.display_name,
            email=args.email,
        )
    except WeakPassword as e:
        print("Passwort abgelehnt: " + "; ".join(e.problems), file=sys.stderr)
        return 1
    except UserExists:
        print(f"Den Benutzer {args.username.strip().lower()} gibt es schon", file=sys.stderr)
        return 1
    except ValueError as e:  # auch InvalidUsername: ungueltiger Name, Rolle oder Mail
        print(str(e), file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"Benutzer {user.username} angelegt (Rolle {user.role})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
