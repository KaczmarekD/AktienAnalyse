// Ein Lauf mit seiner Mail (P3.7).
import { TestBed } from '@angular/core/testing';

import { apiTestingProviders, query, respond, text } from '../testing/api';
import { REPORT, run } from '../testing/fixtures';
import { RunDetailPage } from './run-detail-page';

function render(id: number) {
  TestBed.configureTestingModule({ providers: apiTestingProviders() });
  const fixture = TestBed.createComponent(RunDetailPage);
  fixture.componentRef.setInput('runId', String(id));
  return fixture;
}

describe('RunDetailPage', () => {
  it('shows status, counts and the error of a failed run', async () => {
    const fixture = render(3);
    await respond(
      fixture,
      '/api/v1/runs/3',
      run({
        id: 3,
        status: 'failed',
        exit_code: 1,
        error: 'yfinance antwortet nicht',
        report_id: null,
      }),
    );
    const content = text(fixture);
    expect(content).toContain('Lauf 3');
    expect(content).toContain('fehlgeschlagen');
    expect(content).toContain('yfinance antwortet nicht');
  });

  it('shows the mail in a sandboxed frame and links ranking and CSV', async () => {
    const fixture = render(1);
    await respond(fixture, '/api/v1/runs/1', run({ id: 1 }));
    await respond(fixture, '/api/v1/reports/5', REPORT);
    const frame = query<HTMLIFrameElement>(fixture, 'iframe')[0];
    expect(frame.getAttribute('sandbox')).toBe('');
    expect(frame.getAttribute('srcdoc')).toContain('<h1>Top 20</h1>');
    expect(text(fixture)).toContain(REPORT.subject);
    const hrefs = query<HTMLAnchorElement>(fixture, 'a').map((a) => a.getAttribute('href'));
    expect(hrefs).toContain('/ranking/1');
    expect(hrefs).toContain('/api/v1/reports/5/csv');
  });

  it('says when the run does not exist', async () => {
    const fixture = render(999);
    await respond(fixture, '/api/v1/runs/999', { detail: 'Lauf nicht gefunden' }, 404);
    expect(text(fixture)).toContain('Lauf nicht gefunden');
  });
});
