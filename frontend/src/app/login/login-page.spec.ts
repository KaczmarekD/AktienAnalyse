// Anmeldung (D1.4, NUT-01): Benutzername und Passwort, danach zurück zur Seite, die man wollte.
// Mit Einmal-Passwort geht es zuerst auf die Kontoseite. Fehler sagen, was los ist, ohne zu
// verraten, ob es den Namen gibt.
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { vi } from 'vitest';

import { apiTestingProviders, query, text } from '../testing/api';
import { fakeAuth, me, provideAuthTesting } from '../testing/auth';
import { abbreviationsWithoutExplanation, controlsWithoutTooltip } from '../testing/tooltips';
import { LoginPage } from './login-page';

const LOGIN = '/api/v1/auth/login';

type Fixture = ComponentFixture<LoginPage>;

async function settle(fixture: Fixture): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
    fixture.detectChanges();
  }
}

async function render(next?: string): Promise<Fixture> {
  TestBed.configureTestingModule({ providers: [...apiTestingProviders(), provideAuthTesting()] });
  const fixture = TestBed.createComponent(LoginPage);
  if (next !== undefined) {
    fixture.componentRef.setInput('next', next);
  }
  await settle(fixture);
  return fixture;
}

function type(fixture: Fixture, name: string, value: string): void {
  const input = query<HTMLInputElement>(fixture, `input[name="${name}"]`)[0];
  input.value = value;
  input.dispatchEvent(new Event('input'));
  fixture.detectChanges();
}

async function submit(fixture: Fixture, username = 'anna', password = 'Kiefer-Wolke-Rhein-42') {
  type(fixture, 'username', username);
  type(fixture, 'password', password);
  query<HTMLButtonElement>(fixture, 'button[data-action="login"]')[0].click();
  await settle(fixture);
  return TestBed.inject(HttpTestingController).expectOne(LOGIN);
}

async function answer(fixture: Fixture, request: TestRequest, status: number): Promise<void> {
  if (status === 204) {
    request.flush(null, { status: 204, statusText: 'No Content' });
  } else {
    request.flush({ detail: 'x' }, { status, statusText: 'Fehler' });
  }
  await settle(fixture);
}

describe('LoginPage', () => {
  let navigate: ReturnType<typeof vi.spyOn>;

  afterEach(() => navigate?.mockRestore());

  function spyNavigation(): void {
    navigate = vi.spyOn(TestBed.inject(Router), 'navigateByUrl').mockResolvedValue(true);
  }

  it('asks for name and password with the right autocomplete hints', async () => {
    const fixture = await render();
    expect(query(fixture, 'h1')[0].textContent).toContain('Anmelden');
    const [name] = query<HTMLInputElement>(fixture, 'input[name="username"]');
    const [password] = query<HTMLInputElement>(fixture, 'input[name="password"]');
    expect(name.getAttribute('autocomplete')).toBe('username');
    expect(password.type).toBe('password');
    expect(password.getAttribute('autocomplete')).toBe('current-password');
  });

  it('explains every control (tests 1 and 2)', async () => {
    const fixture = await render();
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });

  it('can only be sent with name and password', async () => {
    const fixture = await render();
    const [button] = query<HTMLButtonElement>(fixture, 'button[data-action="login"]');
    expect(button.getAttribute('aria-disabled')).toBe('true');
    type(fixture, 'username', 'anna');
    type(fixture, 'password', 'x');
    expect(button.getAttribute('aria-disabled')).not.toBe('true');
  });

  it('logs in and goes back to the page the user wanted', async () => {
    const fixture = await render('/runs/3');
    spyNavigation();
    fakeAuth().next = me();
    const request = await submit(fixture);
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ username: 'anna', password: 'Kiefer-Wolke-Rhein-42' });
    await answer(fixture, request, 204);
    expect(fakeAuth().calls.refresh).toBe(1);
    expect(navigate).toHaveBeenCalledWith('/runs/3');
  });

  it('goes to the ranking without a return path or with a foreign one', async () => {
    const fixture = await render('https://boese.example');
    spyNavigation();
    fakeAuth().next = me();
    await answer(fixture, await submit(fixture), 204);
    expect(navigate).toHaveBeenCalledWith('/ranking');
  });

  it('sends a user with a one-time password to the account page first', async () => {
    const fixture = await render('/runs');
    spyNavigation();
    fakeAuth().next = me({ must_change_password: true });
    await answer(fixture, await submit(fixture), 204);
    expect(navigate).toHaveBeenCalledWith('/account');
  });

  it.each([
    [401, 'Benutzername oder Passwort falsch.'],
    [422, 'Benutzername oder Passwort falsch.'],
    [429, 'Zu viele Fehlversuche. Bitte in 15 Minuten erneut versuchen.'],
    [503, 'Die Anmeldung ist auf dem Server nicht eingerichtet.'],
    [500, 'Der Server ist nicht erreichbar.'],
  ])('says what went wrong on %i', async (status, message) => {
    const fixture = await render();
    spyNavigation();
    await answer(fixture, await submit(fixture), status);
    const alert = query(fixture, '[role="alert"]')[0];
    expect(alert?.textContent).toContain(message);
    expect(navigate).not.toHaveBeenCalled();
    // Das Passwort ist danach leer, der Name bleibt
    expect(query<HTMLInputElement>(fixture, 'input[name="password"]')[0].value).toBe('');
    expect(query<HTMLInputElement>(fixture, 'input[name="username"]')[0].value).toBe('anna');
  });

  it('says when the browser dropped the session cookie (no HTTPS)', async () => {
    const fixture = await render('/runs');
    spyNavigation();
    fakeAuth().next = undefined; // der Server meldet danach niemanden an
    await answer(fixture, await submit(fixture), 204);
    expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain('HTTPS');
    expect(navigate).not.toHaveBeenCalled();
  });

  it('shows why the user has to log in again', async () => {
    TestBed.configureTestingModule({ providers: [...apiTestingProviders(), provideAuthTesting()] });
    fakeAuth().notice.set('Deine Sitzung ist abgelaufen. Bitte melde dich neu an.');
    const fixture = TestBed.createComponent(LoginPage);
    await settle(fixture);
    expect(text(fixture)).toContain('Deine Sitzung ist abgelaufen.');
  });
});
