// Mail-Adresse bestätigen (D1.6, NUT-10): Die Seite hinter dem Link aus der Mail. Sie schickt das
// Token ohne Anmeldung an den Server; danach gilt die neue Adresse.
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { apiTestingProviders, query, text } from '../testing/api';
import { fakeAuth, me, provideAuthTesting } from '../testing/auth';
import { abbreviationsWithoutExplanation, controlsWithoutTooltip } from '../testing/tooltips';
import { ConfirmEmailPage } from './confirm-email-page';

const CONFIRM = '/api/v1/auth/confirm-email';

type Fixture = ComponentFixture<ConfirmEmailPage>;

async function settle(fixture: Fixture): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
    fixture.detectChanges();
  }
}

async function render(token: string | undefined, user = me()): Promise<Fixture> {
  TestBed.configureTestingModule({
    providers: [...apiTestingProviders(), provideAuthTesting({ user })],
  });
  const fixture = TestBed.createComponent(ConfirmEmailPage);
  if (token !== undefined) {
    fixture.componentRef.setInput('token', token);
  }
  await settle(fixture);
  return fixture;
}

function request(): TestRequest {
  return TestBed.inject(HttpTestingController).expectOne(
    (r) => r.url === CONFIRM && r.method === 'POST',
  );
}

describe('ConfirmEmailPage', () => {
  it('sends the token from the link and says the address is confirmed', async () => {
    const fixture = await render('abc');
    const sent = request();
    expect(sent.request.body).toEqual({ token: 'abc' });
    sent.flush(null, { status: 204, statusText: 'No Content' });
    await settle(fixture);
    expect(query(fixture, '[role="status"]')[0]?.textContent).toContain(
      'Deine Mail-Adresse ist bestätigt.',
    );
    expect(fakeAuth().calls.refresh).toBe(1);
  });

  it('says when the link is invalid, used or expired', async () => {
    const fixture = await render('alt');
    request().flush({ detail: 'Link ungültig oder abgelaufen' }, { status: 400, statusText: 'x' });
    await settle(fixture);
    expect(query(fixture, '[role="alert"]')[0]?.textContent).toContain(
      'Der Link ist ungültig oder abgelaufen.',
    );
  });

  it('needs a token', async () => {
    const fixture = await render(undefined);
    TestBed.inject(HttpTestingController).expectNone(CONFIRM);
    expect(text(fixture)).toContain('Der Link ist unvollständig.');
  });

  it('explains every control (tests 1 and 2)', async () => {
    const fixture = await render('abc');
    request().flush(null, { status: 204, statusText: 'No Content' });
    await settle(fixture);
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });
});
