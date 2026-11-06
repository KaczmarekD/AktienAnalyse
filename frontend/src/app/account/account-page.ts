import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  linkedSignal,
  signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterLink } from '@angular/router';

import { listSessionsResource } from '../api/@angular/common.gen';
import { changePassword, revokeAllSessions, updateProfile } from '../api/sdk.gen';
import { AuthStore } from '../shared/auth/auth.store';
import { ACCOUNT_CONTROLS } from '../shared/auth/controls';
import { DayTimePipe } from '../shared/format';
import { keptValue, loadError } from '../shared/resource';
import { FORM_FIELD_DEFAULTS, inputValue } from '../shared/ui/form-field';
import { AppIcon } from '../shared/ui/icon';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { PageHeader } from '../shared/ui/page-header';
import { AppSection } from '../shared/ui/section';
import { AppState } from '../shared/ui/state';

const MIN_PASSWORD = 12; // wie im web-api (NUT-05)

/** Browser und Betriebssystem aus dem User-Agent, grob: „Firefox unter Windows“. */
export function device(userAgent: string | null): string {
  if (!userAgent) {
    return 'unbekannter Browser';
  }
  const browser =
    [
      ['Edg/', 'Edge'],
      ['Firefox/', 'Firefox'],
      ['Chrome/', 'Chrome'],
      ['Safari/', 'Safari'],
    ].find(([mark]) => userAgent.includes(mark))?.[1] ?? 'Browser';
  const system = [
    ['Windows', 'Windows'],
    ['iPhone', 'iOS'],
    ['iPad', 'iOS'],
    ['Android', 'Android'],
    ['Mac OS X', 'macOS'],
    ['Linux', 'Linux'],
  ].find(([mark]) => userAgent.includes(mark))?.[1];
  return system ? `${browser} unter ${system}` : browser;
}

/** Meldung, wenn der Server das neue Passwort ablehnt. */
function refused(status: number | undefined, error: unknown): string {
  if (status === 429) {
    return 'Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.';
  }
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (status === 400 && typeof detail === 'string') {
    return detail;
  }
  return 'Das Passwort konnte nicht geändert werden.';
}

/**
 * Eigenes Konto (/account, D1.4, NUT-11): Anzeigename, Passwort und Sitzungen. Mit Einmal-Passwort
 * führt jeder Weg zuerst hierher; nach dem neuen Passwort geht es zum Ranking.
 */
@Component({
  selector: 'app-account-page',
  imports: [
    AppIcon,
    AppSection,
    AppState,
    DayTimePipe,
    MatButtonModule,
    MatFormFieldModule,
    MatInputModule,
    MatTooltipModule,
    NoticeBox,
    PageHeader,
    RouterLink,
  ],
  providers: [FORM_FIELD_DEFAULTS],
  templateUrl: './account-page.html',
  styleUrl: './account-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AccountPage {
  protected readonly auth = inject(AuthStore);
  private readonly router = inject(Router);
  protected readonly controls = ACCOUNT_CONTROLS;
  protected readonly value = inputValue;
  protected readonly device = device;
  protected readonly minPassword = MIN_PASSWORD;

  // Anzeigename
  protected readonly displayName = linkedSignal(() => this.auth.user()?.display_name ?? '');
  protected readonly savingName = signal(false);
  protected readonly nameNotice = signal<Notice | undefined>(undefined);

  // Passwort
  protected readonly current = signal('');
  protected readonly next = signal('');
  protected readonly repeat = signal('');
  protected readonly changing = signal(false);
  protected readonly passwordNotice = signal<Notice | undefined>(undefined);
  protected readonly tooShort = computed(
    () => this.next() !== '' && this.next().length < MIN_PASSWORD,
  );
  protected readonly mismatch = computed(
    () => this.repeat() !== '' && this.next() !== this.repeat(),
  );
  protected readonly canChange = computed(
    () =>
      this.current() !== '' &&
      this.next().length >= MIN_PASSWORD &&
      this.next() === this.repeat() &&
      !this.changing(),
  );

  // Sitzungen
  private readonly sessionsResource = listSessionsResource(() => ({}));
  protected readonly sessions = keptValue(() => this.sessionsResource);
  protected readonly sessionsError = computed(() =>
    loadError(this.sessionsResource, 'Keine Sitzungen gefunden.'),
  );
  protected readonly revokeNotice = signal<Notice | undefined>(undefined);

  protected async saveName(): Promise<void> {
    this.savingName.set(true);
    this.nameNotice.set(undefined);
    const result = await updateProfile({
      body: { display_name: this.displayName().trim() || null },
    });
    this.savingName.set(false);
    if (!result.data) {
      this.nameNotice.set({ text: 'Der Name konnte nicht gespeichert werden.', error: true });
      return;
    }
    await this.auth.refresh();
    this.nameNotice.set({ text: 'Anzeigename gespeichert.' });
  }

  protected async changePassword(): Promise<void> {
    // disabledInteractive: Der Button bleibt fokussierbar, ein Klick darf dann nichts tun
    if (!this.canChange()) {
      return;
    }
    const wasOneTime = this.auth.user()?.must_change_password ?? false;
    this.changing.set(true);
    this.passwordNotice.set(undefined);
    const result = await changePassword({
      body: { current_password: this.current(), new_password: this.next() },
    });
    this.changing.set(false);
    // 204 ohne Inhalt: Die Prüfung des Clients meldet dann einen Fehler, der Status zählt
    if (result.response?.status !== 204) {
      this.current.set('');
      this.passwordNotice.set({
        text: refused(result.response?.status, result.error),
        error: true,
      });
      return;
    }
    this.current.set('');
    this.next.set('');
    this.repeat.set('');
    this.passwordNotice.set({ text: 'Passwort geändert. Deine anderen Sitzungen sind beendet.' });
    this.sessionsResource.reload();
    if (wasOneTime) {
      await this.auth.refresh();
      await this.router.navigateByUrl('/ranking');
    }
  }

  protected async revokeAll(): Promise<void> {
    this.revokeNotice.set(undefined);
    const result = await revokeAllSessions();
    if (result.response?.status !== 204) {
      this.revokeNotice.set({ text: 'Die Sitzungen konnten nicht beendet werden.', error: true });
      return;
    }
    this.auth.signedOut();
    await this.router.navigateByUrl('/login');
  }
}
