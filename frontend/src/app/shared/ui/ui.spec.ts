// Gemeinsame UI-Bausteine (docs/architecture/styleguide.md).
import { HttpTestingController } from '@angular/common/http/testing';
import { ChangeDetectionStrategy, Component, LOCALE_ID, signal, Type } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { provideRouter } from '@angular/router';
import { vi } from 'vitest';

import '../../locale';
import { apiTestingProviders } from '../../testing/api';
import { FACTORS } from '../../testing/fixtures';

import type { Progress } from '../realtime/live.store';
import { BackLink } from './back-link';
import { ColumnGroup, ColumnPicker } from './column-picker';
import { AppIcon, ICONS } from './icon';
import { InfoTip } from './info-tip';
import { Notice, NoticeBox } from './notice';
import { PageHeader } from './page-header';
import { RunStatus } from './run-status';
import { AppSection } from './section';
import { Score } from './score';
import { Sparkline, SparkPoint } from './sparkline';
import { StatCard } from './stat-card';
import { AppState } from './state';
import { Term } from './term';
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

@Component({
  imports: [Term],
  template: `
    <app-term key="ev_ebit" data-case="factor" />
    <app-term key="revenue_growth_5y" variant="short" data-case="short" />
    <app-term key="scoring_run" data-case="content">Bewertungslauf #42</app-term>
    <app-term key="value_trap" [params]="params" data-case="params" />
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class TermHost {
  readonly params = { value_trap_value_threshold: 0.7, value_trap_quality_threshold: 0.3 };
}

@Component({
  imports: [InfoTip],
  template: `
    <app-info-tip text="Holt die Daten neu von Yahoo." label="Was heißt Daten neu abrufen?" />
    <app-info-tip key="min_market_cap" />
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class InfoTipHost {}

@Component({
  imports: [Term],
  template: `<app-term key="DAX" [focusable]="false" />`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class QuietTermHost {}

@Component({
  imports: [Score],
  template: `
    <app-score [value]="0.777" bar data-case="bar" />
    <app-score [value]="0.4" data-case="plain" />
    <app-score [value]="null" data-case="missing" />
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class ScoreHost {}

@Component({
  imports: [StatCard],
  template: `
    <app-stat-card label="Bewertet" tip="Titel mit Composite." data-case="plain">
      3 <span statSub>mit Composite</span>
    </app-stat-card>
    <app-stat-card
      label="Spitzenreiter"
      tip="Öffnet den Titel."
      link="/instruments/ALV.DE"
      data-case="link"
    >
      Allianz
    </app-stat-card>
    <app-stat-card
      label="Value-Traps"
      tip="Zeigt nur die Value-Traps."
      [pressed]="pressed()"
      (toggled)="pressed.set(!pressed())"
      data-case="toggle"
      >1</app-stat-card
    >
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class StatCardHost {
  readonly pressed = signal(false);
}

@Component({
  imports: [ColumnPicker],
  template: `<app-column-picker [groups]="groups" [(selected)]="selected" />`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class ColumnPickerHost {
  readonly groups: ColumnGroup[] = [
    { label: 'Allgemein', columns: [{ key: 'sector', label: 'Sektor', tip: 'Branche.' }] },
    {
      label: 'Value-Faktoren',
      columns: [{ key: 'pb_ratio', label: 'KBV', tip: 'Kurs-Buchwert.' }],
    },
  ];
  readonly selected = signal<string[]>(['sector']);
}

@Component({
  imports: [Sparkline],
  template: `<app-sparkline [points]="points()" label="Composite" />`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class SparklineHost {
  readonly points = signal<SparkPoint[]>([
    { label: '23.10.2026', value: 0.71, detail: 'Rang 3' },
    { label: '30.10.2026', value: null, detail: 'ohne Composite' },
    { label: '06.11.2026', value: 0.78, detail: 'Rang 1' },
  ]);
}

/** Mit Antwort auf die Faktortexte, die der GlossaryStore beim ersten Gebrauch lädt. */
async function renderWithGlossary<T>(host: Type<T>, factors = true) {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  const fixture = TestBed.createComponent(host);
  fixture.detectChanges();
  TestBed.tick();
  const request = TestBed.inject(HttpTestingController).expectOne('/api/v1/scoring/factors');
  if (factors) {
    request.flush(FACTORS);
  }
  await new Promise((resolve) => setTimeout(resolve));
  TestBed.tick();
  fixture.detectChanges();
  return { fixture, element: fixture.nativeElement as HTMLElement };
}

function tooltip(fixture: ComponentFixture<unknown>, element: Element | null): string | undefined {
  return fixture.debugElement
    .queryAll(By.directive(MatTooltip))
    .find((debug) => debug.nativeElement === element)
    ?.injector.get(MatTooltip)
    .message.replace(/\s/g, ' '); // geschützte Leerzeichen wie normale
}

function render<T>(host: Type<T>) {
  TestBed.configureTestingModule({
    providers: [provideRouter([]), { provide: LOCALE_ID, useValue: 'de-DE' }],
  });
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
    // Bedeutung ohne Farbe: Icon und Tooltip aus dem Glossar
    expect(status?.querySelector('app-icon svg')).not.toBeNull();
    expect(tooltip(fixture, status?.querySelector('[tabindex="0"]') ?? null)).toContain(
      'abgebrochen',
    );
  });

  it('shows the progress of a running fetch only when there is one', () => {
    const { fixture, element } = render(RunStatusHost);
    expect(element.querySelector('[data-progress]')).toBeNull();

    fixture.componentInstance.progress.set({ done: 57, total: 90, symbol: 'SAP.DE' });
    fixture.detectChanges();
    const progress = element.querySelector('[data-progress]');
    expect(progress?.textContent?.trim()).toBe('57/90');
    // Tooltip statt nativem title (Spec, Technik)
    expect(progress?.hasAttribute('title')).toBe(false);
    expect(tooltip(fixture, progress)).toBe('57 von 90 Titeln abgerufen, zuletzt SAP.DE.');
    expect(element.querySelector('[data-progress] [role="progressbar"]')).not.toBeNull();
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
    // Bedeutung ohne Farbe: Erfolg mit Häkchen, Fehler mit Fehler-Icon
    expect(element.querySelector('[role="status"] app-icon svg')).not.toBeNull();
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

describe('Term', () => {
  it('shows the label with the tooltip from the glossary and can be focused', async () => {
    const { fixture, element } = await renderWithGlossary(TermHost);
    const term = (name: string) => element.querySelector(`[data-case="${name}"] span`);
    expect(term('factor')?.textContent?.trim()).toBe('EV/EBIT');
    expect(term('factor')?.getAttribute('tabindex')).toBe('0');
    expect(tooltip(fixture, term('factor'))).toMatch(/Niedriger ist besser\. Value-Faktor\.$/);
    expect(term('short')?.textContent?.trim()).toBe('Umsatz 5 J.');
    expect(term('content')?.textContent?.trim()).toBe('Bewertungslauf #42');
    expect(tooltip(fixture, term('content'))).toContain('Berechnung des Rankings');
    expect(tooltip(fixture, term('params'))).toContain('Value ≥ 0,70');
  });

  it('is plain text without tooltip while there is no text', async () => {
    const { element } = await renderWithGlossary(TermHost, false);
    const factor = element.querySelector('[data-case="factor"] span');
    expect(factor?.textContent?.trim()).toBe('EV/EBIT');
    expect(factor?.hasAttribute('tabindex')).toBe(false);
  });
});

describe('InfoTip', () => {
  it('is an icon button with aria-label and the same explanation as tooltip', async () => {
    const { fixture, element } = await renderWithGlossary(InfoTipHost);
    const [own, glossary] = Array.from(element.querySelectorAll('app-info-tip button'));
    expect(own.getAttribute('type')).toBe('button');
    expect(own.getAttribute('aria-label')).toBe('Was heißt Daten neu abrufen?');
    expect(tooltip(fixture, own)).toBe('Holt die Daten neu von Yahoo.');
    expect(own.querySelector('app-icon')).not.toBeNull();
    expect(glossary.getAttribute('aria-label')).toBe('Was heißt Größenschwelle?');
    expect(tooltip(fixture, glossary)).toContain('Börsenwert');
  });
});

describe('Term without focus', () => {
  it('keeps the tooltip but is no tab stop, e.g. in every table row', async () => {
    const { fixture, element } = await renderWithGlossary(QuietTermHost);
    const term = element.querySelector('app-term span');
    expect(term?.hasAttribute('tabindex')).toBe(false);
    expect(tooltip(fixture, term)).toContain('40 größten');
  });
});

describe('Score', () => {
  it('shows the score with optional bar and explains it as percentile', () => {
    const { fixture, element } = render(ScoreHost);
    const score = (name: string) => element.querySelector(`[data-case="${name}"] span`);
    expect(score('bar')?.textContent?.trim()).toBe('0,78');
    expect(element.querySelector('[data-case="bar"] [data-bar]')).not.toBeNull();
    expect(element.querySelector('[data-case="plain"] [data-bar]')).toBeNull();
    expect(tooltip(fixture, score('bar'))).toContain('besser als etwa 78 %');
    expect(score('missing')?.textContent?.trim()).toBe('–');
    expect(tooltip(fixture, score('missing'))).toContain('Kein Composite');
  });
});

describe('StatCard', () => {
  it('is a focusable card, a link or a toggle button, each with tooltip', () => {
    const { fixture, element } = render(StatCardHost);
    const card = (name: string) => element.querySelector(`[data-case="${name}"] [data-stat]`);
    expect(card('plain')?.tagName).toBe('DIV');
    expect(card('plain')?.getAttribute('tabindex')).toBe('0');
    expect(card('plain')?.textContent).toContain('Bewertet');
    expect(card('plain')?.textContent).toContain('mit Composite');
    expect(card('link')?.tagName).toBe('A');
    expect(card('link')?.getAttribute('href')).toBe('/instruments/ALV.DE');
    expect(card('toggle')?.tagName).toBe('BUTTON');
    expect(card('toggle')?.getAttribute('aria-pressed')).toBe('false');
    for (const name of ['plain', 'link', 'toggle']) {
      expect(tooltip(fixture, card(name))).toBeTruthy();
    }

    (card('toggle') as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(card('toggle')?.getAttribute('aria-pressed')).toBe('true');
  });
});

describe('ColumnPicker', () => {
  it('opens a menu with the columns by group and switches them on and off', async () => {
    const { fixture, element } = render(ColumnPickerHost);
    const button = element.querySelector<HTMLButtonElement>('button[data-action="columns"]');
    expect(button?.getAttribute('aria-label')).toBe('Spalten wählen');
    expect(tooltip(fixture, button)).toBe('Weitere Faktoren ein- oder ausblenden.');
    button?.click();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(document.body.textContent).toContain('Value-Faktoren');
    const kbv = document.querySelector<HTMLInputElement>('[data-column="pb_ratio"] input');
    kbv?.click();
    fixture.detectChanges();
    expect(fixture.componentInstance.selected()).toEqual(['sector', 'pb_ratio']);
    const sector = document.querySelector<HTMLInputElement>('[data-column="sector"] input');
    sector?.click();
    fixture.detectChanges();
    expect(fixture.componentInstance.selected()).toEqual(['pb_ratio']);
  });
});

describe('Sparkline', () => {
  it('draws the values as a line with a dot each and describes the change', () => {
    const { fixture, element } = render(SparklineHost);
    const svg = element.querySelector('app-sparkline svg');
    expect(svg?.getAttribute('role')).toBe('img');
    expect(svg?.getAttribute('aria-label')).toBe('Verlauf des Composite von 0,71 auf 0,78');
    // Punkte ohne Wert fehlen in der Linie
    expect(svg?.querySelector('polyline')?.getAttribute('points')?.split(' ')).toHaveLength(2);
    const dots = Array.from(svg?.querySelectorAll('circle') ?? []);
    expect(dots).toHaveLength(2);
    expect(tooltip(fixture, dots[1])).toBe('06.11.2026: Composite 0,78, Rang 1');
  });

  it('says when there are too few values for a line', () => {
    const { fixture, element } = render(SparklineHost);
    fixture.componentInstance.points.set([{ label: '30.10.2026', value: 0.78, detail: 'Rang 1' }]);
    fixture.detectChanges();
    expect(element.querySelector('app-sparkline svg')).toBeNull();
    expect(element.textContent).toContain('Zu wenige Bewertungen für einen Verlauf.');
  });
});
