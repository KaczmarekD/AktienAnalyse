"""Anleihen rechnen (D4.3, ANA-07; docs/architecture/depot/analyse.md, Abschnitt Anleihen).

Nachgerechnet von Hand:
- Auf einem Kupontermin zu 100 ist die Rendite der Kupon, Stückzinsen gibt es keine.
- 5 % Kupon, zwei Jahre, Kurs 98,16661: Rendite 6 %, Macaulay-Duration
  (1 x 4,71698 + 2 x 93,44963) / 98,16661 = 1,95195, modifiziert 1,95195 / 1,06 = 1,84146.
- Bund 2,6 % 15.08.2033 am 20.11.2026: Stückzinsen 2,6 x 97 / 365 = 0,690959 (ACT/ACT ICMA, 97
  Tage seit dem 15.08.2026, die Periode hat 365).
- Nullkupon: Rendite (100 / Kurs) ^ (1 / Jahre) - 1.
"""

from __future__ import annotations

from datetime import date

import pytest

from va_portfolio.domain.bonds import (
    BondTerms,
    accrued_interest,
    bond_figures,
    coupon_dates,
    special_form,
)

BUND = BondTerms(coupon=2.6, maturity=date(2033, 8, 15))
NOV_20 = date(2026, 11, 20)


class TestSchedule:
    def test_coupons_on_the_anniversary_of_the_maturity(self):
        dates = coupon_dates(BUND, after=NOV_20)
        assert dates[0] == date(2027, 8, 15)
        assert dates[-1] == date(2033, 8, 15)
        assert len(dates) == 7

    def test_semiannual(self):
        terms = BondTerms(coupon=4.0, maturity=date(2028, 3, 1), frequency=2)
        assert coupon_dates(terms, after=date(2027, 1, 10)) == [
            date(2027, 3, 1),
            date(2027, 9, 1),
            date(2028, 3, 1),
        ]

    def test_a_short_month_clamps_the_day(self):
        """Tag der Fälligkeit, in kurzen Monaten der letzte; ohne Monatsende-Regel."""
        terms = BondTerms(coupon=3.0, maturity=date(2028, 2, 29), frequency=2)
        assert coupon_dates(terms, after=date(2027, 1, 1))[:2] == [
            date(2027, 2, 28),
            date(2027, 8, 29),
        ]

    def test_a_coupon_on_the_day_goes_to_the_seller(self):
        dates = coupon_dates(BUND, after=date(2027, 8, 15))
        assert dates[0] == date(2028, 8, 15)


class TestAccrued:
    def test_act_act_icma(self):
        assert accrued_interest(BUND, NOV_20) == pytest.approx(2.6 * 97 / 365)

    def test_nothing_on_a_coupon_date(self):
        assert accrued_interest(BUND, date(2026, 8, 15)) == 0

    def test_30e_360(self):
        terms = BondTerms(coupon=6.0, maturity=date(2030, 3, 31), day_count="30E/360")
        # 31.03.2026 bis 20.11.2026: 7 Monate und 20 Tage = 230 Tage nach 30E/360
        assert accrued_interest(terms, NOV_20) == pytest.approx(6.0 * 230 / 360)


class TestYield:
    def test_at_par_on_a_coupon_date_the_yield_is_the_coupon(self):
        figures = bond_figures(BUND, clean_price=100.0, on=date(2026, 8, 15))
        assert figures.ytm == pytest.approx(0.026, abs=1e-9)
        assert figures.accrued == 0

    def test_hand_computed_two_years(self):
        terms = BondTerms(coupon=5.0, maturity=date(2028, 11, 20))
        figures = bond_figures(terms, clean_price=98.16661, on=NOV_20)
        assert figures.ytm == pytest.approx(0.06, abs=1e-6)
        assert figures.macaulay_duration == pytest.approx(1.95195, abs=1e-4)
        assert figures.modified_duration == pytest.approx(1.84146, abs=1e-4)

    def test_zero_coupon(self):
        terms = BondTerms(coupon=0.0, maturity=date(2031, 11, 20))
        figures = bond_figures(terms, clean_price=90.0, on=NOV_20)
        expected = (100 / 90) ** (1 / 5) - 1
        assert figures.ytm == pytest.approx(expected, abs=1e-9)
        assert figures.modified_duration == pytest.approx(5 / (1 + expected), abs=1e-6)

    def test_negative_yield(self):
        figures = bond_figures(BUND, clean_price=125.0, on=date(2026, 8, 15))
        assert figures.ytm is not None
        assert figures.ytm < 0

    def test_between_coupons_the_dirty_price_counts(self):
        """Der Preis aus der Rendite, zurückgerechnet, ergibt wieder den Dirty-Preis."""
        figures = bond_figures(BUND, clean_price=97.5, on=NOV_20)
        assert figures.ytm is not None
        assert figures.dirty_price == pytest.approx(97.5 + 2.6 * 97 / 365)
        v = 268 / 365  # 20.11.2026 bis 15.08.2027
        price = sum(2.6 / (1 + figures.ytm) ** (v + k) for k in range(7)) + 100 / (
            1 + figures.ytm
        ) ** (v + 6)
        assert price == pytest.approx(figures.dirty_price, abs=1e-8)

    def test_next_coupon_and_the_remaining_dates(self):
        figures = bond_figures(BUND, clean_price=97.5, on=NOV_20)
        assert figures.next_coupon == date(2027, 8, 15)
        assert figures.coupon_dates[-1] == date(2033, 8, 15)
        assert figures.years_to_maturity == pytest.approx(
            (date(2033, 8, 15) - NOV_20).days / 365.25
        )

    def test_a_price_outside_the_range_has_no_yield(self):
        figures = bond_figures(BUND, clean_price=20000.0, on=NOV_20)
        assert (figures.ytm, figures.special) == (None, "out_of_range")
        assert figures.accrued == pytest.approx(2.6 * 97 / 365)

    def test_matured_has_no_yield(self):
        figures = bond_figures(BUND, clean_price=100.0, on=date(2033, 8, 15))
        assert (figures.ytm, figures.special) == (None, "matured")


class TestSpecialForms:
    @pytest.mark.parametrize(
        ("terms", "cfi", "form"),
        [
            (BondTerms(coupon=1.0, maturity=date(2030, 1, 1), floating=True), None, "floating"),
            (BondTerms(coupon=1.0, maturity=date(2030, 1, 1)), "DBVTFB", "floating"),
            (BondTerms(coupon=1.0, maturity=date(2030, 1, 1)), "DCFUFB", "convertible"),
            (BondTerms(coupon=4.0, maturity=None), "DBFUPB", "perpetual"),
            (BondTerms(coupon=4.0, maturity=None), None, "perpetual"),
            (BondTerms(coupon=None, maturity=date(2030, 1, 1)), None, "no_terms"),
            (BondTerms(coupon=1.0, maturity=date(2030, 1, 1)), "DBFTFB", None),
        ],
    )
    def test_recognized_from_terms_and_cfi(self, terms, cfi, form):
        assert special_form(terms, cfi) == form

    def test_no_yield_for_special_forms(self):
        terms = BondTerms(coupon=1.0, maturity=date(2030, 1, 1), floating=True)
        figures = bond_figures(terms, clean_price=99.0, on=NOV_20)
        assert (figures.ytm, figures.modified_duration, figures.special) == (None, None, "floating")
        assert figures.accrued is None
