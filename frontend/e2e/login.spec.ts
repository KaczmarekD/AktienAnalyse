import { expect, test, type Page } from '@playwright/test';

// Anmelden und Abmelden im echten Browser (D1.4): ohne Sitzung zur Anmeldeseite, danach zurück
// zur gewünschten Seite, Abmelden führt wieder zur Anmeldung. Mit leerer Konsole, auch auf der
// Anmeldeseite (deshalb fragt das UI GET /auth/session, das ohne Sitzung nicht mit 401 antwortet).

const username = process.env['E2E_USERNAME'] ?? '';
const password = process.env['E2E_PASSWORD'] ?? '';

// Ohne gespeicherte Anmeldung aus auth.setup.ts
test.use({ storageState: { cookies: [], origins: [] } });

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(message.text());
    }
  });
  page.on('pageerror', (error) => errors.push(error.message));
  return errors;
}

test('anmelden, Läufe sehen, abmelden', async ({ page }) => {
  test.skip(!username || !password, 'ohne E2E_USERNAME/E2E_PASSWORD (make local-e2e setzt beide)');
  const errors = collectErrors(page);

  await page.goto('/runs');
  await expect(page).toHaveURL(/\/login\?next=%2Fruns$/);
  await expect(page.getByRole('heading', { name: 'Anmelden' })).toBeVisible();
  // Ohne Anmeldung keine Navigation
  await expect(
    page.getByRole('navigation', { name: 'Hauptnavigation' }).getByRole('link'),
  ).toHaveCount(0);

  await page.getByLabel('Benutzername').fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Anmelden' }).click();

  await expect(page).toHaveURL(/\/runs$/);
  await expect(page.getByRole('heading', { name: 'Läufe' })).toBeVisible();
  await expect(page.getByRole('link', { name: /^Konto von / })).toBeVisible();

  await page.getByRole('button', { name: 'Abmelden' }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto('/ranking');
  await expect(page).toHaveURL(/\/login\?next=%2Franking$/);

  expect(errors, 'Fehler in der Konsole').toEqual([]);
});

test('falsches Passwort: Meldung, keine Anmeldung', async ({ page }) => {
  test.skip(!username, 'ohne E2E_USERNAME (make local-e2e setzt es)');
  await page.goto('/login');
  await page.getByLabel('Benutzername').fill(username);
  await page.getByLabel('Passwort', { exact: true }).fill('Falsch-Falsch-Falsch-1');
  await page.getByRole('button', { name: 'Anmelden' }).click();
  await expect(page.getByRole('alert')).toContainText('Benutzername oder Passwort falsch.');
  await expect(page).toHaveURL(/\/login/);
});
