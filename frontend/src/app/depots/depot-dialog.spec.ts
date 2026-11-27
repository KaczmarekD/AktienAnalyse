// Dialog „Neues Depot“ und „Depot umbenennen“ (D3.6, DEP-01): Er speichert selbst, schließt sich
// mit der Nummer des Depots und bleibt bei einem Fehler mit dem Grund offen.
import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDialog, MatDialogRef } from '@angular/material/dialog';

import { apiTestingProviders } from '../testing/api';
import { depot } from '../testing/depots';
import { DepotDialog } from './depot-dialog';

function open(data: object = {}): MatDialogRef<DepotDialog, number> {
  TestBed.configureTestingModule({
    providers: [
      ...apiTestingProviders(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
    ],
  });
  const ref = TestBed.inject(MatDialog).open<DepotDialog, object, number>(DepotDialog, { data });
  TestBed.tick();
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

async function settle(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
  }
}

describe('DepotDialog', () => {
  afterEach(() => TestBed.inject(MatDialog).closeAll());

  it('creates a watchlist and closes with its id', async () => {
    const ref = open();
    let closedWith: number | undefined;
    ref.afterClosed().subscribe((id) => (closedWith = id));
    type('[data-field="name"]', '  Ideen ');
    el('[data-option="watchlist"] input').click();
    el('button[data-action="save"]').click();
    await settle();
    const request = TestBed.inject(HttpTestingController).expectOne('/api/v1/depots');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ name: 'Ideen', kind: 'watchlist', description: null });
    request.flush(depot({ id: 7, name: 'Ideen', kind: 'watchlist' }), {
      status: 201,
      statusText: 'Created',
    });
    await settle();
    expect(closedWith).toBe(7);
  });

  it('needs a name', async () => {
    open();
    el('button[data-action="save"]').click();
    await settle();
    TestBed.inject(HttpTestingController).expectNone('/api/v1/depots');
    expect(document.body.textContent).toContain('Der Name fehlt.');
  });

  it('renames a depot without asking for the kind', async () => {
    open({ depot: depot({ id: 3, name: 'DKB', description: 'alt' }) });
    expect(el('h2').textContent).toContain('Depot umbenennen');
    expect(el('[data-option="watchlist"]')).toBeNull();
    type('[data-field="name"]', 'Rente');
    el('button[data-action="save"]').click();
    await settle();
    const request = TestBed.inject(HttpTestingController).expectOne('/api/v1/depots/3');
    expect(request.request.method).toBe('PUT');
    expect(request.request.body).toEqual({ name: 'Rente', description: 'alt' });
  });

  it('stays open and names the reason when the server refuses', async () => {
    const ref = open();
    let closed = false;
    ref.afterClosed().subscribe(() => (closed = true));
    type('[data-field="name"]', 'DKB');
    el('button[data-action="save"]').click();
    await settle();
    TestBed.inject(HttpTestingController)
      .expectOne('/api/v1/depots')
      .flush({ detail: 'Der Name hat hoechstens 100 Zeichen' }, { status: 422, statusText: 'x' });
    await settle();
    expect(closed).toBe(false);
    expect(document.body.textContent).toContain('Der Name hat hoechstens 100 Zeichen');
  });
});
