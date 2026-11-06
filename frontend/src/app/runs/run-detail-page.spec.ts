// Ein Lauf mit seiner Mail (P3.7, neu gestaltet mit Track G, G6).
import { TestBed } from '@angular/core/testing';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { REPORT, run } from '../testing/fixtures';
import { abbreviationsWithoutExplanation, controlsWithoutTooltip } from '../testing/tooltips';
import { RunDetailPage } from './run-detail-page';

function render(id: number) {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  const fixture = TestBed.createComponent(RunDetailPage);
  fixture.componentRef.setInput('runId', String(id));
  return fixture;
}

const FAILED = run({
  id: 3,
  status: 'failed',
  exit_code: 1,
  error: 'yfinance antwortet nicht\nTraceback (most recent call last):\n  File "yahoo.py"',
  report_id: null,
  scoring_run_id: null,
});

describe('RunDetailPage', () => {
  it('names the run with status and shows the first line of the error', async () => {
    const fixture = render(3);
    await respond(fixture, '/api/v1/runs/3', FAILED);
    const heading = query(fixture, 'h1')[0].textContent ?? '';
    expect(heading).toContain('Lauf #3');
    expect(heading).toContain('fehlgeschlagen');
    const alert = query(fixture, '[role="alert"]')[0]?.textContent ?? '';
    expect(alert).toContain('yfinance antwortet nicht');
    expect(alert).not.toContain('Traceback');
  });

  it('keeps exit code, version, numbers and the full error in the technical details', async () => {
    const fixture = render(3);
    await respond(fixture, '/api/v1/runs/3', FAILED);
    const details = query(fixture, 'mat-expansion-panel')[0];
    expect(details.textContent).toContain('Technische Details');
    expect(details.textContent).toContain('Exit-Code');
    expect(details.textContent).toContain('0.3.0');
    expect(details.textContent).toContain('Traceback (most recent call last)');
    // geschlossen, bis jemand hineinschaut
    expect(details.classList).not.toContain('mat-expanded');
  });

  it('gives an overview of start, end, duration, scored titles and kind', async () => {
    const fixture = render(1);
    await respond(fixture, '/api/v1/runs/1', run({ id: 1, force_refresh: true }));
    const overview = (query(fixture, '[data-section="overview"]')[0]?.textContent ?? '').replace(
      /\s+/g,
      ' ',
    );
    expect(overview).toContain('30.10.2026');
    expect(overview).toContain('5 min');
    expect(overview).toContain('88 von 90, 2 fehlgeschlagen');
    expect(overview).toContain('Abruf und Bewertung, neu abgerufen');
  });

  it('shows the mail in a sandboxed frame and links ranking and CSV', async () => {
    const fixture = render(1);
    await respond(fixture, '/api/v1/runs/1', run({ id: 1 }));
    await respond(fixture, '/api/v1/reports/5', REPORT);
    const frame = query<HTMLIFrameElement>(fixture, 'iframe')[0];
    expect(frame.getAttribute('sandbox')).toBe('');
    expect(frame.getAttribute('srcdoc')).toContain('<h1>Top 20</h1>');
    expect(query(fixture, '[data-subject]')[0].textContent?.trim()).toBe(REPORT.subject);
    const hrefs = query<HTMLAnchorElement>(fixture, 'a').map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('/ranking/1');
    expect(hrefs).toContain('/api/v1/reports/5/csv');
  });

  it('marks a dry run in the header', async () => {
    const fixture = render(1);
    await respond(fixture, '/api/v1/runs/1', run({ id: 1, dry_run: true }));
    expect(query(fixture, 'h1')[0].textContent).toContain('Probelauf');
  });

  it('says when the run does not exist', async () => {
    const fixture = render(999);
    await respond(fixture, '/api/v1/runs/999', { detail: 'Lauf nicht gefunden' }, 404);
    expect(text(fixture)).toContain('Lauf nicht gefunden');
  });

  it('explains every control, label and abbreviation (tests 1 and 2)', async () => {
    const fixture = render(1);
    await respond(fixture, '/api/v1/runs/1', run({ id: 1, dry_run: true }));
    await respond(fixture, '/api/v1/reports/5', REPORT);
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
  });
});
