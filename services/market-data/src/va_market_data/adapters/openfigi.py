"""OpenFIGI: ISIN -> Yahoo-Symbol ueber das Xetra-Listing (fuer Neuaufnahmen ohne CSV-Eintrag).

Ohne API-Key, hoechstens 10 ISINs je Anfrage.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from ..domain.universe import YAHOO_SUFFIX

log = logging.getLogger(__name__)

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_EXCHANGE = "GY"  # Xetra
OPENFIGI_BATCH = 10  # Limit ohne API-Key


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=20))
def openfigi_post(jobs: list[dict[str, str]], timeout: float = 30.0) -> Any:
    response = requests.post(OPENFIGI_URL, json=jobs, timeout=timeout)
    response.raise_for_status()
    return response.json()


def resolve_isins_openfigi(isins: Iterable[str], timeout: float = 30.0) -> dict[str, str]:
    """ISIN -> Yahoo-Symbol. Fehler ergeben Luecken, keine Exception."""
    isins = list(isins)
    result: dict[str, str] = {}
    for start in range(0, len(isins), OPENFIGI_BATCH):
        batch = isins[start : start + OPENFIGI_BATCH]
        jobs = [{"idType": "ID_ISIN", "idValue": i, "exchCode": OPENFIGI_EXCHANGE} for i in batch]
        try:
            answers = openfigi_post(jobs, timeout)
        except Exception as e:
            log.warning("OpenFIGI nicht erreichbar: %s", e)
            continue
        if not isinstance(answers, list):
            log.warning("OpenFIGI: unerwartete Antwort %r", answers)
            continue
        for isin, answer in zip(batch, answers, strict=False):
            ticker = _figi_ticker(answer)
            if ticker:
                result[isin] = f"{ticker}{YAHOO_SUFFIX}"
    return result


def _figi_ticker(answer: Any) -> str | None:
    data = answer.get("data") if isinstance(answer, dict) else None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    ticker = data[0].get("ticker")
    return ticker if isinstance(ticker, str) and ticker else None
