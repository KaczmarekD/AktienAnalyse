// Antworten des web-api für die Tests der Depot-Seiten (D3.6).
import type {
  Depot,
  DepotAnalysis,
  DepotValuation,
  Holdings,
  PositionScore,
  PositionValue,
} from '../api/types.gen';

export const SAP = 'DE0007164600';
export const APPLE = 'US0378331005';
export const BUND = 'DE0001102580';
export const WORLD = 'IE00B4L5Y983';
export const FLOATER = 'XS2000000009';

export function valuation(values: Partial<DepotValuation> = {}): DepotValuation {
  return {
    value_eur: '12459.10',
    positions_eur: '12209.00',
    cash_eur: '250.10',
    complete: true,
    unvalued: 0,
    pending: 0,
    cost_basis_eur: null,
    difference_eur: null,
    price_date: '2026-11-20',
    positions: [],
    ...values,
  };
}

export function depot(values: Partial<Depot> & Pick<Depot, 'id' | 'name'>): Depot {
  return {
    kind: 'depot',
    description: null,
    status: 'active',
    created_at: '2026-11-22T10:00:00Z',
    version: 2,
    positions: 2,
    valuation: valuation(),
    ...values,
  };
}

export function position(
  values: Partial<PositionValue> & Pick<PositionValue, 'isin'>,
): PositionValue {
  return {
    name: null,
    asset_class: null,
    pending: false,
    quantity: '10',
    unit: 'pieces',
    price: null,
    price_currency: null,
    price_date: null,
    price_source: null,
    percent_of_par: false,
    fx_rate: null,
    value_eur: null,
    cost_basis_eur: null,
    difference_eur: null,
    missing: null,
    score: null,
    ...values,
  };
}

/** Scores einer Aktie aus einem Bewertungslauf (D4.2), Standard: Titel des Rankings. */
export function score(values: Partial<PositionScore> = {}): PositionScore {
  return {
    scoring_run_id: 8,
    as_of: '2026-11-20',
    symbol: 'SAP.DE',
    reference: 'universe',
    rank: 12,
    value_score: 0.41,
    quality_score: 0.83,
    composite_score: 0.578,
    composite_percentile: 0.71,
    value_trap_flag: false,
    value_trap_reason: null,
    industry_rule: false,
    reason: null,
    ...values,
  };
}

/** Ein Depot mit SAP (bewertet), Apple (ohne Kurs) und Kasse. */
export const DETAIL = depot({
  id: 3,
  name: 'DKB',
  description: 'Altersvorsorge',
  version: 2,
  positions: 2,
  valuation: valuation({
    value_eur: '2565.10',
    positions_eur: '2315.00',
    cash_eur: '250.10',
    complete: false,
    unvalued: 1,
    pending: 1,
    cost_basis_eur: '2000.00',
    difference_eur: '315.00',
    price_date: '2026-11-20',
    positions: [
      position({
        isin: SAP,
        name: 'SAP SE',
        asset_class: 'equity',
        quantity: '10',
        price: '231.5',
        price_currency: 'EUR',
        price_date: '2026-11-20',
        price_source: 'yahoo',
        fx_rate: '1',
        value_eur: '2315.00',
        cost_basis_eur: '2000',
        difference_eur: '315.00',
        score: score(),
      }),
      position({
        isin: APPLE,
        quantity: '3',
        pending: true,
        missing: 'price',
        score: score({
          symbol: 'AAPL',
          reference: 'outside',
          rank: null,
          value_score: 0.12,
          quality_score: 0.97,
          composite_score: 0.46,
          composite_percentile: 0.38,
          value_trap_flag: true,
          value_trap_reason: 'momentum',
        }),
      }),
    ],
  }),
});

export const HOLDINGS: Holdings = {
  depot_id: 3,
  version: 2,
  source: 'manual',
  created_at: '2026-11-22T10:00:00Z',
  created_by: 1,
  lines: [
    { isin: SAP, quantity: '10.00000000', unit: 'pieces', cost_basis_eur: '2000', note: 'Kauf' },
    { isin: APPLE, quantity: '3', unit: 'pieces', cost_basis_eur: null, note: null },
  ],
  cash: [{ currency: 'EUR', amount: '250.10' }],
};

/** Analyse eines Depots (D4.4/D4.5): SAP, ein Welt-ETF mit Durchschau und eine Bundesanleihe. */
export function analysis(values: Partial<DepotAnalysis> = {}): DepotAnalysis {
  return {
    value_eur: '7000.00',
    allocation: {
      asset_class: [
        { key: 'equity', value_eur: '3350.00', weight: 0.478571 },
        { key: 'etf', value_eur: '2000.00', weight: 0.285714 },
        { key: 'bond', value_eur: '975.00', weight: 0.139286 },
        { key: 'cash', value_eur: '675.00', weight: 0.096429 },
      ],
      currency: [
        { key: 'EUR', value_eur: '3650.00', weight: 0.521429 },
        { key: 'USD', value_eur: '3350.00', weight: 0.478571 },
      ],
      sector: [
        { key: 'Technology', value_eur: '3850.00', weight: 0.55 },
        { key: 'unknown', value_eur: '1200.00', weight: 0.171429 },
        { key: 'bonds', value_eur: '975.00', weight: 0.139286 },
        { key: 'cash', value_eur: '675.00', weight: 0.096429 },
        { key: 'Financial Services', value_eur: '300.00', weight: 0.042857 },
      ],
      country: [
        { key: 'DE', value_eur: '2975.00', weight: 0.425 },
        { key: 'US', value_eur: '2750.00', weight: 0.392857 },
        { key: 'cash', value_eur: '675.00', weight: 0.096429 },
        { key: 'no_look_through', value_eur: '500.00', weight: 0.071429 },
        { key: 'XS', value_eur: '100.00', weight: 0.014286 },
      ],
    },
    concentration: {
      largest: { isin: SAP, name: 'SAP SE', weight: 0.285714 },
      top: [
        { isin: SAP, name: 'SAP SE', weight: 0.285714 },
        { isin: APPLE, name: 'Apple Inc.', weight: 0.207143 },
        { isin: BUND, name: 'Bund 2033', weight: 0.139286 },
      ],
      top_weight: 0.632143,
      effective_positions: 3.71347,
      lower_bound: true,
    },
    quality: {
      equity_eur: '3350.00',
      covered: 1,
      composite: 0.519403,
      value_score: 0.319403,
      quality_score: 0.819403,
      value_traps: 1,
      quintiles: [
        { quintile: 1, count: 1, weight: 0.402985 },
        { quintile: 2, count: 0, weight: 0 },
        { quintile: 3, count: 0, weight: 0 },
        { quintile: 4, count: 1, weight: 0.597015 },
        { quintile: 5, count: 0, weight: 0 },
      ],
      funds: [{ isin: WORLD, score: null, covered: 0.05, lower_bound: true }],
    },
    costs: { etf_eur: '2000.00', covered: 1, ter: 0.2, running_costs_eur: '4.00' },
    bonds: {
      bond_eur: '975.00',
      covered: 1,
      ytm: 0.030145,
      modified_duration: 6.034057,
      maturities: [{ year: 2033, value_eur: '975.00' }],
      positions: [
        {
          isin: BUND,
          value_eur: '975.00',
          maturity: '2033-08-15',
          ytm: 0.030145,
          modified_duration: 6.034057,
          accrued: 0.690959,
          next_coupon: '2027-08-15',
          special: null,
        },
        {
          isin: FLOATER,
          value_eur: null,
          maturity: '2029-04-10',
          ytm: null,
          modified_duration: null,
          accrued: null,
          next_coupon: null,
          special: 'floating',
        },
      ],
    },
    data: {
      positions: 5,
      valued: 4,
      look_through: 1,
      oldest_price: '2026-11-19',
      oldest_score: '2026-11-20',
      oldest_fund_data: '2026-11-15',
    },
    ...values,
  };
}
