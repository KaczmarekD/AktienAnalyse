import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import type { Progress } from '../realtime/live.store';
import { RunStatusPipe } from '../format';

/**
 * Status eines Laufs auf Deutsch; fehlgeschlagen und ohne Daten in Rot. Während eines Abrufs
 * steht der Fortschritt daneben (P4.6), das Symbol des letzten Titels im Tooltip.
 */
@Component({
  selector: 'app-run-status',
  imports: [RunStatusPipe],
  host: { '[attr.data-status]': 'status()' },
  template: `
    {{ status() | runStatus }}
    @if (progress(); as step) {
      <span class="progress" data-progress [title]="step.symbol"
        >{{ step.done }}/{{ step.total }}</span
      >
    }
  `,
  styles: `
    :host([data-status='failed']),
    :host([data-status='no_data']) {
      color: var(--mat-sys-error);
      font-weight: var(--va-weight-emphasis);
    }

    .progress {
      margin-left: var(--va-space-sm);
      color: var(--mat-sys-on-surface-variant);
      font-variant-numeric: tabular-nums;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunStatus {
  readonly status = input.required<string>();
  readonly progress = input<Progress | undefined>();
}
