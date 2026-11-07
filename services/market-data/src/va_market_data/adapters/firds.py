"""ESMA FIRDS: Stammdaten je ISIN (D2.1, Port ``MasterSource``).

Die Suche des Registers (Solr) ist nicht als API dokumentiert, aber ohne Schluessel abrufbar und
am 06./07.11.2026 live geprueft. Je Handelsplatz gibt es einen Datensatz; massgeblich ist der mit
``latest_received_flag = 1``. Dokumentierter Rueckfallweg waeren die FIRDS-Dateien.

Die Feldnamen stehen nur in ``FIELDS``. Benennt ESMA um, ist das die einzige Stelle.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests

from ..domain.securities import BondTerms, SecurityMaster, asset_class_from_cfi, floating_rate
from .http import USER_AGENT

log = logging.getLogger(__name__)

FIRDS_URL = "https://registers.esma.europa.eu/solr/esma_registers_firds/select"
FIELDS = {
    "isin": "isin",
    "name": "gnr_full_name",
    "cfi": "gnr_cfi_code",
    "currency": "gnr_notional_curr_code",
    "lei": "lei",
    "coupon": "bnd_fixed_rate",
    "maturity": "bnd_maturity_date",
    "denomination": "bnd_nmnl_value_unit",
    "seniority": "bnd_seniority",
    "latest": "latest_received_flag",
}


def _text(doc: dict[str, Any], key: str) -> str | None:
    value = doc.get(FIELDS[key])
    if isinstance(value, list):  # Solr liefert manche Felder als Liste
        value = value[0] if value else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(doc: dict[str, Any], key: str) -> float | None:
    text = _text(doc, key)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _date(doc: dict[str, Any], key: str) -> date | None:
    text = _text(doc, key)
    if text is None:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def master_from_firds(doc: dict[str, Any]) -> SecurityMaster:
    """Ein Datensatz des Registers -> Stammdaten. Fehlende Felder bleiben leer."""
    isin = _text(doc, "isin") or ""
    cfi = _text(doc, "cfi")
    asset_class = asset_class_from_cfi(cfi) or "other"
    bond = None
    if asset_class == "bond":
        bond = BondTerms(
            coupon=_number(doc, "coupon"),
            maturity=_date(doc, "maturity"),
            denomination=_number(doc, "denomination"),
            seniority=_text(doc, "seniority"),
            floating=floating_rate(cfi),
        )
    return SecurityMaster(
        isin=isin,
        name=_text(doc, "name") or isin,
        asset_class=asset_class,
        currency=_text(doc, "currency"),
        lei=_text(doc, "lei"),
        cfi=cfi,
        bond=bond,
    )


class FirdsSource:
    """``MasterSource`` ueber die Suche des Registers. Wirft bei Ausfall (der Anwendungsfall
    faellt dann auf OpenFIGI zurueck). Ein Versuch mit kurzem Timeout, wie ``OpenFigiLookup``."""

    def __init__(self, *, timeout: float = 8.0) -> None:
        self._timeout = timeout

    def master(self, isin: str) -> SecurityMaster | None:
        params = {
            "q": f"{FIELDS['isin']}:{isin} AND {FIELDS['latest']}:1",
            "rows": "1",
            "wt": "json",
        }
        response = requests.get(
            FIRDS_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=self._timeout
        )
        response.raise_for_status()
        answer = response.json()
        docs = answer.get("response", {}).get("docs", []) if isinstance(answer, dict) else []
        if not docs or not isinstance(docs[0], dict):
            return None
        return master_from_firds(docs[0])
