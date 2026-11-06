import { ChangeDetectionStrategy, Component, computed, inject, input, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';

import { login } from '../api/sdk.gen';
import { AuthStore, safeNext } from '../shared/auth/auth.store';
import { ACCOUNT_CONTROLS } from '../shared/auth/controls';
import { FORM_FIELD_DEFAULTS, inputValue } from '../shared/ui/form-field';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { PageHeader } from '../shared/ui/page-header';

/** Meldung, wenn die Anmeldung scheitert; sie verrät nicht, ob es den Namen gibt. */
function failure(status: number | undefined): string {
  switch (status) {
    case 401:
    case 422: // ungültige Eingabe: dieselbe Antwort, sie verrät nichts über die Konten
      return 'Benutzername oder Passwort falsch.';
    case 429:
      return 'Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.';
    case 503:
      return 'Die Anmeldung ist auf dem Server nicht eingerichtet.';
    default:
      return 'Der Server ist nicht erreichbar.';
  }
}

/**
 * Anmelden (/login, D1.4, NUT-01): Benutzername und Passwort. Danach geht es zur Seite, die man
 * wollte (?next=, nur eigene Pfade), mit Einmal-Passwort zuerst zum Konto. Das Cookie setzt der
 * Server (HttpOnly); das UI sieht davon nichts.
 */
@Component({
  selector: 'app-login-page',
  imports: [
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatTooltipModule,
    NoticeBox,
    PageHeader,
  ],
  providers: [FORM_FIELD_DEFAULTS],
  template: `
    <app-page-header>Anmelden</app-page-header>
    @if (auth.notice(); as reason) {
      <p class="reason" role="status">{{ reason }}</p>
    }
    <form class="login" (submit)="submit($event)">
      <mat-form-field>
        <mat-label>Benutzername</mat-label>
        <input
          matInput
          name="username"
          autocomplete="username"
          autocapitalize="none"
          spellcheck="false"
          maxlength="64"
          [value]="username()"
          (input)="username.set(value($event))"
        />
      </mat-form-field>
      <mat-form-field>
        <mat-label>Passwort</mat-label>
        <input
          matInput
          name="password"
          type="password"
          autocomplete="current-password"
          maxlength="1024"
          [value]="password()"
          (input)="password.set(value($event))"
        />
      </mat-form-field>
      <app-notice [notice]="error()" />
      <button
        matButton="filled"
        type="submit"
        data-action="login"
        disabledInteractive
        [disabled]="!ready() || busy()"
        [matTooltip]="ready() ? controls['login.submit'] : controls['login.blocked']"
      >
        {{ busy() ? 'Meldet an …' : 'Anmelden' }}
      </button>
    </form>
  `,
  styles: `
    .login {
      display: flex;
      flex-direction: column;
      gap: var(--va-space-xs);
      max-width: 24rem;
    }

    .reason {
      max-width: 24rem;
    }

    button {
      align-self: flex-start;
      margin-top: var(--va-space-sm);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LoginPage {
  protected readonly auth = inject(AuthStore);
  private readonly router = inject(Router);
  protected readonly controls = ACCOUNT_CONTROLS;
  protected readonly value = inputValue;

  /** Rücksprung aus ?next= (withComponentInputBinding) */
  readonly next = input<string | undefined>();

  protected readonly username = signal('');
  protected readonly password = signal('');
  protected readonly busy = signal(false);
  protected readonly error = signal<Notice | undefined>(undefined);
  protected readonly ready = computed(
    () => this.username().trim() !== '' && this.password() !== '',
  );

  protected async submit(event: Event): Promise<void> {
    event.preventDefault();
    // disabledInteractive: Der Button bleibt fokussierbar, ein Klick darf dann nichts tun
    if (!this.ready() || this.busy()) {
      return;
    }
    this.busy.set(true);
    this.error.set(undefined);
    const result = await login({
      body: { username: this.username().trim(), password: this.password() },
    });
    this.busy.set(false);
    if (result.response?.status !== 204) {
      this.password.set('');
      this.error.set({ text: failure(result.response?.status), error: true });
      return;
    }
    this.password.set('');
    const user = await this.auth.refresh();
    if (!user) {
      // Meist das Cookie: Es ist Secure, über HTTP ohne HTTPS verwirft der Browser es (NAS bis
      // D1.5). Seltener war nur die Nachfrage beim Server gestört.
      this.error.set({
        text: 'Die Anmeldung ließ sich nicht bestätigen. Bitte erneut versuchen; ohne HTTPS speichert der Browser sie nicht.',
        error: true,
      });
      return;
    }
    this.auth.notice.set(undefined);
    await this.router.navigateByUrl(
      user?.must_change_password ? '/account' : safeNext(this.next()),
    );
  }
}
