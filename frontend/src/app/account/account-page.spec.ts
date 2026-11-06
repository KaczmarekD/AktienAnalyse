// Eigenes Konto (D1.4, NUT-11): Anzeigename, Passwort ändern, Sitzungen und „überall abmelden“.
// Mit Einmal-Passwort steht oben, dass es zuerst ersetzt werden muss.
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { vi } from 'vitest';

import type { SessionInfo } from '../api/types.gen';
import { apiTestingProviders, query, respond, text } from '../testing/api';
import { ADMIN, fakeAuth, me, provideAuthTesting } from '../testing/auth';
import {
  abbreviationsWithoutExplanation,
  controlsWithoutTooltip,
  headersWithoutScope,
} from '../testing/tooltips';
import { AccountPage } from './account-page';

const SESSIONS = '/api/v1/me/sessions';
const PASSWORD = 'Kiefer-Wolke-Rhein-42';
const NEW = 'Ahorn-Nebel-Mosel-17';

type Fixture = ComponentFixture<AccountPage>;

function session(values: Partial<SessionInfo> = {}): SessionInfo {
  return {
    created_at: '2026-11-06T10:00:00Z',
    last_seen: '2026-11-06T11:00:00Z',
    expires_at: '2026-12-06T10:00:00Z',
    user_agent: 'Mozilla/5.0 (Windows NT 10.0) Firefox/140.0',
    current: false,
    ...values,
  };
}

async function settle(fixture: Fixture): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
    fixture.detectChanges();
  }
}

async function render(user = me(), sessions = [session({ current: true }), session()]) {
  TestBed.configureTestingModule({
    providers: [...apiTestingProviders(), provideAuthTesting({ user })],
  });
  const fixture = TestBed.createComponent(AccountPage);
  fixture.detectChanges();
  await respond(fixture, SESSIONS, sessions);
  fixture.detectChanges();
  return fixture;
}

function type(fixture: Fixture, name: string, value: string): void {
  const input = query<HTMLInputElement>(fixture, `input[name="${name}"]`)[0];
  input.value = value;
  input.dispatchEvent(new Event('input'));
  fixture.detectChanges();
}

function button(fixture: Fixture, action: string): HTMLButtonElement {
  return query<HTMLButtonElement>(fixture, `button[data-action="${action}"]`)[0];
}

function expectRequest(url: string, method: string): TestRequest {
  return TestBed.inject(HttpTestingController).expectOne(
    (r) => r.url === url && r.method === method,
  );
}

async function changePassword(fixture: Fixture, current = PASSWORD, next = NEW, repeat = NEW) {
  type(fixture, 'current-password', current);
  type(fixture, 'new-password', next);
  type(fixture, 'repeat-password', repeat);
  button(fixture, 'change-password').click();
  await settle(fixture);
  return expectRequest('/api/v1/me/password', 'PUT');
}

describe('AccountPage', () => {
  let navigate: ReturnType<typeof vi.spyOn>;

  afterEach(() => navigate?.mockRestore());

  function spyNavigation(): void {
    navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
  }

  it('shows the account with name and role', async () => {
    const fixture = await render();
    expect(text(fixture)).toContain('anna');
    expect(text(fixture)).toContain('Nutzer');
    expect(query<HTMLInputElement>(fixture, 'input[name="display-name"]')[0].value).toBe('Anna');
  });

  it('explains every control, header and badge (tests 1 and 2)', async () => {
    const fixture = await render(ADMIN);
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(headersWithoutScope(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });

  it('links admins to the user management', async () => {
    expect(query(await render(ADMIN), 'a[href="/admin/users"]').length).toBe(1);
    TestBed.resetTestingModule();
    expect(query(await render(), 'a[href="/admin/users"]').length).toBe(0);
  });

  it('saves the display name', async () => {
    const fixture = await render();
    spyNavigation();
    type(fixture, 'display-name', 'Anna B.');
    button(fixture, 'save-name').click();
    await settle(fixture);
    const request = expectRequest('/api/v1/me/profile', 'PUT');
    expect(request.request.body).toEqual({ display_name: 'Anna B.' });
    request.flush(me({ display_name: 'Anna B.' }));
    await settle(fixture);
    expect(fakeAuth().calls.refresh).toBe(1);
    expect(query(fixture, '[role="status"]')[0]?.textContent).toContain('Anzeigename gespeichert.');
  });

  describe('mail address (D1.6)', () => {
    it('shows the confirmed address and a pending one', async () => {
      const fixture = await render(
        me({ email: 'anna@example.com', pending_email: 'neu@example.com' }),
      );
      expect(query<HTMLInputElement>(fixture, 'input[name="email"]')[0].value).toBe(
        'anna@example.com',
      );
      expect(text(fixture)).toContain('Bestätigung ausstehend');
      expect(text(fixture)).toContain('neu@example.com');
    });

    it('asks for a confirmation of a new address', async () => {
      const fixture = await render(me({ email: 'anna@example.com' }));
      type(fixture, 'email', 'neu@example.com');
      button(fixture, 'save-name').click();
      await settle(fixture);
      const request = expectRequest('/api/v1/me/profile', 'PUT');
      expect(request.request.body).toEqual({ display_name: 'Anna', email: 'neu@example.com' });
      fakeAuth().next = me({ email: 'anna@example.com', pending_email: 'neu@example.com' });
      request.flush(me({ email: 'anna@example.com', pending_email: 'neu@example.com' }));
      await settle(fixture);
      expect(query(fixture, '[role="status"]')[0]?.textContent).toContain(
        'Wir haben eine Mail an neu@example.com geschickt',
      );
    });

    it('shows the reason when the server refuses the address', async () => {
      const fixture = await render(me({ email: 'anna@example.com' }));
      type(fixture, 'email', 'falsch@x');
      button(fixture, 'save-name').click();
      await settle(fixture);
      expectRequest('/api/v1/me/profile', 'PUT').flush(
        { detail: 'Keine gültige Mail-Adresse' },
        { status: 400, statusText: 'x' },
      );
      await settle(fixture);
      expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain(
        'Keine gültige Mail-Adresse',
      );
    });
  });

  describe('export (D1.6, NUT-12)', () => {
    it('downloads the own data as a file', async () => {
      const fixture = await render();
      const created = vi.fn(() => 'blob:export');
      const revoked = vi.fn();
      Object.assign(URL, { createObjectURL: created, revokeObjectURL: revoked });
      button(fixture, 'export').click();
      await settle(fixture);
      const request = expectRequest('/api/v1/me/export', 'GET');
      request.flush({ account: [{ username: 'anna' }] });
      await settle(fixture);
      expect(created).toHaveBeenCalledTimes(1);
      expect(revoked).toHaveBeenCalledWith('blob:export');
    });
  });

  describe('password', () => {
    it('uses the autocomplete hints of a password manager', async () => {
      const fixture = await render();
      const auto = (name: string) =>
        query<HTMLInputElement>(fixture, `input[name="${name}"]`)[0].getAttribute('autocomplete');
      expect(auto('current-password')).toBe('current-password');
      expect(auto('new-password')).toBe('new-password');
      expect(auto('repeat-password')).toBe('new-password');
    });

    it('can only be changed when both new passwords match and are long enough', async () => {
      const fixture = await render();
      type(fixture, 'current-password', PASSWORD);
      type(fixture, 'new-password', NEW);
      type(fixture, 'repeat-password', NEW + 'x');
      expect(button(fixture, 'change-password').getAttribute('aria-disabled')).toBe('true');
      expect(text(fixture)).toContain('Die beiden neuen Passwörter stimmen nicht überein.');
      type(fixture, 'new-password', 'zu-kurz');
      type(fixture, 'repeat-password', 'zu-kurz');
      expect(button(fixture, 'change-password').getAttribute('aria-disabled')).toBe('true');
      expect(text(fixture)).toContain('mindestens 12 Zeichen');
      type(fixture, 'new-password', NEW);
      type(fixture, 'repeat-password', NEW);
      expect(button(fixture, 'change-password').getAttribute('aria-disabled')).not.toBe('true');
    });

    it('changes the password and says that the other sessions ended', async () => {
      const fixture = await render();
      const request = await changePassword(fixture);
      expect(request.request.body).toEqual({ current_password: PASSWORD, new_password: NEW });
      request.flush(null, { status: 204, statusText: 'No Content' });
      await settle(fixture);
      // Die Liste der Sitzungen lädt neu: Die anderen sind beendet
      await respond(fixture, SESSIONS, [session({ current: true })]);
      expect(query(fixture, '[role="status"]')[0]?.textContent).toContain('Passwort geändert.');
      expect(query<HTMLInputElement>(fixture, 'input[name="new-password"]')[0].value).toBe('');
    });

    it('shows the reason from the server when it refuses', async () => {
      const fixture = await render();
      const request = await changePassword(fixture);
      request.flush(
        { detail: 'Das bisherige Passwort stimmt nicht.' },
        { status: 400, statusText: 'x' },
      );
      await settle(fixture);
      expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain(
        'Das bisherige Passwort stimmt nicht.',
      );
    });

    it('says when too many attempts locked the account', async () => {
      const fixture = await render();
      const request = await changePassword(fixture);
      request.flush({ detail: 'x' }, { status: 429, statusText: 'x' });
      await settle(fixture);
      expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain('15 Minuten');
    });

    it('asks first for a new password instead of the one-time password', async () => {
      const fixture = await render(me({ must_change_password: true }));
      spyNavigation();
      expect(text(fixture)).toContain('Einmal-Passwort');
      fakeAuth().next = me();
      const request = await changePassword(fixture);
      request.flush(null, { status: 204, statusText: 'No Content' });
      await settle(fixture);
      expect(fakeAuth().calls.refresh).toBe(1);
      expect(navigate).toHaveBeenCalledWith('/ranking');
    });
  });

  describe('sessions', () => {
    it('lists the sessions and marks this one', async () => {
      const fixture = await render();
      const rows = query(fixture, 'tr[data-session]');
      expect(rows.length).toBe(2);
      expect(rows[0].textContent).toContain('dieses Gerät');
      expect(rows[0].textContent).toContain('Firefox');
      expect(rows[1].textContent).not.toContain('dieses Gerät');
    });

    it('logs out everywhere and goes to the login page', async () => {
      const fixture = await render();
      spyNavigation();
      button(fixture, 'revoke-all').click();
      await settle(fixture);
      expectRequest('/api/v1/me/sessions/revoke-all', 'POST').flush(null, {
        status: 204,
        statusText: 'No Content',
      });
      await settle(fixture);
      expect(fakeAuth().calls.signedOut).toBe(1);
      expect(navigate).toHaveBeenCalledWith('/login');
    });
  });
});
