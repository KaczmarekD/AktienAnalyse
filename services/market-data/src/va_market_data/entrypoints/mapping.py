"""Wertpapiere als Contracts (D2.1, D2.4): fuer Request/Reply und ``marketdata.securities.updated``.

Ein ETF nennt seine Fondsdaten, Gewichte und die groessten Positionen, nicht die ganze Liste:
Die steht in ``market_data.etf_composition`` (ein Anleihe-ETF hat ueber 4.000 Positionen).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from va_contracts.securities import BondTermsV1, EtfHoldingV1, EtfV1, ListingV1, SecurityV1

if TYPE_CHECKING:
    from ..application.securities import ResolvedSecurity
    from ..domain.etf import EtfComposition, Holding
    from ..domain.securities import Listing


def listing_v1(listing: Listing) -> ListingV1:
    return ListingV1(
        symbol=listing.symbol,
        ticker=listing.ticker,
        exchange=listing.exchange,
        currency=listing.currency,
    )


def _holding_v1(holding: Holding) -> EtfHoldingV1:
    return EtfHoldingV1(
        name=holding.name,
        weight=holding.weight,
        isin=holding.isin,
        ticker=holding.ticker,
        asset_class=holding.asset_class,
        sector=holding.sector,
        country=holding.country,
        currency=holding.currency,
    )


def etf_v1(composition: EtfComposition) -> EtfV1:
    facts = composition.facts
    return EtfV1(
        source=composition.source,
        as_of=composition.as_of,
        complete=composition.complete,
        name=facts.name,
        ter=facts.ter,
        fund_size=facts.fund_size,
        fund_currency=facts.currency,
        distribution=facts.distribution,
        provider=facts.provider,
        effective_duration=facts.effective_duration,
        holdings_count=composition.holdings_count,
        top_holdings=[_holding_v1(h) for h in composition.top()],
        sectors=dict(composition.sectors),
        countries=dict(composition.countries),
        asset_classes=dict(composition.asset_classes),
    )


def security_v1(resolved: ResolvedSecurity) -> SecurityV1:
    master = resolved.master
    bond = master.bond
    return SecurityV1(
        isin=master.isin,
        name=master.name,
        asset_class=master.asset_class,
        currency=master.currency,
        lei=master.lei,
        cfi=master.cfi,
        bond=None
        if bond is None
        else BondTermsV1(
            coupon=bond.coupon,
            maturity=bond.maturity,
            denomination=bond.denomination,
            seniority=bond.seniority,
            floating=bond.floating,
        ),
        listings=[listing_v1(listing) for listing in resolved.listings],
        listing=None if resolved.listing is None else listing_v1(resolved.listing),
        etf=None if resolved.etf is None else etf_v1(resolved.etf),
    )
