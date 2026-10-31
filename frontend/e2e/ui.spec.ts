import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// Ranking, Titel und Läufe im echten Browser, mit dem web-api hinter nginx (U5.3).
// Die Erwartung kommt aus derselben API, die das UI nutzt. So läuft der Test mit Replay-Daten
// (make local-e2e) wie mit echten Daten (lokaler Stack). Die Werte selbst prüft tests/e2e.

interface RankingRow {
  rank: number | null;
  symbol: string;
  name: string | null;
  passed_filter: boolean;
}

interface RunSummary {
  id: number;
  finished_at: string | null;
  dry_run: boolean;
}

interface RunDetail extends RunSummary {
  report_id: number | null;
}

interface Report {
  subject: string;
}

async function getJson<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path);
  expect(response.ok(), `${path}: ${response.status()}`).toBe(true);
  return (await response.json()) as T;
}

// Fehler in der Konsole und Ausnahmen der Seite, auch Verstöße gegen die CSP
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

function dataRows(page: Page) {
  // Zeilen mit Zellen: ohne die Kopfzeile
  return page.getByRole('row').filter({ has: page.getByRole('cell') });
}

let errors: string[] = [];

test.beforeEach(({ page }) => {
  errors = collectErrors(page);
});

test.afterEach(() => {
  expect(errors, 'Fehler in der Konsole').toEqual([]);
});

test('Ranking zeigt die Titel in der Reihenfolge der API', async ({ page, request }) => {
  const ranking = await getJson<{ rows: RankingRow[] }>(request, '/api/v1/ranking/latest');
  const top = ranking.rows.filter((row) => row.rank !== null).slice(0, 5);
  expect(top.length).toBeGreaterThan(0);

  await page.goto('/');
  await expect(page).toHaveURL(/\/ranking$/);
  const rows = dataRows(page);
  for (const [i, row] of top.entries()) {
    await expect(rows.nth(i)).toContainText(row.symbol);
  }
});

test('Klick auf den Spitzenreiter öffnet das Titel-Detail', async ({ page, request }) => {
  const ranking = await getJson<{ rows: RankingRow[] }>(request, '/api/v1/ranking/latest');
  const [first] = ranking.rows;
  const title = first.name ?? first.symbol;

  await page.goto('/ranking');
  await dataRows(page).first().getByRole('link', { name: title }).click();
  await expect(page).toHaveURL(`/instruments/${encodeURIComponent(first.symbol)}`);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(title);
  await expect(page.getByRole('heading', { name: 'Kennzahlen' })).toBeVisible();
});

test('Lauf-Detail zeigt die Mail abgeschottet im iframe', async ({ page, request }) => {
  const runs = await getJson<RunSummary[]>(request, '/api/v1/runs');
  const sent = runs.find((run) => run.finished_at !== null && !run.dry_run);
  if (sent === undefined) {
    throw new Error('kein abgeschlossener Lauf ohne Dry-Run');
  }
  const run = await getJson<RunDetail>(request, `/api/v1/runs/${sent.id}`);
  expect(run.report_id).not.toBeNull();
  const report = await getJson<Report>(request, `/api/v1/reports/${run.report_id}`);

  await page.goto('/runs');
  await page.getByRole('link', { name: `#${run.id}`, exact: true }).click();
  await expect(page).toHaveURL(`/runs/${run.id}`);
  await expect(page.getByRole('heading', { level: 1 })).toContainText(`Lauf ${run.id}`);
  await expect(page.getByText(report.subject, { exact: true })).toBeVisible();

  const mail = page.locator('iframe[title="Mail des Laufs"]');
  // Leeres sandbox: keine Skripte, kein Zugriff auf die Seite
  await expect(mail).toHaveAttribute('sandbox', '');
  await expect(
    page.frameLocator('iframe[title="Mail des Laufs"]').locator('table').first(),
  ).toBeVisible();
});
