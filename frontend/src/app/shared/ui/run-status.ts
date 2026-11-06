import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatTooltipModule } from '@angular/material/tooltip';

import { RunStatusPipe } from '../format';
import { ENTRIES, GlossaryEntry, TermKey, termTip } from '../glossary/glossary';
import type { Progress } from '../realtime/live.store';
import { AppIcon, IconName } from './icon';

/** Icon je Status (Spec, „Bedeutung ohne Farbe“); die Fläche setzt das SCSS über data-status. */
const ICON: Record<string, IconName> = {
  running: 'progress_activity',
  success: 'check_circle',
  partial: 'info',
  no_data: 'error',
  failed: 'error',
};

/**
 * Status eines Laufs auf Deutsch, mit Icon und Fläche je Status und dem Tooltip aus dem Glossar.
 * Während eines Abrufs steht der Fortschritt daneben (P4.6): Balken und „57/90“, der zuletzt
 * abgerufene Titel im Tooltip.
 */
@Component({
  selector: 'app-run-status',
  imports: [AppIcon, MatProgressBarModule, MatTooltipModule, RunStatusPipe],
  host: { '[attr.data-status]': 'status()' },
  template: `
    <span class="status" tabindex="0" [matTooltip]="tip()">
      <app-icon [name]="icon()" [spin]="status() === 'running'" />
      {{ status() | runStatus }}
    </span>
    @if (progress(); as step) {
      <span class="progress" data-progress tabindex="0" [matTooltip]="progressTip()">
        <mat-progress-bar
          mode="determinate"
          [value]="step.total > 0 ? (step.done / step.total) * 100 : 0"
          [attr.aria-label]="progressTip()"
        />
        {{ step.done }}/{{ step.total }}
      </span>
    }
  `,
  styles: `
    :host {
      display: inline-flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--va-space-sm);
    }

    .status {
      display: inline-flex;
      align-items: center;
      gap: var(--va-space-xs);
      padding: var(--va-space-2xs) var(--va-space-sm);
      border: 1px solid transparent;
      border-radius: var(--va-radius-pill);
      font: var(--mat-sys-label-large);
      white-space: nowrap;
    }

    // Erfolg ist der Normalfall: ohne Fläche, nur das Häkchen
    :host([data-status='success']) .status {
      padding-inline: 0;
    }

    :host([data-status='running']) .status {
      border: var(--va-outline);
      background-color: var(--mat-sys-surface);
    }

    :host([data-status='partial']) .status {
      background-color: var(--mat-sys-surface-container-highest);
    }

    :host([data-status='no_data']) .status {
      background-color: var(--mat-sys-error-container);
      color: var(--mat-sys-on-error-container);
    }

    :host([data-status='failed']) .status {
      background-color: var(--mat-sys-error);
      color: var(--mat-sys-on-error);
    }

    .progress {
      display: inline-flex;
      align-items: center;
      gap: var(--va-space-sm);
      color: var(--mat-sys-on-surface-variant);
      font: var(--mat-sys-body-small);
      font-variant-numeric: tabular-nums;
    }

    mat-progress-bar {
      width: var(--va-size-bar);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunStatus {
  readonly status = input.required<string>();
  readonly progress = input<Progress | undefined>();

  protected readonly icon = computed<IconName>(() => ICON[this.status()] ?? 'info');
  protected readonly tip = computed(() => {
    const entry = ENTRIES[`status.${this.status()}` as TermKey] as GlossaryEntry | undefined;
    return entry ? termTip(entry) : '';
  });
  protected readonly progressTip = computed(() => {
    const step = this.progress();
    if (!step) {
      return '';
    }
    const last = step.symbol ? `, zuletzt ${step.symbol}` : '';
    return `${step.done} von ${step.total} Titeln abgerufen${last}.`;
  });
}
