// Titel-Detail (P3.7, neu gestaltet mit Track G, G5): Warum steht dieser Titel dort, wo er steht?
import { Clipboard } from '@angular/cdk/clipboard';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { vi } from 'vitest';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { FACTORS, INSTRUMENT, RANKING } from '../testing/fixtures';
import { abbreviationsWithoutExplanation, controlsWithoutTooltip } from '../testing/tooltips';
import { InstrumentPage } from './instrument-page';

const URL = '/api/v1/instruments/ALV.DE';
const LATEST = '/api/v1/ranking/latest';
const FACTORS_URL = '/api/v1/scoring/factors';

type Fixture = ComponentFixture<InstrumentPage>;

function render(symbol: string): Fixture {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  const fixture = TestBed.createComponent(InstrumentPage);
  fixture.componentRef.setInput('symbol', symbol);
  return fixture;
}

async function loaded(instrument = INSTRUMENT): Promise<Fixture> {
  const fixture = render('ALV.DE');
  await respond(fixture, URL, instrument);
  await respond(fixture, LATEST, RANKING);
  await respond(fixture, FACTORS_URL, FACTORS);
  return fixture;
}

function plain(element: Element | undefined): string {
  return (element?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function tooltip(fixture: Fixture, element: Element | undefined): string | undefined {
  return fixture.debugElement
    .queryAll(By.directive(MatTooltip))
    .find((debug) => debug.nativeElement === element)
    ?.injector.get(MatTooltip)
    .message.replace(/\s/g, ' ');
}

describe('InstrumentPage', () => {
  it('shows name, symbol, ISIN, index, sector in German and industry', async () => {
    const content = text(await loaded());
    for (const part of [
      'Allianz',
      'ALV.DE',
      'DE0008404005',
      'DAX',
      'Finanzen',
      'Insurance - Diversified',
    ]) {
      expect(content).toContain(part);
    }
  });

  it('copies the ISIN and confirms it', async () => {
    const fixture = await loaded();
    const copy = vi.spyOn(TestBed.inject(Clipboard), 'copy').mockReturnValue(true);
    const snack = vi.spyOn(TestBed.inject(MatSnackBar), 'open');
    const button = query<HTMLButtonElement>(fixture, 'button[data-action="copy-isin"]')[0];
    expect(button.getAttribute('aria-label')).toBe('ISIN kopieren');
    button.click();
    expect(copy).toHaveBeenCalledWith('DE0008404005');
    expect(snack.mock.calls[0][0]).toBe('ISIN kopiert');
  });

  it('sums up rank, composite, value and quality in cards from the newest scoring', async () => {
    const fixture = await loaded();
    const card = (name: string) => plain(query(fixture, `[data-card="${name}"]`)[0]);
    expect(card('rank')).toContain('1 von 84');
    expect(card('rank')).toContain('2 seit 23.10.2026');
    expect(card('composite')).toContain('0,78');
    expect(card('composite')).toContain('60 % Value, 40 % Quality');
    expect(card('value')).toContain('0,70');
    expect(card('value')).toContain('aus 3 von 4 Value-Faktoren');
    expect(card('quality')).toContain('0,90');
  });

  it('groups the figures into valuation, quality, and market and growth', async () => {
    const fixture = await loaded();
    const headings = query(fixture, 'app-section h3').map((h) => plain(h));
    expect(headings).toEqual(['Bewertung (Value)', 'Qualität (Quality)', 'Markt und Wachstum']);
    const valuation = plain(query(fixture, 'app-section')[0]);
    expect(valuation).toContain('Nur zur Information');
    expect(valuation).toContain('KGV 14,4');
    const content = text(fixture);
    expect(content).toContain('Stand 30.10.2026');
    expect(content).toContain('ROIC 12,3 %');
    expect(content).toContain('140,0 Mrd');
    expect(content).toContain('381,50 EUR');
  });

  it('shows the percentile per factor, missing data and factors the profile does not use', async () => {
    const fixture = await loaded();
    const figure = (field: string) => query(fixture, `[data-figure="${field}"]`)[0];
    expect(plain(figure('pb_ratio'))).toContain('besser als 37 %');
    expect(figure('pb_ratio').querySelector('[data-bar]')).not.toBeNull();
    expect(plain(figure('ev_ebit'))).toContain('keine Daten');
    expect(plain(figure('net_debt_ebitda'))).toContain('nicht aktiv');
    // Reine Information hat kein Perzentil
    expect(plain(figure('pe_ratio'))).not.toContain('besser als');
  });

  it('warns when the fetch was incomplete and shows its notes', async () => {
    const fixture = await loaded({
      ...INSTRUMENT,
      latest: { ...INSTRUMENT.latest!, fetch_ok: false, errors: ['Bilanz fehlt'] },
    });
    const content = text(fixture);
    expect(content).toContain('Abruf unvollständig');
    expect(content).toContain('Hinweise vom Abruf: Bilanz fehlt');
  });

  it('draws the composite as sparkline and lists the history, newest first', async () => {
    const fixture = await loaded();
    const spark = query(fixture, 'app-sparkline svg')[0];
    expect(spark.getAttribute('aria-label')).toContain('Verlauf des Composite');
    const rows = query(fixture, 'tr[data-scoring-run]');
    expect(rows.map((r) => r.getAttribute('data-scoring-run'))).toEqual(['2', '1']);
    expect(rows[1].textContent).toContain('0,71');
    const link = rows[1].querySelector('a');
    expect(link?.getAttribute('href')).toBe('/ranking/1');
    expect(tooltip(fixture, link ?? undefined)).toContain('Ranking dieses Bewertungslaufs');
  });

  it('marks a value trap in the header', async () => {
    const [older, newest] = INSTRUMENT.score_history;
    const fixture = await loaded({
      ...INSTRUMENT,
      score_history: [older, { ...newest, value_trap_flag: true }],
    });
    expect(query(fixture, 'app-page-header app-value-trap-badge .badge')).toHaveLength(1);
  });

  it('says when the title does not exist', async () => {
    const fixture = render('GIBTS.DE');
    await respond(fixture, '/api/v1/instruments/GIBTS.DE', { detail: 'Titel nicht gefunden' }, 404);
    expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain('Titel nicht gefunden');
  });

  it('explains every control, label and abbreviation (tests 1 and 2)', async () => {
    const fixture = await loaded();
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });
});
