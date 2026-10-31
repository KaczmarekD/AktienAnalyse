"""OpenAPI des web-api als Golden-File (P3.1).

Der Snapshot ist die Vorlage fuer den generierten Client im Frontend (P3.5) und spaeter die
Referenz fuer ``oasdiff breaking`` (P3.8). Eine gewollte Aenderung an der API schreibt ihn mit
``--update-golden`` neu; der Diff wird im Review begruendet. Auch ein Update von FastAPI oder
Pydantic kann ihn aendern, ohne dass sich die API aendert.
"""

from __future__ import annotations

import json

from pydantic import SecretStr

from va_web_api.main import create_app
from va_web_api.settings import WebApiSettings


def test_openapi_matches_the_snapshot(golden):
    url = SecretStr("postgresql+psycopg://va_read:x@127.0.0.1:1/x")
    app = create_app(WebApiSettings(database_url=url))
    schema = json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    golden("openapi/v1.json", schema.encode("utf-8"))
