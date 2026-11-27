import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  InjectionToken,
  input,
  output,
  signal,
  untracked,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';

import { searchSecuritiesResource } from '../api/@angular/common.gen';
import { saveHoldings } from '../api/sdk.gen';
import type { Holdings, HoldingLineInput, SecurityHit } from '../api/types.gen';
import { loaded } from '../shared/resource';
import { FORM_FIELD_DEFAULTS } from '../shared/ui/form-field';
import { AppIcon } from '../shared/ui/icon';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { AppSection } from '../shared/ui/section';
import { Term } from '../shared/ui/term';
import { DEPOT_CONTROLS, detailOf, parseAmount, toInput, UNIT } from './controls';

/** Wartezeit der Suche nach dem letzten Tastendruck (ms); Tests setzen 0. */
export const SEARCH_DEBOUNCE_MS = new InjectionToken<number>('SEARCH_DEBOUNCE_MS', {
  factory: () => 300,
});

type Unit = 'pieces' | 'nominal';

/** Eine Zeile im Editor; Mengen und Beträge als Text, wie im Feld. */
interface Row {
  isin: string;
  name: string | null;
  quantity: string;
  unit: Unit;
  cost: string;
  note: string;
}

interface RowErrors {
  quantity?: string;
  cost?: string;
}

/**
 * Bearbeiten eines Depotstands (D3.6, DEP-02 bis 04): Menge, Einheit, Einstand und Notiz je
 * Position, die Kasse und neue Wertpapiere über die Suche. Gespeichert wird der ganze Stand mit
 * `If-Match` auf die Version, auf der die Änderung beruht. Hat jemand anderes inzwischen
 * gespeichert (409), sagt der Editor das und bietet „Neu laden“.
 */
@Component({
  selector: 'app-holdings-editor',
  imports: [
    AppIcon,
    AppSection,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatTooltipModule,
    NoticeBox,
    Term,
  ],
  providers: [FORM_FIELD_DEFAULTS],
  template: `
    <app-section heading="Positionen bearbeiten" data-editor>
      <table class="data-table edit-table">
        <thead>
          <tr>
            <th scope="col"><app-term key="security" /></th>
            @if (kind() === 'depot') {
              <th scope="col"><app-term key="quantity" /></th>
              <th scope="col"><span tabindex="0" [matTooltip]="controls.unit">Einheit</span></th>
              <th scope="col"><app-term key="cost_basis" /></th>
            }
            <th scope="col"><span tabindex="0" [matTooltip]="noteTip">Notiz</span></th>
          </tr>
        </thead>
        <tbody>
          @for (row of rows(); track row.isin; let i = $index) {
            <tr [attr.data-row]="row.isin">
              <td>
                <span class="name">{{ row.name ?? row.isin }}</span>
                <span class="hint">{{ row.isin }}</span>
              </td>
              @if (kind() === 'depot') {
                <td>
                  <mat-form-field class="narrow">
                    <mat-label>Menge</mat-label>
                    <input
                      matInput
                      inputmode="decimal"
                      data-field="quantity"
                      [value]="row.quantity"
                      (input)="setField(i, 'quantity', $event)"
                    />
                  </mat-form-field>
                  @if (touched() && errors()[i].quantity; as message) {
                    <span class="field-error" data-error="quantity">{{ message }}</span>
                  }
                </td>
                <td>
                  <mat-form-field class="narrow">
                    <mat-label>Einheit</mat-label>
                    <!-- natives select: mat-select zöge Teile von Overlay und A11y ins Start-Bundle -->
                    <select
                      matNativeControl
                      data-field="unit"
                      [value]="row.unit"
                      [matTooltip]="controls.unit"
                      (change)="setUnit(i, unitOf($event))"
                    >
                      <option value="pieces">{{ units.pieces }}</option>
                      <option value="nominal">{{ units.nominal }}</option>
                    </select>
                  </mat-form-field>
                </td>
                <td>
                  <mat-form-field class="narrow">
                    <mat-label>Einstand in €</mat-label>
                    <input
                      matInput
                      inputmode="decimal"
                      data-field="cost"
                      [value]="row.cost"
                      (input)="setField(i, 'cost', $event)"
                    />
                  </mat-form-field>
                  @if (touched() && errors()[i].cost; as message) {
                    <span class="field-error" data-error="cost">{{ message }}</span>
                  }
                </td>
              }
              <td class="note">
                <mat-form-field>
                  <mat-label>Notiz</mat-label>
                  <input
                    matInput
                    data-field="note"
                    maxlength="500"
                    [value]="row.note"
                    (input)="setField(i, 'note', $event)"
                  />
                </mat-form-field>
                <button
                  matIconButton
                  type="button"
                  data-action="remove"
                  [attr.aria-label]="'Entfernen: ' + (row.name ?? row.isin)"
                  [matTooltip]="controls.remove"
                  (click)="remove(i)"
                >
                  <app-icon name="delete" />
                </button>
              </td>
            </tr>
          } @empty {
            <tr>
              <td class="hint" colspan="6">
                Noch keine Position. Füge unten ein Wertpapier hinzu.
              </td>
            </tr>
          }
        </tbody>
      </table>

      <div class="search">
        <mat-form-field>
          <mat-label>Wertpapier suchen</mat-label>
          <input
            matInput
            type="search"
            data-field="search"
            [value]="query()"
            [matTooltip]="controls.search"
            (input)="query.set(value($event))"
          />
          <app-icon matSuffix name="search" />
        </mat-form-field>
        @if (hits(); as hits) {
          <ul class="divided-list hits" data-hits>
            @for (hit of hits; track hit.isin ?? hit.name) {
              <li [attr.data-hit]="hit.isin">
                <span class="name">{{ hit.name }}</span>
                <span class="hint">{{ hit.isin ?? 'ohne ISIN' }}</span>
                <button
                  matButton
                  type="button"
                  data-action="add"
                  [disabled]="!canAdd(hit)"
                  [matTooltip]="addTip(hit)"
                  (click)="add(hit)"
                >
                  Hinzufügen
                </button>
              </li>
            } @empty {
              <li class="hint">Kein Treffer.</li>
            }
          </ul>
        }
      </div>

      @if (kind() === 'depot') {
        <mat-form-field class="cash">
          <mat-label>Kasse in €</mat-label>
          <input
            matInput
            inputmode="decimal"
            data-field="cash"
            [value]="cash()"
            (input)="setCash($event)"
          />
        </mat-form-field>
        @if (touched() && cashError(); as message) {
          <span class="field-error" data-error="cash">{{ message }}</span>
        }
      }

      @if (conflict()) {
        <p class="notice notice--error" role="alert" data-conflict>
          <app-icon name="error" />
          Inzwischen hat jemand einen neueren Depotstand gespeichert. Lade ihn neu und ändere dann
          noch einmal.
          <button
            matButton="outlined"
            type="button"
            data-action="reload"
            [matTooltip]="controls.reload"
            (click)="reload.emit()"
          >
            Neu laden
          </button>
        </p>
      }
      <app-notice [notice]="notice()" />

      <div class="cluster actions">
        <button
          matButton="filled"
          type="button"
          data-action="save"
          [disabled]="saving()"
          [matTooltip]="valid() ? controls.save : controls.saveBlocked"
          (click)="save()"
        >
          {{ saving() ? 'Speichert …' : 'Als neuen Depotstand speichern' }}
        </button>
        <button
          matButton
          type="button"
          data-action="discard"
          [matTooltip]="controls.discard"
          (click)="cancelled.emit()"
        >
          Verwerfen
        </button>
      </div>
    </app-section>
  `,
  styles: `
    .edit-table td {
      vertical-align: top;
    }

    .note {
      display: flex;
      align-items: flex-start;
      gap: var(--va-space-xs);
    }

    .field-error {
      display: block;
    }

    // Felder für Zahlen sind schmaler als die Notiz, nur hier
    .narrow {
      width: 9rem;
    }

    .name {
      display: block;
    }

    .search {
      margin-top: var(--va-space-lg);
    }

    .hits li {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--va-space-sm);
    }

    .hits .name {
      flex: 1 1 auto;
    }

    .cash {
      margin-top: var(--va-space-md);
    }

    .actions {
      margin-top: var(--va-space-md);
    }

    .notice button {
      margin-left: var(--va-space-sm);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HoldingsEditor {
  readonly depotId = input.required<number>();
  readonly kind = input.required<'depot' | 'watchlist'>();
  readonly holdings = input.required<Holdings>();
  /** Namen der Wertpapiere aus der Bewertung, je ISIN */
  readonly names = input<Readonly<Record<string, string>>>({});

  readonly saved = output<Holdings>();
  readonly cancelled = output<void>();
  readonly reload = output<void>();

  private readonly delay = inject(SEARCH_DEBOUNCE_MS);
  protected readonly controls = DEPOT_CONTROLS;
  protected readonly units = UNIT;
  protected readonly noteTip =
    'Eigene Notiz zur Position, etwa der Kaufgrund. Höchstens 500 Zeichen.';

  protected readonly rows = signal<Row[]>([]);
  protected readonly cash = signal('');
  protected readonly saving = signal(false);
  protected readonly conflict = signal(false);
  protected readonly notice = signal<Notice | undefined>(undefined);
  /** Fehler erst zeigen, nachdem jemand speichern wollte oder ein Feld geändert hat */
  protected readonly touched = signal(false);

  protected readonly query = signal('');
  private readonly debounced = signal('');
  private readonly searchResource = searchSecuritiesResource(() => {
    const q = this.debounced().trim();
    return q.length >= 2 ? { query: { q } } : undefined;
  });
  protected readonly hits = computed<SecurityHit[] | undefined>(() =>
    this.debounced().trim().length >= 2 ? loaded(this.searchResource) : undefined,
  );

  protected readonly errors = computed<RowErrors[]>(() =>
    this.rows().map((row) => {
      if (this.kind() === 'watchlist') {
        return {};
      }
      const errors: RowErrors = {};
      const quantity = parseAmount(row.quantity);
      if (quantity === null) {
        errors.quantity = 'Die Menge fehlt.';
      } else if (quantity === undefined || Number(quantity) <= 0) {
        errors.quantity = 'Eine Zahl größer als 0.';
      }
      if (parseAmount(row.cost) === undefined) {
        errors.cost = 'Eine Zahl ab 0, etwa 1.500,25.';
      }
      return errors;
    }),
  );
  protected readonly cashError = computed(() =>
    parseAmount(this.cash(), true) === undefined
      ? 'Eine Zahl, etwa 250,10; im Dispo mit Minus.'
      : undefined,
  );
  protected readonly valid = computed(
    () =>
      this.errors().every((errors) => !errors.quantity && !errors.cost) &&
      this.cashError() === undefined,
  );

  constructor() {
    // Ausgangspunkt: der Depotstand, den die Seite geladen hat. Nur ein neuer Depotstand setzt
    // die Zeilen zurück; die Namen liest es ohne Abhängigkeit, sonst verwürfe jedes Nachladen des
    // Depots (etwa nach „Umbenennen“) die Eingaben.
    effect(() => {
      const holdings = this.holdings();
      const names = untracked(() => this.names());
      this.rows.set(
        holdings.lines.map((line) => ({
          isin: line.isin,
          name: names[line.isin] ?? null,
          quantity: toInput(line.quantity),
          unit: line.unit ?? 'pieces',
          cost: toInput(line.cost_basis_eur),
          note: line.note ?? '',
        })),
      );
      this.cash.set(toInput(holdings.cash[0]?.amount));
      this.conflict.set(false);
      this.notice.set(undefined);
    });
    // Suche erst nach einer Pause
    effect((onCleanup) => {
      const q = this.query();
      if (this.delay === 0) {
        this.debounced.set(q);
        return;
      }
      const timer = setTimeout(() => this.debounced.set(q), this.delay);
      onCleanup(() => clearTimeout(timer));
    });
  }

  protected value(event: Event): string {
    return (event.target as HTMLInputElement).value;
  }

  protected setField(index: number, field: 'quantity' | 'cost' | 'note', event: Event): void {
    const text = this.value(event);
    this.touched.set(true);
    this.rows.update((rows) =>
      rows.map((row, i) => (i === index ? { ...row, [field]: text } : row)),
    );
  }

  protected unitOf(event: Event): Unit {
    return (event.target as HTMLSelectElement).value === 'nominal' ? 'nominal' : 'pieces';
  }

  protected setUnit(index: number, unit: Unit): void {
    this.rows.update((rows) => rows.map((row, i) => (i === index ? { ...row, unit } : row)));
  }

  protected setCash(event: Event): void {
    this.touched.set(true);
    this.cash.set(this.value(event));
  }

  protected remove(index: number): void {
    this.rows.update((rows) => rows.filter((_, i) => i !== index));
  }

  protected canAdd(hit: SecurityHit): boolean {
    return hit.isin !== null && !this.rows().some((row) => row.isin === hit.isin);
  }

  protected addTip(hit: SecurityHit): string {
    if (hit.isin === null) {
      return this.controls.addDisabled;
    }
    return this.canAdd(hit) ? this.controls.add : this.controls.addPresent;
  }

  protected add(hit: SecurityHit): void {
    const isin = hit.isin;
    if (isin === null || !this.canAdd(hit)) {
      return;
    }
    this.rows.update((rows) => [
      ...rows,
      {
        isin,
        name: hit.name,
        quantity: '',
        unit: hit.asset_class === 'bond' ? 'nominal' : 'pieces',
        cost: '',
        note: '',
      },
    ]);
    this.query.set('');
  }

  protected async save(): Promise<void> {
    this.touched.set(true);
    if (!this.valid() || this.saving()) {
      return;
    }
    const depot = this.kind() === 'depot';
    const lines: HoldingLineInput[] = this.rows().map((row) => ({
      isin: row.isin,
      quantity: depot ? parseAmount(row.quantity) : null,
      unit: row.unit,
      cost_basis_eur: depot ? (parseAmount(row.cost) ?? null) : null,
      note: row.note.trim() || null,
    }));
    const amount = depot ? parseAmount(this.cash(), true) : null;
    this.saving.set(true);
    this.conflict.set(false);
    this.notice.set(undefined);
    const result = await saveHoldings({
      path: { depot_id: this.depotId() },
      body: { lines, cash: amount ? [{ amount }] : [] },
      headers: { 'if-match': `"${this.holdings().version}"` },
    });
    this.saving.set(false);
    if (result.data) {
      this.saved.emit(result.data);
      return;
    }
    const status = result.response?.status;
    if (status === 409) {
      const archived = detailOf(result.error)?.includes('archiviert') ?? false;
      if (archived) {
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
