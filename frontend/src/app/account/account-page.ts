import { HttpResponse } from '@angular/common/http';
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
import { changePassword, exportData, revokeAllSessions, updateProfile } from '../api/sdk.gen';
import type { ProfileUpdate } from '../api/types.gen';
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

/** Grund aus einer Antwort mit 400, sonst der Ersatztext. */
function reason(status: number | undefined, error: unknown, fallback: string): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return status === 400 && typeof detail === 'string' ? detail : fallback;
}

/** Meldung, wenn der Server das neue Passwort ablehnt. */
function refused(status: number | undefined, error: unknown): string {
  if (status === 429) {
    return 'Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.';
  }
  return reason(status, error, 'Das Passwort konnte nicht geändert werden.');
}

/**
 * Eigenes Konto (/account, D1.4, NUT-11): Anzeigename, Passwort und Sitzungen. Mit Einmal-Passwort
 * führt jeder Weg zuerst hierher; nach dem neuen Passwort geht es zum Ranking.
 *
 * Seit D1.6: Mail-Adresse (eine neue gilt erst nach dem Link aus der Mail, bis dahin „Bestätigung
 * ausstehend“, NUT-10) und „Meine Daten herunterladen“ (NUT-12).
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
  protected readonly email = linkedSignal(() => this.auth.user()?.email ?? '');
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

  // Export
  protected readonly exporting = signal(false);
  protected readonly exportNotice = signal<Notice | undefined>(undefined);

  protected async saveName(): Promise<void> {
    const body: ProfileUpdate = { display_name: this.displayName().trim() || null };
    // Die Adresse nur, wenn sie neu ist: Sonst ginge jedes Mal eine Bestätigungsmail raus
    const email = this.email().trim();
    const current = this.auth.user()?.email ?? '';
    if (email === '' && current !== '') {
      // Der Server kennt kein Entfernen; ohne Hinweis sähe Speichern wie Erfolg aus
      this.nameNotice.set({ text: 'Bitte eine Mail-Adresse angeben.', error: true });
      return;
    }
    if (email !== '' && email.toLowerCase() !== current.toLowerCase()) {
      body.email = email;
    }
    this.savingName.set(true);
    this.nameNotice.set(undefined);
    const result = await updateProfile({ body });
    this.savingName.set(false);
    if (!result.data) {
      this.nameNotice.set({
        text: reason(result.response?.status, result.error, 'Konnte nicht gespeichert werden.'),
        error: true,
      });
      return;
    }
    await this.auth.refresh();
    this.nameNotice.set({
      text: body.email
        ? `Wir haben eine Mail an ${body.email} geschickt. Die neue Adresse gilt, sobald du den Link darin öffnest.`
        : 'Anzeigename gespeichert.',
    });
  }

  protected async download(): Promise<void> {
    this.exporting.set(true);
    this.exportNotice.set(undefined);
    const result = await exportData();
    this.exporting.set(false);
    // Die Datei so, wie der Server sie schickt, auch mit Abschnitten, die der Client nicht kennt
    const response = result.response;
    if (!(response instanceof HttpResponse) || response.status !== 200) {
      this.exportNotice.set({ text: 'Der Export ist gescheitert.', error: true });
      return;
    }
    const body: unknown = response.body;
    const file = new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(file);
    const link = document.createElement('a');
    link.href = url;
    link.download = `va-daten-${this.auth.user()?.username ?? 'konto'}.json`;
    link.click();
    URL.revokeObjectURL(url);
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
