// Gemeinsame UI-Bausteine (docs/architecture/styleguide.md).
import { ChangeDetectionStrategy, Component, signal, Type } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { vi } from 'vitest';

import type { Progress } from '../realtime/live.store';
import { BackLink } from './back-link';
import { AppIcon, ICONS } from './icon';
import { Notice, NoticeBox } from './notice';
import { PageHeader } from './page-header';
import { RunStatus } from './run-status';
import { AppSection } from './section';
import { AppState } from './state';
import { ValueTrapBadge } from './value-trap-badge';

@Component({
  imports: [AppIcon],
  template: `<app-icon name="warning" /><app-icon name="progress_activity" size="md" spin />`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class IconHost {}

@Component({
  imports: [AppSection],
  template: `
    <app-section heading="Kennzahlen">
      <button sectionInfo type="button" aria-label="Was steht hier?">i</button>
      <button sectionActions type="button">Kopieren</button>
      <p>Inhalt</p>
    </app-section>
    <app-section heading="Verlauf" [level]="3"><p>mehr</p></app-section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class SectionHost {}

@Component({
  imports: [AppState],
  template: `
    <app-state [error]="error()" [empty]="empty()" loading="Lade das Ranking …">
      <button type="button">Lauf starten</button>
    </app-state>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class StateHost {
  readonly error = signal<string | undefined>(undefined);
  readonly empty = signal<string | undefined>(undefined);
}

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

describe('AppIcon', () => {
  it('draws the path from the fixed list and hides it from screen readers', () => {
    const [warning, progress] = Array.from(render(IconHost).element.querySelectorAll('app-icon'));
    const svg = warning.querySelector('svg');
    expect(svg?.getAttribute('aria-hidden')).toBe('true');
    expect(svg?.querySelector('path')?.getAttribute('d')).toBe(ICONS.warning);
    expect(warning.getAttribute('data-size')).toBe('sm');
    expect(warning.hasAttribute('data-spin')).toBe(false);
    expect(progress.getAttribute('data-size')).toBe('md');
    expect(progress.hasAttribute('data-spin')).toBe(true);
  });

  it('has every icon of the spec', () => {
    expect(Object.keys(ICONS)).toEqual(
      expect.arrayContaining([
        'leaderboard',
        'history',
        'tune',
        'help',
        'info',
        'warning',
        'error',
        'check_circle',
        'progress_activity',
        'play_arrow',
        'download',
        'content_copy',
        'search',
        'view_column',
        'arrow_back',
        'arrow_upward',
        'arrow_downward',
        'cloud_off',
        'close',
      ]),
    );
  });
});

describe('AppSection', () => {
  it('is a region named by its heading, with info and actions in the head', () => {
    const [first, second] = Array.from(
      render(SectionHost).element.querySelectorAll('app-section section'),
    );
    const heading = first.querySelector('h2');
    expect(heading?.textContent?.trim()).toBe('Kennzahlen');
    expect(first.getAttribute('aria-labelledby')).toBe(heading?.id);
    const head = first.querySelector('[data-section-head]');
    expect(head?.querySelector('button[aria-label="Was steht hier?"]')).not.toBeNull();
    expect(head?.textContent).toContain('Kopieren');
    expect(head?.textContent).not.toContain('Inhalt');
    expect(first.textContent).toContain('Inhalt');
    expect(second.querySelector('h3')?.textContent?.trim()).toBe('Verlauf');
    expect(second.getAttribute('aria-labelledby')).not.toBe(first.getAttribute('aria-labelledby'));
  });
});

describe('AppState', () => {
  it('shows the loading bar and text only after 300 ms', () => {
    vi.useFakeTimers();
    try {
      const { fixture, element } = render(StateHost);
      vi.advanceTimersByTime(299);
      fixture.detectChanges();
      expect(element.querySelector('app-state')?.textContent?.trim()).toBe('');

      vi.advanceTimersByTime(1);
      fixture.detectChanges();
      expect(element.querySelector('[role="status"]')?.textContent).toContain('Lade das Ranking …');
      expect(element.querySelector('[role="progressbar"]')).not.toBeNull();
      expect(element.textContent).not.toContain('Lauf starten');
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows an error at once as alert, without the loading bar', () => {
    const { fixture, element } = render(StateHost);
    fixture.componentInstance.error.set('Der Server oder seine Datenbank ist nicht erreichbar.');
    fixture.detectChanges();
    expect(element.querySelector('[role="alert"]')?.textContent).toContain('nicht erreichbar');
    expect(element.querySelector('[role="alert"] app-icon')).not.toBeNull();
    expect(element.querySelector('[role="progressbar"]')).toBeNull();
  });

  it('shows the empty state with icon, sentence and the next step', () => {
    const { fixture, element } = render(StateHost);
    fixture.componentInstance.empty.set('Noch keine Läufe.');
    fixture.detectChanges();
    const state = element.querySelector('app-state');
    expect(state?.textContent).toContain('Noch keine Läufe.');
    expect(state?.querySelector('button')?.textContent).toBe('Lauf starten');
    expect(state?.querySelector('app-icon')).not.toBeNull();
    expect(element.querySelector('[role="alert"]')).toBeNull();
  });
});
