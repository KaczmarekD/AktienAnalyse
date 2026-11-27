import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

import { depotAnalysisResource } from '../api/@angular/common.gen';
import type { AllocationSlice } from '../api/types.gen';
import { DayPipe, DecPipe, EurPipe, NumPipe, PctPipe, sectorName } from '../shared/format';
import { loaded, loadError } from '../shared/resource';
import { Score } from '../shared/ui/score';
import { AppSection } from '../shared/ui/section';
import { AppState } from '../shared/ui/state';
import { ANALYSIS, BOND_SPECIAL, countryName, SLICE } from './controls';

type Dimension = 'asset_class' | 'currency' | 'sector' | 'country';

interface Row {
  key: string;
  label: string;
  value_eur: string;
  weight: number;
}

const QUINTILE_LABEL: Record<number, string> = {
  5: 'oberstes Fünftel',
  4: 'zweites Fünftel',
  3: 'mittleres Fünftel',
  2: 'viertes Fünftel',
  1: 'unterstes Fünftel',
};

/**
 * Analyse eines Depots (D4.5, ANA-05, 07 bis 09): Qualität, Allokation, Konzentration, Kosten,
 * Anleihen und Datenlage aus `GET /depots/{id}/analysis`. Fehlt eine Größe, steht „keine Daten“
 * da, nie ein Ersatzwert. Lädt neu, sobald sich der Depotstand ändert.
 */
@Component({
  selector: 'app-analysis-panel',
  imports: [
    AppSection,
    AppState,
    DayPipe,
    DecPipe,
    EurPipe,
    MatTooltipModule,
    NumPipe,
    PctPipe,
    Score,
  ],
  templateUrl: './analysis-panel.html',
  styleUrl: './analysis-panel.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AnalysisPanel {
  readonly depotId = input.required<number>();
  /** Depotstand: ändert er sich, rechnet die Analyse neu. */
  readonly version = input(0);
  /** Namen der Wertpapiere im Depot je ISIN (ETFs und Anleihen). */
  readonly names = input<Record<string, string>>({});

  protected readonly tips = ANALYSIS;
  protected readonly special = BOND_SPECIAL;
  protected readonly quintileLabel = QUINTILE_LABEL;

  private readonly resource = depotAnalysisResource(() => {
    this.version();
    return { path: { depot_id: this.depotId() } };
  });

  protected readonly analysis = computed(() => loaded(this.resource));
  protected readonly error = computed(() => loadError(this.resource, 'Depot nicht gefunden.'));
  protected readonly loading = computed(() => this.resource.isLoading());

  protected readonly dimensions: { key: Dimension; heading: string; tip: string }[] = [
    { key: 'asset_class', heading: 'Anlageklasse', tip: ANALYSIS.assetClass },
    { key: 'currency', heading: 'Währung', tip: ANALYSIS.currency },
    { key: 'sector', heading: 'Sektor', tip: ANALYSIS.sector },
    { key: 'country', heading: 'Land', tip: ANALYSIS.country },
  ];

  /** Die Fünftel von oben nach unten. */
  protected readonly quintiles = computed(() =>
    [...(this.analysis()?.quality.quintiles ?? [])].sort((a, b) => b.quintile - a.quintile),
  );

  protected rows(dimension: Dimension): Row[] {
    const slices: AllocationSlice[] = this.analysis()?.allocation[dimension] ?? [];
    return slices.map((slice) => ({ ...slice, label: this.label(dimension, slice.key) }));
  }

  /** Ein Betrag der API (Dezimalzahl im String) ist groesser als 0. */
  protected hasAmount(amount: string): boolean {
    return Number(amount) > 0;
  }

  protected percent(weight: number): number {
    return Math.round(Math.max(0, Math.min(1, weight)) * 100);
  }

  protected name(isin: string, fallback?: string | null): string {
    return this.names()[isin] ?? fallback ?? isin;
  }

  private label(dimension: Dimension, key: string): string {
    if (key in SLICE) {
      return SLICE[key as keyof typeof SLICE];
    }
    if (dimension === 'sector') {
      return sectorName(key);
    }
    if (dimension === 'country') {
      return countryName(key);
    }
    return key;
  }
}
