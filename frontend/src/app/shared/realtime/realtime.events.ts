import { type } from '@ngrx/signals';
import { eventGroup } from '@ngrx/signals/events';

import { EventMessage } from './protocol';

/** Nachrichten des Servers als NgRx-Events (frontend.md): Stores reagieren mit withReducer. */
export const serverEvents = eventGroup({
  source: 'Server',
  events: {
    event: type<EventMessage>(),
    resync: type<{ topic: string }>(),
  },
});
