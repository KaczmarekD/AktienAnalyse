import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink } from '@angular/router';

import { listDepotsResource } from '../api/@angular/common.gen';
import type { Depot } from '../api/types.gen';
import { DayPipe, EurPipe } from '../shared/format';
import { ENTRIES, termTip } from '../shared/glossary/glossary';
import { loaded, loadError } from '../shared/resource';
import { AppIcon } from '../shared/ui/icon';
import { PageHeader } from '../shared/ui/page-header';
import { AppSection } from '../shared/ui/section';
import { AppState } from '../shared/ui/state';
import { Term } from '../shared/ui/term';
import { DEPOT_CONTROLS, KIND } from './controls';
import { DepotDialog } from './depot-dialog';

/**
 * Meine Depots (/depots, D3.6, DEP-01, 07, 09): die Startseite nach der Anmeldung. Je Depot eine
 * Karte mit Art, Wert, Stand und Zahl der Positionen; „unvollständig“, wenn Positionen keinen
 * Wert haben, „wird geprüft“ ohne Stammdaten. Archivierte nur auf Wunsch. „Neues Depot“ öffnet
 * den Dialog und danach das neue Depot.
 */
@Component({
  selector: 'app-depots-page',
  imports: [
    AppIcon,
    AppSection,
    AppState,
    DayPipe,
    EurPipe,
    MatButtonModule,
    MatSlideToggleModule,
    MatTooltipModule,
    PageHeader,
    RouterLink,
    Term,
  ],
  templateUrl: './depots-page.html',
  styleUrl: './depots-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DepotsPage {
  private readonly dialog = inject(MatDialog);
  private readonly router = inject(Router);
  protected readonly controls = DEPOT_CONTROLS;
  protected readonly kinds = KIND;
  protected readonly tips = {
    depot: termTip(ENTRIES.depot),
    watchlist: termTip(ENTRIES.watchlist),
    incomplete: termTip(ENTRIES.incomplete),
    pending: termTip(ENTRIES.pending),
  };

  protected readonly archived = signal(false);
  private readonly resource = listDepotsResource(() => ({
    query: { include_archived: this.archived() },
  }));
  protected readonly depots = computed(() => loaded(this.resource));
  protected readonly error = computed(() => loadError(this.resource, 'Keine Depots gefunden.'));

  protected kindTip(depot: Depot): string {
    return depot.kind === 'watchlist' ? this.tips.watchlist : this.tips.depot;
  }

  protected incompleteTip(unvalued: number): string {
    const what = unvalued === 1 ? 'Eine Position hat' : `${unvalued} Positionen haben`;
    return `${what} keinen Wert. ${this.tips.incomplete}`;
  }

  protected create(): void {
    this.dialog
      .open<DepotDialog, object, number>(DepotDialog, { data: {}, autoFocus: 'first-tabbable' })
      .afterClosed()
      .subscribe((id) => {
        if (id !== undefined) {
          void this.router.navigate(['/depots', id]);
        }
      });
  }
}
