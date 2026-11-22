"""Service portfolio (D3, ADR-0013): Depots und Depotstaende eines Nutzers.

Persoenliche Daten liegen nur hier (Schema ``portfolio``, Rolle ``va_portfolio``). Das web-api
liest und aendert Depots per Request/Reply (``rpc.va.portfolio.*``); Events in ``VA_EVENTS``
nennen nur IDs und Versionen.
"""
