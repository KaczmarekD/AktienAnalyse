// Läufe (P3.7, Echtzeit P4.6, Start P4.7, neu gestaltet mit Track G, G6): Lief der letzte Lauf
// sauber? Start über einen Dialog mit zwei Mail-Optionen (Entscheidung E3).
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDialog } from '@angular/material/dialog';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { Dispatcher } from '@ngrx/signals/events';

import { serverEvents } from '../shared/realtime/realtime.events';
import { apiTestingProviders, query, respond, text } from '../testing/api';
import { me, provideAuthTesting } from '../testing/auth';
import { run } from '../testing/fixtures';
import {
  abbreviationsWithoutExplanation,
  controlsWithoutTooltip,
  headersWithoutScope,
} from '../testing/tooltips';
import { RunsPage } from './runs-page';

const RUNS = '/api/v1/runs?limit=50';
const START = '/api/v1/runs';

type Fixture = ComponentFixture<RunsPage>;

function expectRequest(url: string, method: string): TestRequest {
  return TestBed.inject(HttpTestingController).expectOne(
    (r) => r.urlWithParams === url && r.method === method,
  );
}

/** Wartet, bis Promises, Effects und Animationen des Dialogs durch sind. */
async function settle(fixture: Fixture): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
    fixture.detectChanges();
  }
}

function dialog(): HTMLElement | null {
  return document.querySelector('mat-dialog-container');
}

function inDialog<T extends Element = HTMLElement>(selector: string): T | null {
  return dialog()?.querySelector<T>(selector) ?? null;
}

async function openStart(fixture: Fixture): Promise<void> {
  query(fixture, 'button[data-action="open-start"]')[0].click();
  await settle(fixture);
}

async function confirm(fixture: Fixture): Promise<TestRequest> {
  inDialog<HTMLButtonElement>('button[data-action="start"]')?.click();
  await settle(fixture);
  return expectRequest(START, 'POST');
}

function tooltip(fixture: Fixture, element: Element | undefined): string | undefined {
  return fixture.debugElement
    .queryAll(By.directive(MatTooltip))
    .find((debug) => debug.nativeElement === element)
    ?.injector.get(MatTooltip).message;
}

function render(): Fixture {
  TestBed.configureTestingModule({
    // Ohne Animationen öffnet und schließt der Dialog ohne Wartezeit
    providers: [
      ...apiTestingProviders(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
    ],
  });
  return TestBed.createComponent(RunsPage);
}

describe('RunsPage', () => {
  afterEach(() => TestBed.inject(MatDialog).closeAll());

  it('offers the start only to admins (D1.4)', async () => {
    TestBed.configureTestingModule({
      providers: [...apiTestingProviders(), provideAuthTesting({ user: me() })],
    });
    const fixture = TestBed.createComponent(RunsPage);
    await respond(fixture, RUNS, [run({ id: 1 })]);
    expect(query(fixture, 'button[data-action="open-start"]').length).toBe(0);
    expect(query(fixture, 'tr[data-run]').length).toBe(1);
  });

  it('lists runs with start, duration, status, counts, kind and marks', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [
      run({ id: 2, dry_run: true, force_refresh: true, status: 'success', scored_count: 90 }),
      run({ id: 1 }),
    ]);
    const rows = query(fixture, 'tr[data-run]');
    expect(rows.map((r) => r.getAttribute('data-run'))).toEqual(['2', '1']);
    expect(rows[0].textContent).toContain('Probelauf');
    expect(rows[0].textContent).toContain('neu abgerufen');
    expect(rows[0].textContent).toContain('erfolgreich');
    const older = (rows[1].textContent ?? '').replace(/\s+/g, ' ');
    expect(older).toContain('teilweise');
    expect(older).toContain('88/90');
    expect(older).toContain('30.10.2026');
    expect(older).toContain('5 min');
    expect(older).toContain('Abruf und Bewertung');
    // Der Exit-Code steht nur noch im Lauf-Detail
    expect(query(fixture, 'th').map((th) => th.textContent?.trim())).not.toContain('Exit');
  });

  it('links each run to its detail page', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [run({ id: 1 })]);
    const link = query<HTMLAnchorElement>(fixture, 'tr[data-run="1"] a')[0];
    expect(link.getAttribute('href')).toBe('/runs/1');
  });

  it('sums up the latest finished run with a link to its ranking', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [
      run({ id: 3, status: 'running', finished_at: null, scored_count: null }),
      run({ id: 2 }),
    ]);
    await respond(fixture, '/api/v1/runs/2', run({ id: 2, scoring_run_id: 7 }));
    const card = (query(fixture, '[data-card="last-run"]')[0]?.textContent ?? '').replace(
      /\s+/g,
      ' ',
    );
    expect(card).toContain('#2');
    expect(card).toContain('teilweise');
    expect(card).toContain('88 von 90 bewertet, 2 fehlgeschlagen');
    const link = query<HTMLAnchorElement>(
      fixture,
      '[data-card="last-run"] a[data-action="ranking"]',
    )[0];
    expect(link.getAttribute('href')).toBe('/ranking/7');
  });

  it('says when there are no runs yet', async () => {
    const fixture = render();
    await respond(fixture, RUNS, []);
    expect(text(fixture)).toContain(
      'Noch keine Läufe. Der erste startet mit „Lauf starten“ oder zum geplanten Termin.',
    );
  });

  it('says when the server is not reachable', async () => {
    const fixture = render();
    await respond(fixture, RUNS, null, 503);
    expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain('nicht erreichbar');
  });

  it('loads the detail of the latest run once while it stays the latest', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [run({ id: 2 })]);
    await respond(fixture, '/api/v1/runs/2', run({ id: 2, scoring_run_id: 7 }));
    TestBed.inject(Dispatcher).dispatch(
      serverEvents.event({
        op: 'event',
        topic: 'runs',
        type: 'screening.run.requested',
        seq: 8,
        data: { runId: 3 },
      }),
    );
    // Während die Liste nachlädt, bleibt die alte stehen (Spec, Zustände)
    TestBed.tick();
    expect(query(fixture, 'tr[data-run]').map((r) => r.getAttribute('data-run'))).toEqual(['2']);
    await respond(fixture, RUNS, [
      run({ id: 3, status: 'running', finished_at: null }),
      run({ id: 2 }),
    ]);
    await settle(fixture);
    TestBed.inject(HttpTestingController).expectNone((r) => r.urlWithParams === '/api/v1/runs/2');
    const link = query<HTMLAnchorElement>(
      fixture,
      '[data-card="last-run"] a[data-action="ranking"]',
    );
    expect(link[0]?.getAttribute('href')).toBe('/ranking/7');
  });

  // P4.6: Echtzeit über den LiveStore
  it('reloads when a run event arrives', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [run({ id: 1 })]);
    TestBed.inject(Dispatcher).dispatch(
      serverEvents.event({
        op: 'event',
        topic: 'runs',
        type: 'screening.run.requested',
        seq: 7,
        data: { runId: 2 },
      }),
    );
    await respond(fixture, RUNS, [run({ id: 2, status: 'running' }), run({ id: 1 })]);
    expect(query(fixture, 'tr[data-run]').map((r) => r.getAttribute('data-run'))).toEqual([
      '2',
      '1',
    ]);
  });

  it('shows the progress of a running fetch with the last title in the tooltip', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [run({ id: 3, status: 'running', finished_at: null })]);
    TestBed.inject(Dispatcher).dispatch(
      serverEvents.event({
        op: 'event',
        topic: 'runs',
        type: 'marketdata.fetch.progressed',
        seq: null,
        data: { runId: 3, done: 57, total: 90, symbol: 'SAP.DE', ok: true },
      }),
    );
    await settle(fixture);
    // Die Liste lädt nicht nach: Der Fortschritt kommt allein aus dem LiveStore
    TestBed.inject(HttpTestingController).expectNone((r) => r.urlWithParams === RUNS);
    const progress = query(fixture, 'tr[data-run="3"] [data-progress]')[0];
    expect(progress?.textContent).toContain('57/90');
    expect(tooltip(fixture, progress)).toContain('zuletzt SAP.DE');
  });

  // P4.7 mit Dialog (E3): verschicken oder Probelauf, dazu neu abrufen
  it('starts a run with mail by default from the dialog', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [run({ id: 1 })]);
    await openStart(fixture);
    expect(dialog()?.textContent).toContain('Lauf starten');
    expect(inDialog<HTMLInputElement>('[data-option="send"] input')?.checked).toBe(true);

    const request = await confirm(fixture);
    expect(request.request.body).toEqual({ force_refresh: false, dry_run: false, notify: true });
    const button = inDialog<HTMLButtonElement>('button[data-action="start"]');
    expect(button?.disabled).toBe(true);
    expect(button?.textContent?.trim()).toBe('Startet …');
    request.flush({ id: 8 }, { status: 202, statusText: 'Accepted' });
    await settle(fixture);
    expect(dialog()).toBeNull();
    expect(query(fixture, '[role="status"]')[0]?.textContent).toContain('Lauf #8 gestartet');
  });

  it('starts a dry run that fetches the data again', async () => {
    const fixture = render();
    await respond(fixture, RUNS, []);
    await openStart(fixture);
    inDialog<HTMLInputElement>('[data-option="dry"] input')?.click();
    inDialog<HTMLInputElement>('[data-option="force"] input')?.click();
    await settle(fixture);
    const request = await confirm(fixture);
    expect(request.request.body).toEqual({ force_refresh: true, dry_run: true, notify: false });
    request.flush({ id: 9 }, { status: 202, statusText: 'Accepted' });
    await settle(fixture);
  });

  it('keeps the dialog open and says why when a run is already active', async () => {
    const fixture = render();
    await respond(fixture, RUNS, []);
    await openStart(fixture);
    (await confirm(fixture)).flush(
      { detail: 'Lauf #3 läuft noch' },
      { status: 409, statusText: 'Conflict' },
    );
    await settle(fixture);
    expect(inDialog('[role="alert"]')?.textContent).toContain('Lauf #3 läuft noch');
    expect(dialog()).not.toBeNull();
  });

  it('says in the dialog when runs cannot be started here', async () => {
    const fixture = render();
    await respond(fixture, RUNS, []);
    await openStart(fixture);
    (await confirm(fixture)).flush(
      { detail: 'Runs starten braucht NATS' },
      { status: 503, statusText: 'Service Unavailable' },
    );
    await settle(fixture);
    expect(inDialog('[role="alert"]')?.textContent).toContain(
      'Hier lassen sich keine Läufe starten',
    );
  });

  it('blocks starting while a run is running and names it', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [run({ id: 3, status: 'running', finished_at: null })]);
    const button = query<HTMLButtonElement>(fixture, 'button[data-action="open-start"]')[0];
    expect(button.getAttribute('aria-disabled')).toBe('true');
    expect(tooltip(fixture, button)).toContain('Es läuft schon ein Lauf (#3)');
    button.click();
    await settle(fixture);
    expect(dialog()).toBeNull();
  });

  it('explains every control, header, badge and abbreviation (tests 1 and 2)', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [
      run({ id: 2, dry_run: true, force_refresh: true, status: 'success' }),
      run({ id: 1 }),
    ]);
    await respond(fixture, '/api/v1/runs/2', run({ id: 2, scoring_run_id: 7 }));
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
    // Spaltenköpfe mit scope (Spec, Barrierefreiheit)
    expect(headersWithoutScope(fixture)).toEqual([]);
  });
});
