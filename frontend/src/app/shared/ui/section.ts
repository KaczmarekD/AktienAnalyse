import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { MatCardModule } from '@angular/material/card';

let nextId = 0;

/**
 * Abschnitt als Blatt (mat-card outlined) mit Überschrift: ein Bereich, den Screenreader über
 * seinen Titel ansagen. Neben dem Titel ist Platz für ein ⓘ ([sectionInfo]), rechts für
 * Aktionen ([sectionActions]). Der übrige Inhalt steht darunter.
 */
@Component({
  selector: 'app-section',
  imports: [MatCardModule],
  template: `
    <mat-card appearance="outlined">
      <section [attr.aria-labelledby]="headingId">
        <div class="head" data-section-head>
          @if (level() === 3) {
            <h3 [id]="headingId">{{ heading() }}</h3>
          } @else {
            <h2 [id]="headingId">{{ heading() }}</h2>
          }
          <ng-content select="[sectionInfo]" />
          <span class="spacer"></span>
          <ng-content select="[sectionActions]" />
        </div>
        <ng-content />
      </section>
    </mat-card>
  `,
  styles: `
    :host {
      display: block;
    }

    section {
      padding: var(--va-space-lg);
    }

    .head {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--va-space-sm);
      margin-bottom: var(--va-space-md);
    }

    h2,
    h3 {
      margin: 0;
      font: var(--mat-sys-title-medium);
    }

    .spacer {
      flex: 1;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppSection {
  readonly heading = input.required<string>();
  /** Ebene der Überschrift: 2 für Abschnitte der Seite, 3 innerhalb eines Abschnitts. */
  readonly level = input<2 | 3>(2);

  protected readonly headingId = `section-heading-${++nextId}`;
}
