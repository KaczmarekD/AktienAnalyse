import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';

import { getTargetAllocation, saveTargetAllocation } from '../api/sdk.gen';
import { PctPipe } from '../shared/format';
import { FORM_FIELD_DEFAULTS, inputValue } from '../shared/ui/form-field';
import { AppIcon } from '../shared/ui/icon';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { detailOf, parseAmount, SLICE, TARGET_CLASSES, TARGET_DIALOG, toInput } from './controls';
import type { SettingsDialogData } from './hint-params-dialog';

type TargetClass = (typeof TARGET_CLASSES)[number];

/** Toleranz der Summe in Prozentpunkten, wie ``TARGET_TOLERANCE`` im Contract (0,1 Punkte). */
const TOLERANCE = 0.1;

function emptyValues(): Record<TargetClass, string> {
  return Object.fromEntries(TARGET_CLASSES.map((kind) => [kind, ''])) as Record<
    TargetClass,
    string
  >;
}

/**
 * Dialog „Zielallokation“ (D5.4, DEP-10): Ziel-Anteil je Anlageklasse in Prozent, zusammen 100 %,
 * oder alles leer für „ohne Ziel“. Weicht das Depot um mehr als die Schwelle ab, entsteht HIN-A01.
 * Gespeichert wird mit `If-Match` auf die geladene Version, wie bei den Schwellen.
 */
@Component({
  selector: 'app-target-dialog',
  imports: [
    AppIcon,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatTooltipModule,
    NoticeBox,
    PctPipe,
  ],
  providers: [FORM_FIELD_DEFAULTS],
  template: `
    <h2 mat-dialog-title>Zielallokation</h2>
    <mat-dialog-content>
      <p class="hint">{{ texts.intro }}</p>
      @if (loading()) {
        <p class="hint" role="status">Lade die Zielallokation …</p>
      } @else if (loadedOnce()) {
        <div class="fields" data-target>
          @for (kind of classes; track kind) {
            <div>
              <mat-form-field class="narrow">
                <mat-label>{{ labels[kind] }}</mat-label>
                <input
                  matInput
                  inputmode="decimal"
                  [attr.data-field]="kind"
                  [value]="values()[kind]"
                  [matTooltip]="texts.share"
                  (input)="set(kind, $event)"
                />
                <span matTextSuffix>%</span>
              </mat-form-field>
              @if (touched() && errors()[kind]; as message) {
                <span class="field-error" [attr.data-error]="kind">{{ message }}</span>
              }
            </div>
          }
        </div>
        <p data-sum>
          <span class="label" tabindex="0" [matTooltip]="texts.sum">zusammen</span>
          {{ sum() / 100 | pct: '1.0-1' }}
          @if (touched() && sumError(); as message) {
            <span class="field-error" data-error="sum">{{ message }}</span>
          }
        </p>
      }
      @if (conflict()) {
        <p class="notice notice--error" role="alert" data-conflict>
          <app-icon name="error" />
          Inzwischen hat jemand eine neuere Zielallokation gespeichert. Lade sie neu und ändere dann
          noch einmal.
          <button
            matButton="outlined"
            type="button"
            data-action="reload"
            [matTooltip]="reloadTip"
            (click)="load()"
          >
            Neu laden
          </button>
        </p>
      }
      <app-notice [notice]="notice()" />
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button
        matButton
        type="button"
        data-action="clear"
        [disabled]="loading() || !loadedOnce()"
        [matTooltip]="texts.clear"
        (click)="clear()"
      >
        Ohne Ziel
      </button>
      <button matButton type="button" mat-dialog-close data-action="cancel" [matTooltip]="cancel">
        Abbrechen
      </button>
      <button
        matButton="filled"
        type="button"
        data-action="save"
        [disabled]="saving() || loading() || !loadedOnce()"
        [matTooltip]="texts.save"
        (click)="save()"
      >
        @if (saving()) {
          Speichert …
        } @else {
          Speichern
        }
      </button>
    </mat-dialog-actions>
  `,
  styles: `
    .fields {
      display: flex;
      flex-wrap: wrap;
      gap: 0 var(--va-space-md);
    }

    /* Maß dieses Dialogs: Platz für die Zahl und das Prozentzeichen */
    .narrow {
      width: 9rem;
    }

    .field-error {
      display: block;
    }

    .label {
      color: var(--mat-sys-on-surface-variant);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TargetDialog {
  private readonly ref = inject<MatDialogRef<TargetDialog, boolean>>(MatDialogRef);
  private readonly data = inject<SettingsDialogData>(MAT_DIALOG_DATA);
  protected readonly texts = TARGET_DIALOG;
  protected readonly classes = TARGET_CLASSES;
  protected readonly labels = SLICE;
  protected readonly cancel = 'Schließt den Dialog, ohne etwas zu ändern.';
  protected readonly reloadTip = 'Lädt die neueste Version. Deine Änderungen gehen dabei verloren.';

  protected readonly loading = signal(true);
  protected readonly loadedOnce = signal(false);
  protected readonly values = signal<Record<TargetClass, string>>(emptyValues());
  protected readonly saving = signal(false);
  protected readonly conflict = signal(false);
  protected readonly notice = signal<Notice | undefined>(undefined);
  protected readonly touched = signal(false);
  private version = 0;

  /** Je Klasse der Anteil in Prozent; leer null, keine Zahl undefined */
  private readonly parsed = computed(
    () =>
      Object.fromEntries(
        TARGET_CLASSES.map((kind) => {
          const text = parseAmount(this.values()[kind]);
          return [kind, text === null || text === undefined ? text : Number(text)];
        }),
      ) as Record<TargetClass, number | null | undefined>,
  );

  protected readonly errors = computed(() => {
    const errors: Partial<Record<TargetClass, string>> = {};
    for (const kind of TARGET_CLASSES) {
      const value = this.parsed()[kind];
      if (value === undefined) {
        errors[kind] = 'Keine Zahl.';
      } else if (value !== null && value > 100) {
        errors[kind] = 'Höchstens 100 %.';
      }
    }
    return errors;
  });

  protected readonly sum = computed(() =>
    TARGET_CLASSES.reduce((total, kind) => total + (this.parsed()[kind] ?? 0), 0),
  );

  /** Ohne Eingabe heißt ohne Ziel; sonst muss die Summe 100 % ergeben. */
  protected readonly sumError = computed(() => {
    const empty = TARGET_CLASSES.every((kind) => this.parsed()[kind] === null);
    return empty || Math.abs(this.sum() - 100) <= TOLERANCE
      ? undefined
      : 'Die Anteile müssen zusammen 100 % ergeben.';
  });

  constructor() {
    void this.load();
  }

  protected set(kind: TargetClass, event: Event): void {
    const text = inputValue(event);
    this.values.update((values) => ({ ...values, [kind]: text }));
    this.touched.set(true);
  }

  protected clear(): void {
    this.values.set(emptyValues());
    this.touched.set(true);
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.conflict.set(false);
    this.notice.set(undefined);
    const result = await getTargetAllocation({ path: { depot_id: this.data.depotId } });
    this.loading.set(false);
    if (!result.data) {
      this.notice.set({
        text: 'Die Zielallokation ließ sich nicht laden. Ist der Server erreichbar?',
        error: true,
      });
      return;
    }
    this.version = result.data.version;
    const shares = result.data.shares;
    this.values.set(
      Object.fromEntries(
        TARGET_CLASSES.map((kind) => [
          kind,
          kind in shares ? toInput(Math.round(shares[kind] * 100000) / 1000) : '',
        ]),
      ) as Record<TargetClass, string>,
    );
    this.loadedOnce.set(true);
    this.touched.set(false);
  }

  protected async save(): Promise<void> {
    this.touched.set(true);
    if (Object.keys(this.errors()).length || this.sumError()) {
      return;
    }
    const shares: Record<string, number> = {};
    for (const kind of TARGET_CLASSES) {
      const value = this.parsed()[kind];
      if (value !== null && value !== undefined) {
        shares[kind] = Math.round(value * 1000) / 100000;
      }
    }
    this.saving.set(true);
    this.conflict.set(false);
    this.notice.set(undefined);
    const result = await saveTargetAllocation({
      path: { depot_id: this.data.depotId },
      body: { shares },
      headers: { 'if-match': `"${this.version}"` },
    });
    this.saving.set(false);
    if (result.data) {
      this.ref.close(true);
      return;
    }
    const status = result.response?.status;
    if (status === 409) {
      if (detailOf(result.error)?.includes('archiviert')) {
        this.notice.set({ text: 'Das Depot ist archiviert. Erst wiederherstellen.', error: true });
      } else {
        this.conflict.set(true);
      }
    } else if (status === 422) {
      this.notice.set({ text: detailOf(result.error) ?? 'Die Eingabe passt nicht.', error: true });
    } else {
      this.notice.set({
        text: 'Speichern hat nicht geklappt. Ist der Server erreichbar?',
        error: true,
      });
    }
  }
}
