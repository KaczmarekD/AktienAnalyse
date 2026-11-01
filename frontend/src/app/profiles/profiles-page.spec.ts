// Profilliste (P3.7): Profile mit neuester Version, das aktive markiert, Link zum Editor.
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { PROFILES } from '../testing/fixtures';
import { ProfilesPage } from './profiles-page';

const URL = '/api/v1/scoring/profiles';

async function render(): Promise<ComponentFixture<ProfilesPage>> {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  return TestBed.createComponent(ProfilesPage);
}

describe('ProfilesPage', () => {
  it('lists profiles with newest version and marks the active one', async () => {
    const fixture = await render();
    await respond(fixture, URL, PROFILES);
    const [standard, defensive] = query(fixture, '[data-profile]');
    expect(standard.textContent).toContain('Standard');
    expect(standard.textContent).toContain('v2');
    expect(standard.textContent).toContain('aktiv: v1');
    expect(defensive.textContent).toContain('Defensiv');
    expect(defensive.textContent).not.toContain('aktiv');
  });

  it('links each profile to its editor', async () => {
    const fixture = await render();
    await respond(fixture, URL, PROFILES);
    const link = query<HTMLAnchorElement>(fixture, '[data-profile="1"] a')[0];
    expect(link.getAttribute('href')).toBe('/profiles/1');
  });

  it('explains where the first profile comes from', async () => {
    const fixture = await render();
    await respond(fixture, URL, []);
    expect(text(fixture)).toContain('entsteht mit dem ersten Lauf');
  });
});
