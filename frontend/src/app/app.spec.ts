// Smoke-Test des Geruests (P3.5): App-Huelle mit Material-Toolbar, Navigation und dem aus der
// OpenAPI generierten Client. Die Ansichten selbst kommen mit P3.7.
import { HttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { latestRankingResource, listRunsResource } from './api/@angular/common.gen';
import { App } from './app';
import { appConfig } from './app.config';
import { RealtimeService } from './shared/realtime/realtime.service';
import { FakeWebSocket, realtimeTestingProviders } from './testing/realtime';

describe('App', () => {
  beforeEach(async () => {
    FakeWebSocket.reset();
    await TestBed.configureTestingModule({
      imports: [App],
      // P4.6: kein echter WebSocket im Test
      providers: [...appConfig.providers, ...realtimeTestingProviders()],
    }).compileComponents();
  });

  afterEach(() => TestBed.inject(RealtimeService).stop());

  it('shows the toolbar with the product name', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const toolbar = (fixture.nativeElement as HTMLElement).querySelector('mat-toolbar');
    expect(toolbar?.textContent).toContain('Value-Analyzer');
  });

  it('links to ranking, runs and profiles', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const links = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>('nav a'),
    ).map((a) => a.getAttribute('href'));
    expect(links).toEqual(['/ranking', '/runs', '/profiles']);
  });

  it('provides the HTTP client for the generated API', () => {
    expect(TestBed.inject(HttpClient)).toBeTruthy();
    expect(typeof latestRankingResource).toBe('function');
    expect(typeof listRunsResource).toBe('function');
  });

  it('connects the realtime service at start', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    expect(FakeWebSocket.instances.length).toBe(1);
  });

  it('shows offline while the connection is down', async () => {
    vi.useFakeTimers();
    try {
      const fixture = TestBed.createComponent(App);
      fixture.detectChanges();
      const status = () => (fixture.nativeElement as HTMLElement).querySelector('[data-realtime]');
      FakeWebSocket.latest().open();
      fixture.detectChanges();
      expect(status()?.getAttribute('data-realtime')).toBe('online');
      expect(status()?.textContent?.trim()).toBe('');

      FakeWebSocket.latest().drop();
      fixture.detectChanges();
      expect(status()?.getAttribute('data-realtime')).toBe('offline');
      expect(status()?.textContent).toContain('offline');
    } finally {
      vi.useRealTimers();
    }
  });
});
