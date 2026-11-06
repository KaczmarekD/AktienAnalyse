import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

/**
 * Kennzahlkarte: Label, großer Wert (Inhalt), Nebenzeile (`statSub`). Mit `link` führt sie
 * dorthin, mit `pressed` ist sie ein Schalter (aria-pressed), etwa für einen Filter. Der Tooltip
 * sagt, was die Karte zeigt oder bewirkt.
 */
@Component({
  selector: 'app-stat-card',
  imports: [MatTooltipModule, NgTemplateOutlet, RouterLink],
  template: `
    <ng-template #body>
      <span class="label">{{ label() }}</span>
      <span class="value"><ng-content /></span>
      <span class="sub"><ng-content select="[statSub]" /></span>
    </ng-template>
    @if (link(); as link) {
      <a class="stat" data-stat [routerLink]="link" [matTooltip]="tip()">
        <ng-container [ngTemplateOutlet]="body" />
      </a>
    } @else if (pressed() !== undefined) {
      <button
        class="stat"
        data-stat
        type="button"
        [attr.aria-pressed]="pressed()"
        [matTooltip]="tip()"
        (click)="toggled.emit()"
      >
        <ng-container [ngTemplateOutlet]="body" />
      </button>
    } @else {
      <div class="stat" data-stat tabindex="0" [matTooltip]="tip()">
        <ng-container [ngTemplateOutlet]="body" />
      </div>
    }
  `,
  styles: `
    :host {
      display: block;
    }

    .stat {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: var(--va-space-xs);
      width: 100%;
      height: 100%;
      padding: var(--va-space-md) var(--va-space-lg);
      border: var(--va-divider);
      border-radius: var(--va-radius-card);
      background-color: var(--mat-sys-surface-container-lowest);
      color: inherit;
      font: inherit;
      text-align: left;
      text-decoration: none;
    }

    a.stat,
    button.stat {
      cursor: pointer;

      &:hover {
        background-color: var(--mat-sys-surface-container-low);
      }
    }

    button.stat[aria-pressed='true'] {
      box-shadow: inset 0 0 0 var(--va-focus-width) var(--mat-sys-primary);
    }

    .label {
      color: var(--mat-sys-on-surface-variant);
      font: var(--mat-sys-label-large);
    }

    .value {
      display: flex;
      align-items: baseline;
      gap: var(--va-space-sm);
      font-family: var(--va-font-figures);
      font-size: var(--mat-sys-headline-medium-size);
      line-height: var(--mat-sys-headline-medium-line-height);
      font-variant-numeric: tabular-nums;
    }

    .sub {
      display: flex;
      align-items: center;
      gap: var(--va-space-xs);
      color: var(--mat-sys-on-surface-variant);
      font: var(--mat-sys-body-small);
    }

    .sub:empty {
      display: none;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StatCard {
  readonly label = input.required<string>();
  readonly tip = input.required<string>();
  readonly link = input<string | undefined>(undefined);
  /** Gesetzt: die Karte ist ein Schalter */
  readonly pressed = input<boolean | undefined>(undefined);
  readonly toggled = output<void>();
}
