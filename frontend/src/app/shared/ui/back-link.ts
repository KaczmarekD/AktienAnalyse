import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';

/** Zurück zur übergeordneten Ansicht, z. B. vom Titel zum Ranking. Der Inhalt ist das Ziel. */
@Component({
  selector: 'app-back-link',
  imports: [RouterLink],
  template: `<a [routerLink]="to()">← <ng-content /></a>`,
  styles: `
    :host {
      display: block;
      margin-bottom: var(--va-space-md);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BackLink {
  readonly to = input.required<string>();
}
