// Hinweise eines Depots (D5.4, HIN-01 bis 05): nach Schwere, mit Messwert, Schwelle, Datenstand
// und Ansatzpunkt, Status neu/besteht/erledigt, „zur Kenntnis genommen“ ausgeblendet, bis man sie
// zeigt, Disclaimer, schreibgeschützt im Archiv, ohne Lauf ein Grund statt einer leeren Liste.
import { HttpTestingController } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDialog } from '@angular/material/dialog';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { hint, hints, SAP, WORLD } from '../testing/depots';
import {
  abbreviationsWithoutExplanation,
  controlsWithoutTooltip,
  headersWithoutScope,
} from '../testing/tooltips';
import { HintsPanel } from './hints-panel';

const URL = '/api/v1/depots/3/hints';
const SPDR = 'IE00B5BMR087';

const LIST = hints([
  hint({ rule: 'HIN-A02', subject: 'depot', severity: 'info', measured: 0.15, threshold: 0.1 }),
  hint({
    rule: 'HIN-K01',
    subject: SAP,
    severity: 'critical',
    status: 'new',
    measured: 0.262,
    threshold: 0.2,
  }),
  hint({ rule: 'HIN-K04', subject: 'DE', severity: 'info', measured: 0.62, threshold: 0.5 }),
  hint({
    rule: 'HIN-E02',
    subject: `${WORLD}+${SPDR}`,
    severity: 'info',
    measured: 0.71,
    threshold: 0.5,
    title: 'Zwei ETFs überschneiden sich',
  }),
  hint({
    rule: 'HIN-B01',
    subject: 'DE0001102580',
    severity: 'info',
    measured: 45,
    threshold: 90,
    title: 'Anleihe wird bald fällig',
    acknowledged: true,
  }),
  hint({
    rule: 'HIN-D01',
    subject: 'US0378331005',
    status: 'resolved',
    title: 'Kurs fehlt oder ist alt',
  }),
]);

type Fixture = ComponentFixture<HintsPanel>;

async function settle(fixture: Fixture): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
    fixture.detectChanges();
  }
}

async function render(body: object = LIST, status = 200, readonly = false): Promise<Fixture> {
  TestBed.configureTestingModule({
    providers: [
      ...apiTestingProviders(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
    ],
  });
  const fixture = TestBed.createComponent(HintsPanel);
  fixture.componentRef.setInput('depotId', 3);
  fixture.componentRef.setInput('readonly', readonly);
  fixture.componentRef.setInput('names', {
    [SAP]: 'SAP SE',
    [WORLD]: 'iShares Core MSCI World',
    [SPDR]: 'SPDR MSCI World',
    DE0001102580: 'Bund 2033',
  });
  await respond(fixture, URL, body, status);
  await settle(fixture);
  return fixture;
}

function cell(fixture: Fixture, selector: string): string {
  return (query(fixture, selector)[0]?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

function keys(fixture: Fixture, list: string): string[] {
  return query(fixture, `[data-${list}] > li`).map((li) => li.getAttribute('data-hint') ?? '');
}

describe('HintsPanel', () => {
  afterEach(() => TestBed.inject(MatDialog).closeAll());

  it('lists the open hints, the most severe and the new ones first', async () => {
    const fixture = await render();
    expect(keys(fixture, 'open')).toEqual([
      `HIN-K01:${SAP}`,
      'HIN-A02:depot',
      `HIN-E02:${WORLD}+${SPDR}`,
      'HIN-K04:DE',
    ]);
    const k01 = `[data-hint="HIN-K01:${SAP}"]`;
    expect(cell(fixture, `${k01} [data-severity-badge]`)).toContain('Kritisch');
    expect(cell(fixture, `${k01} [data-new]`)).toBe('neu');
    expect(cell(fixture, `${k01} [data-subject]`)).toBe('SAP SE');
  });

  it('names measured value, threshold, data date and what to check', async () => {
    const fixture = await render();
    const k01 = `[data-hint="HIN-K01:${SAP}"]`;
    expect(cell(fixture, `${k01} [data-measured]`)).toContain('26,2 %');
    expect(cell(fixture, `${k01} [data-threshold]`)).toContain('20 %');
    expect(cell(fixture, `${k01} [data-as-of]`)).toContain('20.11.2026');
    expect(cell(fixture, `${k01} [data-approach]`)).toContain('Gewicht und Doppelung');
    expect(cell(fixture, '[data-hint="HIN-K04:DE"] [data-subject]')).toBe('Deutschland');
    expect(cell(fixture, `[data-hint="HIN-E02:${WORLD}+${SPDR}"] [data-subject]`)).toBe(
      'iShares Core MSCI World und SPDR MSCI World',
    );
  });

  it('shows the disclaimer: observations, no advice', async () => {
    const fixture = await render();
    expect(cell(fixture, '[data-disclaimer]')).toContain('keine Anlageempfehlung');
  });

  it('hides acknowledged hints until asked and lists the resolved ones', async () => {
    const fixture = await render();
    expect(keys(fixture, 'open')).not.toContain('HIN-B01:DE0001102580');
    expect(query(fixture, '[data-acknowledged]')).toHaveLength(0);
    query(fixture, 'button[data-action="toggle-acknowledged"]')[0].click();
    fixture.detectChanges();
    expect(keys(fixture, 'acknowledged')).toEqual(['HIN-B01:DE0001102580']);
    expect(cell(fixture, '[data-acknowledged] [data-measured]')).toContain('45 Tage');
    expect(cell(fixture, '[data-resolved]')).toContain('Kurs fehlt oder ist alt');
  });

  it('acknowledges a hint and shows the answer of the server', async () => {
    const fixture = await render();
    const button = query(fixture, `[data-hint="HIN-K01:${SAP}"] button[data-action="ack"]`)[0];
    button.click();
    await settle(fixture);
    const request = TestBed.inject(HttpTestingController).expectOne(
      (r) => r.method === 'POST' && r.url.startsWith(`${URL}/`) && r.url.endsWith('/ack'),
    );
    expect(decodeURIComponent(request.request.url)).toBe(`${URL}/HIN-K01:${SAP}/ack`);
    request.flush(
      hints(LIST.hints.map((h) => (h.rule === 'HIN-K01' ? { ...h, acknowledged: true } : h))),
    );
    await settle(fixture);
    expect(keys(fixture, 'open')).not.toContain(`HIN-K01:${SAP}`);
    expect(text(fixture)).toContain('Zur Kenntnis genommen: Großer Einzeltitel (SAP SE).');
    expect(text(fixture)).toContain('Zur Kenntnis genommen (2)');
  });

  it('is read-only for an archived depot', async () => {
    const fixture = await render(LIST, 200, true);
    expect(query(fixture, 'button[data-action="ack"]')).toHaveLength(0);
    const thresholds = query<HTMLButtonElement>(fixture, 'button[data-action="thresholds"]')[0];
    expect(thresholds.disabled).toBe(true);
  });

  it('says why there are no hints without a run', async () => {
    const fixture = await render(hints([], { analysis_run_id: null, computed_at: null }));
    expect(text(fixture)).toContain('fehlen Kurse oder Stammdaten');
    expect(query(fixture, '[data-open]')).toHaveLength(0);
  });

  it('says so when there is nothing open', async () => {
    const fixture = await render(hints([]));
    expect(cell(fixture, '[data-no-hints]')).toBe('Keine offenen Hinweise.');
  });

  it('names the error when the server is unavailable', async () => {
    const fixture = await render({ detail: 'Depots nicht verfuegbar' }, 503);
    expect(text(fixture)).toContain('nicht erreichbar');
  });

  it('has a tooltip on every control, badge and label', async () => {
    const fixture = await render();
    query(fixture, 'button[data-action="toggle-acknowledged"]')[0].click();
    fixture.detectChanges();
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(headersWithoutScope(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });
});
