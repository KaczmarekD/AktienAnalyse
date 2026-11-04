import { computed } from '@angular/core';
import { signalStore, withComputed, withState } from '@ngrx/signals';
import { on, withReducer } from '@ngrx/signals/events';

import { EventMessage } from './protocol';
import { serverEvents } from './realtime.events';

/** Fortschritt eines laufenden Abrufs (marketdata.fetch.progressed). */
export interface Progress {
  done: number;
  total: number;
  symbol: string;
}

interface LiveState {
  /** Je Topic ein Zaehler: steigt bei jedem dauerhaften Event und bei resync. */
  versions: Record<string, number>;
  /** Je Run der letzte Fortschritt; mit dem Ende des Runs faellt er weg. */
  progress: Record<number, Progress>;
}

const PROGRESS = 'marketdata.fetch.progressed';
const RUN_ENDS = new Set(['notification.report.sent', 'screening.run.failed']);

function bump(versions: Record<string, number>, topic: string): Record<string, number> {
  return { ...versions, [topic]: (versions[topic] ?? 0) + 1 };
}

function reduceEvent(state: LiveState, message: EventMessage): Partial<LiveState> {
  const update: Partial<LiveState> = {};
  if (message.seq !== null) {
    update.versions = bump(state.versions, message.topic);
  }
  const runId = message.data['runId'];
  if (typeof runId !== 'number') {
    return update;
  }
  if (message.type === PROGRESS) {
    update.progress = {
      ...state.progress,
      [runId]: {
        done: Number(message.data['done']),
        total: Number(message.data['total']),
        symbol: String(message.data['symbol'] ?? ''),
      },
    };
  } else if (RUN_ENDS.has(message.type) && runId in state.progress) {
    update.progress = Object.fromEntries(
      Object.entries(state.progress).filter(([id]) => Number(id) !== runId),
    );
  }
  return update;
}

/**
 * Was der WebSocket meldet (P4.6). Ansichten lesen die Versionen und laden neu, wenn sie steigen:
 * REST liefert den Zustand, der WebSocket meldet nur Aenderungen (web-api-realtime.md).
 */
export const LiveStore = signalStore(
  { providedIn: 'root' },
  withState<LiveState>({ versions: {}, progress: {} }),
  withReducer(
    on(serverEvents.event, ({ payload }, state) => reduceEvent(state, payload)),
    on(serverEvents.resync, ({ payload }, state) => ({
      versions: bump(state.versions, payload.topic),
    })),
  ),
  withComputed(({ versions }) => ({
    runsVersion: computed(() => versions()['runs'] ?? 0),
    rankingVersion: computed(() => versions()['ranking'] ?? 0),
    profilesVersion: computed(() => versions()['profiles'] ?? 0),
  })),
);
