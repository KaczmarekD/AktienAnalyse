// Profil-Editor (P3.7 mit den Endpunkten aus P3.3): Formular, Live-Vorschau, Speichern mit
// If-Match, Konflikt (409), Aktivieren. Die Vorschau wartet hier nicht (PREVIEW_DEBOUNCE_MS = 0).
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_FORM_FIELD_DEFAULT_OPTIONS } from '@angular/material/form-field';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { FACTORS, PARAMS, PREVIEW, PROFILE } from '../testing/fixtures';
import { PREVIEW_DEBOUNCE_MS, ProfileEditorPage } from './profile-editor-page';

const DETAIL = '/api/v1/scoring/profiles/1';
const FACTORS_URL = '/api/v1/scoring/factors';
const PREVIEW_URL = '/api/v1/scoring/preview?top=20';
const ACTIVATE = '/api/v1/scoring/profiles/1/activate';

type Fixture = ComponentFixture<ProfileEditorPage>;

function http(): HttpTestingController {
  return TestBed.inject(HttpTestingController);
}

/** Wartet, bis Promises (Validierung im Client) und Effects durch sind. */
async function settle(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
  }
}

async function render(): Promise<Fixture> {
  TestBed.configureTestingModule({
    providers: [...apiTestingProviders(), { provide: PREVIEW_DEBOUNCE_MS, useValue: 0 }],
  });
  const fixture = TestBed.createComponent(ProfileEditorPage);
  fixture.componentRef.setInput('profileId', '1');
  await respond(fixture, FACTORS_URL, FACTORS);
  await respond(fixture, DETAIL, PROFILE);
  await respond(fixture, PREVIEW_URL, PREVIEW); // erste Vorschau mit der neuesten Version
  return fixture;
}

function input(fixture: Fixture, name: string): HTMLInputElement {
  return query<HTMLInputElement>(fixture, `[data-field="${name}"]`)[0];
}

async function type(fixture: Fixture, name: string, value: string): Promise<void> {
  const element = input(fixture, name);
  element.value = value;
  element.dispatchEvent(new Event('input'));
  await settle();
}

async function click(selector: string, fixture: Fixture): Promise<void> {
  query(fixture, selector)[0].click();
  await settle();
}

function expectRequest(url: string, method: string): TestRequest {
  return http().expectOne((r) => r.urlWithParams === url && r.method === method);
}

describe('ProfileEditorPage', () => {
  it('uses form fields with an outline (G1, not in the start bundle)', async () => {
    const fixture = await render();
    expect(fixture.debugElement.injector.get(MAT_FORM_FIELD_DEFAULT_OPTIONS).appearance).toBe(
      'outline',
    );
  });

  it('loads the newest version into the form', async () => {
    const fixture = await render();
    expect(input(fixture, 'value_weight').value).toBe('0.5');
    expect(input(fixture, 'min_market_cap').value).toBe('300000000');
    const content = text(fixture);
    expect(content).toContain('Standard');
    expect(content).toContain('Grundlage: Version 2');
    expect(content).toMatch(/50\s%\sQuality/);
  });

  it('shows the factors with direction and hint', async () => {
    const fixture = await render();
    const content = text(fixture);
    expect(content).toContain('EV/EBIT');
    expect(content).toContain('niedriger ist besser');
    expect(content).toContain('Unternehmenswert zu EBIT.');
    const pb = query<HTMLInputElement>(fixture, '[data-factor="pb"] input[type="checkbox"]')[0];
    expect(pb.checked).toBe(true);
  });

  it('lists the versions with the active one marked', async () => {
    const fixture = await render();
    const [newest, first] = query(fixture, '[data-version]');
    expect(newest.textContent).toContain('mehr Quality');
    expect(query(fixture, '[data-activate="2"]')).toHaveLength(1);
    expect(first.textContent).toContain('aktiv');
    expect(query(fixture, '[data-activate="1"]')).toHaveLength(0);
  });

  it('previews a change against the active profile', async () => {
    const fixture = await render();
    await type(fixture, 'value_weight', '0.4');
    const preview = expectRequest(PREVIEW_URL, 'POST');
    expect(preview.request.body).toEqual({ ...PARAMS, value_weight: 0.4 });
    preview.flush(PREVIEW);
    await settle();
    const content = text(fixture);
    expect(content).toContain('Neu in den Top 20: SAP');
    expect(content).toContain('Nicht mehr in den Top 20: DBK.DE');
    expect(content).toContain('Value-Trap geändert: BASF');
    const sap = query(fixture, 'tr[data-symbol="SAP.DE"]')[0];
    expect(sap.textContent).toContain('↑ 23');
  });

  it('marks value traps in the preview like the ranking does', async () => {
    const fixture = await render();
    const flagged = PREVIEW.rows.find((row) => row.value_trap_flag && row.rank !== null);
    const row = query(fixture, `tr[data-symbol="${flagged?.symbol}"]`)[0];
    expect(row.textContent).toContain('Value-Trap?');
  });

  it('shows a field error and sends no preview for an invalid value', async () => {
    const fixture = await render();
    await type(fixture, 'value_weight', '1.5');
    http().expectNone(PREVIEW_URL);
    const errors = query(fixture, '[data-error="value_weight"]');
    expect(errors).toHaveLength(1);
    // Zod meldet auf Deutsch: Die Sprache laedt der Editor selbst, nicht das Start-Bundle
    expect(errors[0].textContent).toContain('Zu groß');
    const save = query<HTMLButtonElement>(fixture, 'button[data-action="save"]')[0];
    expect(save.disabled).toBe(true);
  });

  it('shows the rule the server checks and blocks saving', async () => {
    const fixture = await render();
    await click('[data-factor="pb"] input[type="checkbox"]', fixture);
    const preview = expectRequest(PREVIEW_URL, 'POST');
    expect(preview.request.body.value_factors).toEqual(['ev_ebit', 'p_fcf', 'shareholder_yield']);
    preview.flush(
      {
        detail: [
          {
            type: 'value_error',
            loc: ['body'],
            msg: 'Value error, value_factors: mindestens 2 aktive Faktoren',
          },
        ],
      },
      { status: 422, statusText: 'Unprocessable Entity' },
    );
    await settle();
    expect(text(fixture)).toContain('value_factors: mindestens 2 aktive Faktoren');
    const save = query<HTMLButtonElement>(fixture, 'button[data-action="save"]')[0];
    expect(save.disabled).toBe(true);
  });

  it('saves a new version on top of the newest one', async () => {
    const fixture = await render();
    await type(fixture, 'value_weight', '0.45');
    expectRequest(PREVIEW_URL, 'POST').flush(PREVIEW);
    await settle();
    await type(fixture, 'comment', 'etwas mehr Quality');
    await click('button[data-action="save"]', fixture);

    const save = expectRequest(DETAIL, 'PUT');
    expect(save.request.headers.get('If-Match')).toBe('"2"');
    expect(save.request.body).toEqual({
      params: { ...PARAMS, value_weight: 0.45 },
      comment: 'etwas mehr Quality',
    });
    save.flush(
      { profile_id: 1, version: 3, parent_version: 2 },
      { status: 201, statusText: 'Created' },
    );
    await settle();
    expectRequest(DETAIL, 'GET').flush({ ...PROFILE, latest_version: 3 });
    await settle();
    expect(query(fixture, '[role="status"]')[0]?.textContent).toContain('Version 3 gespeichert');
  });

  it('says while saving and reports a failed save as alert', async () => {
    const fixture = await render();
    await click('button[data-action="save"]', fixture);
    const button = query<HTMLButtonElement>(fixture, 'button[data-action="save"]')[0];
    expect(button.textContent?.trim()).toBe('Speichert …');

    expectRequest(DETAIL, 'PUT').flush(null, { status: 500, statusText: 'Server Error' });
    await settle();
    expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain(
      'Speichern hat nicht geklappt',
    );
    expect(button.textContent?.trim()).toBe('Als neue Version speichern');
  });

  it('offers a reload after a conflict', async () => {
    const fixture = await render();
    await click('button[data-action="save"]', fixture);
    expectRequest(DETAIL, 'PUT').flush(
      { detail: 'Version 2 ist nicht mehr die neueste (aktuell: 3)' },
      { status: 409, statusText: 'Conflict' },
    );
    await settle();
    expect(text(fixture)).toContain('Inzwischen wurde eine neuere Version gespeichert');

    await click('button[data-action="reload"]', fixture);
    expectRequest(DETAIL, 'GET').flush(PROFILE);
    await settle();
  });

  it('activates a version', async () => {
    const fixture = await render();
    await click('[data-activate="2"]', fixture);
    const activate = expectRequest(ACTIVATE, 'POST');
    expect(activate.request.body).toEqual({ version: 2 });
    activate.flush({ profile_id: 1, version: 2 });
    await settle();
    expectRequest(DETAIL, 'GET').flush({ ...PROFILE, active_version: 2 });
    await settle();
    expect(text(fixture)).toContain('Version 2 ist aktiv');
  });
});
