// Titel-Detail (P3.7): Stammdaten, Kennzahlen des neuesten Abrufs, Score-Verlauf.
import { TestBed } from '@angular/core/testing';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { INSTRUMENT } from '../testing/fixtures';
import { InstrumentPage } from './instrument-page';

function render(symbol: string) {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  const fixture = TestBed.createComponent(InstrumentPage);
  fixture.componentRef.setInput('symbol', symbol);
  return fixture;
}

describe('InstrumentPage', () => {
  it('shows name, symbol, ISIN, index and sector', async () => {
    const fixture = render('ALV.DE');
    await respond(fixture, '/api/v1/instruments/ALV.DE', INSTRUMENT);
    const content = text(fixture);
    for (const part of ['Allianz', 'ALV.DE', 'DE0008404005', 'DAX', 'Financial Services']) {
      expect(content).toContain(part);
    }
  });

  it('shows the figures of the latest fetch the German way', async () => {
    const fixture = render('ALV.DE');
    await respond(fixture, '/api/v1/instruments/ALV.DE', INSTRUMENT);
    const content = text(fixture);
    expect(content).toContain('Stand 30.10.2026');
    expect(content).toContain('14,38'); // KGV
    expect(content).toContain('12,3 %'); // ROIC
    expect(content).toContain('140,0 Mrd');
  });

  it('lists the score history, newest first', async () => {
    const fixture = render('ALV.DE');
    await respond(fixture, '/api/v1/instruments/ALV.DE', INSTRUMENT);
    const rows = query(fixture, 'tr[data-scoring-run]');
    expect(rows.map((r) => r.getAttribute('data-scoring-run'))).toEqual(['2', '1']);
    expect(rows[1].textContent).toContain('0,71');
  });

  it('says when the title does not exist', async () => {
    const fixture = render('GIBTS.DE');
    await respond(fixture, '/api/v1/instruments/GIBTS.DE', { detail: 'Titel nicht gefunden' }, 404);
    expect(text(fixture)).toContain('Titel nicht gefunden');
  });
});
