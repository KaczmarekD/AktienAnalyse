import { ChangeDetectionStrategy, Component } from '@angular/core';

/**
 * Kopf jeder Seite: Der Inhalt wird zur h1 (Text und Badges), Elemente mit dem Attribut
 * pageAction stehen rechts daneben.
 */
@Component({
  selector: 'app-page-header',
  template: `
    <h1><ng-content /></h1>
    <ng-content select="[pageAction]" />
  `,
  styles: `
    :host {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--va-space-md);
      margin-bottom: var(--va-space-sm);
    }

    h1 {
      margin: 0;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PageHeader {}
