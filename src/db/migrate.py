"""Schema-Migrationen (Alembic) - laeuft beim Container-Start vor cron.

    python -m src.db.migrate

Nutzt ``DATABASE_OWNER_URL`` (Fallback ``DATABASE_URL``). Migrationen sind
ausschliesslich additiv: keine Tabelle und keine Spalte mit Daten wird entfernt.

Danach die Login-Rollen des web-api, wenn ihr Passwort gesetzt ist: ``va_profiles`` (P3.3,
``VA_PROFILES_PASSWORD``) und ``va_web`` (P4.4, ``VA_WEB_PASSWORD``). Das Init-Skript
``db/init/01_roles.sh`` laeuft nur in einer leeren Datenbank, eine bestehende bekommt die Rollen
hier. Ihr Passwort folgt der ``.env``.
"""

from __future__ import annotations

import logging
import sys
from functools import partial
from pathlib import Path

from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, text
from tenacity import retry, stop_after_attempt, wait_exponential

from va_platform.db import normalize_url
from va_platform.db.ddl import (
    PROFILES_ROLE,
    SERVICE_ROLES,
    WEB_ROLE,
    profiles_grant_statements,
    service_grant_statements,
    web_grant_statements,
    web_run_grant_statements,
)

from ..config import DatabaseSettings
from .backfill import backfill_projections

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def alembic_config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # Ueber attributes statt sqlalchemy.url: ConfigParser wuerde '%' im Passwort interpretieren
    cfg.attributes["url"] = normalize_url(url)
    return cfg


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(alembic_config(url), revision)


@retry(
    stop=stop_after_attempt(10), wait=wait_exponential(multiplier=1, min=2, max=20), reraise=True
)
def _upgrade_with_retry(url: str) -> None:
    # Direkt nach 'docker compose up' kann Postgres noch starten
    upgrade(url)


def ensure_login_role(url: str, role: str, password: str) -> None:
    """Legt die Login-Rolle an oder setzt ihr Passwort neu (idempotent).

    Name und Passwort gehen gequotet ueber psycopg in das SQL, nie per String-Verkettung.
    """
    engine = create_engine(normalize_url(url))
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
            ).scalar()
            verb = "ALTER" if exists else "CREATE"
            raw = conn.connection.dbapi_connection
            assert raw is not None
            cursor = raw.cursor()
            try:
                cursor.execute(
                    sql.SQL(verb + " ROLE {} WITH LOGIN PASSWORD {}").format(
                        sql.Identifier(role), sql.Literal(password)
                    )
                )
            finally:
                cursor.close()
    finally:
        engine.dispose()


def ensure_profiles_role(url: str, password: str) -> None:
    """Die Rolle der Profil-Befehle samt Rechten, auch in einer Datenbank von vor P3.3."""
    ensure_login_role(url, PROFILES_ROLE, password)
    engine = create_engine(normalize_url(url))
    try:
        with engine.begin() as conn:
            conn.execute(text(profiles_grant_statements()))
    finally:
        engine.dispose()


def ensure_web_role(url: str, password: str) -> None:
    """Die Rolle der Projektionen (P4.4) samt Rechten im Schema ``web`` und auf ``batch.run``."""
    ensure_login_role(url, WEB_ROLE, password)
    engine = create_engine(normalize_url(url))
    try:
        with engine.begin() as conn:
            conn.execute(text(web_grant_statements()))
            conn.execute(text(web_run_grant_statements()))  # P4.7: Runs in batch.run
    finally:
        engine.dispose()


def ensure_service_role(url: str, password: str, *, role: str) -> None:
    """Eine Service-Rolle (P5.3) samt Rechten im eigenen Schema."""
    ensure_login_role(url, role, password)
    engine = create_engine(normalize_url(url))
    try:
        with engine.begin() as conn:
            conn.execute(text(service_grant_statements(role)))
    finally:
        engine.dispose()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
    settings = DatabaseSettings()
    secret = settings.database_owner_url or settings.database_url
    if secret is None:
        log.error("Keine Datenbank-URL: DATABASE_OWNER_URL oder DATABASE_URL setzen")
        return 1
    try:
        _upgrade_with_retry(secret.get_secret_value())
    except Exception:
        log.exception("Migration fehlgeschlagen")
        return 1
    log.info("Datenbankschema ist aktuell")
    roles = (
        (PROFILES_ROLE, settings.va_profiles_password, ensure_profiles_role),
        (WEB_ROLE, settings.va_web_password, ensure_web_role),
        # P5.3: eine Rolle je Service
        *(
            (role, getattr(settings, f"{role}_password"), partial(ensure_service_role, role=role))
            for role in SERVICE_ROLES
        ),
    )
    for role, password, ensure in roles:
        if password is None:
            continue
        try:
            ensure(secret.get_secret_value(), password.get_secret_value())
        except Exception:
            # Der Batch braucht die Rollen nicht; nur Teile des web-api fallen dann aus
            log.warning("Rolle %s nicht eingerichtet", role, exc_info=True)
    _backfill(secret.get_secret_value())
    return 0


def _backfill(url: str) -> None:
    """P4.9: Projektionen aus den Tabellen nachfuellen. Scheitert es, laeuft der Batch trotzdem;
    nur die REST-Antworten aus den Projektionen fehlen dann (naechster Start versucht es erneut)."""
    engine = create_engine(normalize_url(url))
    try:
        backfill_projections(engine)
    except Exception:
        log.warning("Projektionen nicht nachgefuellt", exc_info=True)
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
