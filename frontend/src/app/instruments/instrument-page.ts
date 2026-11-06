import { Clipboard } from '@angular/cdk/clipboard';
import { formatDate, formatNumber, NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  LOCALE_ID,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { getInstrumentResource, latestRankingResource } from '../api/@angular/common.gen';
import type { Snapshot } from '../api/types.gen';
import { DayPipe, MrdPipe, NumPipe, OrDashPipe, PctPipe, SectorPipe, DAY } from '../shared/format';
import { CONTROLS } from '../shared/glossary/controls';
import { ENTRIES, FIELD_FACTOR, TermKey, termTip, TipParams } from '../shared/glossary/glossary';
import { loaded, loadError } from '../shared/resource';
import { BackLink } from '../shared/ui/back-link';
import { AppIcon } from '../shared/ui/icon';
import { InfoTip } from '../shared/ui/info-tip';
import { PageHeader } from '../shared/ui/page-header';
import { Score } from '../shared/ui/score';
import { AppSection } from '../shared/ui/section';
import { Sparkline, SparkPoint } from '../shared/ui/sparkline';
import { StatCard } from '../shared/ui/stat-card';
import { AppState } from '../shared/ui/state';
import { Term } from '../shared/ui/term';
import { ValueTrapBadge } from '../shared/ui/value-trap-badge';

type SnapshotField = keyof Omit<
  Snapshot,
  'fetch_run_id' | 'fetched_on' | 'fetch_ok' | 'errors' | 'currency'
>;
type Format = 'num1' | 'num2' | 'pct' | 'mrd' | 'price';

interface Figure {
  field: SnapshotField;
  term: TermKey;
  format: Format;
  /** Faktor des Scorings: zeigt sein Perzentil */
  factor?: string;
}

const figure = (field: SnapshotField, format: Format, term?: TermKey): Figure => {
  const factor = (FIELD_FACTOR as Record<string, string>)[field];
  return { field, format, term: (term ?? factor ?? field) as TermKey, factor };
};

const VALUATION = [
  figure('ev_ebit', 'num1'),
  figure('pb_ratio', 'num1'),
  figure('p_fcf', 'num1'),
  figure('shareholder_yield', 'pct'),
];
const VALUATION_INFO = [figure('pe_ratio', 'num1'), figure('dividend_yield', 'pct')];
const QUALITY = [
  figure('roic', 'pct'),
  figure('fcf_margin', 'pct'),
  figure('operating_margin', 'pct'),
  figure('net_debt_ebitda', 'num1'),
  figure('earnings_stability', 'num2'),
];
const MARKET = [
  figure('price', 'price'),
  figure('market_cap', 'mrd'),
  figure('revenue_growth_5y', 'pct'),
  figure('eps_growth_5y', 'pct'),
];
const VALUE_FACTORS = ['ev_ebit', 'pb', 'p_fcf', 'shareholder_yield'];
const QUALITY_FACTORS = [
  'roic',
  'fcf_margin',
  'operating_margin',
  'net_debt_ebitda',
  'earnings_stability',
];

/**
 * Ein Titel (/instruments/:symbol, Track G, G5): Warum steht er dort, wo er steht? Oben Rang und
 * Scores des jüngsten Bewertungslaufs, darunter die Kennzahlen mit Perzentil je Faktor (G3), dann
 * der Verlauf.
 */
@Component({
  selector: 'app-instrument-page',
  imports: [
    AppIcon,
    AppSection,
    AppState,
    BackLink,
    DayPipe,
    InfoTip,
    MatButtonModule,
    MatTableModule,
    MatTooltipModule,
    MrdPipe,
    NgTemplateOutlet,
    NumPipe,
    OrDashPipe,
    PageHeader,
    PctPipe,
    RouterLink,
    Score,
    SectorPipe,
    Sparkline,
    StatCard,
    Term,
    ValueTrapBadge,
  ],
  templateUrl: './instrument-page.html',
  styleUrl: './instrument-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InstrumentPage {
  readonly symbol = input.required<string>();

  private readonly clipboard = inject(Clipboard);
  private readonly snackBar = inject(MatSnackBar);
  private readonly locale = inject(LOCALE_ID);
  protected readonly controls = CONTROLS;
  protected readonly groups = { VALUATION, VALUATION_INFO, QUALITY, MARKET };

  private readonly resource = getInstrumentResource(() => ({ path: { symbol: this.symbol() } }));
  // Gewichte und Schwellen des jüngsten Bewertungslaufs für Karten und Tooltips
  private readonly ranking = latestRankingResource(() => ({}));

  protected readonly instrument = computed(() => loaded(this.resource));
  protected readonly error = computed(() => loadError(this.resource, 'Titel nicht gefunden.'));
  protected readonly params = computed<TipParams>(() => {
    const ranking = loaded(this.ranking);
    return {
      value_weight: ranking?.value_weight,
      value_trap_value_threshold: ranking?.params?.value_trap_value_threshold,
      value_trap_quality_threshold: ranking?.params?.value_trap_quality_threshold,
      min_market_cap: ranking?.params?.min_market_cap,
    };
  });
  /** Gewichte des jüngsten Bewertungslaufs als Nebenzeile der Karte Composite */
  protected readonly weightText = computed(() => {
    const ranking = loaded(this.ranking);
    if (ranking?.value_weight == null || ranking.quality_weight == null) {
      return undefined;
    }
    const pct = (share: number) => `${formatNumber(share * 100, this.locale, '1.0-0')}\u00a0%`;
    return `${pct(ranking.value_weight)} Value, ${pct(ranking.quality_weight)} Quality`;
  });

  /** Neueste Bewertung zuerst. */
  protected readonly history = computed(() =>
    [...(this.instrument()?.score_history ?? [])].reverse(),
  );
  protected readonly newest = computed(() => this.history()[0]);
  /** Veränderung des Rangs zur Bewertung davor */
  protected readonly move = computed(() => {
    const [newest, before] = this.history();
    if (newest?.rank == null || before?.rank == null) {
      return undefined;
    }
    return { by: before.rank - newest.rank, since: before.created_at };
  });
  protected readonly spark = computed<SparkPoint[]>(() =>
    (this.instrument()?.score_history ?? []).map((point) => ({
      label: formatDate(point.created_at, DAY, this.locale),
      value: point.composite_score,
      detail: point.rank == null ? undefined : `Rang ${point.rank}`,
    })),
  );
  /** Wie viele Faktoren je Gruppe Daten haben, von den aktiven */
  protected readonly coverage = computed(() => {
    const ranks = this.instrument()?.factor_ranks?.ranks;
    if (!ranks) {
      return undefined;
    }
    const count = (keys: string[]) => {
      const active = keys.filter((key) => key in ranks);
      return { found: active.filter((key) => ranks[key] != null).length, active: active.length };
    };
    return { value: count(VALUE_FACTORS), quality: count(QUALITY_FACTORS) };
  });

  protected readonly columns = [
    'created_at',
    'rank',
    'composite_score',
    'value_score',
    'quality_score',
    'value_trap_flag',
  ];

  /** Tooltip einer Kennzahlkarte aus dem Glossar */
  protected cardTip(key: TermKey): string {
    return termTip(ENTRIES[key], this.params());
  }

  protected value(snapshot: Snapshot, field: SnapshotField): number | null {
    return snapshot[field];
  }

  /** Perzentil eines Faktors: Zahl, null (keine Daten) oder undefined (im Profil nicht aktiv). */
  protected rank(factor: string): number | null | undefined {
    const ranks = this.instrument()?.factor_ranks?.ranks;
    return ranks === undefined || !(factor in ranks) ? undefined : ranks[factor];
  }

  protected hasRanks(): boolean {
    return this.instrument()?.factor_ranks != null;
  }

  protected copyIsin(isin: string): void {
    if (this.clipboard.copy(isin)) {
      this.snackBar.open('ISIN kopiert', undefined, { duration: 2500 });
    }
  }
}
