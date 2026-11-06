import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatRadioModule } from '@angular/material/radio';
import { MatTooltipModule } from '@angular/material/tooltip';

import { startRun } from '../api/sdk.gen';
import type { RunStart } from '../api/types.gen';
import { CONTROLS } from '../shared/glossary/controls';
import { InfoTip } from '../shared/ui/info-tip';
import { Notice, NoticeBox } from '../shared/ui/notice';

/** Was mit der Mail geschieht (Entscheidung E3): verschicken oder nur speichern. */
type Mail = 'send' | 'dry';

/**
 * Dialog „Lauf starten“ (Track G, G6): Mail verschicken oder Probelauf, dazu „Daten neu abrufen“.
 * Er startet den Lauf selbst und schließt sich mit dessen Nummer. Scheitert der Start (409, 503),
 * bleibt er offen und nennt den Grund.
 */
@Component({
  selector: 'app-start-run-dialog',
  imports: [
    InfoTip,
    MatButtonModule,
    MatCheckboxModule,
    MatDialogModule,
    MatRadioModule,
    MatTooltipModule,
    NoticeBox,
  ],
  template: `
    <h2 mat-dialog-title>Lauf starten</h2>
    <mat-dialog-content>
      <div class="field">
        <span id="start-mail" class="label">Mail</span>
        <mat-radio-group
          aria-labelledby="start-mail"
          [value]="mail()"
          (change)="mail.set($event.value)"
        >
          <mat-radio-button value="send" data-option="send" [matTooltip]="controls['start.send']"
            >verschicken</mat-radio-button
          >
          <mat-radio-button value="dry" data-option="dry" [matTooltip]="controls['start.dry']"
            >Probelauf: Mail nur erstellen und speichern</mat-radio-button
          >
        </mat-radio-group>
      </div>
      <div class="force">
        <mat-checkbox
          data-option="force"
          [checked]="force()"
          [matTooltip]="controls['start.force']"
          (change)="force.set($event.checked)"
          >Daten neu abrufen</mat-checkbox
        >
        <app-info-tip label="Was heißt Daten neu abrufen?" [text]="controls['start.force']" />
      </div>
      <app-notice [notice]="notice()" />
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button
        matButton
        type="button"
        mat-dialog-close
        data-action="cancel"
        [matTooltip]="controls['start.cancel']"
      >
        Abbrechen
      </button>
      <button
        matButton="filled"
        type="button"
        data-action="start"
        [disabled]="starting()"
        [matTooltip]="controls['start.confirm']"
        (click)="start()"
      >
        {{ starting() ? 'Startet …' : 'Lauf starten' }}
      </button>
    </mat-dialog-actions>
  `,
  styles: `
    .field {
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: var(--va-space-md);
      align-items: start;
    }

    // Die Zeile der Optionen fluchtet mit dem Text der ersten Option
    .label {
      padding-top: var(--va-space-sm);
      color: var(--mat-sys-on-surface-variant);
      font: var(--mat-sys-label-large);
    }

    mat-radio-group {
      display: flex;
      flex-direction: column;
    }

    .force {
      display: flex;
      align-items: center;
      margin-top: var(--va-space-sm);
    }

    app-notice {
      display: block;
      margin-top: var(--va-space-md);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StartRunDialog {
  private readonly ref = inject<MatDialogRef<StartRunDialog, number>>(MatDialogRef);
  protected readonly controls = CONTROLS;

  protected readonly mail = signal<Mail>('send');
  protected readonly force = signal(false);
  protected readonly starting = signal(false);
  protected readonly notice = signal<Notice | undefined>(undefined);

  protected async start(): Promise<void> {
    this.starting.set(true);
    this.notice.set(undefined);
    const dry = this.mail() === 'dry';
    const body: Required<RunStart> = { force_refresh: this.force(), dry_run: dry, notify: !dry };
    const result = await startRun({ body });
    this.starting.set(false);
    if (result.data) {
      this.ref.close(result.data.id);
      return;
    }
    this.notice.set({ text: startFailure(result.response?.status, result.error), error: true });
  }
}

/** Meldung, wenn der Start scheitert: 409 mit dem Grund des Servers, 503 ohne NATS. */
function startFailure(status: number | undefined, error: unknown): string {
  if (status === 409) {
    const detail = (error as { detail?: unknown } | undefined)?.detail;
    return typeof detail === 'string' ? detail : 'Es läuft schon ein Lauf.';
  }
  if (status === 503) {
    return 'Hier lassen sich keine Läufe starten: Der Server läuft ohne NATS.';
  }
  return 'Der Lauf konnte nicht gestartet werden.';
}
