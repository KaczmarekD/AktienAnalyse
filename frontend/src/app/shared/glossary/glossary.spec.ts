// Glossar (Track G, Test 3): eine Quelle für alle Texte, vollständig und kurz genug für Tooltips.
import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { zProfileParamsV1Input } from '../../api/zod.gen';
import { apiTestingProviders } from '../../testing/api';
import { FACTORS, INSTRUMENT, RANKING, row, run } from '../../testing/fixtures';
import { RUN_KINDS, RUN_STATUSES, SECTORS } from '../format';
import { CONTROLS } from './controls';
import { ENTRIES, FIELD_FACTOR, GLOSSARY, TermKey, TipParams } from './glossary';
import { GlossaryStore } from './glossary.store';

const FACTORS_URL = '/api/v1/scoring/factors';

const PARAMS: TipParams = {
  value_weight: 0.6,
  value_trap_value_threshold: 0.7,
  value_trap_quality_threshold: 0.3,
  min_market_cap: 300_000_000,
  top: 20,
};

async function store(answer: 'factors' | 'error' = 'factors'): Promise<GlossaryStore> {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  const glossary = TestBed.inject(GlossaryStore);
  TestBed.tick();
  const request = TestBed.inject(HttpTestingController).expectOne(FACTORS_URL);
  if (answer === 'factors') {
    request.flush(FACTORS);
  } else {
    request.flush(null, { status: 503, statusText: 'Service Unavailable' });
  }
  await new Promise((resolve) => setTimeout(resolve));
  TestBed.tick();
  return glossary;
}

function factorKeys(): string[] {
  const shape = zProfileParamsV1Input.shape;
  return [
    ...shape.value_factors.unwrap().element.options,
    ...shape.quality_factors.unwrap().element.options,
  ];
}

describe('GLOSSARY', () => {
  it('has an entry for every factor key of the generated client, mapped to a ranking field', () => {
    const fields = Object.keys(row({ symbol: 'X.DE' }));
    for (const key of factorKeys()) {
      expect(ENTRIES[key as TermKey]?.role, key).toMatch(/^(value|quality)$/);
      const field = Object.entries(FIELD_FACTOR).find(([, factor]) => factor === key)?.[0];
      expect(fields, key).toContain(field);
    }
  });

  it('has a text for every run status, run kind and sector of the fixtures', () => {
    const statuses = new Set([...RUN_STATUSES, run({ id: 1 }).status]);
    for (const status of statuses) {
      expect(GLOSSARY[`status.${status}` as TermKey], status).toBeDefined();
    }
    for (const kind of RUN_KINDS) {
      expect(GLOSSARY[`kind.${kind}` as TermKey], kind).toBeDefined();
    }
    const sectors = [...RANKING.rows.map((r) => r.sector), INSTRUMENT.sector].filter(Boolean);
    for (const sector of sectors) {
      expect(SECTORS[sector as string], String(sector)).toBeDefined();
    }
  });

  it('keeps every control text short and not empty', () => {
    for (const [key, text] of Object.entries(CONTROLS)) {
      const value = typeof text === 'function' ? text(7) : text;
      expect(value.length, key).toBeGreaterThan(0);
      expect(value.length, key).toBeLessThanOrEqual(200);
    }
  });
});

describe('GlossaryStore', () => {
  it('gives every term a tooltip of at most 200 characters, with and without profile values', async () => {
    const glossary = await store();
    for (const key of Object.keys(GLOSSARY) as TermKey[]) {
      for (const params of [PARAMS, {}]) {
        const tip = glossary.tip(key, params);
        expect(tip.length, key).toBeGreaterThan(0);
        expect(tip.length, key).toBeLessThanOrEqual(200);
      }
    }
  });

  it('adds direction and role to the factor texts of the API', async () => {
    const glossary = await store();
    expect(glossary.label('pb')).toBe('KBV');
    expect(glossary.tip('pb')).toBe(`${FACTORS[1].hint} Niedriger ist besser. Value-Faktor.`);
    expect(glossary.tip('roic')).toMatch(/Höher ist besser\. Quality-Faktor\.$/);
  });

  it('marks information that is not part of the score', async () => {
    const glossary = await store();
    expect(glossary.tip('price')).toMatch(/Nicht im Score\.$/);
    // Wo der Text schon sagt, wie es zum Score steht, kommt kein Zusatz
    expect(glossary.tip('dividend_yield')).not.toMatch(/Nicht im Score\.$/);
  });

  it('puts the values of the profile into the text and stays general without them', async () => {
    const glossary = await store();
    // Zahl und Einheit trennt ein geschütztes Leerzeichen
    const tip = (key: TermKey, params?: TipParams) => glossary.tip(key, params).replace(/\s/g, ' ');
    expect(tip('value_trap', PARAMS)).toContain('Value ≥ 0,70');
    expect(tip('value_trap', PARAMS)).toContain('Quality ≤ 0,30');
    expect(tip('value_trap')).not.toMatch(/\d/);
    expect(tip('composite', PARAMS)).toContain('60 % Value und 40 % Quality');
    expect(tip('below_threshold', PARAMS)).toContain('300 Mio. €');
    expect(tip('rank_delta', PARAMS)).toContain('Top 20');
  });

  it('shows factors with their label only while the API does not answer', async () => {
    const glossary = await store('error');
    expect(glossary.label('ev_ebit')).toBe('EV/EBIT');
    expect(glossary.tip('ev_ebit')).toBe('');
    expect(glossary.tip('isin')).toContain('Wertpapierkennnummer');
  });
});
