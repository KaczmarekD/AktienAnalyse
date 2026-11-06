import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';

import { TermKey, TipParams } from '../glossary/glossary';
import { GlossaryStore } from '../glossary/glossary.store';
import { AppIcon } from './icon';

/**
 * ⓘ als Icon-Button neben Formular-Labels und Abschnittsköpfen. Der Text kommt aus dem Glossar
 * (`key`) oder direkt (`text`); `aria-label` sagt, wonach gefragt wird.
 */
@Component({
  selector: 'app-info-tip',
  imports: [AppIcon, MatButtonModule, MatTooltipModule],
  template: `
    <button matIconButton type="button" [attr.aria-label]="ariaLabel()" [matTooltip]="message()">
      <app-icon name="info" />
    </button>
  `,
  styles: `
    :host {
      display: inline-flex;
      color: var(--mat-sys-on-surface-variant);
    }

    button {
      --mat-icon-button-state-layer-size: var(--va-size-control);
      color: inherit;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InfoTip {
  private readonly glossary = inject(GlossaryStore);

  readonly key = input<TermKey | undefined>(undefined);
  readonly text = input<string | undefined>(undefined);
  readonly label = input<string | undefined>(undefined);
  readonly params = input<TipParams | undefined>(undefined);

  protected readonly message = computed(() => {
    const key = this.key();
    return this.text() ?? (key ? this.glossary.tip(key, this.params() ?? {}) : '');
  });
  protected readonly ariaLabel = computed(() => {
    const key = this.key();
    return this.label() ?? (key ? `Was heißt ${this.glossary.label(key)}?` : 'Erklärung');
  });
}
