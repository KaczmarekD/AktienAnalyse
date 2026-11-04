import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';

import { listRunsResource } from '../api/@angular/common.gen';
import { errorMessage } from '../shared/api-error';
import { RunStatusPipe } from '../shared/format';
import { LiveStore } from '../shared/realtime/live.store';

/** Die letzten Laeufe des Batches, neueste zuerst; live aktualisiert ueber den WebSocket (P4.6). */
@Component({
  selector: 'app-runs-page',
  imports: [DatePipe, MatTableModule, RouterLink, RunStatusPipe],
  templateUrl: './runs-page.html',
  styleUrl: './runs-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunsPage {
  private readonly live = inject(LiveStore);
  // Liest die Version der Runs mit: Ein Run-Event oder resync laedt die Liste neu
  private readonly resource = listRunsResource(() => {
    this.live.runsVersion();
    return { query: { limit: 50 } };
  });

  /** Fortschritt laufender Abrufe je Run (marketdata.fetch.progressed). */
  protected readonly progress = this.live.progress;

  protected readonly runs = computed(() =>
    this.resource.hasValue() ? this.resource.value() : undefined,
  );
  protected readonly error = computed(() => {
    const error = this.resource.error();
    return error ? errorMessage(error, 'Keine Läufe gefunden.') : undefined;
  });

  protected readonly columns = ['id', 'started_at', 'kind', 'status', 'scored', 'exit_code'];
}
