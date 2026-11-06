import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatTooltipModule } from '@angular/material/tooltip';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { RouterLink } from '@angular/router';

import { getReportResource, getRunResource } from '../api/@angular/common.gen';
import { optionalNumber } from '../shared/api-error';
import { DayTimePipe, DurationPipe, OrDashPipe, RunKindPipe } from '../shared/format';
import { CONTROLS } from '../shared/glossary/controls';
import { ENTRIES, termTip } from '../shared/glossary/glossary';
import { loaded, loadError } from '../shared/resource';
import { BackLink } from '../shared/ui/back-link';
import { AppIcon } from '../shared/ui/icon';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { PageHeader } from '../shared/ui/page-header';
import { RunStatus } from '../shared/ui/run-status';
import { AppSection } from '../shared/ui/section';
import { AppState } from '../shared/ui/state';
import { Term } from '../shared/ui/term';
import { firstLine, scoredText } from './run-text';

/**
 * Ein Lauf (/runs/:runId, Track G, G6): Überblick, bei einem Fehler dessen erste Zeile, die
 * technischen Angaben eingeklappt, darunter die Mail, wie sie aussah.
 */
@Component({
  selector: 'app-run-detail-page',
  imports: [
    AppIcon,
    AppSection,
    AppState,
    BackLink,
    DayTimePipe,
    DurationPipe,
    MatButtonModule,
    MatExpansionModule,
    MatTooltipModule,
    NoticeBox,
    OrDashPipe,
    PageHeader,
    RouterLink,
    RunKindPipe,
    RunStatus,
    Term,
  ],
  templateUrl: './run-detail-page.html',
  styleUrl: './run-detail-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunDetailPage {
  readonly runId = input<number | undefined, unknown>(undefined, { transform: optionalNumber });

  private readonly sanitizer = inject(DomSanitizer);
  protected readonly controls = CONTROLS;
  protected readonly dryRunTip = termTip(ENTRIES.dry_run);

  private readonly runResource = getRunResource(() => {
    const id = this.runId();
    return id === undefined ? undefined : { path: { run_id: id } };
  });
  protected readonly run = computed(() => loaded(this.runResource));
  protected readonly error = computed(() => loadError(this.runResource, 'Lauf nicht gefunden.'));

  protected readonly scored = computed(() => {
    const run = this.run();
    return run ? scoredText(run) : '';
  });
  /** Die erste Zeile des Fehlers über den Details; die ganze Meldung steht eingeklappt darunter. */
  protected readonly failure = computed<Notice | undefined>(() => {
    const line = firstLine(this.run()?.error ?? null);
    return line ? { text: `Fehler: ${line}`, error: true } : undefined;
  });

  private readonly reportResource = getReportResource(() => {
    const id = this.run()?.report_id;
    return id == null ? undefined : { path: { report_id: id } };
  });
  protected readonly report = computed(() => loaded(this.reportResource));
  // Die Mail stammt aus dem eigenen Report-Template. Sie läuft in einem iframe mit leerem
  // sandbox-Attribut: keine Skripte, kein Zugriff auf die Seite. Deshalb darf ihr eigenes CSS
  // bleiben, das der HTML-Sanitizer von Angular sonst entfernen würde.
  protected readonly mail = computed<SafeHtml | undefined>(() => {
    const report = this.report();
    return report ? this.sanitizer.bypassSecurityTrustHtml(report.html) : undefined;
  });
}
