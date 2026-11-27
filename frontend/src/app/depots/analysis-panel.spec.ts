// Analyse eines Depots (D4.5, ANA-05, 07 bis 09): Qualität, Allokation mit Durchschau,
// Konzentration, Kosten, Anleihen und Datenlage; „keine Daten“ statt Ersatzwerten, „mindestens“
// bei unvollständigen ETF-Listen, Fehler ohne Marktdaten.
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { analysis, BUND, FLOATER, WORLD } from '../testing/depots';
import {
  abbreviationsWithoutExplanation,
  controlsWithoutTooltip,
  headersWithoutScope,
} from '../testing/tooltips';
import { AnalysisPanel } from './analysis-panel';

const URL = '/api/v1/depots/3/analysis';

async function render(
  body: object = analysis(),
  status = 200,
): Promise<ComponentFixture<AnalysisPanel>> {
  TestBed.configureTestingModule({
    providers: [
      ...apiTestingProviders(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
    ],
  });
  const fixture = TestBed.createComponent(AnalysisPanel);
  fixture.componentRef.setInput('depotId', 3);
  fixture.componentRef.setInput('names', {
    [WORLD]: 'iShares Core MSCI World',
    [BUND]: 'Bund 2033',
    [FLOATER]: 'Floater 2029',
  });
  await respond(fixture, URL, body, status);
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
    fixture.detectChanges();
  }
  return fixture;
}

function cell(fixture: ComponentFixture<AnalysisPanel>, selector: string): string {
  return (query(fixture, selector)[0]?.textContent ?? '').replace(/\s+/g, ' ').trim();
}

describe('AnalysisPanel', () => {
  it('shows the value weighted scores, the value traps and the quintiles', async () => {
    const fixture = await render();
    expect(cell(fixture, '[data-composite]')).toContain('0,52');
    expect(cell(fixture, '[data-covered]')).toContain('100 %');
    expect(cell(fixture, '[data-value-traps]')).toContain('1');
    expect(cell(fixture, '[data-quintile="1"]')).toContain('unterstes Fünftel');
    expect(cell(fixture, '[data-quintile="4"]')).toContain('60 %');
  });

  it('names sectors and countries in German, with look-through', async () => {
    const fixture = await render();
    expect(cell(fixture, '[data-dimension="sector"] [data-slice="Technology"]')).toContain(
      'Technologie',
    );
    expect(cell(fixture, '[data-dimension="sector"] [data-slice="unknown"]')).toContain(
      'ohne Angabe',
    );
    expect(cell(fixture, '[data-dimension="country"] [data-slice="US"]')).toContain(
      'Vereinigte Staaten',
    );
    expect(cell(fixture, '[data-dimension="country"] [data-slice="XS"]')).toContain(
      'international',
    );
    expect(cell(fixture, '[data-dimension="country"] [data-slice="no_look_through"]')).toContain(
      'ohne Durchschau',
    );
    expect(cell(fixture, '[data-dimension="asset_class"] [data-slice="cash"]')).toContain('Kasse');
  });

  it('says "mindestens" when an ETF only knows its largest positions', async () => {
    const fixture = await render();
    expect(cell(fixture, '[data-top]')).toContain('mindestens');
    expect(cell(fixture, '[data-largest]')).toContain('SAP SE');
    expect(cell(fixture, `[data-fund="${WORLD}"]`)).toContain('iShares Core MSCI World');
    expect(cell(fixture, `[data-fund="${WORLD}"]`)).toContain('keine Daten');
  });

  it('shows costs and bonds, a floater without yield', async () => {
    const fixture = await render();
    expect(cell(fixture, '[data-ter]')).toContain('0,20 %');
    expect(cell(fixture, '[data-running-costs]')).toContain('4,00 €');
    expect(cell(fixture, '[data-ytm]')).toContain('3,01');
    expect(cell(fixture, `[data-bond="${BUND}"]`)).toContain('15.08.2027');
    expect(cell(fixture, `[data-bond="${FLOATER}"] [data-special]`)).toContain('variabel verzinst');
  });

  it('writes "keine Daten" instead of a substitute value', async () => {
    const empty = analysis();
    const fixture = await render({
      ...empty,
      quality: { ...empty.quality, composite: null, value_score: null, quality_score: null },
    });
    expect(cell(fixture, '[data-composite]')).toContain('keine Daten');
  });

  it('names the data behind the numbers', async () => {
    const fixture = await render();
    expect(cell(fixture, '[data-valued]')).toContain('4 von 5 Positionen');
    expect(text(fixture)).toContain('19.11.2026');
  });

  it('says why there is no analysis without market data', async () => {
    const fixture = await render({ detail: 'Analyse ohne Marktdaten nicht moeglich' }, 503);
    expect(query(fixture, '[data-quality]')).toHaveLength(0);
    expect(text(fixture)).toContain('nicht erreichbar');
  });

  it('has a tooltip on every label and header', async () => {
    const fixture = await render();
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(headersWithoutScope(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });
});
