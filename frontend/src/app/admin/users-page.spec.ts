// Nutzerverwaltung (D1.4, Rollen): Konten ansehen, anlegen, deaktivieren, aktivieren und ein
// Einmal-Passwort setzen. Das Einmal-Passwort entsteht im Browser und steht einmal auf der Seite;
// der Server schickt nie eins zurück.
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDialog } from '@angular/material/dialog';

import type { Account } from '../api/types.gen';
import { apiTestingProviders, query, respond, text } from '../testing/api';
import { ADMIN, provideAuthTesting } from '../testing/auth';
import {
  abbreviationsWithoutExplanation,
  controlsWithoutTooltip,
  headersWithoutScope,
} from '../testing/tooltips';
import { UsersPage } from './users-page';

const USERS = '/api/v1/admin/users';
const ONE_TIME = /^[A-HJ-NP-Za-km-z2-9]{5}(-[A-HJ-NP-Za-km-z2-9]{5}){3}$/;

type Fixture = ComponentFixture<UsersPage>;

function account(values: Partial<Account> & Pick<Account, 'id' | 'username'>): Account {
  return {
    role: 'user',
    display_name: null,
    email: null,
    active: true,
    must_change_password: false,
    created_at: '2026-11-06T10:00:00Z',
    ...values,
  };
}

const ACCOUNTS = [
  account({ id: 1, username: 'dennis', role: 'admin', display_name: 'Dennis' }),
  account({ id: 2, username: 'anna', display_name: 'Anna', must_change_password: true }),
  account({ id: 3, username: 'ben', active: false }),
];

async function settle(fixture: Fixture): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
    fixture.detectChanges();
  }
}

async function render(): Promise<Fixture> {
  TestBed.configureTestingModule({
    providers: [
      ...apiTestingProviders(),
      provideAuthTesting({ user: ADMIN }),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
    ],
  });
  const fixture = TestBed.createComponent(UsersPage);
  fixture.detectChanges();
  await respond(fixture, USERS, ACCOUNTS);
  fixture.detectChanges();
  return fixture;
}

function row(fixture: Fixture, id: number): HTMLElement {
  return query(fixture, `tr[data-user="${id}"]`)[0];
}

function action(fixture: Fixture, id: number, name: string): HTMLButtonElement {
  return row(fixture, id).querySelector<HTMLButtonElement>(`button[data-action="${name}"]`)!;
}

function type(fixture: Fixture, name: string, value: string): void {
  const input = query<HTMLInputElement>(fixture, `input[name="${name}"]`)[0];
  input.value = value;
  input.dispatchEvent(new Event('input'));
  fixture.detectChanges();
}

function expectRequest(url: string, method: string): TestRequest {
  return TestBed.inject(HttpTestingController).expectOne(
    (r) => r.url === url && r.method === method,
  );
}

async function confirmDialog(fixture: Fixture): Promise<void> {
  const button = document.querySelector<HTMLButtonElement>(
    'mat-dialog-container button[data-action="confirm"]',
  );
  expect(button).not.toBeNull();
  button!.click();
  await settle(fixture);
}

describe('UsersPage', () => {
  afterEach(() => TestBed.inject(MatDialog).closeAll());

  it('lists every account with role and state', async () => {
    const fixture = await render();
    expect(query(fixture, 'tr[data-user]').length).toBe(3);
    expect(row(fixture, 1).textContent).toContain('dennis');
    expect(row(fixture, 1).textContent).toContain('Admin');
    expect(row(fixture, 2).textContent).toContain('Einmal-Passwort offen');
    expect(row(fixture, 3).textContent).toContain('deaktiviert');
  });

  it('explains every control, header and badge (tests 1 and 2)', async () => {
    const fixture = await render();
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(headersWithoutScope(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });

  it('does not offer to disable or reset the own account', async () => {
    const fixture = await render();
    expect(action(fixture, 1, 'disable').getAttribute('aria-disabled')).toBe('true');
    expect(action(fixture, 1, 'reset').getAttribute('aria-disabled')).toBe('true');
    expect(action(fixture, 2, 'disable').getAttribute('aria-disabled')).not.toBe('true');
  });

  it('creates an account with a one-time password made in the browser', async () => {
    const fixture = await render();
    type(fixture, 'new-username', 'lena');
    type(fixture, 'new-display-name', 'Lena');
    type(fixture, 'new-email', 'lena@example.com');
    query<HTMLButtonElement>(fixture, 'button[data-action="create"]')[0].click();
    await settle(fixture);
    const request = expectRequest(USERS, 'POST');
    const body = request.request.body as Record<string, string>;
    expect(body).toMatchObject({
      username: 'lena',
      role: 'user',
      display_name: 'Lena',
      email: 'lena@example.com',
    });
    expect(body['one_time_password']).toMatch(ONE_TIME);
    request.flush(account({ id: 4, username: 'lena', must_change_password: true }), {
      status: 201,
      statusText: 'Created',
    });
    await settle(fixture);
    // Das Einmal-Passwort steht einmal auf der Seite, zum Weitergeben
    expect(text(fixture)).toContain(body['one_time_password']);
    expect(query(fixture, 'button[data-action="copy"]').length).toBe(1);
    // Die Liste lädt neu, das Formular ist leer
    await respond(fixture, USERS, [...ACCOUNTS, account({ id: 4, username: 'lena' })]);
    expect(query<HTMLInputElement>(fixture, 'input[name="new-username"]')[0].value).toBe('');
  });

  it('says when the name is taken', async () => {
    const fixture = await render();
    type(fixture, 'new-username', 'anna');
    query<HTMLButtonElement>(fixture, 'button[data-action="create"]')[0].click();
    await settle(fixture);
    expectRequest(USERS, 'POST').flush(
      { detail: 'Den Benutzernamen gibt es schon.' },
      { status: 409, statusText: 'Conflict' },
    );
    await settle(fixture);
    expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain(
      'Den Benutzernamen gibt es schon.',
    );
  });

  it('disables an account after asking', async () => {
    const fixture = await render();
    action(fixture, 2, 'disable').click();
    await settle(fixture);
    expect(document.querySelector('mat-dialog-container')?.textContent).toContain('anna');
    await confirmDialog(fixture);
    expectRequest('/api/v1/admin/users/2/disable', 'POST').flush(null, {
      status: 204,
      statusText: 'No Content',
    });
    await settle(fixture);
    await respond(fixture, USERS, ACCOUNTS);
    expect(query(fixture, '[role="status"]')[0]?.textContent).toContain('anna ist deaktiviert');
  });

  it('enables a disabled account', async () => {
    const fixture = await render();
    action(fixture, 3, 'enable').click();
    await settle(fixture);
    expectRequest('/api/v1/admin/users/3/enable', 'POST').flush(null, {
      status: 204,
      statusText: 'No Content',
    });
    await settle(fixture);
    await respond(fixture, USERS, ACCOUNTS);
    expect(query(fixture, '[role="status"]')[0]?.textContent).toContain('ben ist wieder aktiv');
  });

  it('sets a new one-time password after asking and shows it once', async () => {
    const fixture = await render();
    action(fixture, 2, 'reset').click();
    await settle(fixture);
    await confirmDialog(fixture);
    const request = expectRequest('/api/v1/admin/users/2/reset-password', 'POST');
    const password = (request.request.body as Record<string, string>)['one_time_password'];
    expect(password).toMatch(ONE_TIME);
    request.flush(null, { status: 204, statusText: 'No Content' });
    await settle(fixture);
    await respond(fixture, USERS, ACCOUNTS);
    expect(text(fixture)).toContain(password);
  });

  it('does nothing when the question is cancelled', async () => {
    const fixture = await render();
    action(fixture, 2, 'disable').click();
    await settle(fixture);
    document
      .querySelector<HTMLButtonElement>('mat-dialog-container button[data-action="cancel"]')!
      .click();
    await settle(fixture);
    TestBed.inject(HttpTestingController).expectNone((r) => r.method === 'POST');
  });
});
