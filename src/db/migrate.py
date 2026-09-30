"""Schema-Migrationen (Alembic) - laeuft beim Container-Start vor cron.

    python -m src.db.migrate

Nutzt ``DATABASE_OWNER_URL`` (Fallback ``DATABASE_URL``). Migrationen sind
ausschliesslich additiv: keine Tabelle und keine Spalte mit Daten wird entfernt.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import DatabaseSettings
from .engine import normalize_url

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
