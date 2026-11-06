import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatRadioModule } from '@angular/material/radio';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';

import { listUsersResource } from '../api/@angular/common.gen';
import { createUser, disableUser, enableUser, resetPassword } from '../api/sdk.gen';
import type { Account } from '../api/types.gen';
import { AuthStore } from '../shared/auth/auth.store';
import { ACCOUNT_CONTROLS } from '../shared/auth/controls';
import { oneTimePassword } from '../shared/auth/one-time-password';
import { keptValue, loadError } from '../shared/resource';
import { ConfirmData, ConfirmDialog } from '../shared/ui/confirm-dialog';
import { FORM_FIELD_DEFAULTS, inputValue } from '../shared/ui/form-field';
import { AppIcon } from '../shared/ui/icon';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { PageHeader } from '../shared/ui/page-header';
import { AppSection } from '../shared/ui/section';
import { AppState } from '../shared/ui/state';

type Role = Account['role'];

/** Grund des Servers (400, 409), sonst eine allgemeine Meldung. */
function detail(error: unknown, fallback: string): string {
  const text = (error as { detail?: unknown } | undefined)?.detail;
  return typeof text === 'string' ? text : fallback;
}

/**
 * Nutzerverwaltung (/admin/users, D1.4, nur Admins): Konten ansehen, anlegen, deaktivieren,
 * aktivieren und ein Einmal-Passwort setzen. Das Einmal-Passwort entsteht im Browser
 * (one-time-password.ts) und steht einmal auf der Seite, zum Weitergeben; der Server schickt nie
 * eins zurück. Am eigenen Konto ändert ein Admin hier nichts (dafür gibt es „Konto“).
 */
@Component({
  selector: 'app-users-page',
  imports: [
    AppIcon,
    AppSection,
    AppState,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatRadioModule,
    MatTooltipModule,
    NoticeBox,
    PageHeader,
  ],
  providers: [FORM_FIELD_DEFAULTS],
  templateUrl: './users-page.html',
  styleUrl: './users-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UsersPage {
  private readonly auth = inject(AuthStore);
  private readonly dialog = inject(MatDialog);
  protected readonly controls = ACCOUNT_CONTROLS;
  protected readonly value = inputValue;

  private readonly resource = listUsersResource(() => ({}));
  protected readonly users = keptValue(() => this.resource);
  protected readonly error = computed(() => loadError(this.resource, 'Keine Konten gefunden.'));

  protected readonly username = signal('');
  protected readonly displayName = signal('');
  protected readonly email = signal('');
  protected readonly role = signal<Role>('user');
  protected readonly busy = signal(false);
  protected readonly canCreate = computed(() => this.username().trim() !== '' && !this.busy());

  protected readonly notice = signal<Notice | undefined>(undefined);
  /** Das Einmal-Passwort der letzten Aktion; es steht nur hier, bis zur nächsten Aktion. */
  protected readonly oneTime = signal<{ username: string; password: string } | undefined>(
    undefined,
  );

  protected isSelf(account: Account): boolean {
    return account.id === this.auth.user()?.id;
  }

  protected async create(): Promise<void> {
    // disabledInteractive: Der Button bleibt fokussierbar, ein Klick darf dann nichts tun
    if (!this.canCreate()) {
      return;
    }
    const password = oneTimePassword();
    this.start();
    const result = await createUser({
      body: {
        username: this.username().trim(),
        role: this.role(),
        display_name: this.displayName().trim() || null,
        email: this.email().trim() || null,
        one_time_password: password,
      },
    });
    this.busy.set(false);
    if (!result.data) {
      this.notice.set({
        text: detail(result.error, 'Das Konto konnte nicht angelegt werden.'),
        error: true,
      });
      return;
    }
    const name = result.data.username;
    this.oneTime.set({ username: name, password });
    this.notice.set({ text: `Konto ${name} angelegt.` });
    this.username.set('');
    this.displayName.set('');
    this.email.set('');
    this.role.set('user');
    this.resource.reload();
  }

  protected async disable(account: Account): Promise<void> {
    if (this.isSelf(account) || this.busy()) {
      return;
    }
    const name = account.username;
    const confirmed = await this.ask({
      title: 'Konto deaktivieren?',
      text: `${name} kann sich danach nicht mehr anmelden, alle Sitzungen enden. „Aktivieren“ macht das rückgängig.`,
      confirm: 'Deaktivieren',
      confirmTip: this.controls['confirm.disable'](name),
      cancelTip: this.controls['confirm.cancel'],
    });
    if (!confirmed) {
      return;
    }
    this.start();
    const result = await disableUser({ path: { user_id: account.id } });
    this.finish(
      result.response?.status,
      result.error,
      `${name} ist deaktiviert. Alle Sitzungen sind beendet.`,
    );
  }

  protected async enable(account: Account): Promise<void> {
    if (this.busy()) {
      return;
    }
    this.start();
    const result = await enableUser({ path: { user_id: account.id } });
    this.finish(result.response?.status, result.error, `${account.username} ist wieder aktiv.`);
  }

  protected async reset(account: Account): Promise<void> {
    if (this.isSelf(account) || this.busy()) {
      return;
    }
    const name = account.username;
    const confirmed = await this.ask({
      title: 'Einmal-Passwort setzen?',
      text: `${name} meldet sich danach mit einem neuen Einmal-Passwort an und ersetzt es gleich. Alle Sitzungen von ${name} enden.`,
      confirm: 'Setzen',
      confirmTip: this.controls['confirm.reset'](name),
      cancelTip: this.controls['confirm.cancel'],
    });
    if (!confirmed) {
      return;
    }
    const password = oneTimePassword();
    this.start();
    const result = await resetPassword({
      path: { user_id: account.id },
      body: { one_time_password: password },
    });
    if (
      this.finish(
        result.response?.status,
        result.error,
        `Neues Einmal-Passwort für ${name} gesetzt. Alle Sitzungen von ${name} sind beendet.`,
      )
    ) {
      this.oneTime.set({ username: name, password });
    }
  }

  protected copy(password: string): void {
    const done = navigator.clipboard?.writeText(password) ?? Promise.reject(new Error('ohne'));
    done.then(
      () => this.notice.set({ text: 'Einmal-Passwort kopiert.' }),
      // Ohne Erlaubnis oder ohne Fokus lehnt der Browser ab: kein Fehler in der Konsole
      () =>
        this.notice.set({
          text: 'Kopieren ging nicht. Bitte das Einmal-Passwort von Hand abschreiben.',
          error: true,
        }),
    );
  }

  private start(): void {
    this.busy.set(true);
    this.notice.set(undefined);
    this.oneTime.set(undefined);
  }

  /** Nach Deaktivieren, Aktivieren, Zurücksetzen: 204 heißt erledigt (ohne Inhalt). */
  private finish(status: number | undefined, error: unknown, done: string): boolean {
    this.busy.set(false);
    if (status !== 204) {
      this.notice.set({ text: detail(error, 'Das hat nicht geklappt.'), error: true });
      return false;
    }
    this.notice.set({ text: done });
    this.resource.reload();
    return true;
  }

  private async ask(data: ConfirmData): Promise<boolean> {
    const ref = this.dialog.open<ConfirmDialog, ConfirmData, boolean>(ConfirmDialog, {
      data,
      width: '28rem',
      maxWidth: '100%',
    });
    return (await firstValueFrom(ref.afterClosed())) === true;
  }
}
