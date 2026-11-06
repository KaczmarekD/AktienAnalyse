import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { RouterLink } from '@angular/router';

import { getReportResource, getRunResource } from '../api/@angular/common.gen';
import { optionalNumber } from '../shared/api-error';
import { DayTimePipe, OrDashPipe } from '../shared/format';
import { loaded, loadError } from '../shared/resource';
import { BackLink } from '../shared/ui/back-link';
import { PageHeader } from '../shared/ui/page-header';
import { RunStatus } from '../shared/ui/run-status';

/** Ein Lauf mit Zaehlern, Fehler und der gerenderten Mail (/runs/:runId). */
@Component({
  selector: 'app-run-detail-page',
  imports: [BackLink, DayTimePipe, OrDashPipe, PageHeader, RouterLink, RunStatus],
  templateUrl: './run-detail-page.html',
  styleUrl: './run-detail-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunDetailPage {
  readonly runId = input<number | undefined, unknown>(undefined, { transform: optionalNumber });

  private readonly sanitizer = inject(DomSanitizer);

  private readonly runResource = getRunResource(() => {
    const id = this.runId();
    return id === undefined ? undefined : { path: { run_id: id } };
  });
  protected readonly run = computed(() => loaded(this.runResource));
  protected readonly error = computed(() => loadError(this.runResource, 'Lauf nicht gefunden.'));

  private readonly reportResource = getReportResource(() => {
    const id = this.run()?.report_id;
    return id == null ? undefined : { path: { report_id: id } };
  });
  protected readonly report = computed(() => loaded(this.reportResource));
  // Die Mail stammt aus dem eigenen Report-Template. Sie laeuft in einem iframe mit leerem
  // sandbox-Attribut: keine Skripte, kein Zugriff auf die Seite. Deshalb darf ihr eigenes CSS
  // bleiben, das der HTML-Sanitizer von Angular sonst entfernen wuerde.
  protected readonly mail = computed<SafeHtml | undefined>(() => {
    const report = this.report();
    return report ? this.sanitizer.bypassSecurityTrustHtml(report.html) : undefined;
  });
}
