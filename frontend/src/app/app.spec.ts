// App-Hülle (G1, docs/architecture/ui-neugestaltung.md, App-Hülle): App-Leiste mit Marke,
// Navigation und Verbindungs-Chip, Fußzeile mit Hinweis und Version, dazu die Standardwerte
// für Tooltips und Formularfelder.
import { HttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_TOOLTIP_DEFAULT_OPTIONS, MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { Router } from '@angular/router';
import { vi } from 'vitest';

import { latestRankingResource, listRunsResource } from './api/@angular/common.gen';
import type { Me } from './api/types.gen';
import { App } from './app';
import { appConfig } from './app.config';
import { routes } from './app.routes';
import { AuthStore } from './shared/auth/auth.store';
import { RealtimeService } from './shared/realtime/realtime.service';
import { ADMIN, me } from './testing/auth';
import { FakeWebSocket, realtimeTestingProviders } from './testing/realtime';
import { abbreviationsWithoutExplanation, controlsWithoutTooltip } from './testing/tooltips';

const HEALTH = '/api/v1/health';
const SESSION = '/api/v1/auth/session';

function element(fixture: ComponentFixture<App>): HTMLElement {
  return fixture.nativeElement as HTMLElement;
}

function tooltipOf(fixture: ComponentFixture<App>, host: Element): string | undefined {
  const match = fixture.debugElement
    .queryAll(By.directive(MatTooltip))
    .find((debug) => debug.nativeElement === host);
  return match?.injector.get(MatTooltip).message;
}

/**
 * Beantwortet die Fragen der Hülle beim Start: Version und Sitzungspflicht (GET /health), wer
 * angemeldet ist (GET /auth/session). Ohne auth_required wie vor D1.4.
 */
async function answerStart(options: { required?: boolean; user?: Me } = {}): Promise<void> {
  const http = TestBed.inject(HttpTestingController);
  const health: Record<string, unknown> = { status: 'ok', version: '1.4.0' };
  if (options.required !== undefined) {
    health['auth_required'] = options.required;
  }
  http.expectOne(HEALTH).flush(health);
  http.expectOne(SESSION).flush({ user: options.user ?? null });
  await TestBed.inject(AuthStore).whenReady();
}

/** Zeichnet die Hülle und beantwortet die Fragen beim Start, ohne auf whenStable zu warten. */
async function render(
  options: { required?: boolean; user?: Me } = {},
): Promise<ComponentFixture<App>> {
  const fixture = TestBed.createComponent(App);
  fixture.detectChanges();
  TestBed.tick();
  await answerStart(options);
  await settle(fixture);
  return fixture;
}

async function settle(fixture: ComponentFixture<App>): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve));
  TestBed.tick();
  fixture.detectChanges();
}

describe('App', () => {
  beforeEach(async () => {
    FakeWebSocket.reset();
    await TestBed.configureTestingModule({
      imports: [App],
      // P4.6: kein echter WebSocket im Test; Antworten des web-api aus dem HttpTestingController
      providers: [
        ...appConfig.providers,
        ...realtimeTestingProviders(),
        provideHttpClientTesting(),
      ],
    }).compileComponents();
  });

  afterEach(() => TestBed.inject(RealtimeService).stop());

  it('shows the app bar with the brand linking to the ranking', async () => {
    const fixture = await render();
    const brand = element(fixture).querySelector<HTMLAnchorElement>('header a[data-brand]');
    expect(brand?.textContent).toContain('Value-Analyzer');
    expect(brand?.getAttribute('href')).toBe('/ranking');
  });

  it('links to ranking, runs and profiles with icon, German label and tooltip', async () => {
    const fixture = await render();
    const links = Array.from(element(fixture).querySelectorAll<HTMLAnchorElement>('nav a'));
    expect(links.map((a) => a.getAttribute('href'))).toEqual(['/ranking', '/runs', '/profiles']);
    expect(links.map((a) => a.textContent?.trim())).toEqual(['Ranking', 'Läufe', 'Profile']);
    for (const link of links) {
      expect(link.querySelector('app-icon svg')).not.toBeNull();
      expect(link.getAttribute('aria-label')).toBe(link.textContent?.trim());
      expect(tooltipOf(fixture, link)?.length).toBeGreaterThan(20);
    }
    expect(tooltipOf(fixture, links[1])).toBe(
      'Verlauf aller Läufe, neuen Lauf starten, Mails ansehen.',
    );
  });

  it('links to the glossary with an icon button, aria-label and tooltip', async () => {
    const fixture = await render();
    const help = element(fixture).querySelector<HTMLAnchorElement>('header a[href="/glossary"]');
    expect(help?.getAttribute('aria-label')).toBe('Begriffe');
    expect(help?.querySelector('app-icon svg')).not.toBeNull();
    expect(tooltipOf(fixture, help as Element)).toBe('Alle Begriffe und Abkürzungen erklärt.');
    expect(routes.find((route) => route.path === 'glossary')?.title).toBe(
      'Begriffe · Value-Analyzer',
    );

    await TestBed.inject(Router).navigateByUrl('/glossary');
    fixture.detectChanges();
    expect(help?.getAttribute('aria-current')).toBe('page');
  });

  it('explains every control of the app bar (tests 1 and 2)', async () => {
    const fixture = await render();
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });

  it('marks the active section, the title detail belongs to the ranking', async () => {
    const fixture = await render();
    const active = () =>
      Array.from(element(fixture).querySelectorAll('nav a[aria-current="page"]')).map((a) =>
        a.textContent?.trim(),
      );
    await TestBed.inject(Router).navigateByUrl('/runs/3');
    fixture.detectChanges();
    expect(active()).toEqual(['Läufe']);

    await TestBed.inject(Router).navigateByUrl('/instruments/SAP.DE');
    fixture.detectChanges();
    expect(active()).toEqual(['Ranking']);
  });

  it('calls runs "Läufe" in every tab title', () => {
    const titles = routes.map((route) => route.title).filter(Boolean);
    expect(titles.filter((title) => String(title).includes('Runs'))).toEqual([]);
    expect(routes.find((route) => route.path === 'runs')?.title).toBe('Läufe · Value-Analyzer');
  });

  it('shows the disclaimer and the version from the web-api in the footer', async () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    const footer = () => element(fixture).querySelector('footer')?.textContent ?? '';
    expect(footer()).toContain('Quantitative Vorauswahl, keine Anlageempfehlung.');
    expect(footer()).not.toContain('Version');

    TestBed.tick();
    TestBed.inject(HttpTestingController)
      .expectOne(HEALTH)
      .flush({ status: 'ok', version: '1.4.0' });
    await settle(fixture);
    expect(footer()).toContain('Version 1.4.0');
  });

  it('leaves the version out when the web-api does not answer', async () => {
    const fixture = TestBed.createComponent(App);
    fixture.detectChanges();
    TestBed.tick();
    TestBed.inject(HttpTestingController)
      .expectOne(HEALTH)
      .flush(null, { status: 503, statusText: 'Service Unavailable' });
    await settle(fixture);
    const footer = element(fixture).querySelector('footer')?.textContent ?? '';
    expect(footer).toContain('keine Anlageempfehlung');
    expect(footer).not.toContain('Version');
  });

  it('provides the HTTP client for the generated API', () => {
    expect(TestBed.inject(HttpClient)).toBeTruthy();
    expect(typeof latestRankingResource).toBe('function');
    expect(typeof listRunsResource).toBe('function');
  });

  it('sets the defaults for tooltips once', () => {
    expect(TestBed.inject(MAT_TOOLTIP_DEFAULT_OPTIONS)).toEqual({
      showDelay: 400,
      hideDelay: 0,
      touchendHideDelay: 2500,
      position: 'above',
    });
  });

  it('connects the realtime service at start', async () => {
    await render();
    expect(FakeWebSocket.instances.length).toBe(1);
  });

  it('shows the offline chip with icon and tooltip while the connection is down', async () => {
    vi.useFakeTimers();
    try {
      const fixture = TestBed.createComponent(App);
      fixture.detectChanges();
      await answerStart();
      TestBed.tick();
      const status = () => element(fixture).querySelector('[data-realtime]');
      FakeWebSocket.latest().open();
      fixture.detectChanges();
      expect(status()?.getAttribute('data-realtime')).toBe('online');
      expect(status()?.textContent?.trim()).toBe('');

      FakeWebSocket.latest().drop();
      fixture.detectChanges();
      expect(status()?.getAttribute('data-realtime')).toBe('offline');
      const chip = status()?.querySelector('[tabindex="0"]');
      expect(chip?.textContent?.trim()).toBe('offline');
      expect(chip?.querySelector('app-icon svg')).not.toBeNull();
      expect(tooltipOf(fixture, chip as Element)).toContain('Keine Live-Verbindung zum Server.');
    } finally {
      vi.useRealTimers();
    }
  });

  describe('login (D1.4)', () => {
    it('shows the own name linking to the account page and a logout button', async () => {
      const fixture = await render({ required: true, user: me() });
      const account = element(fixture).querySelector<HTMLAnchorElement>('header a[data-account]');
      expect(account?.getAttribute('href')).toBe('/account');
      expect(account?.textContent).toContain('Anna');
      expect(account?.getAttribute('aria-label')).toBe('Konto von Anna');
      const logout = element(fixture).querySelector<HTMLButtonElement>(
        'header button[data-action="logout"]',
      );
      expect(logout?.getAttribute('aria-label')).toBe('Abmelden');
      expect(tooltipOf(fixture, logout as Element)?.length).toBeGreaterThan(10);
    });

    it('logs out on the server when the button is pressed', async () => {
      const fixture = await render({ required: true, user: me() });
      element(fixture).querySelector<HTMLButtonElement>('button[data-action="logout"]')?.click();
      await settle(fixture);
      const request = TestBed.inject(HttpTestingController).expectOne('/api/v1/auth/logout');
      expect(request.request.method).toBe('POST');
    });

    it('shows no navigation while a login is needed and nobody is logged in', async () => {
      const fixture = await render({ required: true });
      expect(element(fixture).querySelectorAll('nav a').length).toBe(0);
      expect(element(fixture).querySelector('header a[data-account]')).toBeNull();
      expect(element(fixture).querySelector('header button[data-action="logout"]')).toBeNull();
    });

    it('offers "Nutzer" in the navigation only to admins', async () => {
      const links = (fixture: ComponentFixture<App>) =>
        Array.from(element(fixture).querySelectorAll('nav a')).map((a) => a.getAttribute('href'));
      expect(links(await render({ required: true, user: ADMIN }))).toEqual([
        '/ranking',
        '/runs',
        '/profiles',
        '/admin/users',
      ]);
    });

    it('hides "Nutzer" from users', async () => {
      const fixture = await render({ required: true, user: me() });
      expect(element(fixture).querySelector('nav a[href="/admin/users"]')).toBeNull();
    });

    it('offers a login link without a login requirement, for the user management', async () => {
      const fixture = await render({ required: false });
      const login = element(fixture).querySelector<HTMLAnchorElement>('header a[data-login]');
      expect(login?.getAttribute('href')).toBe('/login');
      expect(login?.textContent).toContain('Anmelden');
    });

    it('explains every new control (tests 1 and 2)', async () => {
      const fixture = await render({ required: true, user: ADMIN });
      expect(controlsWithoutTooltip(fixture)).toEqual([]);
      expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
    });

    it('waits with the WebSocket until someone is logged in', async () => {
      await render({ required: true });
      expect(FakeWebSocket.instances.length).toBe(0);
    });
  });
});
