import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';

/** Was der Dialog fragt; die Tooltips sagen, was die Buttons tun. */
export interface ConfirmData {
  title: string;
  text: string;
  confirm: string;
  confirmTip: string;
  cancelTip: string;
}

/**
 * Rückfrage vor einer Aktion, die jemanden betrifft, etwa ein Konto deaktivieren (D1.4). Schließt
 * mit true für „ja“, sonst mit false oder ohne Wert.
 */
@Component({
  selector: 'app-confirm-dialog',
  imports: [MatButtonModule, MatDialogModule, MatTooltipModule],
  template: `
    <h2 mat-dialog-title>{{ data.title }}</h2>
    <mat-dialog-content>
      <p>{{ data.text }}</p>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button
        matButton
        type="button"
        data-action="cancel"
        [mat-dialog-close]="false"
        [matTooltip]="data.cancelTip"
      >
        Abbrechen
      </button>
      <button
        matButton="filled"
        type="button"
        data-action="confirm"
        [mat-dialog-close]="true"
        [matTooltip]="data.confirmTip"
      >
        {{ data.confirm }}
      </button>
    </mat-dialog-actions>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConfirmDialog {
  protected readonly data = inject<ConfirmData>(MAT_DIALOG_DATA);
}
