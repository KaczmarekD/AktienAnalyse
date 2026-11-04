// WebSocket-Protokoll v1 (P4.5/P4.6, docs/architecture/web-api-realtime.md).
// Von Hand gespiegelt aus va_web_api.realtime.protocol. Aendert sich dort ein Modell, faellt das
// am Golden-Schema tests/golden/realtime/v1.json auf; dann diese Datei im selben Commit anpassen.

export const PROTOCOL = 'va.v1';

// --- Server -> Client ------------------------------------------------------------------------

export interface HelloMessage {
  op: 'hello';
  serverTime: string;
  lastSeq: number | null;
}

export interface EventMessage {
  op: 'event';
  topic: string;
  type: string;
  /** Stream-Sequenz; nur dauerhafte Events, fluechtige (Fortschritt) ohne. */
  seq: number | null;
  /** Payload in camelCase; scoring.run.completed ohne Rangliste (rankingSize). */
  data: Record<string, unknown>;
}

export interface ResyncMessage {
  op: 'resync';
  topic: string;
}

export interface PongMessage {
  op: 'pong';
}

export interface ErrorMessage {
  op: 'error';
  code: string;
  message: string;
}

export type ServerMessage =
  HelloMessage | EventMessage | ResyncMessage | PongMessage | ErrorMessage;

// --- Client -> Server ------------------------------------------------------------------------

export interface SubscribeMessage {
  op: 'subscribe';
  topics: string[];
  resumeFrom?: number;
}

export interface UnsubscribeMessage {
  op: 'unsubscribe';
  topics: string[];
}

export interface PingMessage {
  op: 'ping';
}

export type ClientMessage = SubscribeMessage | UnsubscribeMessage | PingMessage;
