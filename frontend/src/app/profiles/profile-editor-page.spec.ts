// Profil-Editor (P3.7 mit den Endpunkten aus P3.3, neu gestaltet mit Track G, G7): Formular in
// Prozent und Mio. €, Live-Vorschau mit Zusammenfassung, Speichern-Leiste mit Grund im Tooltip,
// Speichern mit If-Match, Konflikt (409), Aktivieren. Die Vorschau wartet hier nicht
// (PREVIEW_DEBOUNCE_MS = 0).
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_FORM_FIELD_DEFAULT_OPTIONS } from '@angular/material/form-field';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { FACTORS, PARAMS, PREVIEW, PROFILE } from '../testing/fixtures';
import {
  abbreviationsWithoutExplanation,
  controlsWithoutTooltip,
  headersWithoutScope,
} from '../testing/tooltips';
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

function tooltip(fixture: Fixture, element: Element | undefined): string | undefined {
  return fixture.debugElement
    .queryAll(By.directive(MatTooltip))
    .find((debug) => debug.nativeElement === element)
    ?.injector.get(MatTooltip).message;
}

function saveButton(fixture: Fixture): HTMLButtonElement {
  return query<HTMLButtonElement>(fixture, 'button[data-action="save"]')[0];
}

/** Ändert die Gewichtung und beantwortet die Vorschau, wie es ein Nutzer täte. */
async function change(fixture: Fixture, percent = '45'): Promise<void> {
  await type(fixture, 'value_weight', percent);
  expectRequest(PREVIEW_URL, 'POST').flush(PREVIEW);
  await settle();
}

describe('ProfileEditorPage', () => {
  it('uses form fields with an outline (G1, not in the start bundle)', async () => {
    const fixture = await render();
    expect(fixture.debugElement.injector.get(MAT_FORM_FIELD_DEFAULT_OPTIONS).appearance).toBe(
      'outline',
    );
  });

  it('loads the newest version into the form, in percent and million euros', async () => {
    const fixture = await render();
    // Die Ansicht rechnet um, das Modell bleibt 0 bis 1 und Euro (Spec, Profil-Editor)
    expect(input(fixture, 'value_weight').value).toBe('50');
    expect(input(fixture, 'min_market_cap').value).toBe('300');
    expect(input(fixture, 'min_value_factor_share').value).toBe('50');
    const content = text(fixture);
    expect(query(fixture, 'h1')[0].textContent).toContain('Standard');
    expect(query(fixture, 'h1')[0].textContent).toContain('aktiv: Version 1');
    expect(content).toContain('Grundlage: Version 2. Speichern legt Version 3 an.');
    expect(content).toMatch(/50\s%\sValue · 50\s%\sQuality/);
  });

  it('keeps the rarely changed fields under Erweitert, closed', async () => {
    const fixture = await render();
    const advanced = query(fixture, 'mat-expansion-panel[data-panel="advanced"]')[0];
    expect(advanced.classList).not.toContain('mat-expanded');
    for (const field of [
      'min_value_factor_share',
      'min_quality_factor_share',
      'value_trap_value_threshold',
      'value_trap_quality_threshold',
    ]) {
      expect(advanced.querySelector(`[data-field="${field}"]`)).not.toBeNull();
    }
    expect(advanced.textContent).toContain('Negative Multiples ausschließen');
  });

  it('shows the factors with direction and hint', async () => {
    const fixture = await render();
    const content = text(fixture);
    expect(content).toContain('EV/EBIT');
    expect(content).toContain('niedriger ist besser');
    expect(content).toContain('Unternehmenswert (Börsenwert plus Nettoschulden)');
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

  it('previews a change against the active profile with a summary', async () => {
    const fixture = await render();
    await type(fixture, 'value_weight', '40');
    const preview = expectRequest(PREVIEW_URL, 'POST');
    expect(preview.request.body).toEqual({ ...PARAMS, value_weight: 0.4 });
    preview.flush(PREVIEW);
    await settle();
    expect(text(fixture)).toContain('Abruf 30.10.2026, verglichen mit Standard, Version 1');
    const summary = (name: string) => query(fixture, `[data-summary="${name}"]`)[0];
    expect(summary('entered').textContent?.trim()).toBe('1 neu in den Top 20');
    expect(tooltip(fixture, summary('entered'))).toContain('SAP');
    expect(summary('left').textContent?.trim()).toBe('1 nicht mehr in den Top 20');
    expect(tooltip(fixture, summary('left'))).toContain('DBK.DE');
    expect(summary('trap').textContent?.trim()).toBe('1 Value-Trap geändert');
    expect(tooltip(fixture, summary('trap'))).toContain('BASF');
  });

  it('shows the rank change as arrow with an explanation', async () => {
    const fixture = await render();
    const delta = query(fixture, 'tr[data-symbol="SAP.DE"] [data-delta]')[0];
    expect(delta.textContent?.trim()).toBe('23');
    expect(delta.querySelector('app-icon svg')).not.toBeNull();
    expect(tooltip(fixture, delta)).toBe('23 Plätze besser als mit dem aktiven Profil (Rang 25).');
    const same = query(fixture, 'tr[data-symbol="ALV.DE"] [data-delta]')[0];
    expect(tooltip(fixture, same)).toBe('Gleicher Rang wie mit dem aktiven Profil.');
  });

  it('converts percent and million euros back for the model', async () => {
    const fixture = await render();
    await type(fixture, 'min_market_cap', '500');
    expect(expectRequest(PREVIEW_URL, 'POST').request.body.min_market_cap).toBe(500_000_000);
    await type(fixture, 'min_value_factor_share', '60');
    expect(expectRequest(PREVIEW_URL, 'POST').request.body.min_value_factor_share).toBe(0.6);
  });

  it('marks value traps in the preview like the ranking does', async () => {
    const fixture = await render();
    const flagged = PREVIEW.rows.find((row) => row.value_trap_flag && row.rank !== null);
    const row = query(fixture, `tr[data-symbol="${flagged?.symbol}"]`)[0];
    expect(row.textContent).toContain('Value-Trap?');
  });

  it('shows a field error in the unit of the field and sends no preview', async () => {
    const fixture = await render();
    await type(fixture, 'value_trap_value_threshold', '1.5');
    http().expectNone(PREVIEW_URL);
    const errors = query(fixture, '[data-error="value_trap_value_threshold"]');
    expect(errors).toHaveLength(1);
    expect(errors[0].textContent?.trim()).toBe('Wert zwischen 0 und 1.');
    expect(saveButton(fixture).getAttribute('aria-disabled')).toBe('true');
    expect(tooltip(fixture, saveButton(fixture))).toBe(
      'Erst speichern, wenn alle Felder gültig sind.',
    );

    await type(fixture, 'value_trap_value_threshold', '0.7');
    await type(fixture, 'min_value_factor_share', '120');
    expect(query(fixture, '[data-error="min_value_factor_share"]')[0].textContent?.trim()).toBe(
      'Wert zwischen 0 und 100 %.',
    );
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
    expect(saveButton(fixture).getAttribute('aria-disabled')).toBe('true');
    expect(tooltip(fixture, saveButton(fixture))).toContain('wenn die Regel oben erfüllt ist');
  });

  it('pins the save bar once something changed and says what saving does', async () => {
    const fixture = await render();
    const bar = query(fixture, '[data-bar="save"]')[0];
    expect(bar.classList).not.toContain('sticky-bar');
    expect(saveButton(fixture).getAttribute('aria-disabled')).toBe('true');
    expect(tooltip(fixture, saveButton(fixture))).toContain('Nichts zu speichern');

    await change(fixture);
    expect(bar.classList).toContain('sticky-bar');
    expect(saveButton(fixture).getAttribute('aria-disabled')).not.toBe('true');
    expect(tooltip(fixture, saveButton(fixture))).toBe(
      'Legt Version 3 an. Aktiv wird sie erst mit „Aktivieren“.',
    );
  });

  it('discards the changes back to the base version', async () => {
    const fixture = await render();
    await change(fixture);
    await type(fixture, 'comment', 'verworfen');
    const discard = query<HTMLButtonElement>(fixture, 'button[data-action="discard"]')[0];
    expect(tooltip(fixture, discard)).toBe('Setzt alle Felder auf Version 2 zurück.');
    discard.click();
    await settle();
    fixture.detectChanges();
    expect(input(fixture, 'value_weight').value).toBe('50');
    expect(input(fixture, 'comment').value).toBe('');
    expect(query(fixture, '[data-bar="save"]')[0].classList).not.toContain('sticky-bar');
    // Zurück auf der Grundlage: dieselbe Vorschau wie am Anfang
    expectRequest(PREVIEW_URL, 'POST').flush(PREVIEW);
  });

  it('saves a new version on top of the newest one', async () => {
    const fixture = await render();
    await change(fixture, '45');
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
    await change(fixture);
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
    await change(fixture);
    await click('button[data-action="save"]', fixture);
    expectRequest(DETAIL, 'PUT').flush(
      { detail: 'Version 2 ist nicht mehr die neueste (aktuell: 3)' },
      { status: 409, statusText: 'Conflict' },
    );
    await settle();
    expect(text(fixture)).toContain('Inzwischen wurde eine neuere Version gespeichert');
    const reload = query(fixture, 'button[data-action="reload"]')[0];
    expect(tooltip(fixture, reload)).toContain('Deine Änderungen hier gehen verloren');

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

  it('explains every control, label and abbreviation (tests 1 and 2)', async () => {
    const fixture = await render();
    await change(fixture);
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
    // Spaltenköpfe mit scope (Spec, Barrierefreiheit)
    expect(headersWithoutScope(fixture)).toEqual([]);
  });
});
