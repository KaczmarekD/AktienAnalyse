// RealtimeService (P4.6) mit Fake-WebSocket: Verbinden, Wiederverbinden, resumeFrom, Store.
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { FakeWebSocket, realtimeTestingProviders } from '../../testing/realtime';
import { LiveStore } from './live.store';
import { PROTOCOL } from './protocol';
import { RealtimeService } from './realtime.service';

const TOPICS = ['runs', 'ranking', 'profiles'];

function start(config = {}) {
  TestBed.configureTestingModule({ providers: realtimeTestingProviders(config) });
  const service = TestBed.inject(RealtimeService);
  service.start();
  return service;
}

function event(seq: number | null, topic = 'runs', type = 'screening.run.requested', data = {}) {
  return { op: 'event', topic, type, seq, data };
}

describe('RealtimeService', () => {
  beforeEach(() => {
    FakeWebSocket.reset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    TestBed.inject(RealtimeService).stop();
    vi.useRealTimers();
  });

  it('reports when the server ends the session (code 4401, D1.3/D1.4)', () => {
    const service = start();
    let ended = 0;
    service.sessionEnded.subscribe(() => (ended += 1));
    FakeWebSocket.latest().open();
    FakeWebSocket.latest().end(1000); // normales Ende: keine Meldung
    expect(ended).toBe(0);
    vi.advanceTimersByTime(60_000);
    FakeWebSocket.latest().open();
    FakeWebSocket.latest().end(4401);
    expect(ended).toBe(1);
  });

  it('connects with the subprotocol and subscribes the topics', () => {
    const service = start();
    const socket = FakeWebSocket.latest();
    expect(socket.protocol).toBe(PROTOCOL);
    expect(socket.url).toMatch(/^wss?:\/\/[^/]+\/ws$/);
    expect(service.status()).toBe('connecting');

    socket.open();
    expect(service.status()).toBe('online');
    expect(socket.sent).toEqual([{ op: 'subscribe', topics: TOPICS }]);
  });

  it('reconnects with a growing, capped delay and starts over after success', () => {
    const service = start({ baseDelayMs: 1000, maxDelayMs: 4000 });
    FakeWebSocket.latest().drop();
    expect(service.status()).toBe('offline');

    const delays: number[] = [];
    for (let attempt = 0; attempt < 4; attempt++) {
      const before = FakeWebSocket.instances.length;
      let waited = 0;
      while (FakeWebSocket.instances.length === before) {
        vi.advanceTimersByTime(100);
        waited += 100;
      }
      delays.push(waited);
      FakeWebSocket.latest().drop();
    }
    expect(delays).toEqual([1000, 2000, 4000, 4000]);

    // Nach einer erfolgreichen Verbindung wieder ab der kurzen Wartezeit
    vi.advanceTimersByTime(4000);
    FakeWebSocket.latest().open();
    expect(service.status()).toBe('online');
    FakeWebSocket.latest().drop();
    const before = FakeWebSocket.instances.length;
    vi.advanceTimersByTime(1000);
    expect(FakeWebSocket.instances.length).toBe(before + 1);
  });

  it('adds a random share to the delay', () => {
    start({ baseDelayMs: 1000, random: () => 0 }); // Zufall 0: halbe Wartezeit
    FakeWebSocket.latest().drop();
    vi.advanceTimersByTime(499);
    expect(FakeWebSocket.instances.length).toBe(1);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances.length).toBe(2);
  });

  it('resumes from the last seen sequence', () => {
    start();
    const first = FakeWebSocket.latest();
    first.open();
    first.receive({ op: 'hello', serverTime: '2026-11-04T10:00:00Z', lastSeq: 41 });
    first.drop();
    vi.advanceTimersByTime(1000);

    const second = FakeWebSocket.latest();
    second.open();
    expect(second.sent).toEqual([{ op: 'subscribe', topics: TOPICS, resumeFrom: 41 }]);

    second.receive(event(42));
    second.receive(event(null, 'runs', 'marketdata.fetch.progressed')); // fluechtig: ohne seq
    second.drop();
    vi.advanceTimersByTime(1000);
    const third = FakeWebSocket.latest();
    third.open();
    expect(third.sent).toEqual([{ op: 'subscribe', topics: TOPICS, resumeFrom: 42 }]);
  });

  it('passes events and resync to the store', () => {
    start();
    const socket = FakeWebSocket.latest();
    socket.open();
    const store = TestBed.inject(LiveStore);

    socket.receive(event(5, 'runs'));
    socket.receive({ op: 'resync', topic: 'ranking' });
    socket.receive(
      event(null, 'runs', 'marketdata.fetch.progressed', {
        runId: 3,
        done: 57,
        total: 90,
        symbol: 'SAP.DE',
        ok: true,
      }),
    );

    expect(store.runsVersion()).toBe(1);
    expect(store.rankingVersion()).toBe(1);
    expect(store.progress()[3]).toEqual({ done: 57, total: 90, symbol: 'SAP.DE' });
  });

  it('keeps the console clean for pong and error', () => {
    const errors = vi.spyOn(console, 'error');
    const warnings = vi.spyOn(console, 'warn');
    start();
    const socket = FakeWebSocket.latest();
    socket.open();
    socket.receive({ op: 'pong' });
    socket.receive({ op: 'error', code: 'bad_request', message: 'x' });
    expect(errors).not.toHaveBeenCalled();
    expect(warnings).not.toHaveBeenCalled();
  });

  it('starts only once', () => {
    const service = start();
    service.start();
    expect(FakeWebSocket.instances.length).toBe(1);
  });
});
