import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { getRunResource, listRunsResource } from '../api/@angular/common.gen';
import type { RunSummary } from '../api/types.gen';
import { DayTimePipe, DurationPipe, RunKindPipe } from '../shared/format';
import { CONTROLS } from '../shared/glossary/controls';
import { ENTRIES, termTip } from '../shared/glossary/glossary';
import { LiveStore } from '../shared/realtime/live.store';
import { loaded, loadError } from '../shared/resource';
import { AppIcon } from '../shared/ui/icon';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { PageHeader } from '../shared/ui/page-header';
import { RunStatus } from '../shared/ui/run-status';
import { AppSection } from '../shared/ui/section';
import { AppState } from '../shared/ui/state';
import { Term } from '../shared/ui/term';
import { scoredText } from './run-text';
import { StartRunDialog } from './start-run-dialog';

/**
 * Läufe (/runs, Track G, G6): Lief der letzte Lauf sauber? Oben der letzte abgeschlossene Lauf,
 * darunter alle, neueste zuerst; live über den WebSocket (P4.6). „Lauf starten“ öffnet den
 * Dialog (P4.7, E3); der neue Lauf erscheint über sein Event in der Liste.
 */
@Component({
  selector: 'app-runs-page',
  imports: [
    AppIcon,
    AppSection,
    AppState,
    DayTimePipe,
    DurationPipe,
    MatButtonModule,
    MatTableModule,
    MatTooltipModule,
    NoticeBox,
    PageHeader,
    RouterLink,
    RunKindPipe,
    RunStatus,
    Term,
  ],
  templateUrl: './runs-page.html',
  styleUrl: './runs-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunsPage {
  private readonly live = inject(LiveStore);
  private readonly dialog = inject(MatDialog);
  protected readonly controls = CONTROLS;
  protected readonly tips = {
    dry_run: termTip(ENTRIES.dry_run),
    force_refresh: termTip(ENTRIES.force_refresh),
  };
  protected readonly scoredText = scoredText;

  // Liest die Version der Runs mit: Ein Run-Event oder resync lädt die Liste neu
  private readonly resource = listRunsResource(() => {
    this.live.runsVersion();
    return { query: { limit: 50 } };
  });

  /** Fortschritt laufender Abrufe je Run (marketdata.fetch.progressed). */
  protected readonly progress = this.live.progress;

  protected readonly runs = computed(() => loaded(this.resource));
  protected readonly error = computed(() => loadError(this.resource, 'Keine Läufe gefunden.'));

  /** Der laufende Lauf; solange es ihn gibt, ist der Start gesperrt. */
  protected readonly active = computed(() => this.runs()?.find((run) => run.status === 'running'));
  /** Der neueste abgeschlossene Lauf für die Karte oben. */
  protected readonly last = computed(() => this.runs()?.find((run) => run.status !== 'running'));
  // Die Liste kennt den Bewertungslauf nicht, das Detail des letzten Laufs schon
  private readonly lastDetail = getRunResource(() => {
    const id = this.last()?.id;
    return id === undefined ? undefined : { path: { run_id: id } };
  });
  protected readonly lastRanking = computed(
    () => loaded(this.lastDetail)?.scoring_run_id ?? undefined,
  );

  protected readonly startTip = computed(() => {
    const active = this.active();
    return active ? CONTROLS['runs.startBlocked'](active.id) : CONTROLS['runs.start'];
  });

  protected readonly columns = ['id', 'started_at', 'duration', 'status', 'scored', 'kind'];
  protected readonly notice = signal<Notice | undefined>(undefined);

  protected openStart(): void {
    // disabledInteractive: Der Button bleibt fokussierbar, ein Klick darf dann nichts tun
    if (this.active()) {
      return;
    }
    this.notice.set(undefined);
    this.dialog
      .open<StartRunDialog, unknown, number>(StartRunDialog, { width: '32rem', maxWidth: '100%' })
      .afterClosed()
      .subscribe((id) => {
        if (id !== undefined) {
          this.notice.set({
            text: `Lauf #${id} gestartet. Fortschritt und Ergebnis stehen unten.`,
          });
        }
      });
  }

  protected failedTip(run: RunSummary): string {
    return run.failed_count
      ? `${run.failed_count} Titel ließen sich nicht abrufen.`
      : 'Alle Titel ließen sich abrufen.';
  }
}
