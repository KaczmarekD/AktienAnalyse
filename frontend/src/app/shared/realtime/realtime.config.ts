import { InjectionToken } from '@angular/core';
import type { WebSocketSubjectConfig } from 'rxjs/webSocket';

/** Einstellungen des RealtimeService; Tests tauschen WebSocket, Wartezeiten und Zufall. */
export interface RealtimeConfig {
  /** Adresse des WebSockets, relativ zur Seite (ueber nginx bzw. den Proxy von ng serve). */
  url: () => string;
  /** WebSocket-Klasse; ohne die des Browsers. */
  WebSocketCtor: WebSocketSubjectConfig<unknown>['WebSocketCtor'];
  /** Erste Wartezeit vor dem Wiederverbinden, sie verdoppelt sich bis maxDelayMs. */
  baseDelayMs: number;
  maxDelayMs: number;
  /** Zufallsanteil: Die Wartezeit ist 50-100 % des Werts (verteilt Clients nach einem Neustart). */
  random: () => number;
  /** Was die App abonniert. */
  topics: readonly string[];
}

export const REALTIME_CONFIG = new InjectionToken<Partial<RealtimeConfig>>('REALTIME_CONFIG');

export function websocketUrl(): string {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${location.host}/ws`;
}

export const REALTIME_DEFAULTS: RealtimeConfig = {
  url: websocketUrl,
  WebSocketCtor: undefined,
  baseDelayMs: 1000,
  maxDelayMs: 30_000,
  random: Math.random,
  topics: ['runs', 'ranking', 'profiles'],
};
