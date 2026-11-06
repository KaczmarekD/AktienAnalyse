// Seite „Begriffe“ (Track G, G2): jeder Begriff mit dem Text des Tooltips, Anker, Suche und wie das
// Ranking entsteht.
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { GROUPS } from '../shared/glossary/glossary';
import { apiTestingProviders, query, respond, text } from '../testing/api';
import { FACTORS, RANKING } from '../testing/fixtures';
import { controlsWithoutTooltip } from '../testing/tooltips';
import { GlossaryPage } from './glossary-page';

const FACTORS_URL = '/api/v1/scoring/factors';
const LATEST = '/api/v1/ranking/latest';

async function render(): Promise<ComponentFixture<GlossaryPage>> {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  const fixture = TestBed.createComponent(GlossaryPage);
  await respond(fixture, FACTORS_URL, FACTORS);
  await respond(fixture, LATEST, RANKING);
  return fixture;
}

async function search(fixture: ComponentFixture<GlossaryPage>, value: string): Promise<void> {
  const input = query<HTMLInputElement>(fixture, 'input[type="search"]')[0];
  input.value = value;
  input.dispatchEvent(new Event('input'));
  await new Promise((resolve) => setTimeout(resolve));
  fixture.detectChanges();
}

describe('GlossaryPage', () => {
  it('lists the terms by group with the tooltip text and the role in the score', async () => {
    const fixture = await render();
    const headings = query(fixture, 'h2').map((h) => h.textContent?.trim());
    expect(headings).toEqual([...GROUPS, 'So entsteht das Ranking']);
    const pb = query(fixture, 'dt#pb')[0];
    expect(pb.textContent).toContain('KBV');
    const explanation = pb.nextElementSibling?.textContent ?? '';
    expect(explanation).toContain('Kurs-Buchwert-Verhältnis');
    expect(explanation).toContain('Value-Faktor');
  });

  it('has an anchor for every term, e.g. /glossary#roic', async () => {
    const fixture = await render();
    expect(query(fixture, 'dt#roic')).toHaveLength(1);
    expect(query(fixture, 'dt#status\\.failed')).toHaveLength(1);
  });

  it('filters by the search text and says when nothing matches', async () => {
    const fixture = await render();
    await search(fixture, 'kapital');
    const terms = query(fixture, 'dt').map((dt) => dt.id);
    expect(terms).toContain('roic');
    expect(terms).not.toContain('isin');

    await search(fixture, 'xyz');
    expect(query(fixture, 'dt')).toHaveLength(0);
    expect(text(fixture)).toContain('Kein Begriff passt zur Suche.');
  });

  it('explains the ranking with the weights of the latest scoring run', async () => {
    const fixture = await render();
    const method = text(fixture);
    expect(method).toContain('60 % Value und 40 % Quality');
    expect(method).toContain('keine Anlageempfehlung');
  });

  it('gives every control a tooltip (test 1)', async () => {
    expect(controlsWithoutTooltip(await render())).toEqual([]);
  });
});
