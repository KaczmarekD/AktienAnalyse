// Profilliste (P3.7, neu gestaltet mit Track G, G7): je Profil eine Karte mit aktiver und
// neuester Version und dem Weg in den Editor.
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { PROFILES } from '../testing/fixtures';
import { abbreviationsWithoutExplanation, controlsWithoutTooltip } from '../testing/tooltips';
import { ProfilesPage } from './profiles-page';

const URL = '/api/v1/scoring/profiles';

type Fixture = ComponentFixture<ProfilesPage>;

function render(): Fixture {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  return TestBed.createComponent(ProfilesPage);
}

function tooltip(fixture: Fixture, element: Element | undefined): string | undefined {
  return fixture.debugElement
    .queryAll(By.directive(MatTooltip))
    .find((debug) => debug.nativeElement === element)
    ?.injector.get(MatTooltip).message;
}

function card(fixture: Fixture, id: number): string {
  return (query(fixture, `[data-profile="${id}"]`)[0]?.textContent ?? '').replace(/\s+/g, ' ');
}

describe('ProfilesPage', () => {
  it('says what a profile is and which version counts', async () => {
    const fixture = render();
    await respond(fixture, URL, PROFILES);
    expect(text(fixture)).toContain(
      'Ein Profil legt fest, welche Faktoren zählen und wie Value und Quality gewichtet werden.',
    );
    expect(text(fixture)).toContain('Der nächste Lauf rechnet mit der aktiven Version.');
  });

  it('shows one card per profile with active and newest version', async () => {
    const fixture = render();
    await respond(fixture, URL, PROFILES);
    const standard = card(fixture, 1);
    expect(standard).toContain('Standard');
    expect(standard).toContain('aktiv: Version 1');
    expect(standard).toContain('neueste: Version 2, nicht aktiv');
    expect(standard).toContain('angelegt am 31.10.2026');
    const latest = query(fixture, '[data-profile="1"] [data-latest]')[0];
    expect(tooltip(fixture, latest)).toContain('erst, wenn du sie im Editor aktivierst');
  });

  it('names the newest version only when it is not the active one', async () => {
    const fixture = render();
    await respond(fixture, URL, [{ ...PROFILES[0], latest_version: 1, active_version: 1 }]);
    expect(card(fixture, 1)).toContain('aktiv: Version 1');
    expect(card(fixture, 1)).not.toContain('neueste');
  });

  it('marks a profile that was never activated', async () => {
    const fixture = render();
    await respond(fixture, URL, PROFILES);
    const defensive = card(fixture, 2);
    expect(defensive).toContain('Defensiv');
    expect(defensive).not.toContain('aktiv: Version');
    expect(defensive).toContain('neueste: Version 1, nicht aktiv');
  });

  it('opens the editor with Bearbeiten', async () => {
    const fixture = render();
    await respond(fixture, URL, PROFILES);
    const edit = query<HTMLAnchorElement>(fixture, '[data-profile="1"] a[data-action="edit"]')[0];
    expect(edit.getAttribute('href')).toBe('/profiles/1');
    expect(edit.textContent?.trim()).toBe('Bearbeiten');
  });

  it('explains where the first profile comes from', async () => {
    const fixture = render();
    await respond(fixture, URL, []);
    expect(text(fixture)).toContain('Noch kein Profil. „Standard“ entsteht mit dem ersten Lauf.');
  });

  it('says when the server is not reachable', async () => {
    const fixture = render();
    await respond(fixture, URL, null, 503);
    expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain('nicht erreichbar');
  });

  it('explains every control, badge and abbreviation (tests 1 and 2)', async () => {
    const fixture = render();
    await respond(fixture, URL, PROFILES);
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });
});
