import { ChangeDetectionStrategy, Component, input, model } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatMenuModule } from '@angular/material/menu';
import { MatTooltipModule } from '@angular/material/tooltip';

import { CONTROLS } from '../glossary/controls';
import { AppIcon } from './icon';

export interface ColumnChoice {
  key: string;
  label: string;
  tip: string;
}

export interface ColumnGroup {
  label: string;
  columns: ColumnChoice[];
}

/**
 * Spaltenwahl einer Tabelle: ein Menü mit Checkboxen nach Gruppen. `selected` hält die Schlüssel
 * der gewählten Spalten in der Reihenfolge, in der sie gewählt wurden; speichern tut die Ansicht.
 */
@Component({
  selector: 'app-column-picker',
  imports: [AppIcon, MatButtonModule, MatCheckboxModule, MatMenuModule, MatTooltipModule],
  template: `
    <button
      matButton="outlined"
      type="button"
      data-action="columns"
      aria-label="Spalten wählen"
      [matTooltip]="tip"
      [matMenuTriggerFor]="menu"
    >
      <app-icon name="view_column" />
      Spalten
    </button>
    <mat-menu #menu="matMenu" class="column-picker">
      @for (group of groups(); track group.label) {
        <p class="group">{{ group.label }}</p>
        @for (column of group.columns; track column.key) {
          <!-- Fängt nur den Klick ab, damit das Menü beim Anhaken offen bleibt; bedient wird die
               Checkbox selbst, mit Maus und Tastatur -->
          <!-- eslint-disable-next-line @angular-eslint/template/click-events-have-key-events, @angular-eslint/template/interactive-supports-focus -->
          <div class="choice" [attr.data-column]="column.key" (click)="$event.stopPropagation()">
            <mat-checkbox
              [checked]="selected().includes(column.key)"
              [matTooltip]="column.tip"
              matTooltipPosition="left"
              (change)="toggle(column.key, $event.checked)"
              >{{ column.label }}</mat-checkbox
            >
          </div>
        }
      }
    </mat-menu>
  `,
  styles: `
    .group {
      margin: 0;
      padding: var(--va-space-sm) var(--va-space-md) var(--va-space-xs);
      color: var(--mat-sys-on-surface-variant);
      font: var(--mat-sys-label-medium);
    }

    .choice {
      padding: 0 var(--va-space-sm);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ColumnPicker {
  readonly groups = input.required<ColumnGroup[]>();
  readonly selected = model.required<string[]>();

  protected readonly tip = CONTROLS['ranking.columns'];

  protected toggle(key: string, on: boolean): void {
    const rest = this.selected().filter((selected) => selected !== key);
    this.selected.set(on ? [...rest, key] : rest);
  }
}
