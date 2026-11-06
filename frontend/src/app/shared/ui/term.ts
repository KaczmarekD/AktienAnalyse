import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { TermKey, TipParams } from '../glossary/glossary';
import { GlossaryStore } from '../glossary/glossary.store';

/**
 * Begriff mit Tooltip aus dem Glossar, gepunktet unterstrichen und mit der Tastatur erreichbar:
 * `<app-term key="ev_ebit" />`. Statt des Labels darf eigener Text stehen
 * (`<app-term key="scoring_run">Bewertungslauf #42</app-term>`), `variant="short"` nimmt das
 * Kurzlabel für Spaltenköpfe. Ohne Text (Faktor, solange die API nicht antwortet) bleibt es Text.
 * `[focusable]="false"` nimmt den Tab-Stopp weg, etwa für das Kürzel des Index in jeder
 * Tabellenzeile; der Tooltip bleibt für die Maus, die Tastatur findet ihn am Filter.
 */
@Component({
  selector: 'app-term',
  imports: [MatTooltipModule],
  template: `
    <span
      [class.term]="!!tip()"
      [attr.tabindex]="tip() && focusable() ? 0 : null"
      [matTooltip]="tip()"
      [matTooltipDisabled]="!tip()"
      ><ng-content>{{ label() }}</ng-content></span
    >
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Term {
  private readonly glossary = inject(GlossaryStore);

  readonly key = input.required<TermKey>();
  readonly variant = input<'long' | 'short'>('long');
  /** Werte aus dem Profil, etwa die Schwellen für „Value-Trap?“ */
  readonly params = input<TipParams | undefined>(undefined);
  readonly focusable = input(true);

  protected readonly label = computed(() => this.glossary.label(this.key(), this.variant()));
  protected readonly tip = computed(() => this.glossary.tip(this.key(), this.params() ?? {}));
}
