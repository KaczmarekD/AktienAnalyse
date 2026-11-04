import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatTableModule } from '@angular/material/table';
import { RouterLink } from '@angular/router';

import { listRunsResource } from '../api/@angular/common.gen';
import { startRun } from '../api/sdk.gen';
import type { RunStart } from '../api/types.gen';
import { errorMessage } from '../shared/api-error';
import { RunStatusPipe } from '../shared/format';
import { LiveStore } from '../shared/realtime/live.store';

/** Optionen eines Runs aus dem UI (P4.7), wie RunOptionsV1 im Event. */
type RunOptions = Required<RunStart>;

const DEFAULT_OPTIONS: RunOptions = { force_refresh: false, dry_run: false, notify: true };

/**
 * Die letzten Laeufe, neueste zuerst; live aktualisiert ueber den WebSocket (P4.6). Mit NATS
 * startet das Formular einen Run (P4.7); er erscheint ueber das Run-Event in der Liste.
 */
@Component({
  selector: 'app-runs-page',
  imports: [
    DatePipe,
    MatButtonModule,
    MatCheckboxModule,
    MatTableModule,
    RouterLink,
    RunStatusPipe,
  ],
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

  protected readonly options = signal<RunOptions>({ ...DEFAULT_OPTIONS });
  protected readonly starting = signal(false);
  protected readonly notice = signal<string | undefined>(undefined);

  protected setOption(name: keyof RunOptions, value: boolean): void {
    this.options.update((options) => ({ ...options, [name]: value }));
  }

  protected async start(): Promise<void> {
    this.starting.set(true);
    this.notice.set(undefined);
    const result = await startRun({ body: this.options() });
    this.starting.set(false);
    if (result.data) {
      this.notice.set(`Lauf #${result.data.id} gestartet.`);
      return;
    }
    const status = result.response?.status;
    if (status === 409) {
      const detail = (result.error as { detail?: unknown } | undefined)?.detail;
      this.notice.set(typeof detail === 'string' ? detail : 'Es läuft schon ein Lauf.');
    } else if (status === 503) {
      this.notice.set('Hier lassen sich keine Läufe starten: Das web-api läuft ohne NATS.');
    } else {
      this.notice.set('Der Lauf konnte nicht gestartet werden.');
    }
  }
}
