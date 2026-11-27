// Antworten des web-api für die Tests der Depot-Seiten (D3.6).
import type { Depot, DepotValuation, Holdings, PositionValue } from '../api/types.gen';

export const SAP = 'DE0007164600';
export const APPLE = 'US0378331005';
export const BUND = 'DE0001102580';

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
      }),
      position({ isin: APPLE, quantity: '3', pending: true, missing: 'price' }),
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
