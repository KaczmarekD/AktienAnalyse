import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatRadioModule } from '@angular/material/radio';
import { MatTooltipModule } from '@angular/material/tooltip';

import { createDepot, updateDepot } from '../api/sdk.gen';
import type { Depot } from '../api/types.gen';
import { FORM_FIELD_DEFAULTS } from '../shared/ui/form-field';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { DEPOT_CONTROLS } from './controls';

/** Ohne Depot legt der Dialog eins an, mit Depot ändert er Name und Beschreibung. */
export interface DepotDialogData {
  depot?: Depot;
}

const MAX_NAME = 100;
const MAX_TEXT = 500;

/** Meldung einer abgelehnten Anfrage (FastAPI: detail als Text oder Liste). */
function detailOf(error: unknown): string | undefined {
  const detail = (error as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail.map((item) => String((item as { msg?: unknown }).msg ?? '')).join('; ');
  }
  return undefined;
}

/**
 * Dialog „Neues Depot“ und „Depot umbenennen“ (D3.6, DEP-01): Name, Art (nur beim Anlegen) und
 * Beschreibung. Er speichert selbst und schließt sich mit der Nummer des Depots; scheitert es,
 * bleibt er offen und nennt den Grund.
 */
@Component({
  selector: 'app-depot-dialog',
  imports: [
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatRadioModule,
    MatTooltipModule,
    NoticeBox,
  ],
  providers: [FORM_FIELD_DEFAULTS],
  template: `
    <h2 mat-dialog-title>{{ depot ? 'Depot umbenennen' : 'Neues Depot' }}</h2>
    <mat-dialog-content>
      <mat-form-field>
        <mat-label>Name</mat-label>
        <input
          matInput
          data-field="name"
          required
          [attr.maxlength]="maxName"
          [value]="name()"
          (input)="name.set(value($event))"
        />
      </mat-form-field>
      @if (nameError(); as message) {
        <span class="field-error" data-error="name">{{ message }}</span>
      }
      @if (!depot) {
        <div class="field">
          <span id="depot-kind" class="label">Art</span>
          <mat-radio-group
            aria-labelledby="depot-kind"
            [value]="kind()"
            (change)="kind.set($event.value)"
          >
            <mat-radio-button value="depot" data-option="depot" [matTooltip]="controls.kindDepot"
              >Depot mit Mengen und Kasse</mat-radio-button
            >
            <mat-radio-button
              value="watchlist"
              data-option="watchlist"
              [matTooltip]="controls.kindWatchlist"
              >Beobachtungsliste ohne Mengen</mat-radio-button
            >
          </mat-radio-group>
        </div>
      }
      <mat-form-field>
        <mat-label>Beschreibung (optional)</mat-label>
        <textarea
          matInput
          data-field="description"
          rows="2"
          [attr.maxlength]="maxText"
          [value]="description()"
          (input)="description.set(value($event))"
        ></textarea>
      </mat-form-field>
      <app-notice [notice]="notice()" />
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button
        matButton
        type="button"
        mat-dialog-close
        data-action="cancel"
        [matTooltip]="controls.cancel"
      >
        Abbrechen
      </button>
      <button
        matButton="filled"
        type="button"
        data-action="save"
        [disabled]="busy()"
        [matTooltip]="depot ? controls.confirmRename : controls.confirmCreate"
        (click)="save()"
      >
        @if (busy()) {
          Speichert …
        } @else {
          {{ depot ? 'Speichern' : 'Anlegen' }}
        }
      </button>
    </mat-dialog-actions>
  `,
  styles: `
    mat-dialog-content {
      display: flex;
      flex-direction: column;
      gap: var(--va-space-sm);
    }

    .field {
      display: grid;
      grid-template-columns: max-content 1fr;
      gap: var(--va-space-md);
      align-items: start;
      margin-bottom: var(--va-space-md);
    }

    .label {
      padding-top: var(--va-space-sm);
      color: var(--mat-sys-on-surface-variant);
      font: var(--mat-sys-label-large);
    }

    mat-radio-group {
      display: flex;
      flex-direction: column;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DepotDialog {
  private readonly ref = inject<MatDialogRef<DepotDialog, number>>(MatDialogRef);
  protected readonly depot = inject<DepotDialogData>(MAT_DIALOG_DATA, { optional: true })?.depot;
  protected readonly controls = DEPOT_CONTROLS;
  protected readonly maxName = MAX_NAME;
  protected readonly maxText = MAX_TEXT;

  protected readonly name = signal(this.depot?.name ?? '');
  protected readonly kind = signal<'depot' | 'watchlist'>('depot');
  protected readonly description = signal(this.depot?.description ?? '');
  protected readonly busy = signal(false);
  protected readonly notice = signal<Notice | undefined>(undefined);
  protected readonly nameError = signal<string | undefined>(undefined);

  protected value(event: Event): string {
    return (event.target as HTMLInputElement | HTMLTextAreaElement).value;
  }

  protected async save(): Promise<void> {
    const name = this.name().trim();
    if (name === '') {
      this.nameError.set('Der Name fehlt.');
      return;
    }
    this.nameError.set(undefined);
    this.busy.set(true);
    this.notice.set(undefined);
    const description = this.description().trim() || null;
    const result = this.depot
      ? await updateDepot({ path: { depot_id: this.depot.id }, body: { name, description } })
      : await createDepot({ body: { name, kind: this.kind(), description } });
    this.busy.set(false);
    if (result.data) {
      this.ref.close(result.data.id);
      return;
    }
    const status = result.response?.status;
    this.notice.set({
      text:
        status === 422
          ? (detailOf(result.error) ?? 'Die Eingabe passt nicht.')
          : 'Speichern hat nicht geklappt. Ist der Server erreichbar?',
      error: true,
    });
  }
}
