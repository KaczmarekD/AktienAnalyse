// Gemeinsame UI-Bausteine (docs/architecture/styleguide.md).
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { BackLink } from './back-link';
import { PageHeader } from './page-header';

@Component({
  imports: [BackLink, PageHeader],
  template: `
    <app-back-link to="/runs">Alle Läufe</app-back-link>
    <app-page-header>
      Lauf 3 <span class="badge">Dry-Run</span>
      <button pageAction type="button">Run starten</button>
    </app-page-header>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class Host {}

function render(): HTMLElement {
  TestBed.configureTestingModule({ providers: [provideRouter([])] });
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  return fixture.nativeElement as HTMLElement;
}

describe('BackLink', () => {
  it('links to the target and names it', () => {
    const link = render().querySelector<HTMLAnchorElement>('app-back-link a');
    expect(link?.getAttribute('href')).toBe('/runs');
    expect(link?.textContent?.trim()).toBe('← Alle Läufe');
  });
});

describe('PageHeader', () => {
  it('puts text and badges into the h1 and actions next to it', () => {
    const header = render().querySelector('app-page-header');
    const h1 = header?.querySelector('h1');
    expect(h1?.textContent).toContain('Lauf 3');
    expect(h1?.querySelector('.badge')?.textContent).toBe('Dry-Run');
    expect(h1?.querySelector('button')).toBeNull();
    expect(header?.querySelector(':scope > button')?.textContent).toBe('Run starten');
  });
});
