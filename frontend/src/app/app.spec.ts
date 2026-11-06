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
import { App } from './app';
import { appConfig } from './app.config';
import { routes } from './app.routes';
import { RealtimeService } from './shared/realtime/realtime.service';
import { FakeWebSocket, realtimeTestingProviders } from './testing/realtime';

const HEALTH = '/api/v1/health';

function element(fixture: ComponentFixture<App>): HTMLElement {
  return fixture.nativeElement as HTMLElement;
}

function tooltipOf(fixture: ComponentFixture<App>, host: Element): string | undefined {
  const match = fixture.debugElement
    .queryAll(By.directive(MatTooltip))
    .find((debug) => debug.nativeElement === host);
  return match?.injector.get(MatTooltip).message;
}

/** Zeichnet die Hülle und beantwortet die Frage nach der Version, ohne auf whenStable zu warten. */
async function render(): Promise<ComponentFixture<App>> {
  const fixture = TestBed.createComponent(App);
  fixture.detectChanges();
  TestBed.tick();
  TestBed.inject(HttpTestingController).expectOne(HEALTH).flush({ status: 'ok', version: '1.4.0' });
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

  it('marks the active section, the title detail belongs to the ranking', async () => {
    const fixture = TestBed.createComponent(App);
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
});
