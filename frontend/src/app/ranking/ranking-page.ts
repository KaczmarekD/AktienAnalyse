import { DatePipe, PercentPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';

import { getRankingResource, latestRankingResource } from '../api/@angular/common.gen';
import type { RankingRow } from '../api/types.gen';
import { errorMessage, optionalNumber } from '../shared/api-error';
import { MrdPipe, NumPipe, PctPipe } from '../shared/format';
import { LiveStore } from '../shared/realtime/live.store';
import { PageHeader } from '../shared/ui/page-header';

type IndexFilter = 'all' | 'DAX' | 'MDAX';
type SortKey = keyof RankingRow;

/** Ranking eines Bewertungslaufs: der juengste oder der aus der Route (/ranking/:scoringRunId). */
@Component({
  selector: 'app-ranking-page',
  imports: [
    DatePipe,
    MatButtonToggleModule,
    MatFormFieldModule,
    MatInputModule,
    MatSlideToggleModule,
    MatSortModule,
    MatTableModule,
    MrdPipe,
    NumPipe,
    PageHeader,
    PctPipe,
    PercentPipe,
    RouterLink,
  ],
  templateUrl: './ranking-page.html',
  styleUrl: './ranking-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RankingPage {
  readonly scoringRunId = input<number | undefined, unknown>(undefined, {
    transform: optionalNumber,
  });

  // Eine der beiden Resources bleibt untaetig: ohne Optionen schickt sie keine Anfrage
  private readonly live = inject(LiveStore);
  // Das neueste Ranking laedt neu, wenn der WebSocket ein neues meldet (P4.6)
  private readonly latest = latestRankingResource(() => {
    this.live.rankingVersion();
    return this.scoringRunId() === undefined ? {} : undefined;
  });
  private readonly byId = getRankingResource(() => {
    const id = this.scoringRunId();
    return id === undefined ? undefined : { path: { scoring_run_id: id } };
  });
  protected readonly resource = computed(() =>
    this.scoringRunId() === undefined ? this.latest : this.byId,
  );
  protected readonly ranking = computed(() => {
    const resource = this.resource();
    return resource.hasValue() ? resource.value() : undefined;
  });
  protected readonly error = computed(() => {
    const error = this.resource().error();
    return error
      ? errorMessage(error, 'Noch kein Bewertungslauf. Er entsteht mit dem ersten Lauf.')
      : undefined;
  });

  protected readonly index = signal<IndexFilter>('all');
  protected readonly search = signal('');
  protected readonly showFiltered = signal(false);
  protected readonly sort = signal<Sort>({ active: 'rank', direction: 'asc' });

  protected readonly columns = [
    'rank',
    'title',
    'index',
    'sector',
    'composite_score',
    'value_score',
    'quality_score',
    'value_trap_flag',
    'market_cap',
    'ev_ebit',
    'pb_ratio',
    'roic',
  ];

  protected readonly rows = computed(() => {
    const ranking = this.ranking();
    if (!ranking) {
      return [];
    }
    const index = this.index();
    const needle = this.search().trim().toLowerCase();
    const matches = ranking.rows.filter(
      (row) =>
        (index === 'all' || row.index === index) &&
        (!needle ||
          row.symbol.toLowerCase().includes(needle) ||
          (row.name ?? '').toLowerCase().includes(needle)),
    );
    const sort = this.sort();
    const key = (sort.direction ? sort.active : 'rank') as SortKey;
    const direction = sort.direction || 'asc';
    const ranked = matches
      .filter((row) => row.passed_filter)
      .sort((a, b) => compare(a[key], b[key], direction));
    // Titel unter der Groessenschwelle haben keinen Rang und stehen immer am Ende
    const filtered = this.showFiltered() ? matches.filter((row) => !row.passed_filter) : [];
    return [...ranked, ...filtered];
  });

  protected onSearch(event: Event): void {
    this.search.set((event.target as HTMLInputElement).value);
  }
}

/** Fehlende Werte stehen unabhaengig von der Richtung am Ende. */
function compare(a: unknown, b: unknown, direction: 'asc' | 'desc'): number {
  if (a == null || b == null) {
    if (a == null && b == null) {
      return 0;
    }
    return a == null ? 1 : -1;
  }
  const result =
    typeof a === 'string' && typeof b === 'string'
      ? a.localeCompare(b, 'de')
      : Number(a) - Number(b);
  return direction === 'desc' ? -result : result;
}
