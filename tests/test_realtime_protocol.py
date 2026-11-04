"""Das WebSocket-Protokoll v1 als JSON-Schema (P4.6): Golden-File statt generierter Typen.

Die TypeScript-Typen im Frontend (``frontend/src/app/shared/realtime/protocol.ts``) sind von Hand
gespiegelt. Aendert sich ein Modell in ``va_web_api.realtime.protocol``, faellt das hier auf; dann
gehoeren Golden-File (``--update-golden``) und ``protocol.ts`` in denselben Commit.
"""

from __future__ import annotations

import json

from pydantic import TypeAdapter

from va_web_api.realtime.protocol import ClientMessage, ServerMessage


def test_protocol_schema_is_unchanged(golden):
    schema = {
        "client": TypeAdapter(ClientMessage).json_schema(by_alias=True),
        "server": TypeAdapter(ServerMessage).json_schema(by_alias=True),
    }
    text = json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    golden("realtime/v1.json", text.encode("utf-8"))
