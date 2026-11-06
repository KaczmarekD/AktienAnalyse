import { defineConfig, devices } from '@playwright/test';

import { STORAGE_STATE } from './e2e/state';

// Browser-Test des UI (U5.3, docs/architecture/umgebungen.md) gegen einen laufenden Stack:
// docker/e2e.sh (make local-e2e, CI) oder der lokale Stack. Startet selbst keinen Server.
// Chromium liegt unter .local/playwright (make ui-e2e-install), nicht auf C:.
export default defineConfig({
  testDir: './e2e',
  forbidOnly: !!process.env['CI'],
  retries: 0,
  reporter: [['list']],
  outputDir: 'test-results',
  use: {
    baseURL: process.env['E2E_BASE_URL'] ?? 'http://127.0.0.1:18080',
    locale: 'de-DE',
    timezoneId: 'Europe/Berlin',
    // Aus: Die Aufzeichnung fuehrt Skripte in jedem Frame aus. Im abgeschotteten Mail-iframe
    // meldet Chrome das als Fehler in der Konsole, und die Tests verlangen eine leere Konsole.
    // Zum Debuggen: npx playwright test --trace on
    trace: 'off',
  },
  projects: [
    // D1.4: meldet sich einmal an (E2E_USERNAME, E2E_PASSWORD), die Tests nutzen das Cookie
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], storageState: STORAGE_STATE },
      dependencies: ['setup'],
    },
  ],
});
