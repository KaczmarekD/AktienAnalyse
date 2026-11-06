import { formatNumber } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  LOCALE_ID,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

/** Ein Punkt des Verlaufs, ältester zuerst; ohne Wert fehlt er in der Linie. */
export interface SparkPoint {
  label: string;
  value: number | null;
  /** Nebenangabe im Tooltip, z. B. „Rang 3“ */
  detail?: string;
}

// Maße des Zeichenbereichs (viewBox), skaliert mit der Breite
const WIDTH = 320;
const HEIGHT = 72;
const PAD = 8;
const LEFT = 34;

/**
 * Verlauf als kleine Linie in Tinte (Inline-SVG, ohne Diagramm-Bibliothek). Die Skala folgt dem
 * Wertebereich, sonst wirkte eine Bewegung von Woche zu Woche flach; zwei Linien nennen oben und
 * unten den Wert. Jeder Punkt hat einen Tooltip, das SVG beschreibt die Veränderung für
 * Screenreader.
 */
@Component({
  selector: 'app-sparkline',
  imports: [MatTooltipModule],
  template: `
    @if (shape(); as shape) {
      <svg [attr.viewBox]="viewBox" role="img" [attr.aria-label]="shape.description">
        @for (axis of shape.axes; track axis.y) {
          <line [attr.x1]="left" [attr.x2]="right" [attr.y1]="axis.y" [attr.y2]="axis.y" />
          <text x="0" [attr.y]="axis.y + 4">{{ axis.label }}</text>
        }
        <polyline [attr.points]="shape.line" />
        @for (dot of shape.dots; track dot.x; let last = $last) {
          <circle
            [class.last]="last"
            [attr.cx]="dot.x"
            [attr.cy]="dot.y"
            r="3.5"
            [matTooltip]="dot.tip"
          />
        }
      </svg>
    } @else {
      <p class="hint">Zu wenige Bewertungen für einen Verlauf.</p>
    }
  `,
  styles: `
    :host {
      display: block;
    }

    svg {
      display: block;
      width: 100%;
      height: auto;
    }

    polyline {
      fill: none;
      stroke: var(--mat-sys-primary);
      stroke-width: 2;
      stroke-linejoin: round;
      stroke-linecap: round;
    }

    line {
      stroke: var(--mat-sys-outline-variant);
      stroke-width: 1;
    }

    circle {
      fill: var(--mat-sys-surface-container-lowest);
      stroke: var(--mat-sys-primary);
      stroke-width: 2;
    }

    circle.last {
      fill: var(--mat-sys-primary);
    }

    text {
      fill: var(--mat-sys-on-surface-variant);
      font: var(--mat-sys-body-small);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Sparkline {
  private readonly locale = inject(LOCALE_ID);

  readonly points = input.required<SparkPoint[]>();
  /** Was verläuft, z. B. „Composite“ */
  readonly label = input.required<string>();

  protected readonly viewBox = `0 0 ${WIDTH} ${HEIGHT}`;
  protected readonly left = LEFT;
  protected readonly right = WIDTH - PAD;

  protected readonly shape = computed(() => {
    const points = this.points().filter(
      (point): point is SparkPoint & { value: number } => point.value !== null,
    );
    if (points.length < 2) {
      return undefined;
    }
    const values = points.map((point) => point.value);
    const low = Math.max(0, Math.min(...values) - 0.03);
    const high = Math.min(1, Math.max(...values) + 0.03);
    const x = (i: number) => LEFT + (i * (WIDTH - LEFT - PAD)) / (points.length - 1);
    const y = (value: number) =>
      HEIGHT - PAD - ((value - low) / (high - low || 1)) * (HEIGHT - 2 * PAD);
    const label = this.label();
    const dots = points.map((point, i) => ({
      x: round(x(i)),
      y: round(y(point.value)),
      tip: `${point.label}: ${label} ${this.number(point.value)}${point.detail ? `, ${point.detail}` : ''}`,
    }));
    return {
      line: dots.map((dot) => `${dot.x},${dot.y}`).join(' '),
      dots,
      axes: [high, low].map((value) => ({ y: round(y(value)), label: this.number(value) })),
      description: `Verlauf des ${label} von ${this.number(values[0])} auf ${this.number(values.at(-1) ?? values[0])}`,
    };
  });

  private number(value: number): string {
    return formatNumber(value, this.locale, '1.2-2');
  }
}

function round(value: number): number {
  return Math.round(value * 10) / 10;
}
