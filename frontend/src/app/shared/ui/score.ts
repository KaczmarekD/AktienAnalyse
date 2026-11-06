import {
  booleanAttribute,
  ChangeDetectionStrategy,
  Component,
  computed,
  input,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { NumPipe } from '../format';
import { scoreTip } from '../glossary/glossary';

/**
 * Score als Zahl (0 bis 1), auf Wunsch mit Balken in Tinte; der Tooltip ordnet ihn ein
 * („besser als etwa 78 % der bewerteten Titel“). Ohne Wert ein Strich mit dem Grund.
 */
@Component({
  selector: 'app-score',
  imports: [MatTooltipModule, NumPipe],
  template: `
    <span class="score" [matTooltip]="tip()"
      >{{ value() | num }}
      @if (bar() && hasValue()) {
        <span class="bar" data-bar aria-hidden="true"
          ><span [style.width.%]="percent()"></span
        ></span>
      }
    </span>
  `,
  styles: `
    .score {
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      gap: var(--va-space-sm);
      font-variant-numeric: tabular-nums;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Score {
  readonly value = input<number | null | undefined>(null);
  readonly bar = input(false, { transform: booleanAttribute });

  protected readonly tip = computed(() => scoreTip(this.value()));
  protected readonly hasValue = computed(() => this.value() !== null && this.value() !== undefined);
  protected readonly percent = computed(() => Math.round(Math.min(1, this.value() ?? 0) * 100));
}
