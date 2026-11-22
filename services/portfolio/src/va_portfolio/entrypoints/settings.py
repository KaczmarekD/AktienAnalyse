"""Settings von portfolio (D3.1): bisher nur die gemeinsamen Felder aller Services.

``DATABASE_URL`` verbindet als ``va_portfolio`` (nur das Schema ``portfolio``), ``NATS_URL`` als
NATS-Nutzer ``portfolio``.
"""

from __future__ import annotations

from va_platform.service import ServiceSettings


class PortfolioSettings(ServiceSettings):
    pass
