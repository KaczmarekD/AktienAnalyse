import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { RouterLink } from '@angular/router';

import { getReportResource, getRunResource } from '../api/@angular/common.gen';
import { errorMessage, optionalNumber } from '../shared/api-error';
import { RunStatusPipe } from '../shared/format';

/** Ein Lauf mit Zaehlern, Fehler und der gerenderten Mail (/runs/:runId). */
@Component({
  selector: 'app-run-detail-page',
  imports: [DatePipe, RouterLink, RunStatusPipe],
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
  protected readonly run = computed(() =>
    this.runResource.hasValue() ? this.runResource.value() : undefined,
  );
  protected readonly error = computed(() => {
    const error = this.runResource.error();
    return error ? errorMessage(error, 'Lauf nicht gefunden.') : undefined;
  });

  private readonly reportResource = getReportResource(() => {
    const id = this.run()?.report_id;
    return id == null ? undefined : { path: { report_id: id } };
  });
  protected readonly report = computed(() =>
    this.reportResource.hasValue() ? this.reportResource.value() : undefined,
  );
  // Die Mail stammt aus dem eigenen Report-Template. Sie laeuft in einem iframe mit leerem
  // sandbox-Attribut: keine Skripte, kein Zugriff auf die Seite. Deshalb darf ihr eigenes CSS
  // bleiben, das der HTML-Sanitizer von Angular sonst entfernen wuerde.
  protected readonly mail = computed<SafeHtml | undefined>(() => {
    const report = this.report();
    return report ? this.sanitizer.bypassSecurityTrustHtml(report.html) : undefined;
  });
}
