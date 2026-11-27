import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';

import { getHintParams, hintCatalog, saveHintParams } from '../api/sdk.gen';
import type { HintParamsV1, HintRule } from '../api/types.gen';
import { zHintParamsV1 } from '../api/zod.gen';
import { FORM_FIELD_DEFAULTS, inputValue } from '../shared/ui/form-field';
import { AppIcon } from '../shared/ui/icon';
import { Notice, NoticeBox } from '../shared/ui/notice';
import {
  detailOf,
  HINT_UNIT,
  THRESHOLD_DIALOG,
  THRESHOLDS,
  Threshold,
  ThresholdField,
} from './controls';
import { parseThreshold, thresholdValues } from './hints';

/** Daten der Dialoge „Schwellen“ und „Zielallokation“: das Depot. */
export interface SettingsDialogData {
  depotId: number;
}

type Rule = HintParamsV1['disabled'] extends (infer R)[] | undefined ? R : never;

/**
 * Dialog „Schwellen“ (D5.4, HIN-04): je Regel des Katalogs ihre Schwellen in der Einheit des
 * Messwerts und ein Schalter, der sie abschaltet. Regeln, die noch nicht gerechnet werden (News,
 * Bank), fehlen; ihre Werte bleiben, wie sie sind. Seit D5.5 schaltet er die Prüfkandidaten
 * (HIN-06) ein, standardmäßig sind sie aus. Gespeichert wird mit `If-Match` auf die geladene
 * Version; hat jemand anderes inzwischen gespeichert (409), bietet der Dialog „Neu laden“. Er
 * schließt sich erst nach dem Speichern, mit `true`.
 */
@Component({
  selector: 'app-hint-params-dialog',
  imports: [
    AppIcon,
    MatButtonModule,
    MatCheckboxModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatTooltipModule,
    NoticeBox,
  ],
  providers: [FORM_FIELD_DEFAULTS],
  template: `
    <h2 mat-dialog-title>Schwellen der Hinweise</h2>
    <mat-dialog-content>
      <p class="hint">{{ texts.intro }}</p>
      @if (loading()) {
        <p class="hint" role="status">Lade die Schwellen …</p>
      } @else if (rules().length) {
        <table class="data-table" data-thresholds>
          <thead>
            <tr>
              <th scope="col"><span tabindex="0" [matTooltip]="texts.rule">Regel</span></th>
              <th scope="col"><span tabindex="0" [matTooltip]="texts.value">Schwelle</span></th>
              <th scope="col"><span tabindex="0" [matTooltip]="texts.enabled">An</span></th>
            </tr>
          </thead>
          <tbody>
            @for (rule of rules(); track rule.rule) {
              <tr [attr.data-rule]="rule.rule">
                <td>
                  <span class="name">{{ rule.title }}</span>
                  <span class="hint">{{ rule.group }}</span>
                </td>
                <td class="values">
                  @for (threshold of thresholdsOf(rule.rule); track threshold.field) {
                    <mat-form-field class="narrow">
                      <mat-label>{{ threshold.label }}</mat-label>
                      <input
                        matInput
                        inputmode="decimal"
                        [attr.data-field]="threshold.field"
                        [value]="values()[threshold.field]"
                        (input)="set(threshold.field, $event)"
                      />
                      @if (units[threshold.unit]) {
                        <span matTextSuffix>{{ units[threshold.unit] }}</span>
                      }
                    </mat-form-field>
                    @if (shownError(threshold.field); as message) {
                      <span class="field-error" [attr.data-error]="threshold.field">{{
                        message
                      }}</span>
                    }
                  } @empty {
                    <span class="hint">ohne Schwelle</span>
                  }
                </td>
                <td>
                  <mat-checkbox
                    [attr.data-toggle]="rule.rule"
                    [checked]="!disabled().has(rule.rule)"
                    [aria-label]="'Regel an: ' + rule.title"
                    [matTooltip]="texts.toggle"
                    (change)="toggle(rule.rule, $event.checked)"
                  />
                </td>
              </tr>
            }
          </tbody>
        </table>
        <mat-checkbox
          class="candidates"
          data-toggle="candidates"
          [checked]="candidates()"
          [matTooltip]="texts.candidates"
          (change)="candidates.set($event.checked)"
          >Prüfkandidaten zum Vergleich zeigen</mat-checkbox
        >
      }
      @if (conflict()) {
        <p class="notice notice--error" role="alert" data-conflict>
          <app-icon name="error" />
          Inzwischen hat jemand neuere Schwellen gespeichert. Lade sie neu und ändere dann noch
          einmal.
          <button
            matButton="outlined"
            type="button"
            data-action="reload"
            [matTooltip]="texts.reload"
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
        data-action="defaults"
        [disabled]="loading() || !rules().length"
        [matTooltip]="texts.defaults"
        (click)="defaults()"
      >
        Standardwerte
      </button>
      <button matButton type="button" mat-dialog-close data-action="cancel" [matTooltip]="cancel">
        Abbrechen
      </button>
      <button
        matButton="filled"
        type="button"
        data-action="save"
        [disabled]="saving() || loading() || !rules().length"
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
    @use '../../styles/breakpoints';

    td {
      vertical-align: top;
    }

    .name {
      display: block;
    }

    .values {
      display: flex;
      flex-wrap: wrap;
      gap: 0 var(--va-space-md);
    }

    /* Maß dieses Dialogs: Platz für die Zahl und die Einheit */
    .narrow {
      width: 11rem;
    }

    .field-error {
      flex-basis: 100%;
    }

    .candidates {
      display: block;
      margin-top: var(--va-space-md);
    }

    // Schmal: Regel, Schwellen und Schalter untereinander statt drei Spalten
    @media (max-width: breakpoints.$narrow) {
      thead {
        display: none;
      }

      tr,
      td {
        display: block;
      }

      td {
        border: 0;
        padding-inline: 0;
      }

      tr {
        border-bottom: var(--va-divider);
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HintParamsDialog {
  private readonly ref = inject<MatDialogRef<HintParamsDialog, boolean>>(MatDialogRef);
  private readonly data = inject<SettingsDialogData>(MAT_DIALOG_DATA);
  protected readonly texts = THRESHOLD_DIALOG;
  protected readonly units = HINT_UNIT;
  protected readonly cancel = 'Schließt den Dialog, ohne etwas zu ändern.';

  protected readonly loading = signal(true);
  protected readonly rules = signal<HintRule[]>([]);
  protected readonly values = signal<Record<ThresholdField, string>>(thresholdValues({}));
  protected readonly disabled = signal<ReadonlySet<string>>(new Set());
  /** D5.5: Prüfkandidaten (HIN-06), standardmäßig aus */
  protected readonly candidates = signal(false);
  protected readonly saving = signal(false);
  protected readonly conflict = signal(false);
  protected readonly notice = signal<Notice | undefined>(undefined);
  /** Fehler erst zeigen, nachdem jemand etwas geändert oder speichern wollte */
  protected readonly touched = signal(false);
  private params: HintParamsV1 = {};
  private version = 0;

  protected readonly errors = computed(() => {
    const values = this.values();
    const errors: Partial<Record<ThresholdField, string>> = {};
    const parsed = new Map<ThresholdField, number>();
    for (const threshold of THRESHOLDS) {
      const result = parseThreshold(threshold, values[threshold.field]);
      if ('error' in result) {
        errors[threshold.field] = result.error;
      } else {
        parsed.set(threshold.field, result.value);
      }
    }
    const warning = parsed.get('k01_warning');
    const critical = parsed.get('k01_critical');
    if (warning !== undefined && critical !== undefined && critical <= warning) {
      errors.k01_critical = 'Muss über der Warnung liegen.';
    }
    return errors;
  });

  constructor() {
    void this.load();
  }

  protected thresholdsOf(rule: string): Threshold[] {
    return THRESHOLDS.filter((threshold) => threshold.rule === rule);
  }

  protected shownError(field: ThresholdField): string | undefined {
    return this.touched() ? this.errors()[field] : undefined;
  }

  protected set(field: ThresholdField, event: Event): void {
    const text = inputValue(event);
    this.values.update((values) => ({ ...values, [field]: text }));
    this.touched.set(true);
  }

  protected toggle(rule: string, on: boolean): void {
    this.disabled.update((current) => {
      const next = new Set(current);
      if (on) {
        next.delete(rule);
      } else {
        next.add(rule);
      }
      return next;
    });
  }

  protected defaults(): void {
    this.values.set(thresholdValues(zHintParamsV1.parse({})));
    this.disabled.set(new Set());
    this.candidates.set(false);
    this.touched.set(true);
  }

  protected async load(): Promise<void> {
    this.loading.set(true);
    this.conflict.set(false);
    this.notice.set(undefined);
    const path = { depot_id: this.data.depotId };
    const [params, catalog] = await Promise.all([getHintParams({ path }), hintCatalog()]);
    this.loading.set(false);
    if (!params.data || !catalog.data) {
      this.notice.set({
        text: 'Die Schwellen ließen sich nicht laden. Ist der Server erreichbar?',
        error: true,
      });
      return;
    }
    this.params = params.data.params;
    this.version = params.data.version;
    this.values.set(thresholdValues(zHintParamsV1.parse(this.params)));
    this.disabled.set(new Set(this.params.disabled ?? []));
    this.candidates.set(this.params.candidates ?? false);
    this.rules.set(catalog.data.filter((rule) => rule.available));
    this.touched.set(false);
  }

  protected async save(): Promise<void> {
    this.touched.set(true);
    if (Object.keys(this.errors()).length) {
      return;
    }
    const body: HintParamsV1 = {
      ...this.params,
      disabled: [...this.disabled()] as Rule[],
      candidates: this.candidates(),
    };
    for (const threshold of THRESHOLDS) {
      const result = parseThreshold(threshold, this.values()[threshold.field]);
      if ('value' in result) {
        body[threshold.field] = result.value;
      }
    }
    this.saving.set(true);
    this.conflict.set(false);
    this.notice.set(undefined);
    const result = await saveHintParams({
      path: { depot_id: this.data.depotId },
      body,
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
