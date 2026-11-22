import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { ENTRIES, termTip, TipParams } from '../glossary/glossary';
import { AppIcon } from './icon';

/**
 * Value-Trap-Flag (oberes Value-, unteres Quality-Quartil) in voller Tinte mit Warn-Icon. Das
 * Fragezeichen wie in der Mail: ein Hinweis, genauer hinzusehen, kein Urteil. Der Tooltip nennt
 * die Regel (`reason`, F2.3: „momentum“ für die Regel mit Momentum und F-Score, sonst die
 * bisherige) und die Schwellen des Profils (`params`), ohne sie den allgemeinen Text. Ohne Flag
 * zeigt er nichts.
 */
@Component({
  selector: 'app-value-trap-badge',
  imports: [AppIcon, MatTooltipModule],
  template: `
    @if (flagged()) {
      <span class="badge badge--error" tabindex="0" [matTooltip]="tip()"
        ><app-icon name="warning" />Value-Trap?</span
      >
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ValueTrapBadge {
  readonly flagged = input<boolean | null | undefined>(false);
  readonly reason = input<'quality' | 'momentum' | null | undefined>(undefined);
  readonly params = input<TipParams | undefined>(undefined);

  protected readonly tip = computed(() =>
    termTip(
      this.reason() === 'momentum' ? ENTRIES.value_trap_momentum : ENTRIES.value_trap,
      this.params() ?? {},
    ),
  );
}
