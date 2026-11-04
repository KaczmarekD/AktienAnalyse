// Liste der Laeufe (P3.7).
import { TestBed } from '@angular/core/testing';
import { Dispatcher } from '@ngrx/signals/events';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { run } from '../testing/fixtures';
import { serverEvents } from '../shared/realtime/realtime.events';
import { RunsPage } from './runs-page';

const RUNS = '/api/v1/runs?limit=50';

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
});
