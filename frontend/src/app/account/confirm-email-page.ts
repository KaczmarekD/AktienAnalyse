import {
  ChangeDetectionStrategy,
  Component,
  afterNextRender,
  inject,
  input,
  signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { confirmEmail } from '../api/sdk.gen';
import { AuthStore } from '../shared/auth/auth.store';
import { ACCOUNT_CONTROLS } from '../shared/auth/controls';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { PageHeader } from '../shared/ui/page-header';

/**
 * Mail-Adresse bestätigen (/confirm-email?token=…, D1.6, NUT-10): die Seite hinter dem Link aus der
 * Bestätigungsmail. Sie braucht keine Anmeldung, das Token ist der Nachweis; sie schickt es einmal
 * an den Server. Wer angemeldet ist, sieht danach die neue Adresse im Konto.
 */
@Component({
  selector: 'app-confirm-email-page',
  imports: [MatButtonModule, MatTooltipModule, NoticeBox, PageHeader, RouterLink],
  template: `
    <app-page-header>Mail-Adresse bestätigen</app-page-header>
    @if (!token()) {
      <app-notice [notice]="{ text: 'Der Link ist unvollständig.', error: true }" />
    } @else if (notice(); as notice) {
      <app-notice [notice]="notice" />
    } @else {
      <p class="meta" role="status">Bestätige die Adresse …</p>
    }
    @if (done()) {
      @if (auth.user()) {
        <a matButton="outlined" routerLink="/account" [matTooltip]="controls['confirm.account']"
          >Zum Konto</a
        >
      } @else {
        <a matButton="outlined" routerLink="/login" [matTooltip]="controls['confirm.login']"
          >Anmelden</a
        >
      }
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ConfirmEmailPage {
  protected readonly auth = inject(AuthStore);
  protected readonly controls = ACCOUNT_CONTROLS;
  /** Aus dem Link (?token=, withComponentInputBinding). */
  readonly token = input<string>();
  protected readonly notice = signal<Notice | undefined>(undefined);
  protected readonly done = signal(false);

  constructor() {
    // Einmal nach dem ersten Rendern: Das Token steht dann als Input fest
    afterNextRender(() => void this.confirm());
  }

  private async confirm(): Promise<void> {
    const token = this.token();
    if (!token) {
      return;
    }
    const result = await confirmEmail({ body: { token } });
    // 204 ohne Inhalt: Die Prüfung des Clients meldet dann einen Fehler, der Status zählt
    if (result.response?.status !== 204) {
      this.notice.set({ text: 'Der Link ist ungültig oder abgelaufen.', error: true });
    } else {
      this.notice.set({ text: 'Deine Mail-Adresse ist bestätigt.' });
      await this.auth.refresh();
    }
    this.done.set(true);
  }
}
