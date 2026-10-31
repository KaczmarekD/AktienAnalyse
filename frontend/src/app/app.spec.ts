// Smoke-Test des Geruests (P3.5): App-Huelle mit Material-Toolbar, Navigation und dem aus der
// OpenAPI generierten Client. Die Ansichten selbst kommen mit P3.7.
import { HttpClient } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';

import { latestRankingResource, listRunsResource } from './api/@angular/common.gen';
import { App } from './app';
import { appConfig } from './app.config';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: appConfig.providers,
    }).compileComponents();
  });

  it('shows the toolbar with the product name', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const toolbar = (fixture.nativeElement as HTMLElement).querySelector('mat-toolbar');
    expect(toolbar?.textContent).toContain('Value-Analyzer');
  });

  it('links to ranking and runs', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const links = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll<HTMLAnchorElement>('nav a'),
    ).map((a) => a.getAttribute('href'));
    expect(links).toEqual(['/ranking', '/runs']);
  });

  it('provides the HTTP client for the generated API', () => {
    expect(TestBed.inject(HttpClient)).toBeTruthy();
    expect(typeof latestRankingResource).toBe('function');
    expect(typeof listRunsResource).toBe('function');
  });
});
