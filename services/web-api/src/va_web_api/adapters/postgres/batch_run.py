"""``batch.run`` aus Sicht des web-api (P4.7): die Spalten, die es anlegt, liest und abschliesst.

Das ORM-Modell gehoert der Ablaufsteuerung (``src/db/models/batch.py``), und das web-api darf
``src`` nicht importieren. Deshalb hier nur eine schlanke Tabellenbeschreibung ohne Metadaten,
Alembic sieht sie nicht. In Phase 5 gehoert das Schema ``batch`` dem web-api
(docs/architecture/datenhaltung.md).
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, DateTime, Text, column, table

BATCH_RUN = table(
    "run",
    column("id", BigInteger),
    column("kind", Text),
    column("status", Text),
    column("started_at", DateTime(timezone=True)),
    column("finished_at", DateTime(timezone=True)),
    column("app_version", Text),
    column("dry_run", Boolean),
    column("force_refresh", Boolean),
    column("fetch_run_id", BigInteger),
    column("scoring_run_id", BigInteger),
    column("report_id", BigInteger),
    column("universe_size", BigInteger),
    column("scored_count", BigInteger),
    column("failed_count", BigInteger),
    column("exit_code", BigInteger),
    column("error", Text),
    schema="batch",
)
