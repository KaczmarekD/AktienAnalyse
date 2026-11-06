import { HttpClient, HttpRequest, HttpResponse } from '@angular/common/http';
import {
  computed,
  effect,
  inject,
  Injectable,
  Injector,
  runInInjectionContext,
  signal,
  untracked,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, UrlTree } from '@angular/router';
import { filter, firstValueFrom } from 'rxjs';

import { currentSessionRequest, healthRequest, logoutRequest } from '../../api/@angular/common.gen';
import type { Health, Me, SessionState } from '../../api/types.gen';
import { RealtimeService } from '../realtime/realtime.service';

export const SESSION_ENDED = 'Deine Sitzung ist abgelaufen. Bitte melde dich neu an.';
const HOME = '/ranking';

/** Rücksprung nach der Anmeldung: nur ein Pfad dieser App, sonst das Ranking. */
export function safeNext(next: unknown): string {
  if (
    typeof next !== 'string' ||
    !next.startsWith('/') ||
    next.startsWith('//') ||
    next.includes('\\') ||
    /^\/login([/?#]|$)/.test(next)
  ) {
    return HOME;
  }
  return next;
}

/** Die Anmeldeseite, mit Rücksprung auf url, wenn es einen gibt. */
export function loginTree(router: Router, url: string): UrlTree {
  return url === '/' || url === '' || url.startsWith('/login')
    ? router.createUrlTree(['/login'])
    : router.createUrlTree(['/login'], { queryParams: { next: url } });
}

/**
 * Wer angemeldet ist (D1.4, docs/architecture/depot/nutzer.md). Fragt beim Start GET /health
 * (Version, Sitzungspflicht) und GET /auth/session (antwortet ohne Sitzung mit 200, damit die
 * Anmeldeseite keinen Fehler in die Konsole schreibt).
 *
 * - Ohne Sitzungspflicht (Übergang bis D1.5) bleibt das UI wie bisher: Jeder darf alles, nur die
 *   Nutzerverwaltung braucht eine echte Admin-Sitzung.
 * - Der WebSocket läuft nur, wenn er darf: angemeldet ohne Einmal-Passwort, oder ohne
 *   Sitzungspflicht. Code 4401 und jedes 401 (auth.interceptor.ts) beenden die Sitzung.
 *
 * Nutzt die Request-Bausteine des Clients ohne zod: Der Store gehört zum Start-Bundle.
 */
@Injectable({ providedIn: 'root' })
export class AuthStore {
  private readonly http = inject(HttpClient);
  private readonly injector = inject(Injector);
  private readonly router = inject(Router);
  private readonly realtime = inject(RealtimeService);

  private readonly health = signal<Health | undefined>(undefined);
  private readonly account = signal<Me | undefined>(undefined);
  private readonly loaded = signal(false);
  private readonly started: Promise<void>;

  /** Beide Antworten beim Start sind da (oder gescheitert). */
  readonly ready = this.loaded.asReadonly();
  /** Mit Sitzungspflicht; ist der Server nicht erreichbar, gilt das alte Verhalten. */
  readonly required = computed(() => this.health()?.auth_required === true);
  readonly user = this.account.asReadonly();
  readonly version = computed(() => this.health()?.version);
  /** Darf Läufe starten und Profile speichern (ohne Sitzungspflicht jeder, wie bisher). */
  readonly isAdmin = computed(() => !this.required() || this.user()?.role === 'admin');
  /** Darf Konten verwalten: nur mit echter Admin-Sitzung, auch ohne Sitzungspflicht. */
  readonly canManageUsers = computed(() => this.user()?.role === 'admin');
  /** Warum die Anmeldeseite erscheint, etwa nach Ablauf der Sitzung. */
  readonly notice = signal<string | undefined>(undefined);

  private readonly live = computed(() => {
    if (!this.ready()) {
      return undefined;
    }
    const user = this.user();
    return user ? !user.must_change_password : !this.required();
  });

  constructor() {
    this.started = this.load();
    effect(() => {
      const live = this.live();
      if (live !== undefined) {
        untracked(() => (live ? this.realtime.start() : this.realtime.stop()));
      }
    });
    this.realtime.sessionEnded.pipe(takeUntilDestroyed()).subscribe(() => this.sessionEnded());
  }

  whenReady(): Promise<void> {
    return this.started;
  }

  /** Lädt das eigene Konto neu, etwa nach der Anmeldung oder einer Änderung am Konto. */
  async refresh(): Promise<Me | undefined> {
    const state = await this.send<SessionState>(() => currentSessionRequest({}));
    this.account.set(state?.user ?? undefined);
    return this.account();
  }

  /** Abgemeldet (Abmelden, überall abmelden): Das Konto ist vergessen. */
  signedOut(): void {
    this.account.set(undefined);
  }

  /** Die Sitzung endete auf dem Server (401, WebSocket 4401): zur Anmeldung, falls nötig. */
  sessionEnded(): void {
    if (!this.account()) {
      return;
    }
    this.account.set(undefined);
    if (this.required()) {
      // Ohne Sitzungspflicht bleibt die Seite stehen; die Meldung wäre dann später veraltet
      this.notice.set(SESSION_ENDED);
      void this.router.navigateByUrl(loginTree(this.router, this.router.url));
    }
  }

  async logout(): Promise<void> {
    if (!(await this.ok(() => logoutRequest({})))) {
      // Der Server hat nicht abgemeldet: Gilt die Sitzung noch, bleibt der Nutzer angemeldet,
      // statt nur so auszusehen, als wäre er es nicht mehr
      if (await this.refresh()) {
        return;
      }
    }
    this.signedOut();
    await this.router.navigateByUrl(this.required() ? '/login' : HOME);
  }

  private async load(): Promise<void> {
    const [, state] = await Promise.all([
      this.send<Health>(() => healthRequest({})).then((health) => this.health.set(health)),
      this.send<SessionState>(() => currentSessionRequest({})),
    ]);
    this.account.set(state?.user ?? undefined);
    this.loaded.set(true);
  }

  /** Eine Anfrage über die Bausteine des Clients; ihr Inhalt, bei einem Fehler undefined. */
  private async send<T>(build: () => HttpRequest<unknown>): Promise<T | undefined> {
    return (await this.request<T>(build))?.body ?? undefined;
  }

  /** Ob die Anfrage gelang (auch ohne Inhalt, etwa 204). */
  private async ok(build: () => HttpRequest<unknown>): Promise<boolean> {
    return (await this.request(build)) !== undefined;
  }

  private async request<T>(
    build: () => HttpRequest<unknown>,
  ): Promise<HttpResponse<T> | undefined> {
    // Die Bausteine lesen die Konfiguration des Clients aus dem Injector
    const request = runInInjectionContext(this.injector, build);
    try {
      return await firstValueFrom(
        this.http
          .request<T>(request as HttpRequest<T>)
          .pipe(filter((event): event is HttpResponse<T> => event instanceof HttpResponse)),
      );
    } catch {
      return undefined;
    }
  }
}
