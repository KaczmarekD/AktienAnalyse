import AxeBuilder from '@axe-core/playwright';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// Abschluss der Neugestaltung (Track G, G8, docs/architecture/ui-neugestaltung.md, Test 5):
// Tooltips bei Hover und Tastaturfokus, die Seite „Begriffe“ über die App-Leiste und axe ohne
// Befund der Stufen „serious“ und „critical“, hell und dunkel. Die Konsole bleibt leer.

interface RankingRow {
  symbol: string;
  passed_filter: boolean;
}

interface RunSummary {
  id: number;
}

interface ProfileSummary {
  id: number;
}

async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  expect(response.ok(), `${path}: ${response.status()}`).toBe(true);
  return (await response.json()) as T;
}

let errors: string[] = [];

test.beforeEach(({ page }) => {
  errors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') {
      errors.push(message.text());
    }
  });
  page.on('pageerror', (error) => errors.push(error.message));
});

test.afterEach(() => {
  expect(errors, 'Fehler in der Konsole').toEqual([]);
});

/** Ein Titel mit Kennzahlen: der erste bewertete im jüngsten Ranking. */
async function rankedSymbol(request: APIRequestContext): Promise<string> {
  const ranking = await getJson<{ rows: RankingRow[] }>(request, '/api/v1/ranking/latest');
  const row = ranking.rows.find((candidate) => candidate.passed_filter);
  if (row === undefined) {
    throw new Error('kein bewerteter Titel');
  }
  return row.symbol;
}

const tooltip = (page: Page) => page.locator('.mat-mdc-tooltip-surface');

test('Tooltip erscheint bei Hover und beim Tastaturfokus auf „EV/EBIT“', async ({ page }) => {
  const request = page.request;
  const symbol = await rankedSymbol(request);
  await page.goto(`/instruments/${encodeURIComponent(symbol)}`);
  // Der fokussierbare Teil von app-term ist das innere span mit dem Tooltip
  const term = page.locator('[data-figure="ev_ebit"] app-term .term');
  await expect(term).toHaveText('EV/EBIT');

  await term.hover();
  await expect(tooltip(page)).toContainText('Unternehmenswert');

  // Weg mit der Maus, dann per Tab zurück: Der Fokus kommt von der Tastatur
  await page.mouse.move(0, 0);
  await expect(tooltip(page)).toHaveCount(0);
  await term.focus();
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Tab');
  await expect(term).toBeFocused();
  await expect(tooltip(page)).toContainText('Unternehmenswert');
});

test('Die Seite „Begriffe“ ist über die App-Leiste erreichbar', async ({ page }) => {
  await page.goto('/ranking');
  await page.getByRole('link', { name: 'Begriffe' }).click();
  await expect(page).toHaveURL('/glossary');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Begriffe');
  await expect(page.locator('#roic')).toBeVisible();
});

/** Alle Ansichten mit Daten aus derselben API, die das UI nutzt. */
async function pages(request: APIRequestContext): Promise<string[]> {
  const symbol = await rankedSymbol(request);
  const runs = await getJson<RunSummary[]>(request, '/api/v1/runs');
  const profiles = await getJson<ProfileSummary[]>(request, '/api/v1/scoring/profiles');
  return [
    '/ranking',
    `/instruments/${encodeURIComponent(symbol)}`,
    '/runs',
    ...runs.slice(0, 1).map((run) => `/runs/${run.id}`),
    '/profiles',
    ...profiles.slice(0, 1).map((profile) => `/profiles/${profile.id}`),
    '/glossary',
    // D1.4: angemeldet als Admin (auth.setup.ts); ohne Anmeldung führen beide zur Anmeldeseite
    '/account',
    '/admin/users',
  ];
}

for (const scheme of ['light', 'dark'] as const) {
  test(`axe findet nichts Ernstes (${scheme === 'light' ? 'hell' : 'dunkel'})`, async ({
    page,
  }) => {
    const request = page.request;
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: 'reduce' });
    const found: string[] = [];
    for (const path of await pages(request)) {
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      // Erst messen, wenn nichts mehr lädt
      await expect(page.locator('app-state [role="status"]')).toHaveCount(0);
      const result = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
        // Die Mail ist ein eigenes Dokument aus dem Report-Template, nicht Teil des UI
        .exclude('iframe')
        .analyze();
      for (const violation of result.violations) {
        if (violation.impact === 'serious' || violation.impact === 'critical') {
          const targets = violation.nodes.map((node) => node.target.join(' ')).slice(0, 3);
          found.push(`${path}: ${violation.id} (${violation.impact}) ${targets.join(', ')}`);
        }
      }
    }
    expect(found).toEqual([]);
  });
}
