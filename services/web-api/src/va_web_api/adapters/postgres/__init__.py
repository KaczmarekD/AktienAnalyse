"""Schema ``web``: Projektionen des web-api und seine Inbox/Outbox (P4.4)."""

from .models import RUN_STATES, RankingRow, RunStatus, WebInbox, WebOutbox

__all__ = ["RUN_STATES", "RankingRow", "RunStatus", "WebInbox", "WebOutbox"]
