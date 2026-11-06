import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';

import { getInstrumentResource } from '../api/@angular/common.gen';
import { DayPipe, MrdPipe, NumPipe, OrDashPipe, PctPipe } from '../shared/format';
import { loaded, loadError } from '../shared/resource';
import { BackLink } from '../shared/ui/back-link';
import { PageHeader } from '../shared/ui/page-header';
import { ValueTrapBadge } from '../shared/ui/value-trap-badge';

/** Ein Titel: Stammdaten, Kennzahlen des neuesten Abrufs, Score-Verlauf (/instruments/:symbol). */
@Component({
  selector: 'app-instrument-page',
  imports: [
    BackLink,
    DayPipe,
    MatTableModule,
    MrdPipe,
    NumPipe,
    OrDashPipe,
    PageHeader,
    PctPipe,
    RouterLink,
    ValueTrapBadge,
  ],
  templateUrl: './instrument-page.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InstrumentPage {
  readonly symbol = input.required<string>();

  private readonly resource = getInstrumentResource(() => ({ path: { symbol: this.symbol() } }));

  protected readonly instrument = computed(() => loaded(this.resource));
  protected readonly error = computed(() => loadError(this.resource, 'Titel nicht gefunden.'));
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
