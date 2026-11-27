// Dialog „Schwellen“ (D5.4, HIN-04): Schwellen in Prozent statt Bruchteilen, Regeln abschalten,
// Regeln für später fehlen, Grenzen und kritisch über Warnung, Speichern mit If-Match, Konflikt
// mit „Neu laden“, Standardwerte.
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';

import { apiTestingProviders } from '../testing/api';
import { CATALOG, PARAMS } from '../testing/depots';
import { HintParamsDialog, SettingsDialogData } from './hint-params-dialog';

const URL = '/api/v1/depots/3/hint-params';

function http(): HttpTestingController {
  return TestBed.inject(HttpTestingController);
}

async function settle(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
  }
}

async function open(): Promise<MatDialogRef<HintParamsDialog, boolean>> {
  TestBed.configureTestingModule({
    providers: [
      ...apiTestingProviders(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
    ],
  });
  const ref = TestBed.inject(MatDialog).open<HintParamsDialog, SettingsDialogData, boolean>(
    HintParamsDialog,
    { data: { depotId: 3 } },
  );
  await settle();
  http()
    .expectOne(URL)
    .flush(PARAMS, { headers: { ETag: '"2"' } });
  http().expectOne('/api/v1/hints/catalog').flush(CATALOG);
  await settle();
  return ref;
}

function el<T extends Element = HTMLElement>(selector: string): T {
  return document.querySelector<T>(`mat-dialog-container ${selector}`)!;
}

function type(selector: string, value: string): void {
  const input = el<HTMLInputElement>(selector);
  input.value = value;
  input.dispatchEvent(new Event('input'));
  TestBed.tick();
}

async function save(): Promise<TestRequest> {
  el('button[data-action="save"]').click();
  await settle();
  return http().expectOne((r) => r.url === URL && r.method === 'PUT');
}

describe('HintParamsDialog', () => {
  afterEach(() => TestBed.inject(MatDialog).closeAll());

  it('shows the thresholds in percent and the rules that are computed', async () => {
    await open();
    expect(el<HTMLInputElement>('[data-field="k01_warning"]').value).toBe('15');
    expect(el<HTMLInputElement>('[data-field="k01_critical"]').value).toBe('25');
    // Ohne gespeicherten Wert der Standard
    expect(el<HTMLInputElement>('[data-field="a02_cash"]').value).toBe('10');
    expect(el('[data-rule="HIN-N01"]')).toBeNull();
    expect(el('[data-rule="HIN-Q01"]').textContent).toContain('ohne Schwelle');
    const q01 = el<HTMLInputElement>('[data-toggle="HIN-Q01"] input');
    expect(q01.checked).toBe(false);
  });

  it('saves on the loaded version, keeps the rules for later and closes', async () => {
    const ref = await open();
    let closedWith: boolean | undefined;
    ref.afterClosed().subscribe((saved) => (closedWith = saved));
    type('[data-field="a02_cash"]', '12,5');
    el<HTMLInputElement>('[data-toggle="HIN-A02"] input').click();
    TestBed.tick();
    const request = await save();
    expect(request.request.headers.get('if-match')).toBe('"2"');
    const body = request.request.body as Record<string, unknown>;
    expect(body['a02_cash']).toBe(0.125);
    expect(body['k01_warning']).toBe(0.15);
    expect(body['disabled']).toEqual(['HIN-Q01', 'HIN-N01', 'HIN-A02']);
    request.flush({ ...PARAMS, version: 3 });
    await settle();
    expect(closedWith).toBe(true);
  });

  it('checks the bounds and that critical lies above the warning', async () => {
    await open();
    type('[data-field="k01_critical"]', '10');
    type('[data-field="d01_trading_days"]', '2,5');
    type('[data-field="a02_cash"]', '120');
    el('button[data-action="save"]').click();
    await settle();
    http().expectNone((r) => r.method === 'PUT');
    expect(el('[data-error="k01_critical"]').textContent).toContain('über der Warnung');
    expect(el('[data-error="d01_trading_days"]').textContent).toContain('ganze Zahlen');
    expect(el('[data-error="a02_cash"]').textContent).toContain('bis 100');
  });

  it('offers a reload after a conflict', async () => {
    await open();
    (await save()).flush(
      { detail: 'Inzwischen gibt es Version 3' },
      { status: 409, statusText: 'Conflict' },
    );
    await settle();
    expect(el('[data-conflict]').textContent).toContain('neuere Schwellen');
    el('button[data-action="reload"]').click();
    await settle();
    http()
      .expectOne(URL)
      .flush({ ...PARAMS, version: 3, params: { k01_warning: 0.3, k01_critical: 0.4 } });
    http().expectOne('/api/v1/hints/catalog').flush(CATALOG);
    await settle();
    expect(el<HTMLInputElement>('[data-field="k01_warning"]').value).toBe('30');
    expect(el('[data-conflict]')).toBeNull();
  });

  it('resets to the defaults of the catalog', async () => {
    await open();
    el('button[data-action="defaults"]').click();
    TestBed.tick();
    expect(el<HTMLInputElement>('[data-field="k01_warning"]').value).toBe('10');
    expect(el<HTMLInputElement>('[data-toggle="HIN-Q01"] input').checked).toBe(true);
  });
});
