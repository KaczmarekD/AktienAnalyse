"""``entrypoint.sh``: Der Cron-Lauf bekommt jede Einstellung des Batches (P4.7).

Cron startet eine Shell ohne die Umgebung des Containers. Das Skript schreibt deshalb die
Variablen, deren Namen ``ENV_PATTERN`` trifft, in ``/app/.env.cron``. Fehlte dort ein Name, liefe
der Cron-Lauf still mit dem Standardwert; so lief er bis P4.7 immer im Prozess, auch mit
``EVENT_BUS=nats`` in der ``.env``.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.config import Settings

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"
# Liest das Skript selbst, nicht der Lauf
NOT_FOR_CRON = {"CRON_SCHEDULE"}


def _pattern() -> re.Pattern[str]:
    match = re.search(r"^ENV_PATTERN='(.+)'$", ENTRYPOINT.read_text(encoding="utf-8"), re.M)
    assert match, "ENV_PATTERN nicht gefunden"
    return re.compile(match.group(1))


def test_every_setting_reaches_the_cron_run():
    pattern = _pattern()
    names = {name.upper() for name in Settings.model_fields} - NOT_FOR_CRON
    missing = sorted(name for name in names if not pattern.search(name))
    assert missing == []


def test_the_nats_switch_reaches_the_cron_run():
    pattern = _pattern()
    for name in ("EVENT_BUS", "NATS_URL", "RUN_TIMEOUT_MINUTES"):
        assert pattern.search(name), name


def test_nothing_else_slips_through():
    pattern = _pattern()
    for name in ("POSTGRES_PASSWORD", "VA_READ_PASSWORD", "EVENT_BUSX", "PATH", "HOME"):
        assert not pattern.search(name), name
