// Liste der Laeufe (P3.7), live (P4.6), Start aus dem UI (P4.7).
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Dispatcher } from '@ngrx/signals/events';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { run } from '../testing/fixtures';
import { serverEvents } from '../shared/realtime/realtime.events';
import { RunsPage } from './runs-page';

const RUNS = '/api/v1/runs?limit=50';
const START = '/api/v1/runs';

function expectRequest(url: string, method: string): TestRequest {
  return TestBed.inject(HttpTestingController).expectOne(
    (r) => r.urlWithParams === url && r.method === method,
  );
}

/** Wartet, bis Promises und Effects durch sind. */
async function settle(): Promise<void> {
  for (let i = 0; i < 3; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
  }
}

async function toggle(fixture: ComponentFixture<RunsPage>, option: string): Promise<void> {
  query<HTMLInputElement>(fixture, `[data-option="${option}"] input`)[0].click();
  await settle();
}

async function start(fixture: ComponentFixture<RunsPage>): Promise<TestRequest> {
  query(fixture, 'button[data-action="start"]')[0].click();
  await settle();
  return expectRequest(START, 'POST');
}

function render() {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  return TestBed.createComponent(RunsPage);
}

describe('RunsPage', () => {
  it('lists runs with status, counts and a dry-run mark', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [
      run({ id: 2, dry_run: true, status: 'success', scored_count: 90, failed_count: 0 }),
      run({ id: 1 }),
    ]);
    const rows = query(fixture, 'tr[data-run]');
    expect(rows.map((r) => r.getAttribute('data-run'))).toEqual(['2', '1']);
    expect(rows[0].textContent).toContain('Dry-Run');
    expect(rows[0].textContent).toContain('erfolgreich');
    expect(rows[1].textContent).toContain('teilweise');
    expect(rows[1].textContent).toContain('88/90');
    expect(rows[1].textContent).toContain('30.10.2026');
  });

  it('links each run to its detail page', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [run({ id: 1 })]);
    const link = query<HTMLAnchorElement>(fixture, 'tr[data-run="1"] a')[0];
    expect(link.getAttribute('href')).toBe('/runs/1');
  });

  it('says when there are no runs yet', async () => {
    const fixture = render();
    await respond(fixture, RUNS, []);
    expect(text(fixture)).toContain('Noch keine Läufe');
  });

  it('says when the web-api is not reachable', async () => {
    const fixture = render();
    await respond(fixture, RUNS, null, 503);
    expect(text(fixture)).toContain('nicht erreichbar');
  });

  // P4.6: Echtzeit ueber den LiveStore
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

  it('shows the progress of a running fetch', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [run({ id: 3, status: 'running' })]);
    TestBed.inject(Dispatcher).dispatch(
      serverEvents.event({
        op: 'event',
        topic: 'runs',
        type: 'marketdata.fetch.progressed',
        seq: null,
        data: { runId: 3, done: 57, total: 90, symbol: 'SAP.DE', ok: true },
      }),
    );
    await fixture.whenStable();
    const progress = query(fixture, 'tr[data-run="3"] [data-progress]')[0];
    expect(progress?.textContent).toContain('57/90');
  });

  // P4.7: Start aus dem UI
  it('starts a run with the chosen options', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [run({ id: 1 })]);
    await toggle(fixture, 'dry_run');
    await toggle(fixture, 'notify');

    const request = await start(fixture);
    expect(request.request.body).toEqual({ force_refresh: false, dry_run: true, notify: false });
    const button = query<HTMLButtonElement>(fixture, 'button[data-action="start"]')[0];
    expect(button.disabled).toBe(true);
    expect(button.textContent?.trim()).toBe('Startet …');
    request.flush({ id: 8 }, { status: 202, statusText: 'Accepted' });
    await settle();
    expect(query(fixture, '[role="status"]')[0]?.textContent).toContain('Lauf #8 gestartet');
    expect(button.textContent?.trim()).toBe('Lauf starten');
  });

  it('starts with mail and without dry-run by default', async () => {
    const fixture = render();
    await respond(fixture, RUNS, []);
    const request = await start(fixture);
    expect(request.request.body).toEqual({ force_refresh: false, dry_run: false, notify: true });
    request.flush({ id: 1 }, { status: 202, statusText: 'Accepted' });
    await settle();
  });

  it('says when a run is already active', async () => {
    const fixture = render();
    await respond(fixture, RUNS, [run({ id: 3, status: 'running' })]);
    (await start(fixture)).flush(
      { detail: 'Lauf #3 läuft noch' },
      { status: 409, statusText: 'Conflict' },
    );
    await settle();
    expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain('Lauf #3 läuft noch');
  });

  it('says when runs cannot be started here', async () => {
    const fixture = render();
    await respond(fixture, RUNS, []);
    (await start(fixture)).flush(
      { detail: 'Runs starten braucht NATS' },
      { status: 503, statusText: 'Service Unavailable' },
    );
    await settle();
    expect(text(fixture)).toContain('Hier lassen sich keine Läufe starten');
  });
});
