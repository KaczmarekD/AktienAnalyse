import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Value-Trap-Flag (oberes Value-, unteres Quality-Quartil). Das Fragezeichen wie in der Mail:
 * ein Hinweis, genauer hinzusehen, kein Urteil. Ohne Flag zeigt der Baustein nichts.
 */
@Component({
  selector: 'app-value-trap-badge',
  template: `
    @if (flagged()) {
      <span class="badge badge--error">Value-Trap?</span>
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ValueTrapBadge {
  readonly flagged = input<boolean | null | undefined>(false);
}
