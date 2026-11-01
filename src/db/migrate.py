"""Schema-Migrationen (Alembic) - laeuft beim Container-Start vor cron.

    python -m src.db.migrate

Nutzt ``DATABASE_OWNER_URL`` (Fallback ``DATABASE_URL``). Migrationen sind
ausschliesslich additiv: keine Tabelle und keine Spalte mit Daten wird entfernt.

Danach die Login-Rolle ``va_profiles`` (P3.3), wenn ``VA_PROFILES_PASSWORD`` gesetzt ist: Das
Init-Skript ``db/init/01_roles.sh`` laeuft nur in einer leeren Datenbank, eine bestehende
bekommt die Rolle hier. Ihr Passwort folgt der ``.env``.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import create_engine, text
from tenacity import retry, stop_after_attempt, wait_exponential

from va_platform.db import normalize_url
from va_platform.db.ddl import PROFILES_ROLE, profiles_grant_statements

from ..config import DatabaseSettings

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
    if settings.va_profiles_password is not None:
        try:
            ensure_profiles_role(
                secret.get_secret_value(), settings.va_profiles_password.get_secret_value()
            )
        except Exception:
            # Der Batch braucht die Rolle nicht; nur das Speichern im UI faellt dann aus
            log.warning("Rolle %s nicht eingerichtet", PROFILES_ROLE, exc_info=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
