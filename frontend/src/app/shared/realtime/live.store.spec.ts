// LiveStore (P4.6): Versionen je Topic und Fortschritt laufender Runs aus den Server-Events.
import { TestBed } from '@angular/core/testing';
import { Dispatcher } from '@ngrx/signals/events';

import { LiveStore } from './live.store';
import { serverEvents } from './realtime.events';

function setup() {
  TestBed.configureTestingModule({});
  return { store: TestBed.inject(LiveStore), dispatcher: TestBed.inject(Dispatcher) };
}

const event = (topic: string, seq: number | null, type: string, data = {}) =>
  serverEvents.event({ op: 'event', topic, type, seq, data });

describe('LiveStore', () => {
  it('counts durable events and resync per topic', () => {
    const { store, dispatcher } = setup();
    dispatcher.dispatch(event('runs', 1, 'screening.run.requested'));
    dispatcher.dispatch(event('runs', 2, 'marketdata.snapshot.completed'));
    dispatcher.dispatch(event('ranking', 3, 'scoring.run.completed'));
    dispatcher.dispatch(serverEvents.resync({ topic: 'profiles' }));
    expect([store.runsVersion(), store.rankingVersion(), store.profilesVersion()]).toEqual([
      2, 1, 1,
    ]);
  });

  it('volatile progress does not count as a change', () => {
    const { store, dispatcher } = setup();
    dispatcher.dispatch(
      event('runs', null, 'marketdata.fetch.progressed', { runId: 3, done: 1, total: 90 }),
    );
    expect(store.runsVersion()).toBe(0);
  });

  it('progress comes with the fetch and goes with the end of the run', () => {
    const { store, dispatcher } = setup();
    dispatcher.dispatch(
      event('runs', null, 'marketdata.fetch.progressed', {
        runId: 3,
        done: 57,
        total: 90,
        symbol: 'SAP.DE',
      }),
    );
    dispatcher.dispatch(
      event('runs', null, 'marketdata.fetch.progressed', {
        runId: 4,
        done: 1,
        total: 90,
        symbol: 'ADS.DE',
      }),
    );
    expect(store.progress()[3]).toEqual({ done: 57, total: 90, symbol: 'SAP.DE' });

    dispatcher.dispatch(event('runs', 9, 'notification.report.sent', { runId: 3 }));
    dispatcher.dispatch(event('runs', 10, 'screening.run.failed', { runId: 4 }));
    expect(store.progress()).toEqual({});
  });
});
