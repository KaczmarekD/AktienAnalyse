import { formatDate } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  LOCALE_ID,
  signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { depotHistoryResource, getDepotResource } from '../api/@angular/common.gen';
import { archiveDepot, getHoldings, restoreDepot } from '../api/sdk.gen';
import type { Holdings, PositionValue } from '../api/types.gen';
import { optionalNumber } from '../shared/api-error';
import { DAY, DayPipe, DayTimePipe, DecPipe, EurPipe, PctPipe } from '../shared/format';
import { ENTRIES, termTip } from '../shared/glossary/glossary';
import { loaded, loadError } from '../shared/resource';
import { BackLink } from '../shared/ui/back-link';
import { ConfirmData, ConfirmDialog } from '../shared/ui/confirm-dialog';
import { AppIcon } from '../shared/ui/icon';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { PageHeader } from '../shared/ui/page-header';
import { Score } from '../shared/ui/score';
import { AppSection } from '../shared/ui/section';
import { StatCard } from '../shared/ui/stat-card';
import { AppState } from '../shared/ui/state';
import { Term } from '../shared/ui/term';
import { ValueTrapBadge } from '../shared/ui/value-trap-badge';
import {
  DEPOT_CONTROLS,
  KIND,
  MISSING_VALUE,
  NO_SCORE,
  SCORE_REASON,
  SCORE_REFERENCE,
  SOURCE,
  UNIT,
} from './controls';
import { DepotDialog } from './depot-dialog';
import { HoldingsEditor } from './holdings-editor';
import { ImportPanel } from './import-panel';

/**
 * Ein Depot (/depots/:depotId, D3.6, DEP-02 bis 07, 09, 13): Kennzahlen Wert, Kasse, Einstand
 * und Differenz, die Positionen mit Kurs, Datum und Quelle, „Bearbeiten“ im selben Blatt, die
 * Datei im eigenen Format und der Verlauf der Depotstände. Archivierte Depots sind
 * schreibgeschützt, bis sie wiederhergestellt sind. Seit D4.2 trägt jede Aktie ihre Scores aus
 * dem jüngsten Bewertungslauf: Titel aus DAX/MDAX führen ins Titel-Detail, andere sind ins
 * Referenzuniversum eingeordnet.
 */
@Component({
  selector: 'app-depot-page',
  imports: [
    AppIcon,
    AppSection,
    AppState,
    BackLink,
    DayPipe,
    DayTimePipe,
    DecPipe,
    EurPipe,
    HoldingsEditor,
    ImportPanel,
    MatButtonModule,
    MatTooltipModule,
    NoticeBox,
    PageHeader,
    PctPipe,
    RouterLink,
    Score,
    StatCard,
    Term,
    ValueTrapBadge,
  ],
  templateUrl: './depot-page.html',
  styleUrl: './depot-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DepotPage {
  readonly depotId = input<number | undefined, unknown>(undefined, {
    transform: optionalNumber,
  });

  private readonly dialog = inject(MatDialog);
  private readonly locale = inject(LOCALE_ID);
  protected readonly controls = DEPOT_CONTROLS;
  protected readonly kinds = KIND;
  protected readonly units = UNIT;
  protected readonly sources = SOURCE;
  protected readonly missing = MISSING_VALUE;
  protected readonly references = SCORE_REFERENCE;
  protected readonly noScore = NO_SCORE;
  protected readonly tips = {
    value: termTip(ENTRIES.depot_value),
    cash: termTip(ENTRIES.cash),
    cost: termTip(ENTRIES.cost_basis),
    difference: termTip(ENTRIES.difference),
    pending: termTip(ENTRIES.pending),
    version: termTip(ENTRIES.holdings_version),
    depot: termTip(ENTRIES.depot),
    watchlist: termTip(ENTRIES.watchlist),
  };

  private readonly depotResource = getDepotResource(() => {
    const id = this.depotId();
    return id === undefined ? undefined : { path: { depot_id: id } };
  });
  private readonly historyResource = depotHistoryResource(() => {
    const id = this.depotId();
    return id === undefined ? undefined : { path: { depot_id: id } };
  });

  protected readonly depot = computed(() => loaded(this.depotResource));
  protected readonly error = computed(() => loadError(this.depotResource, 'Depot nicht gefunden.'));
  protected readonly history = computed(() => loaded(this.historyResource));
  protected readonly valuation = computed(() => this.depot()?.valuation ?? null);
  protected readonly positions = computed(() => this.valuation()?.positions ?? []);
  protected readonly archived = computed(() => this.depot()?.status === 'archived');
  /** Namen aus der Bewertung, für den Editor */
  protected readonly names = computed(() =>
    Object.fromEntries(
      this.positions()
        .filter((position) => position.name)
        .map((position) => [position.isin, position.name as string]),
    ),
  );

  /** Im Editor: der Depotstand, auf dem die Änderung beruht */
  protected readonly editing = signal<Holdings | undefined>(undefined);
  protected readonly busy = signal(false);
  protected readonly notice = signal<Notice | undefined>(undefined);

  protected kindTip(): string {
    return this.depot()?.kind === 'watchlist' ? this.tips.watchlist : this.tips.depot;
  }

  protected valueSub(): string {
    const valuation = this.valuation();
    if (!valuation) {
      return 'noch ohne Kurse';
    }
    if (!valuation.complete) {
      const what = valuation.unvalued === 1 ? '1 Position' : `${valuation.unvalued} Positionen`;
      return `unvollständig: ${what} ohne Wert`;
    }
    return 'alle Positionen bewertet';
  }

  protected priceTip(position: PositionValue): string {
    if (position.price === null) {
      return MISSING_VALUE.price.tip;
    }
    const unit = position.percent_of_par
      ? 'in Prozent vom Nennwert'
      : `in ${position.price_currency ?? 'der Währung des Handelsplatzes'}`;
    const source = position.price_source ? `, Quelle ${position.price_source}` : '';
    return `Schlusskurs ${unit}${source}.`;
  }

  protected missingOf(position: PositionValue): { label: string; tip: string } | undefined {
    return position.missing ? MISSING_VALUE[position.missing] : undefined;
  }

  /** D4.2: warum es keinen Composite gibt, nur bei einer Aktie mit Scores. */
  protected reasonOf(position: PositionValue): { label: string; tip: string } | undefined {
    const reason = position.score?.reason;
    return reason ? SCORE_REASON[reason] : undefined;
  }

  /** D4.2: Bewertungslauf und Stand der Scores, für den Tooltip des Composite. */
  protected scoreTip(position: PositionValue): string {
    const score = position.score;
    if (!score) {
      return NO_SCORE;
    }
    const rank = score.rank ? `Rang ${score.rank} im Ranking, ` : '';
    const day = formatDate(score.as_of, DAY, this.locale);
    return `${rank}Bewertungslauf ${score.scoring_run_id} mit Daten vom ${day}.`;
  }

  protected reload(): void {
    this.depotResource.reload();
    this.historyResource.reload();
  }

  protected async edit(): Promise<void> {
    const id = this.depotId();
    if (id === undefined || this.busy()) {
      return;
    }
    this.busy.set(true);
    this.notice.set(undefined);
    const result = await getHoldings({ path: { depot_id: id } });
    this.busy.set(false);
    if (result.data) {
      this.editing.set(result.data);
    } else {
      this.notice.set({ text: 'Der Depotstand ließ sich nicht laden.', error: true });
    }
  }

  /** Nach einem Konflikt: den neuesten Stand laden und im Editor bleiben */
  protected async reloadEditor(): Promise<void> {
    this.reload();
    await this.edit();
  }

  protected onSaved(holdings: Holdings): void {
    this.editing.set(undefined);
    this.notice.set({ text: `Gespeichert: Depotstand ${holdings.version}.` });
    this.reload();
  }

  protected onImported(): void {
    this.editing.set(undefined);
    this.reload();
  }

  protected rename(): void {
    const depot = this.depot();
    if (!depot) {
      return;
    }
    this.dialog
      .open<DepotDialog, object, number>(DepotDialog, { data: { depot } })
      .afterClosed()
      .subscribe((id) => {
        if (id !== undefined) {
          this.notice.set({ text: 'Name und Beschreibung gespeichert.' });
          this.reload();
        }
      });
  }

  protected archive(): void {
    const depot = this.depot();
    if (!depot) {
      return;
    }
    const data: ConfirmData = {
      title: 'Depot archivieren?',
      text: `„${depot.name}“ wird schreibgeschützt und verschwindet aus der Liste. Gelöscht wird nichts, du kannst es jederzeit wiederherstellen.`,
      confirm: 'Archivieren',
      confirmTip: DEPOT_CONTROLS.archiveConfirm,
      cancelTip: DEPOT_CONTROLS.archiveCancel,
    };
    this.dialog
      .open<ConfirmDialog, ConfirmData, boolean>(ConfirmDialog, { data })
      .afterClosed()
      .subscribe((yes) => {
        if (yes) {
          void this.setArchived(true);
        }
      });
  }

  protected async restore(): Promise<void> {
    await this.setArchived(false);
  }

  private async setArchived(archived: boolean): Promise<void> {
    const id = this.depotId();
    if (id === undefined) {
      return;
    }
    this.busy.set(true);
    this.notice.set(undefined);
    const result = archived
      ? await archiveDepot({ path: { depot_id: id } })
      : await restoreDepot({ path: { depot_id: id } });
    this.busy.set(false);
    if (result.data) {
      this.editing.set(undefined);
      this.notice.set({ text: archived ? 'Depot archiviert.' : 'Depot wiederhergestellt.' });
      this.reload();
    } else {
      this.notice.set({
        text: archived ? 'Archivieren hat nicht geklappt.' : 'Wiederherstellen hat nicht geklappt.',
        error: true,
      });
    }
  }
}
