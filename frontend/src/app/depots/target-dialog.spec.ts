// Dialog „Zielallokation“ (D5.4, DEP-10): Anteile in Prozent, zusammen 100 % oder leer für „ohne
// Ziel“, Speichern mit If-Match, Konflikt.
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';

import { apiTestingProviders } from '../testing/api';
import type { SettingsDialogData } from './hint-params-dialog';
import { TargetDialog } from './target-dialog';

const URL = '/api/v1/depots/3/target-allocation';

function http(): HttpTestingController {
  return TestBed.inject(HttpTestingController);
}

async function settle(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
  }
}

async function open(
  shares: Record<string, number> = { equity: 0.6, bond: 0.3, cash: 0.1 },
): Promise<MatDialogRef<TargetDialog, boolean>> {
  TestBed.configureTestingModule({
    providers: [
      ...apiTestingProviders(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
    ],
  });
  const ref = TestBed.inject(MatDialog).open<TargetDialog, SettingsDialogData, boolean>(
    TargetDialog,
    { data: { depotId: 3 } },
  );
  await settle();
  http().expectOne(URL).flush({ version: 1, shares });
  await settle();
  return ref;
}

function el<T extends Element = HTMLElement>(selector: string): T {
  return document.querySelector<T>(`mat-dialog-container ${selector}`)!;
}

/** Text ohne geschützte Leerzeichen: Die Pipes schreiben eins vor das Prozentzeichen. */
function content(selector: string): string {
  return (el(selector).textContent ?? '').replace(/\s+/g, ' ');
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

describe('TargetDialog', () => {
  afterEach(() => TestBed.inject(MatDialog).closeAll());

  it('shows the target in percent with its sum', async () => {
    await open();
    expect(el<HTMLInputElement>('[data-field="equity"]').value).toBe('60');
    expect(el<HTMLInputElement>('[data-field="etf"]').value).toBe('');
    expect(content('[data-sum]')).toContain('100 %');
  });

  it('saves the shares as fractions on the loaded version and closes', async () => {
    const ref = await open();
    let closedWith: boolean | undefined;
    ref.afterClosed().subscribe((saved) => (closedWith = saved));
    type('[data-field="equity"]', '50');
    type('[data-field="etf"]', '10');
    const request = await save();
    expect(request.request.headers.get('if-match')).toBe('"1"');
    expect(request.request.body).toEqual({
      shares: { equity: 0.5, etf: 0.1, bond: 0.3, cash: 0.1 },
    });
    request.flush({ version: 2, shares: request.request.body.shares });
    await settle();
    expect(closedWith).toBe(true);
  });

  it('needs 100 % together', async () => {
    await open();
    type('[data-field="equity"]', '70');
    el('button[data-action="save"]').click();
    await settle();
    http().expectNone((r) => r.method === 'PUT');
    expect(content('[data-error="sum"]')).toContain('100 %');
    expect(content('[data-sum]')).toContain('110 %');
  });

  it('saves an empty target as "without target"', async () => {
    await open();
    el('button[data-action="clear"]').click();
    TestBed.tick();
    const request = await save();
    expect(request.request.body).toEqual({ shares: {} });
  });

  it('offers a reload after a conflict', async () => {
    await open();
    (await save()).flush({ detail: 'Version 2' }, { status: 409, statusText: 'Conflict' });
    await settle();
    expect(el('[data-conflict]').textContent).toContain('neuere Zielallokation');
  });
});
