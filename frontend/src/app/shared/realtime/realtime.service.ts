import { inject, Injectable, signal } from '@angular/core';
import { injectDispatch } from '@ngrx/signals/events';
import { Subject, Subscription } from 'rxjs';
import { webSocket, WebSocketSubject } from 'rxjs/webSocket';

import { ClientMessage, PROTOCOL, ServerMessage, SubscribeMessage } from './protocol';
import { REALTIME_CONFIG, REALTIME_DEFAULTS, RealtimeConfig } from './realtime.config';
import { serverEvents } from './realtime.events';

export type RealtimeStatus = 'idle' | 'connecting' | 'online' | 'offline';

/** Der Server trennt, weil die Sitzung endete (D1.3, web-api-realtime.md). */
const CLOSE_SESSION_ENDED = 4401;

/**
 * Verbindung zum WebSocket des web-api (P4.6, frontend.md, web-api-realtime.md).
 *
 * - Abonniert beim Oeffnen die Topics; beim Wiederverbinden mit resumeFrom, damit der Server
 *   Verpasstes nachspielt (oder resync schickt).
 * - Bricht die Verbindung ab, verbindet er neu: wachsende Wartezeit mit Zufallsanteil, nach
 *   einem Erfolg wieder ab der kurzen.
 * - Servernachrichten gehen als NgRx-Events an die Stores. pong und error bleiben still: Die
 *   Browser-Tests verlangen eine leere Konsole.
 */
@Injectable({ providedIn: 'root' })
export class RealtimeService {
  private readonly config: RealtimeConfig = {
    ...REALTIME_DEFAULTS,
    ...(inject(REALTIME_CONFIG, { optional: true }) ?? {}),
  };
  private readonly dispatch = injectDispatch(serverEvents);
  private readonly state = signal<RealtimeStatus>('idle');

  /** idle (nicht gestartet), connecting, online, offline (wartet auf den naechsten Versuch). */
  readonly status = this.state.asReadonly();
  /**
   * Meldet Code 4401: Die Sitzung endete (D1.4). Der AuthStore entscheidet, ob es weitergeht;
   * bis dahin verbindet der Dienst wie nach jedem Abbruch neu.
   */
  readonly sessionEnded = new Subject<void>();

  private started = false;
  private attempt = 0;
  private lastSeq: number | null = null;
  private subscription: Subscription | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;

  /** Verbindet, falls noch nicht geschehen. */
  start(): void {
    if (this.started) {
      return;
    }
    this.started = true;
    this.connect();
  }

  stop(): void {
    this.started = false;
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.subscription?.unsubscribe();
    this.subscription = null;
    this.state.set('idle');
  }

  private connect(): void {
    this.state.set('connecting');
    const socket: WebSocketSubject<ServerMessage | ClientMessage> = webSocket({
      url: this.config.url(),
      protocol: PROTOCOL,
      WebSocketCtor: this.config.WebSocketCtor,
      openObserver: { next: () => this.opened(socket) },
      closeObserver: {
        next: (event: CloseEvent) => {
          if (event.code === CLOSE_SESSION_ENDED) {
            this.sessionEnded.next();
          }
        },
      },
    });
    this.subscription = socket.subscribe({
      next: (message) => this.received(message as ServerMessage),
      error: () => this.closed(),
      complete: () => this.closed(),
    });
  }

  private opened(socket: WebSocketSubject<ServerMessage | ClientMessage>): void {
    this.attempt = 0;
    this.state.set('online');
    const subscribe: SubscribeMessage = { op: 'subscribe', topics: [...this.config.topics] };
    if (this.lastSeq !== null) {
      subscribe.resumeFrom = this.lastSeq;
    }
    socket.next(subscribe);
  }

  private received(message: ServerMessage): void {
    switch (message.op) {
      case 'hello':
        // Ausgangspunkt fuer das erste Wiederverbinden, solange noch kein Event kam
        if (this.lastSeq === null && message.lastSeq !== null) {
          this.lastSeq = message.lastSeq;
        }
        break;
      case 'event':
        if (message.seq !== null) {
          this.lastSeq = Math.max(this.lastSeq ?? 0, message.seq);
        }
        this.dispatch.event(message);
        break;
      case 'resync':
        this.dispatch.resync({ topic: message.topic });
        break;
      default:
        break; // pong, error: bewusst still
    }
  }

  private closed(): void {
    this.subscription = null;
    if (!this.started) {
      return;
    }
    this.state.set('offline');
    const { baseDelayMs, maxDelayMs, random } = this.config;
    const delay = Math.min(baseDelayMs * 2 ** this.attempt, maxDelayMs) * (0.5 + 0.5 * random());
    this.attempt += 1;
    this.timer = setTimeout(() => {
      this.timer = null;
      if (this.started) {
        this.connect();
      }
    }, delay);
  }
}
