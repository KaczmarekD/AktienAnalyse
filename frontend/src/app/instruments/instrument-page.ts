import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';

import { getInstrumentResource } from '../api/@angular/common.gen';
import { errorMessage } from '../shared/api-error';
import { MrdPipe, NumPipe, PctPipe } from '../shared/format';
import { BackLink } from '../shared/ui/back-link';
import { PageHeader } from '../shared/ui/page-header';

/** Ein Titel: Stammdaten, Kennzahlen des neuesten Abrufs, Score-Verlauf (/instruments/:symbol). */
@Component({
  selector: 'app-instrument-page',
  imports: [BackLink, DatePipe, MatTableModule, MrdPipe, NumPipe, PageHeader, PctPipe, RouterLink],
  templateUrl: './instrument-page.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InstrumentPage {
  readonly symbol = input.required<string>();

  private readonly resource = getInstrumentResource(() => ({ path: { symbol: this.symbol() } }));

  protected readonly instrument = computed(() =>
    this.resource.hasValue() ? this.resource.value() : undefined,
  );
  protected readonly error = computed(() => {
    const error = this.resource.error();
    return error ? errorMessage(error, 'Titel nicht gefunden.') : undefined;
  });
  /** Neueste Bewertung zuerst. */
  protected readonly history = computed(() =>
    [...(this.instrument()?.score_history ?? [])].reverse(),
  );

  protected readonly columns = [
    'created_at',
    'rank',
    'composite_score',
    'value_score',
    'quality_score',
    'value_trap_flag',
  ];
}
