// Ranking-Ansicht (P3.7): Darstellung, Filter, Sortierung, leere und fehlerhafte Antworten.
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { RANKING } from '../testing/fixtures';
import { RankingPage } from './ranking-page';

const LATEST = '/api/v1/ranking/latest';

async function render(id?: number): Promise<ComponentFixture<RankingPage>> {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  const fixture = TestBed.createComponent(RankingPage);
  if (id !== undefined) {
    fixture.componentRef.setInput('scoringRunId', String(id));
  }
  return fixture;
}

function symbols(fixture: ComponentFixture<RankingPage>): string[] {
  return query(fixture, 'tr[data-symbol]').map((tr) => tr.getAttribute('data-symbol') ?? '');
}

async function click(fixture: ComponentFixture<RankingPage>, element: HTMLElement): Promise<void> {
  element.click();
  await fixture.whenStable();
}

describe('RankingPage', () => {
  it('shows the scoring run with day, source and weights', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, RANKING);
    const content = text(fixture);
    expect(content).toContain('Bewertungslauf 1');
    expect(content).toContain('30.10.2026');
    expect(content).toContain('Deka');
    expect(content).toContain('60 % Value');
    expect(content).toContain('40 % Quality');
  });

  it('lists ranked titles in rank order and hides titles below the size filter', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, RANKING);
    expect(symbols(fixture)).toEqual(['ALV.DE', 'PAH3.DE', 'FNTN.DE', 'DBK.DE']);
  });

  it('formats scores, market cap and percentages the German way', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, RANKING);
    // Angular setzt vor % ein geschuetztes Leerzeichen, daher Leerraum vereinheitlichen
    const allianz = (query(fixture, 'tr[data-symbol="ALV.DE"]')[0].textContent ?? '').replace(
      /\s+/g,
      ' ',
    );
    expect(allianz).toContain('0,78');
    expect(allianz).toContain('140,0 Mrd');
    expect(allianz).toContain('12,3 %');
  });

  it('shows a dash for a title without composite', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, RANKING);
    const cell = query(fixture, 'tr[data-symbol="DBK.DE"] td.mat-column-composite_score')[0];
    expect(cell.textContent?.trim()).toBe('–');
  });

  it('marks value traps', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, RANKING);
    const trap = query(fixture, 'tr[data-symbol="FNTN.DE"]')[0];
    expect(trap.classList).toContain('value-trap');
    expect(trap.textContent).toContain('Value-Trap');
  });

  it('links each title to its detail page', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, RANKING);
    const link = query<HTMLAnchorElement>(fixture, 'tr[data-symbol="ALV.DE"] a')[0];
    expect(link.getAttribute('href')).toBe('/instruments/ALV.DE');
  });

  it('filters by index', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, RANKING);
    const mdax = query(fixture, 'mat-button-toggle button').find((b) =>
      b.textContent?.includes('MDAX'),
    );
    await click(fixture, mdax!);
    expect(symbols(fixture)).toEqual(['FNTN.DE']);
  });

  it('searches by name and symbol', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, RANKING);
    const search = query<HTMLInputElement>(fixture, 'input[name="search"]')[0];
    search.value = 'porsche';
    search.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(symbols(fixture)).toEqual(['PAH3.DE']);
    search.value = 'dbk';
    search.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(symbols(fixture)).toEqual(['DBK.DE']);
  });

  it('shows titles below the size filter on demand, at the end', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, RANKING);
    await click(fixture, query(fixture, 'mat-slide-toggle button')[0]);
    expect(symbols(fixture).at(-1)).toBe('TINY.DE');
  });

  it('sorts by a score column, titles without value last', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, RANKING);
    await click(fixture, query(fixture, 'th.mat-column-value_score')[0]);
    expect(symbols(fixture)).toEqual(['PAH3.DE', 'DBK.DE', 'FNTN.DE', 'ALV.DE']);
  });

  it('loads a specific scoring run', async () => {
    const fixture = await render(7);
    await respond(fixture, '/api/v1/ranking/7', { ...RANKING, scoring_run_id: 7 });
    expect(text(fixture)).toContain('Bewertungslauf 7');
  });

  it('says when there is no scoring run yet', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, { detail: 'Bewertungslauf nicht gefunden' }, 404);
    expect(text(fixture)).toContain('Noch kein Bewertungslauf');
  });

  it('says when the web-api is not reachable', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, { detail: 'Datenbank nicht erreichbar' }, 503);
    expect(text(fixture)).toContain('nicht erreichbar');
  });
});
