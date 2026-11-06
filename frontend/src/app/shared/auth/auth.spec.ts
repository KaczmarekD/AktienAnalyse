// Anmeldung im UI (D1.4, docs/architecture/depot/nutzer.md): Zustand aus GET /health und /me,
// Guards vor den Seiten, 401 und WebSocket-Code 4401 führen zur Anmeldung, der WebSocket startet
// erst, wenn er darf. Dazu der Rücksprung nach der Anmeldung und das Einmal-Passwort.
import { HttpClient, provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import {
  ActivatedRouteSnapshot,
  provideRouter,
  Router,
  RouterStateSnapshot,
  UrlTree,
} from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { client } from '../../api/client.gen';
import { provideHeyApiClient } from '../../api/client/client.gen';
import type { Me } from '../../api/types.gen';
import { me } from '../../testing/auth';
import { FakeWebSocket, realtimeTestingProviders } from '../../testing/realtime';
import { RealtimeService } from '../realtime/realtime.service';
import { adminGuard, authGuard, loginGuard, sessionGuard } from './auth.guard';
import { authInterceptor, jsonWritesInterceptor } from './auth.interceptor';
import { AuthStore, safeNext, SESSION_ENDED } from './auth.store';
import { ACCOUNT_CONTROLS } from './controls';
import { oneTimePassword } from './one-time-password';

const HEALTH = '/api/v1/health';
const SESSION = '/api/v1/auth/session';

@Component({ template: '' })
class Blank {}

const ROUTES = ['', 'login', 'account', 'ranking', 'runs', 'admin/users'].map((path) => ({
  path,
  component: Blank,
}));

function http(): HttpTestingController {
  return TestBed.inject(HttpTestingController);
}

/** AuthStore mit Antworten auf /health und /auth/session (ohne user: niemand angemeldet). */
async function start(
  options: { required?: boolean; user?: Me; health?: 'down' } = {},
): Promise<AuthStore> {
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withFetch(), withInterceptors([jsonWritesInterceptor, authInterceptor])),
      provideHttpClientTesting(),
      provideHeyApiClient(client),
      provideRouter(ROUTES),
      ...realtimeTestingProviders(),
    ],
  });
  const auth = TestBed.inject(AuthStore);
  if (options.health === 'down') {
    http().expectOne(HEALTH).flush(null, { status: 503, statusText: 'Fehler' });
  } else {
    http()
      .expectOne(HEALTH)
      .flush({ status: 'ok', version: '1.5.0', auth_required: options.required ?? true });
  }
  http()
    .expectOne(SESSION)
    .flush({ user: options.user ?? null });
  await auth.whenReady();
  TestBed.tick();
  return auth;
}

function state(url: string): RouterStateSnapshot {
  return { url } as RouterStateSnapshot;
}

function route(queryParams: Record<string, string> = {}): ActivatedRouteSnapshot {
  const snapshot = new ActivatedRouteSnapshot();
  Object.defineProperty(snapshot, 'queryParamMap', {
    value: { get: (key: string) => queryParams[key] ?? null },
  });
  return snapshot;
}

/** Ergebnis eines Guards: true oder die Ziel-URL. */
async function guard(
  fn: typeof authGuard,
  url: string,
  queryParams: Record<string, string> = {},
): Promise<true | string> {
  const result = await TestBed.runInInjectionContext(() => fn(route(queryParams), state(url)));
  if (result instanceof UrlTree) {
    return TestBed.inject(Router).serializeUrl(result);
  }
  expect(result).toBe(true);
  return true;
}

describe('AuthStore', () => {
  beforeEach(() => FakeWebSocket.reset());
  afterEach(() => TestBed.inject(RealtimeService).stop());

  it('knows the user, the version and whether a login is needed', async () => {
    const auth = await start({ user: me() });
    expect(auth.ready()).toBe(true);
    expect(auth.required()).toBe(true);
    expect(auth.user()?.username).toBe('anna');
    expect(auth.version()).toBe('1.5.0');
  });

  it('without a login requirement everyone may change the system, as before (ADR-0007)', async () => {
    const auth = await start({ required: false });
    expect(auth.user()).toBeUndefined();
    expect(auth.isAdmin()).toBe(true);
    expect(auth.canManageUsers()).toBe(false); // dafür braucht es eine echte Admin-Sitzung
  });

  it('a user may read but not change the system', async () => {
    const auth = await start({ user: me() });
    expect(auth.isAdmin()).toBe(false);
    expect(auth.canManageUsers()).toBe(false);
  });

  it('a real admin may manage users', async () => {
    const auth = await start({ user: me({ role: 'admin' }) });
    expect(auth.isAdmin()).toBe(true);
    expect(auth.canManageUsers()).toBe(true);
  });

  it('treats an unreachable server like the old behaviour, without a login page', async () => {
    const auth = await start({ health: 'down' });
    expect(auth.required()).toBe(false);
  });

  it('reloads the account after a login', async () => {
    const auth = await start();
    const refreshed = auth.refresh();
    http()
      .expectOne(SESSION)
      .flush({ user: me({ display_name: 'Anna B.' }) });
    expect((await refreshed)?.display_name).toBe('Anna B.');
    expect(auth.user()?.display_name).toBe('Anna B.');
  });

  it('logs out on the server and forgets the user', async () => {
    const auth = await start({ user: me() });
    const done = auth.logout();
    await new Promise((resolve) => setTimeout(resolve));
    const request = http().expectOne('/api/v1/auth/logout');
    expect(request.request.method).toBe('POST');
    // Schreibende Anfragen nur als JSON (ADR-0007 Regel 1), auch ohne Inhalt
    expect(request.request.headers.get('Content-Type')).toBe('application/json');
    request.flush(null, { status: 204, statusText: 'No Content' });
    await done;
    expect(auth.user()).toBeUndefined();
    expect(TestBed.inject(Router).url).toBe('/login');
  });

  it('stays logged in when the server could not log out and the session still counts', async () => {
    const auth = await start({ user: me() });
    const done = auth.logout();
    await new Promise((resolve) => setTimeout(resolve));
    http().expectOne('/api/v1/auth/logout').flush(null, { status: 503, statusText: 'Fehler' });
    await new Promise((resolve) => setTimeout(resolve));
    http().expectOne(SESSION).flush({ user: me() });
    await done;
    expect(auth.user()?.username).toBe('anna');
    expect(TestBed.inject(Router).url).toBe('/');
  });

  describe('WebSocket', () => {
    it('connects only after the login when a login is needed', async () => {
      await start();
      expect(FakeWebSocket.instances.length).toBe(0);
    });

    it('connects for a logged-in user', async () => {
      await start({ user: me() });
      expect(FakeWebSocket.instances.length).toBe(1);
    });

    it('connects without a login requirement, as before', async () => {
      await start({ required: false });
      expect(FakeWebSocket.instances.length).toBe(1);
    });

    it('does not connect with a one-time password', async () => {
      await start({ user: me({ must_change_password: true }) });
      expect(FakeWebSocket.instances.length).toBe(0);
    });

    it('code 4401 (session ended) leads to the login page', async () => {
      const auth = await start({ user: me() });
      FakeWebSocket.latest().open();
      FakeWebSocket.latest().end(4401);
      await new Promise((resolve) => setTimeout(resolve));
      TestBed.tick();
      expect(auth.user()).toBeUndefined();
      expect(auth.notice()).toBe(SESSION_ENDED);
      expect(TestBed.inject(Router).url).toBe('/login');
      expect(TestBed.inject(RealtimeService).status()).toBe('idle');
    });
  });

  describe('401 on any request', () => {
    async function answer401(auth: AuthStore, url: string): Promise<void> {
      const request = firstValueFrom(TestBed.inject(HttpClient).get(url)).catch(() => undefined);
      http().expectOne(url).flush({ detail: 'Nicht angemeldet' }, { status: 401, statusText: 'x' });
      await request;
      await new Promise((resolve) => setTimeout(resolve));
      expect(auth).toBeTruthy();
    }

    it('ends the session and leads to the login page with a return path', async () => {
      const auth = await start({ user: me() });
      await TestBed.inject(Router).navigateByUrl('/runs');
      await answer401(auth, '/api/v1/runs');
      expect(auth.user()).toBeUndefined();
      expect(auth.notice()).toBe(SESSION_ENDED);
      expect(TestBed.inject(Router).url).toBe('/login?next=%2Fruns');
    });

    it('ignores a wrong login, that is the login page’s business', async () => {
      const auth = await start();
      await answer401(auth, '/api/v1/auth/login');
      expect(auth.notice()).toBeUndefined();
      expect(TestBed.inject(Router).url).toBe('/');
    });

    it('without a login requirement it only forgets the user', async () => {
      const auth = await start({ required: false, user: me({ role: 'admin' }) });
      await answer401(auth, '/api/v1/runs');
      expect(auth.user()).toBeUndefined();
      expect(TestBed.inject(Router).url).toBe('/');
    });
  });
});

describe('Guards', () => {
  beforeEach(() => FakeWebSocket.reset());
  afterEach(() => TestBed.inject(RealtimeService).stop());

  it('send to the login page with a return path when a login is needed', async () => {
    await start();
    expect(await guard(authGuard, '/runs/3')).toBe('/login?next=%2Fruns%2F3');
  });

  it('let a logged-in user through', async () => {
    await start({ user: me() });
    expect(await guard(authGuard, '/runs')).toBe(true);
  });

  it('let everyone through without a login requirement', async () => {
    await start({ required: false });
    expect(await guard(authGuard, '/runs')).toBe(true);
  });

  it('send a user with a one-time password to the account page first', async () => {
    await start({ user: me({ must_change_password: true }) });
    expect(await guard(authGuard, '/ranking')).toBe('/account');
    expect(await guard(sessionGuard, '/account')).toBe(true);
    expect(await guard(adminGuard, '/admin/users')).toBe('/account');
  });

  it('need a real session for the account page, also without a login requirement', async () => {
    await start({ required: false });
    expect(await guard(sessionGuard, '/account')).toBe('/login?next=%2Faccount');
  });

  it('let only admins manage users', async () => {
    await start({ user: me() });
    expect(await guard(adminGuard, '/admin/users')).toBe('/ranking');
  });

  it('let an admin manage users', async () => {
    await start({ user: me({ role: 'admin' }) });
    expect(await guard(adminGuard, '/admin/users')).toBe(true);
  });

  it('lead a logged-in user away from the login page to the return path', async () => {
    await start({ user: me() });
    expect(await guard(loginGuard, '/login', { next: '/runs' })).toBe('/runs');
    expect(await guard(loginGuard, '/login', { next: 'https://boese.example' })).toBe('/ranking');
  });

  it('show the login page to everyone else', async () => {
    await start();
    expect(await guard(loginGuard, '/login')).toBe(true);
  });
});

describe('jsonWritesInterceptor', () => {
  function setup(): HttpClient {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withFetch(), withInterceptors([jsonWritesInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    return TestBed.inject(HttpClient);
  }

  it('sends a write without content as an empty JSON object', () => {
    setup().post('/api/v1/admin/users/2/disable', null).subscribe();
    const request = http().expectOne('/api/v1/admin/users/2/disable').request;
    expect(request.body).toEqual({});
    expect(request.headers.get('Content-Type')).toBe('application/json');
  });

  it('leaves writes with content and reads alone', () => {
    const client = setup();
    client.post('/api/v1/runs', { dry_run: true }).subscribe();
    client.get('/api/v1/runs').subscribe();
    expect(http().expectOne((r) => r.method === 'POST').request.body).toEqual({ dry_run: true });
    expect(http().expectOne((r) => r.method === 'GET').request.body).toBeNull();
  });

  it('only touches requests to the web-api', () => {
    setup().post('/anderswo', null).subscribe();
    expect(http().expectOne('/anderswo').request.body).toBeNull();
  });
});

describe('safeNext', () => {
  it('accepts only paths of this app', () => {
    expect(safeNext('/runs/3?x=1')).toBe('/runs/3?x=1');
    expect(safeNext('/instruments/SAP.DE')).toBe('/instruments/SAP.DE');
  });

  it.each([
    null,
    '',
    'runs',
    '//boese.example',
    '/\\boese.example',
    'https://boese.example',
    '/login',
  ])('falls back to the ranking for %s', (next) => {
    expect(safeNext(next)).toBe('/ranking');
  });
});

describe('oneTimePassword', () => {
  it('has four groups of five characters without look-alikes', () => {
    const password = oneTimePassword();
    expect(password).toMatch(/^[A-HJ-NP-Za-km-z2-9]{5}(-[A-HJ-NP-Za-km-z2-9]{5}){3}$/);
  });

  it('comes from the random source of the browser', () => {
    const values = new Set(Array.from({ length: 20 }, () => oneTimePassword()));
    expect(values.size).toBe(20);
  });
});

describe('ACCOUNT_CONTROLS', () => {
  it('keeps every control text short and not empty', () => {
    for (const [key, text] of Object.entries(ACCOUNT_CONTROLS)) {
      const value = typeof text === 'function' ? text('anna') : text;
      expect(value.length, key).toBeGreaterThan(0);
      expect(value.length, key).toBeLessThanOrEqual(200);
    }
  });
});
