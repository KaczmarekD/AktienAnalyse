// Fake-WebSocket fuer den RealtimeService (P4.6): Er tut, was rxjs/webSocket von einem
// WebSocket braucht, und laesst sich von aussen oeffnen, beschicken und abbrechen.
import { REALTIME_CONFIG, RealtimeConfig } from '../shared/realtime/realtime.config';

export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readyState = 0;
  binaryType = 'blob';
  readonly sent: unknown[] = [];
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(
    readonly url: string,
    readonly protocol?: string | string[],
  ) {
    FakeWebSocket.instances.push(this);
  }

  static reset(): void {
    FakeWebSocket.instances = [];
  }

  static latest(): FakeWebSocket {
    const socket = FakeWebSocket.instances.at(-1);
    if (!socket) {
      throw new Error('keine WebSocket-Verbindung aufgebaut');
    }
    return socket;
  }

  send(data: string): void {
    this.sent.push(JSON.parse(data));
  }

  close(): void {
    this.readyState = 3;
  }

  /** Server nimmt die Verbindung an. */
  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event('open'));
  }

  /** Server schickt eine Nachricht. */
  receive(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
  }

  /** Verbindung bricht ab, wie bei einem Neustart des web-api. */
  drop(): void {
    this.readyState = 3;
    this.onclose?.({ wasClean: false, code: 1006, reason: '' } as CloseEvent);
  }
}

/** Provider fuer Tests: Fake-WebSocket, feste Wartezeiten, Zufall fest auf 1 (kein Abschlag). */
export function realtimeTestingProviders(config: Partial<RealtimeConfig> = {}) {
  return [
    {
      provide: REALTIME_CONFIG,
      useValue: {
        WebSocketCtor: FakeWebSocket as unknown as RealtimeConfig['WebSocketCtor'],
        random: () => 1,
        ...config,
      },
    },
  ];
}
