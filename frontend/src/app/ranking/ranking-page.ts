import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSortModule, Sort } from '@angular/material/sort';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { getRankingResource, latestRankingResource } from '../api/@angular/common.gen';
import type { RankingRow } from '../api/types.gen';
import { optionalNumber } from '../shared/api-error';
import {
  DayPipe,
  IndexSourcePipe,
  MrdPipe,
  NumPipe,
  OrDashPipe,
  PctPipe,
  SectorPipe,
  sectorName,
} from '../shared/format';
import { CONTROLS } from '../shared/glossary/controls';
import { ENTRIES, FIELD_FACTOR, TermKey, TipParams } from '../shared/glossary/glossary';
import { GlossaryStore } from '../shared/glossary/glossary.store';
import { LiveStore } from '../shared/realtime/live.store';
import { keptValue, loaded, loadError } from '../shared/resource';
import { ColumnGroup, ColumnPicker } from '../shared/ui/column-picker';
import { FORM_FIELD_DEFAULTS } from '../shared/ui/form-field';
import { AppIcon } from '../shared/ui/icon';
import { PageHeader } from '../shared/ui/page-header';
import { Score } from '../shared/ui/score';
import { StatCard } from '../shared/ui/stat-card';
import { AppState } from '../shared/ui/state';
import { Term } from '../shared/ui/term';
import { ValueTrapBadge } from '../shared/ui/value-trap-badge';

type IndexFilter = 'all' | 'DAX' | 'MDAX';
type Focus = 'traps' | 'no-composite';
type FactorField = keyof typeof FIELD_FACTOR;

/** Gewählte Spalten im Browser, je Nutzer (localStorage, Lesen und Schreiben in try/catch). */
export const COLUMNS_KEY = 'va.ranking.columns';

/** Immer sichtbar */
const FIXED = ['rank', 'title', 'composite_score', 'hint'];
/** Wählbar, in dieser Reihenfolge; die ersten vier sind Standard */
const OPTIONAL = ['sector', 'value_score', 'quality_score', 'market_cap'];
const DEFAULT_COLUMNS = [...OPTIONAL];
const ORDER = [
  'rank',
  'title',
  'sector',
  'composite_score',
  'value_score',
  'quality_score',
  'hint',
  'market_cap',
  ...Object.keys(FIELD_FACTOR),
];

/** Wie Faktorwerte erscheinen: Multiples mit einer Stelle, Renditen und Margen in Prozent. */
const FACTOR_FORMAT: Record<FactorField, 'num1' | 'num2' | 'pct'> = {
  ev_ebit: 'num1',
  pb_ratio: 'num1',
  p_fcf: 'num1',
  shareholder_yield: 'pct',
  roic: 'pct',
  fcf_margin: 'pct',
  operating_margin: 'pct',
  net_debt_ebitda: 'num1',
  earnings_stability: 'num2',
};

/** Multiples und Verschuldung: niedriger ist besser, also beim ersten Klick aufsteigend. */
const ASCENDING: readonly string[] = [
  'rank',
  'sector',
  'ev_ebit',
  'pb_ratio',
  'p_fcf',
  'net_debt_ebitda',
];

function loadColumns(): string[] {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(COLUMNS_KEY) ?? 'null');
    if (Array.isArray(stored) && stored.every((key) => typeof key === 'string')) {
      return stored.filter((key) => ORDER.includes(key));
    }
  } catch {
    // privat, gesperrt oder kaputt: Standard
  }
  return [...DEFAULT_COLUMNS];
}

function saveColumns(columns: string[]): void {
  try {
    localStorage.setItem(COLUMNS_KEY, JSON.stringify(columns));
  } catch {
    // ohne Speicher gilt die Wahl nur bis zum Neuladen
  }
}

/**
 * Ranking eines Bewertungslaufs (Track G, G4): der jüngste oder der aus der Route
 * (/ranking/:scoringRunId). Frage der Ansicht: Welche Titel sind günstig und solide?
 */
@Component({
  selector: 'app-ranking-page',
  imports: [
    AppIcon,
    AppState,
    ColumnPicker,
    DayPipe,
    IndexSourcePipe,
    MatButtonModule,
    MatButtonToggleModule,
    MatFormFieldModule,
    MatInputModule,
    MatSlideToggleModule,
    MatSortModule,
    MatTableModule,
    MatTooltipModule,
    MrdPipe,
    NumPipe,
    OrDashPipe,
    PageHeader,
    PctPipe,
    RouterLink,
    Score,
    SectorPipe,
    StatCard,
    Term,
    ValueTrapBadge,
  ],
  providers: [FORM_FIELD_DEFAULTS],
  templateUrl: './ranking-page.html',
  styleUrl: './ranking-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RankingPage {
  readonly scoringRunId = input<number | undefined, unknown>(undefined, {
    transform: optionalNumber,
  });

  private readonly live = inject(LiveStore);
  protected readonly glossary = inject(GlossaryStore);
  protected readonly controls = CONTROLS;

  // Das jüngste Ranking lädt immer: Es ist die Ansicht ohne ID, und mit ID sagt es, ob die
  // gewählte aktuell ist. Es lädt neu, wenn der WebSocket ein neues meldet (P4.6).
  private readonly latest = latestRankingResource(() => {
    this.live.rankingVersion();
    return {};
  });
  private readonly byId = getRankingResource(() => {
    const id = this.scoringRunId();
    return id === undefined ? undefined : { path: { scoring_run_id: id } };
  });
  private readonly resource = computed(() =>
    this.scoringRunId() === undefined ? this.latest : this.byId,
  );
  // Beim Nachladen nach einem Ereignis bleibt die alte Tabelle stehen
  protected readonly ranking = keptValue(() => this.resource());
  protected readonly error = computed(() =>
    loadError(this.resource(), 'Noch kein Bewertungslauf. Er entsteht mit dem ersten Lauf.'),
  );
  /** Ein älterer Bewertungslauf als der jüngste */
  protected readonly isOld = computed(() => {
    const shown = this.ranking()?.scoring_run_id;
    const newest = loaded(this.latest)?.scoring_run_id;
    return shown !== undefined && newest !== undefined && shown !== newest;
  });

  /** Werte des Profils für die Texte (Schwellen, Gewichte, Größenschwelle) */
  protected readonly params = computed<TipParams>(() => {
    const ranking = this.ranking();
    const params = ranking?.params;
    return {
      value_weight: ranking?.value_weight,
      value_trap_value_threshold: params?.value_trap_value_threshold,
      value_trap_quality_threshold: params?.value_trap_quality_threshold,
      min_market_cap: params?.min_market_cap,
    };
  });

  // Kennzahlkarten, aus allen Zeilen des Laufs
  protected readonly summary = computed(() => {
    const rows = this.ranking()?.rows ?? [];
    return {
      total: rows.length,
      withComposite: rows.filter((row) => row.composite_score != null).length,
      traps: rows.filter((row) => row.value_trap_flag).length,
      noComposite: rows.filter((row) => row.passed_filter && row.composite_score == null).length,
      leader: rows.find((row) => row.rank === 1),
    };
  });

  protected readonly index = signal<IndexFilter>('all');
  protected readonly search = signal('');
  protected readonly showFiltered = signal(false);
  protected readonly focus = signal<Focus | undefined>(undefined);
  protected readonly sort = signal<Sort>({ active: 'rank', direction: 'asc' });
  protected readonly selected = signal<string[]>(loadColumns());

  protected readonly columns = computed(() => {
    const selected = this.selected();
    return ORDER.filter((key) => FIXED.includes(key) || selected.includes(key));
  });
  protected readonly factorColumns = (Object.keys(FIELD_FACTOR) as FactorField[]).map((key) => ({
    key,
    term: FIELD_FACTOR[key] as TermKey,
    format: FACTOR_FORMAT[key],
  }));
  protected readonly columnGroups = computed<ColumnGroup[]>(() => {
    const choice = (key: string, term: TermKey) => ({
      key,
      label: this.glossary.label(term),
      tip: this.glossary.tip(term, this.params()),
    });
    const factors = (role: 'value' | 'quality') =>
      this.factorColumns
        .filter((column) => ENTRIES[column.term].role === role)
        .map((column) => choice(column.key, column.term));
    return [
      {
        label: 'Allgemein',
        columns: [
          choice('sector', 'sector'),
          choice('value_score', 'value_score'),
          choice('quality_score', 'quality_score'),
          choice('market_cap', 'market_cap'),
        ],
      },
      { label: 'Value-Faktoren', columns: factors('value') },
      { label: 'Quality-Faktoren', columns: factors('quality') },
    ];
  });

  protected readonly rows = computed(() => {
    const ranking = this.ranking();
    if (!ranking) {
      return [];
    }
    const index = this.index();
    const needle = this.search().trim().toLowerCase();
    const focus = this.focus();
    const matches = ranking.rows.filter(
      (row) =>
        (index === 'all' || row.index === index) &&
        (!needle ||
          row.symbol.toLowerCase().includes(needle) ||
          (row.name ?? '').toLowerCase().includes(needle)) &&
        (focus !== 'traps' || row.value_trap_flag) &&
        (focus !== 'no-composite' || (row.passed_filter && row.composite_score == null)),
    );
    const sort = this.sort();
    const key = sort.direction ? sort.active : 'rank';
    const direction = sort.direction || 'asc';
    const ranked = matches
      .filter((row) => row.passed_filter)
      .sort((a, b) => compare(sortValue(a, key), sortValue(b, key), direction));
    // Titel unter der Größenschwelle haben keinen Rang und stehen immer am Ende
    const filtered = this.showFiltered() ? matches.filter((row) => !row.passed_filter) : [];
    return [...ranked, ...filtered];
  });

  constructor() {
    effect(() => saveColumns(this.selected()));
  }

  /** Tooltip eines sortierbaren Spaltenkopfs: was die Spalte zeigt, dazu der Hinweis aufs Sortieren */
  protected headTip(term: TermKey): string {
    const tip = this.glossary.tip(term, this.params());
    return tip ? `${tip}\nKlick sortiert.` : 'Klick sortiert.';
  }

  protected start(key: string): 'asc' | 'desc' {
    return ASCENDING.includes(key) ? 'asc' : 'desc';
  }

  protected factorValue(row: RankingRow, key: FactorField): number | null {
    return row[key];
  }

  protected onSearch(event: Event): void {
    this.search.set((event.target as HTMLInputElement).value);
  }

  protected toggleFocus(focus: Focus): void {
    this.focus.update((current) => (current === focus ? undefined : focus));
  }

  protected resetFilter(): void {
    this.index.set('all');
    this.search.set('');
    this.focus.set(undefined);
  }
}

function sortValue(row: RankingRow, key: string): unknown {
  if (key === 'title') {
    return row.name ?? row.symbol;
  }
  if (key === 'sector') {
    return row.sector ? sectorName(row.sector) : null;
  }
  return row[key as keyof RankingRow];
}

/** Fehlende Werte stehen unabhängig von der Richtung am Ende. */
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
