// Gemeinsame UI-Bausteine (docs/architecture/styleguide.md).
import { ChangeDetectionStrategy, Component, signal, Type } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import type { Progress } from '../realtime/live.store';
import { BackLink } from './back-link';
import { Notice, NoticeBox } from './notice';
import { PageHeader } from './page-header';
import { RunStatus } from './run-status';
import { ValueTrapBadge } from './value-trap-badge';

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
class PageHost {}

@Component({
  imports: [RunStatus],
  template: `<app-run-status [status]="status()" [progress]="progress()" />`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class RunStatusHost {
  readonly status = signal('running');
  readonly progress = signal<Progress | undefined>(undefined);
}

@Component({
  imports: [ValueTrapBadge],
  template: `<app-value-trap-badge [flagged]="flagged()" />`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class BadgeHost {
  readonly flagged = signal<boolean | null>(true);
}

@Component({
  imports: [NoticeBox],
  template: `<app-notice [notice]="notice()" />`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class NoticeHost {
  readonly notice = signal<Notice | undefined>(undefined);
}

function render<T>(host: Type<T>) {
  TestBed.configureTestingModule({ providers: [provideRouter([])] });
  const fixture = TestBed.createComponent(host);
  fixture.detectChanges();
  const element = fixture.nativeElement as HTMLElement;
  return { fixture, element };
}

describe('BackLink', () => {
  it('links to the target and names it', () => {
    const link = render(PageHost).element.querySelector<HTMLAnchorElement>('app-back-link a');
    expect(link?.getAttribute('href')).toBe('/runs');
    expect(link?.textContent?.trim()).toBe('← Alle Läufe');
  });
});

describe('PageHeader', () => {
  it('puts text and badges into the h1 and actions next to it', () => {
    const header = render(PageHost).element.querySelector('app-page-header');
    const h1 = header?.querySelector('h1');
    expect(h1?.textContent).toContain('Lauf 3');
    expect(h1?.textContent).toContain('Dry-Run');
    expect(h1?.querySelector('button')).toBeNull();
    expect(header?.querySelector(':scope > button')?.textContent).toBe('Run starten');
  });
});

describe('RunStatus', () => {
  it('names the status in German and marks it with data-status', () => {
    const { fixture, element } = render(RunStatusHost);
    fixture.componentInstance.status.set('failed');
    fixture.detectChanges();
    const status = element.querySelector('app-run-status');
    expect(status?.getAttribute('data-status')).toBe('failed');
    expect(status?.textContent?.trim()).toBe('fehlgeschlagen');
  });

  it('shows the progress of a running fetch only when there is one', () => {
    const { fixture, element } = render(RunStatusHost);
    expect(element.querySelector('[data-progress]')).toBeNull();

    fixture.componentInstance.progress.set({ done: 57, total: 90, symbol: 'SAP.DE' });
    fixture.detectChanges();
    const progress = element.querySelector('[data-progress]');
    expect(progress?.textContent?.trim()).toBe('57/90');
    expect(progress?.getAttribute('title')).toBe('SAP.DE');
  });
});

describe('ValueTrapBadge', () => {
  it('shows the warning only for flagged titles', () => {
    const { fixture, element } = render(BadgeHost);
    const badge = () => element.querySelector('app-value-trap-badge')?.textContent?.trim();
    expect(badge()).toBe('Value-Trap?');

    for (const flagged of [false, null]) {
      fixture.componentInstance.flagged.set(flagged);
      fixture.detectChanges();
      expect(badge()).toBe('');
    }
  });
});

describe('NoticeBox', () => {
  it('shows nothing without a notice', () => {
    expect(render(NoticeHost).element.querySelector('app-notice')?.textContent?.trim()).toBe('');
  });

  it('reports success as status and failure as alert', () => {
    const { fixture, element } = render(NoticeHost);
    fixture.componentInstance.notice.set({ text: 'Lauf #8 gestartet.' });
    fixture.detectChanges();
    expect(element.querySelector('[role="status"]')?.textContent?.trim()).toBe(
      'Lauf #8 gestartet.',
    );
    expect(element.querySelector('[role="alert"]')).toBeNull();

    fixture.componentInstance.notice.set({ text: 'Es läuft schon ein Lauf.', error: true });
    fixture.detectChanges();
    expect(element.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
      'Es läuft schon ein Lauf.',
    );
    expect(element.querySelector('[role="status"]')).toBeNull();
  });
});
