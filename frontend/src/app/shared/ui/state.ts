import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  input,
  signal,
} from '@angular/core';
import { MatProgressBarModule } from '@angular/material/progress-bar';

import { AppIcon, IconName } from './icon';

/** Erst nach dieser Pause erscheint der Ladebalken, damit schnelle Antworten nicht flackern. */
export const LOADING_DELAY_MS = 300;

/**
 * Was eine Ansicht zeigt, solange sie keine Daten zeigen kann (Spec, Zustände):
 * - Fehler sofort, rot gedämpft und mit role="alert", meist aus loadError;
 * - leer mit Icon, einem Satz und dem nächsten Schritt (projizierter Inhalt);
 * - sonst Laden: Balken und Text, erst nach LOADING_DELAY_MS.
 *
 * Die Ansicht zeigt app-state im Zweig ohne Daten, z. B. @if (data(); as d) { … } @else { … }.
 */
@Component({
  selector: 'app-state',
  imports: [AppIcon, MatProgressBarModule],
  template: `
    @if (error(); as error) {
      <p class="notice notice--error" role="alert"><app-icon name="error" />{{ error }}</p>
    } @else if (empty(); as empty) {
      <div class="empty">
        <app-icon [name]="emptyIcon()" size="md" />
        <p>{{ empty }}</p>
        <ng-content />
      </div>
    } @else if (delayed()) {
      <div class="loading" role="status">
        <mat-progress-bar mode="indeterminate" [attr.aria-label]="loading()" />
        <p class="meta">{{ loading() }}</p>
      </div>
    }
  `,
  styles: `
    :host {
      display: block;
    }

    .notice {
      margin: 0;
    }

    .empty {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--va-space-sm);
      padding: var(--va-space-xl);
      color: var(--mat-sys-on-surface-variant);
      text-align: center;
    }

    .empty p,
    .loading p {
      margin: 0;
    }

    .loading {
      display: flex;
      flex-direction: column;
      gap: var(--va-space-sm);
      padding: var(--va-space-md) 0;
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppState {
  readonly error = input<string | undefined>();
  readonly empty = input<string | undefined>();
  /** Was lädt, z. B. „Lade das Ranking …“. */
  readonly loading = input('Lade …');
  readonly emptyIcon = input<IconName>('info');

  protected readonly delayed = signal(false);

  constructor() {
    const timer = setTimeout(() => this.delayed.set(true), LOADING_DELAY_MS);
    inject(DestroyRef).onDestroy(() => clearTimeout(timer));
  }
}
