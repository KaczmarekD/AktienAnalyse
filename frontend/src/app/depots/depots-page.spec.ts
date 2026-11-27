// Meine Depots (D3.6, DEP-01, 07, 09): je Depot eine Karte mit Art, Wert, Stand und Positionen,
// „unvollständig“ und „wird geprüft“ als Hinweis, Archivierte nur auf Wunsch, „Neues Depot“.
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDialog } from '@angular/material/dialog';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { me, provideAuthTesting } from '../testing/auth';
import { depot, valuation } from '../testing/depots';
import {
  abbreviationsWithoutExplanation,
  controlsWithoutTooltip,
  headersWithoutScope,
} from '../testing/tooltips';
import { DepotsPage } from './depots-page';

const URL = '/api/v1/depots?include_archived=false';
const ARCHIVED = '/api/v1/depots?include_archived=true';

type Fixture = ComponentFixture<DepotsPage>;

const DEPOTS = [
  depot({ id: 1, name: 'DKB', description: 'Altersvorsorge' }),
  depot({
    id: 2,
    name: 'Comdirect',
    valuation: valuation({ value_eur: '2315.00', complete: false, unvalued: 1, pending: 1 }),
  }),
  depot({ id: 3, name: 'Ideen', kind: 'watchlist', positions: 4, valuation: valuation() }),
];

function render(): Fixture {
  TestBed.configureTestingModule({
    providers: [
      ...apiTestingProviders(),
      provideAuthTesting({ user: me() }),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
    ],
  });
  return TestBed.createComponent(DepotsPage);
}

function card(fixture: Fixture, id: number): string {
  return (query(fixture, `[data-depot="${id}"]`)[0]?.textContent ?? '').replace(/\s+/g, ' ');
}

describe('DepotsPage', () => {
  afterEach(() => TestBed.inject(MatDialog).closeAll());

  it('shows one card per depot with value, date and positions', async () => {
    const fixture = render();
    await respond(fixture, URL, DEPOTS);
    const dkb = card(fixture, 1);
    expect(dkb).toContain('DKB');
    expect(dkb).toContain('Depot');
    expect(dkb).toContain('12.459,10 €');
    expect(dkb).toContain('20.11.2026');
    expect(dkb).toContain('Altersvorsorge');
    expect(query(fixture, '[data-depot="1"] [data-positions]')[0].textContent?.trim()).toBe('2');
  });

  it('says when a value is incomplete or securities wait for master data', async () => {
    const fixture = render();
    await respond(fixture, URL, DEPOTS);
    expect(query(fixture, '[data-depot="1"] [data-incomplete]')).toHaveLength(0);
    const comdirect = card(fixture, 2);
    expect(comdirect).toContain('unvollständig');
    expect(comdirect).toContain('1 wird geprüft');
    expect(comdirect).toContain('2.315,00 €');
  });

  it('shows a watchlist without a value', async () => {
    const fixture = render();
    await respond(fixture, URL, DEPOTS);
    expect(card(fixture, 3)).toContain('Beobachtungsliste');
    expect(query(fixture, '[data-depot="3"] [data-value]')).toHaveLength(0);
  });

  it('shows a dash while a depot has no valuation', async () => {
    const fixture = render();
    await respond(fixture, URL, [depot({ id: 4, name: 'Neu', valuation: null })]);
    expect(query(fixture, '[data-depot="4"] [data-value]')[0].textContent?.trim()).toBe('–');
  });

  it('invites to create the first depot', async () => {
    const fixture = render();
    await respond(fixture, URL, []);
    expect(text(fixture)).toContain('Noch kein Depot.');
  });

  it('shows archived depots only on request', async () => {
    const fixture = render();
    await respond(fixture, URL, DEPOTS);
    query(fixture, '[data-option="archived"] button')[0].click();
    await respond(fixture, ARCHIVED, [depot({ id: 9, name: 'Alt', status: 'archived' })]);
    expect(card(fixture, 9)).toContain('archiviert');
  });

  it('opens the dialog for a new depot', async () => {
    const fixture = render();
    await respond(fixture, URL, DEPOTS);
    query(fixture, 'button[data-action="create"]')[0].click();
    fixture.detectChanges();
    expect(document.querySelector('mat-dialog-container h2')?.textContent).toContain('Neues Depot');
  });

  it('links each card to its depot', async () => {
    const fixture = render();
    await respond(fixture, URL, DEPOTS);
    const link = query(fixture, '[data-depot="2"] a[data-action="open"]')[0];
    expect(link.getAttribute('href')).toBe('/depots/2');
  });

  it('shows an error when the server does not answer', async () => {
    const fixture = render();
    await respond(fixture, URL, null, 503);
    expect(text(fixture)).toContain('Der Server oder seine Datenbank ist nicht erreichbar.');
  });

  it('explains every control and badge (tests 1 and 2)', async () => {
    const fixture = render();
    await respond(fixture, URL, DEPOTS);
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(headersWithoutScope(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });
});
