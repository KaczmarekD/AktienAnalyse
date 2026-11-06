// Ranking-Ansicht (P3.7, neu gestaltet mit Track G, G4): Kennzahlkarten, Filter, Spaltenwahl,
// Sortierung, Hinweise mit Tooltip, leere und fehlerhafte Antworten.
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_FORM_FIELD_DEFAULT_OPTIONS } from '@angular/material/form-field';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { Dispatcher } from '@ngrx/signals/events';

import { serverEvents } from '../shared/realtime/realtime.events';
import { apiTestingProviders, query, respond, text } from '../testing/api';
import { FACTORS, RANKING } from '../testing/fixtures';
import {
  abbreviationsWithoutExplanation,
  controlsWithoutTooltip,
  headersWithoutScope,
} from '../testing/tooltips';
import { COLUMNS_KEY, RankingPage } from './ranking-page';

const LATEST = '/api/v1/ranking/latest';
const FACTORS_URL = '/api/v1/scoring/factors';

type Fixture = ComponentFixture<RankingPage>;

async function render(id?: number): Promise<Fixture> {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  const fixture = TestBed.createComponent(RankingPage);
  if (id !== undefined) {
    fixture.componentRef.setInput('scoringRunId', String(id));
  }
  return fixture;
}

/** Das jüngste Ranking samt Faktortexten (die Spaltenköpfe erklären die Faktoren). */
async function loaded(): Promise<Fixture> {
  const fixture = await render();
  await respond(fixture, LATEST, RANKING);
  await respond(fixture, FACTORS_URL, FACTORS);
  return fixture;
}

function symbols(fixture: Fixture): string[] {
  return query(fixture, 'tr[data-symbol]').map((tr) => tr.getAttribute('data-symbol') ?? '');
}

function plain(fixture: Fixture, element: Element | undefined): string {
  return (element?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function tooltip(fixture: Fixture, element: Element | undefined): string | undefined {
  return fixture.debugElement
    .queryAll(By.directive(MatTooltip))
    .find((debug) => debug.nativeElement === element)
    ?.injector.get(MatTooltip)
    .message.replace(/\s/g, ' ');
}

async function click(fixture: Fixture, element: HTMLElement | undefined): Promise<void> {
  element?.click();
  await fixture.whenStable();
  fixture.detectChanges();
}

describe('RankingPage', () => {
  beforeEach(() => localStorage.removeItem(COLUMNS_KEY));

  it('uses form fields with an outline (G1, not in the start bundle)', async () => {
    const fixture = await render();
    expect(fixture.debugElement.injector.get(MAT_FORM_FIELD_DEFAULT_OPTIONS).appearance).toBe(
      'outline',
    );
  });

  it('names fetch day, profile with weights, index list and scoring run', async () => {
    const content = text(await loaded());
    expect(content).toContain('Abruf 30.10.2026');
    expect(content).toContain('Profil Standard v3 (60 % Value, 40 % Quality)');
    expect(content).toContain('Indexliste Deka');
    expect(content).toContain('Bewertungslauf #1');
  });

  it('sums up the run in four cards', async () => {
    const fixture = await loaded();
    const cards = query(fixture, '[data-card]').map((card) => plain(fixture, card));
    expect(cards[0]).toContain('3 von 5');
    expect(cards[1]).toContain('Allianz');
    expect(cards[1]).toContain('0,78');
    expect(cards[2]).toContain('1');
    expect(cards[3]).toContain('1');
    const leader = query<HTMLAnchorElement>(fixture, '[data-card="leader"] a')[0];
    expect(leader.getAttribute('href')).toBe('/instruments/ALV.DE');
  });

  it('filters on the value traps and on titles without composite by their cards', async () => {
    const fixture = await loaded();
    const traps = query<HTMLButtonElement>(fixture, '[data-card="traps"] button')[0];
    await click(fixture, traps);
    expect(traps.getAttribute('aria-pressed')).toBe('true');
    expect(symbols(fixture)).toEqual(['FNTN.DE']);

    await click(fixture, query(fixture, '[data-card="no-composite"] button')[0]);
    expect(symbols(fixture)).toEqual(['DBK.DE']);

    await click(fixture, query(fixture, 'button[data-action="clear-focus"]')[0]);
    expect(symbols(fixture)).toEqual(['ALV.DE', 'PAH3.DE', 'FNTN.DE', 'DBK.DE']);
  });

  it('lists ranked titles in rank order and hides titles below the size filter', async () => {
    expect(symbols(await loaded())).toEqual(['ALV.DE', 'PAH3.DE', 'FNTN.DE', 'DBK.DE']);
  });

  it('shows symbol and index under the name and the sector in German', async () => {
    const fixture = await loaded();
    const allianz = plain(fixture, query(fixture, 'tr[data-symbol="ALV.DE"]')[0]);
    // Name und darunter Symbol und Index (eigene Zeile, im Text ohne Leerzeichen dazwischen)
    expect(allianz).toContain('Allianz');
    expect(allianz).toContain('ALV.DE · DAX');
    expect(allianz).toContain('Finanzen');
    expect(allianz).toContain('0,78');
    expect(allianz).toContain('140,0 Mrd');
  });

  it('shows a dash for a title without composite and says why', async () => {
    const fixture = await loaded();
    const cell = query(fixture, 'tr[data-symbol="DBK.DE"] td.mat-column-composite_score')[0];
    expect(cell.textContent?.trim()).toBe('–');
    const badge = query(fixture, 'tr[data-symbol="DBK.DE"] .badge')[0];
    expect(badge?.textContent?.trim()).toBe('ohne Composite');
    expect(tooltip(fixture, badge)).toContain('Banken');
  });

  it('marks value traps with a badge that names the thresholds of the profile', async () => {
    const fixture = await loaded();
    const badge = query(fixture, 'tr[data-symbol="FNTN.DE"] app-value-trap-badge .badge')[0];
    expect(badge.textContent).toContain('Value-Trap?');
    expect(tooltip(fixture, badge)).toContain('Value ≥ 0,70');
    // Keine eingefärbte Zeile mehr (E6): nur das Badge trägt die Warnung
    expect(query(fixture, 'tr.value-trap')).toHaveLength(0);
  });

  it('explains scores as percentiles in their tooltip', async () => {
    const fixture = await loaded();
    const score = query(
      fixture,
      'tr[data-symbol="ALV.DE"] td.mat-column-composite_score app-score span',
    )[0];
    expect(tooltip(fixture, score)).toContain('besser als etwa 78 %');
  });

  it('links each title to its detail page', async () => {
    const fixture = await loaded();
    const link = query<HTMLAnchorElement>(fixture, 'tr[data-symbol="ALV.DE"] a')[0];
    expect(link.getAttribute('href')).toBe('/instruments/ALV.DE');
  });

  it('filters by index', async () => {
    const fixture = await loaded();
    const mdax = query(fixture, 'mat-button-toggle button').find((b) =>
      b.textContent?.includes('MDAX'),
    );
    await click(fixture, mdax);
    expect(symbols(fixture)).toEqual(['FNTN.DE']);
  });

  it('searches by name and symbol and offers to reset the filter when nothing matches', async () => {
    const fixture = await loaded();
    const search = query<HTMLInputElement>(fixture, 'input[name="search"]')[0];
    search.value = 'porsche';
    search.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(symbols(fixture)).toEqual(['PAH3.DE']);

    search.value = 'xyz';
    search.dispatchEvent(new Event('input'));
    await fixture.whenStable();
    expect(text(fixture)).toContain('Kein Titel passt zum Filter.');
    await click(fixture, query(fixture, 'button[data-action="reset"]')[0]);
    expect(symbols(fixture)).toEqual(['ALV.DE', 'PAH3.DE', 'FNTN.DE', 'DBK.DE']);
  });

  it('shows titles below the size filter on demand, at the end, with a badge', async () => {
    const fixture = await loaded();
    await click(fixture, query(fixture, 'mat-slide-toggle button')[0]);
    expect(symbols(fixture).at(-1)).toBe('TINY.DE');
    const badge = query(fixture, 'tr[data-symbol="TINY.DE"] .badge')[0];
    expect(badge?.textContent?.trim()).toBe('unter Größenschwelle');
    expect(tooltip(fixture, badge)).toContain('300 Mio. €');
  });

  it('sorts by a score column, titles without value last', async () => {
    const fixture = await loaded();
    await click(fixture, query(fixture, 'th.mat-column-value_score')[0]);
    expect(symbols(fixture)).toEqual(['PAH3.DE', 'DBK.DE', 'FNTN.DE', 'ALV.DE']);
  });

  it('shows the standard columns and more factors on demand, remembered for next time', async () => {
    const fixture = await loaded();
    const headers = () =>
      query(fixture, 'th').map((th) => th.className.match(/mat-column-(\S+)/)?.[1]);
    expect(headers()).toEqual([
      'rank',
      'title',
      'sector',
      'composite_score',
      'value_score',
      'quality_score',
      'hint',
      'market_cap',
    ]);
    await click(fixture, query(fixture, 'button[data-action="columns"]')[0]);
    const roic = Array.from(document.querySelectorAll<HTMLElement>('[data-column="roic"] input'));
    await click(fixture, roic[0]);
    expect(headers()).toContain('roic');
    expect(plain(fixture, query(fixture, 'tr[data-symbol="ALV.DE"]')[0])).toContain('12,3 %');
    expect(JSON.parse(localStorage.getItem(COLUMNS_KEY) ?? '[]')).toContain('roic');
  });

  it('says when a scoring run is not the current one and links to the current one', async () => {
    const fixture = await render(7);
    await respond(fixture, '/api/v1/ranking/7', {
      ...RANKING,
      scoring_run_id: 7,
      created_at: '2026-10-23T21:00:00Z',
    });
    await respond(fixture, LATEST, RANKING);
    const content = text(fixture);
    expect(content).toContain('Bewertungslauf #7');
    expect(content).toContain('Bewertungslauf vom 23.10.2026, nicht der aktuelle.');
    const link = query<HTMLAnchorElement>(fixture, 'a[data-action="latest"]')[0];
    expect(link.getAttribute('href')).toBe('/ranking');
  });

  it('does not call the current scoring run old', async () => {
    expect(text(await loaded())).not.toContain('nicht der aktuelle');
  });

  it('says when there is no scoring run yet', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, { detail: 'Bewertungslauf nicht gefunden' }, 404);
    expect(text(fixture)).toContain('Noch kein Bewertungslauf');
  });

  it('says when the server is not reachable', async () => {
    const fixture = await render();
    await respond(fixture, LATEST, { detail: 'Datenbank nicht erreichbar' }, 503);
    expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain('nicht erreichbar');
  });

  it('explains every control, header, badge and abbreviation (tests 1 and 2)', async () => {
    const fixture = await loaded();
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
    // Spaltenköpfe mit scope (Spec, Barrierefreiheit)
    expect(headersWithoutScope(fixture)).toEqual([]);
  });

  // P4.6: neues Ranking per WebSocket -> neu laden
  it('reloads the latest ranking when a ranking event arrives', async () => {
    const fixture = await loaded();
    TestBed.inject(Dispatcher).dispatch(
      serverEvents.event({
        op: 'event',
        topic: 'ranking',
        type: 'scoring.run.completed',
        seq: 12,
        data: { scoringRunId: 21, rankingSize: 90 },
      }),
    );
    // Während es nachlädt, bleibt die Tabelle stehen (Spec, Zustände)
    const before = symbols(fixture);
    TestBed.tick();
    expect(symbols(fixture)).toEqual(before);
    await respond(fixture, LATEST, RANKING);
    expect(symbols(fixture).length).toBeGreaterThan(0);
  });
});
