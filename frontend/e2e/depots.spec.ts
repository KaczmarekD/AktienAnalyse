import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// Meine Depots im echten Browser (D3.6, Abnahme von D3): Ein Nutzer legt ein Depot an, trägt
// Kasse ein und übernimmt eine Datei; der Wert stimmt. Ein zweiter Nutzer sieht es nicht.
// Die Replay-Fixture hat keine Tageskurse: Die Position aus der Datei zeigt „Kurs fehlt“, der
// Wert ist die Kasse. Den zweiten Nutzer legt der Test über die Nutzerverwaltung an.

const SAP = 'DE0007164600';

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

/** Ein zweites Konto mit eigenem Passwort, angemeldet in einem eigenen Kontext. */
async function secondUser(
  admin: APIRequestContext,
  newContext: () => Promise<APIRequestContext>,
): Promise<APIRequestContext> {
  const username = `zweiter-${Date.now()}`;
  const oneTime = 'Einmal-Kiefer-Wolke-Rhein-42';
  const password = 'Zweiter-Nutzer-Birke-Main-77';
  const created = await admin.post('/api/v1/admin/users', {
    data: { username, one_time_password: oneTime, role: 'user' },
  });
  expect(created.status(), 'Konto anlegen').toBe(201);
  const other = await newContext();
  expect(
    (await other.post('/api/v1/auth/login', { data: { username, password: oneTime } })).status(),
  ).toBe(204);
  const changed = await other.put('/api/v1/me/password', {
    data: { current_password: oneTime, new_password: password },
  });
  expect(changed.status(), 'eigenes Passwort').toBe(204);
  return other;
}

test('ein Nutzer legt ein Depot an, der Wert stimmt, ein zweiter sieht es nicht', async ({
  page,
  playwright,
  baseURL,
}) => {
  test.skip(!process.env['E2E_USERNAME'], 'braucht die Anmeldung des E2E-Stacks');
  const errors = collectErrors(page);
  const name = `E2E-Depot ${Date.now()}`;

  // Die Startseite nach der Anmeldung ist „Meine Depots“
  await page.goto('/');
  await expect(page).toHaveURL(/\/depots$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(/Meine Depots/);

  await page.locator('button[data-action="create"]').click();
  await page.locator('mat-dialog-container [data-field="name"]').fill(name);
  await page.locator('mat-dialog-container button[data-action="save"]').click();
  await expect(page).toHaveURL(/\/depots\/\d+$/);
  const id = Number(page.url().split('/').pop());
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(new RegExp(name));

  // Kasse eintragen
  await page.locator('button[data-action="edit"]').click();
  await page.locator('[data-field="cash"]').fill('1.000,50');
  await page.locator('button[data-action="save"]').click();
  // Die Rückmeldung der Seite, nicht die der Datei (beide sind app-notice)
  await expect(page.locator('app-depot-page > app-notice')).toContainText(
    'Gespeichert: Depotstand 1.',
  );
  await expect(page.locator('[data-stat-value]')).toContainText('1.000,50 €');

  // Eine Datei übernehmen: neue Position ohne Kurs, die Kasse bleibt
  await page.locator('[data-field="file"]').setInputFiles({
    name: 'depot.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(`isin;menge;einstand;notiz\n${SAP};10;2000;E2E\n`, 'utf-8'),
  });
  await expect(page.locator('[data-summary]')).toContainText('1 neu');
  await page.locator('button[data-action="apply"]').click();
  await expect(page.locator('app-import-panel app-notice')).toContainText(
    'Datei übernommen: Depotstand 2.',
  );
  const row = page.locator(`tr[data-position="${SAP}"]`);
  await expect(row).toContainText(SAP);
  await expect(row.locator('[data-missing]')).toContainText('Kurs fehlt');
  await expect(page.locator('[data-stat-value]')).toContainText('1.000,50 €');
  await expect(page.locator('[data-history] [data-version]')).toHaveCount(2);

  // In der Liste mit Wert
  await page.goto('/depots');
  await expect(page.locator(`[data-depot="${id}"] [data-value]`)).toHaveText('1.000,50 €');

  // Ein zweiter Nutzer sieht das Depot nicht
  const other = await secondUser(page.request, () => playwright.request.newContext({ baseURL }));
  const list = await other.get('/api/v1/depots');
  expect(list.ok()).toBe(true);
  expect(((await list.json()) as { id: number }[]).map((depot) => depot.id)).not.toContain(id);
  expect((await other.get(`/api/v1/depots/${id}`)).status()).toBe(404);
  expect((await other.get(`/api/v1/depots/${id}/holdings/csv`)).status()).toBe(404);
  await other.dispose();

  expect(errors, 'Fehler in der Konsole').toEqual([]);
});
