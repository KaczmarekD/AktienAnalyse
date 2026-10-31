// Beispieldaten im Format des web-api (Typen aus dem generierten Client).
import type {
  Instrument,
  Ranking,
  RankingRow,
  Report,
  RunDetail,
  RunSummary,
  ScorePoint,
  Snapshot,
} from '../api/types.gen';

export function row(values: Partial<RankingRow> & Pick<RankingRow, 'symbol'>): RankingRow {
  return {
    rank: null,
    name: null,
    index: 'DAX',
    sector: null,
    passed_filter: true,
    composite_score: null,
    value_score: null,
    quality_score: null,
    value_trap_flag: false,
    market_cap: null,
    currency: 'EUR',
    ev_ebit: null,
    pb_ratio: null,
    p_fcf: null,
    shareholder_yield: null,
    roic: null,
    fcf_margin: null,
    operating_margin: null,
    net_debt_ebitda: null,
    earnings_stability: null,
    ...values,
  };
}

export const RANKING: Ranking = {
  scoring_run_id: 1,
  fetch_run_id: 1,
  origin: 'live',
  created_at: '2026-10-30T22:36:21Z',
  fetched_on: '2026-10-30',
  universe_source: 'Deka',
  value_weight: 0.6,
  quality_weight: 0.4,
  rows: [
    row({
      rank: 1,
      symbol: 'ALV.DE',
      name: 'Allianz',
      sector: 'Financial Services',
      composite_score: 0.777,
      value_score: 0.7,
      quality_score: 0.9,
      market_cap: 140_000_000_000,
      roic: 0.123,
    }),
    row({
      rank: 2,
      symbol: 'PAH3.DE',
      name: 'Porsche SE',
      composite_score: 0.742,
      value_score: 0.95,
      quality_score: 0.44,
    }),
    row({
      rank: 3,
      symbol: 'FNTN.DE',
      name: 'freenet',
      index: 'MDAX',
      composite_score: 0.736,
      value_score: 0.8,
      quality_score: 0.64,
      value_trap_flag: true,
    }),
    row({ rank: 4, symbol: 'DBK.DE', name: 'Deutsche Bank', value_score: 0.82 }),
    row({ symbol: 'TINY.DE', name: 'Tiny', index: 'MDAX', passed_filter: false }),
  ],
};

export function run(values: Partial<RunDetail> & Pick<RunSummary, 'id'>): RunDetail {
  return {
    kind: 'batch',
    status: 'partial',
    started_at: '2026-10-30T22:31:00Z',
    finished_at: '2026-10-30T22:36:22Z',
    dry_run: false,
    force_refresh: false,
    universe_mode: 'DAX_MDAX',
    universe_size: 90,
    scored_count: 88,
    failed_count: 2,
    exit_code: 0,
    app_version: '0.3.0',
    error: null,
    fetch_run_id: 1,
    scoring_run_id: 1,
    report_id: 5,
    ...values,
  };
}

export const REPORT: Report = {
  id: 5,
  run_id: 1,
  scoring_run_id: 1,
  subject: '[partial 88/90] DAX/MDAX Value-Screening 2026-10-30 - Top: Allianz',
  generated_at: '2026-10-30T22:36:21Z',
  csv_filename: 'value_ranking_20261030.csv',
  html: '<!DOCTYPE html><html><body><h1>Top 20</h1></body></html>',
};

function snapshot(values: Partial<Snapshot> = {}): Snapshot {
  return {
    fetch_run_id: 1,
    fetched_on: '2026-10-30',
    fetch_ok: true,
    price: 381.5,
    currency: 'EUR',
    market_cap: 140_000_000_000,
    ev_ebit: null,
    pe_ratio: 14.383607,
    pb_ratio: 2.1,
    p_fcf: 9.5,
    dividend_yield: 0.045,
    shareholder_yield: 0.06,
    roic: 0.123,
    fcf_margin: 0.15,
    operating_margin: 0.11,
    net_debt_ebitda: null,
    earnings_stability: 0.92,
    revenue_growth_5y: 0.05,
    eps_growth_5y: 0.08,
    errors: [],
    ...values,
  };
}

function point(values: Partial<ScorePoint> & Pick<ScorePoint, 'scoring_run_id'>): ScorePoint {
  return {
    created_at: '2026-10-30T22:36:21Z',
    origin: 'live',
    rank: 1,
    passed_filter: true,
    composite_score: 0.777,
    value_score: 0.7,
    quality_score: 0.9,
    value_trap_flag: false,
    ...values,
  };
}

export const INSTRUMENT: Instrument = {
  symbol: 'ALV.DE',
  isin: 'DE0008404005',
  name: 'Allianz',
  index: 'DAX',
  sector: 'Financial Services',
  industry: 'Insurance - Diversified',
  latest: snapshot(),
  score_history: [
    point({
      scoring_run_id: 1,
      created_at: '2026-10-23T07:40:00Z',
      rank: 3,
      composite_score: 0.71,
    }),
    point({ scoring_run_id: 2 }),
  ],
};
