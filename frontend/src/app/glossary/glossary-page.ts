import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';

import { latestRankingResource } from '../api/@angular/common.gen';
import { TipParams } from '../shared/glossary/glossary';
import { GlossaryStore } from '../shared/glossary/glossary.store';
import { PctPipe } from '../shared/format';
import { loaded } from '../shared/resource';
import { FORM_FIELD_DEFAULTS } from '../shared/ui/form-field';
import { AppIcon } from '../shared/ui/icon';
import { PageHeader } from '../shared/ui/page-header';

/**
 * Seite „Begriffe“ (/glossary, Track G): jeder Begriff mit dem Text, den auch sein Tooltip zeigt,
 * mit Anker (/glossary#roic) und Suche, dazu wie das Ranking entsteht. Werte in den Texten stammen
 * aus dem jüngsten Bewertungslauf; ohne ihn stehen die Texte allgemein.
 */
@Component({
  selector: 'app-glossary-page',
  imports: [AppIcon, MatFormFieldModule, MatInputModule, MatTooltipModule, PageHeader, PctPipe],
  providers: [FORM_FIELD_DEFAULTS],
  templateUrl: './glossary-page.html',
  styleUrl: './glossary-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GlossaryPage {
  private readonly glossary = inject(GlossaryStore);
  private readonly ranking = latestRankingResource(() => ({}));

  protected readonly params = computed<TipParams>(() => {
    const ranking = loaded(this.ranking);
    return { value_weight: ranking?.value_weight ?? null };
  });
  protected readonly search = signal('');
  protected readonly groups = computed(() => this.glossary.groups(this.search(), this.params()));

  protected onSearch(event: Event): void {
    this.search.set((event.target as HTMLInputElement).value);
  }
}
