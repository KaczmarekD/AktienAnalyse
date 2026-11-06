import { expect, test as setup } from '@playwright/test';

import { STORAGE_STATE } from './state';

// Anmeldung für die Browser-Tests (D1.4): einmal über die API, das Cookie gilt dann für alle
// Tests im Projekt chromium (storageState in playwright.config.ts). Das Konto legt der E2E-Stack
// an (docker/e2e.sh, E2E_USERNAME und E2E_PASSWORD aus docker/e2e.env). Ohne die beiden Werte
// laufen die Tests ohne Anmeldung, etwa gegen einen Stack ohne Sitzungspflicht.

setup('anmelden', async ({ request }) => {
  const username = process.env['E2E_USERNAME'];
  const password = process.env['E2E_PASSWORD'];
  if (username && password) {
    const response = await request.post('/api/v1/auth/login', { data: { username, password } });
    expect(response.status(), 'Anmeldung im E2E-Stack').toBe(204);
  }
  await request.storageState({ path: STORAGE_STATE });
});
