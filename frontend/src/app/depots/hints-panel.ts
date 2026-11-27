import { NgTemplateOutlet } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  input,
  LOCALE_ID,
  signal,
} from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';

import { depotHintsResource } from '../api/@angular/common.gen';
import { acknowledgeHint } from '../api/sdk.gen';
import type { DepotHint } from '../api/types.gen';
import { DayPipe, DayTimePipe } from '../shared/format';
import { loaded, loadError } from '../shared/resource';
import { AppIcon, IconName } from '../shared/ui/icon';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { AppSection } from '../shared/ui/section';
import { AppState } from '../shared/ui/state';
import { HINT_STATUS, HINTS, SEVERITY } from './controls';
import { HintParamsDialog, SettingsDialogData } from './hint-params-dialog';
import { formatMeasure, sortHints, subjectLabel } from './hints';
import { TargetDialog } from './target-dialog';

const SEVERITY_ICON: Record<DepotHint['severity'], IconName> = {
  critical: 'error',
  warning: 'warning',
  info: 'info',
};

/**
 * Hinweise eines Depots (D5.4, HIN-01 bis 05): offene Hinweise nach Schwere mit Messwert,
 * Schwelle, Datenstand, Begründung und Ansatzpunkt, Status gegen den vorigen Stand, „zur
 * Kenntnis genommen“ und die erledigten. Dazu die Dialoge „Schwellen“ und „Zielallokation“ und der
 * Disclaimer: Hinweise sind Beobachtungen, keine Anlageempfehlung. Lädt neu, sobald sich der
 * Depotstand ändert oder eine Einstellung gespeichert ist.
 */
@Component({
  selector: 'app-hints-panel',
  imports: [
    AppIcon,
    AppSection,
    AppState,
    DayPipe,
    DayTimePipe,
    MatButtonModule,
    MatTooltipModule,
    NgTemplateOutlet,
    NoticeBox,
  ],
  templateUrl: './hints-panel.html',
  styleUrl: './hints-panel.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HintsPanel {
  readonly depotId = input.required<number>();
  /** Depotstand: ändert er sich, lädt die Liste neu. */
  readonly version = input(0);
  /** Namen der Wertpapiere im Depot je ISIN. */
  readonly names = input<Record<string, string>>({});
  /** Archiviert: nichts zur Kenntnis nehmen, nichts einstellen. */
  readonly readonly = input(false);

  private readonly dialog = inject(MatDialog);
  private readonly locale = inject(LOCALE_ID);
  protected readonly tips = HINTS;
  protected readonly statuses = HINT_STATUS;

  private readonly resource = depotHintsResource(() => {
    this.version();
    return { path: { depot_id: this.depotId() } };
  });

  protected readonly result = computed(() => loaded(this.resource));
  protected readonly error = computed(() => loadError(this.resource, 'Depot nicht gefunden.'));
  private readonly all = computed(() => this.result()?.hints ?? []);
  protected readonly open = computed(() =>
    sortHints(this.all().filter((hint) => hint.status !== 'resolved' && !hint.acknowledged)),
  );
  protected readonly acknowledged = computed(() =>
    sortHints(this.all().filter((hint) => hint.status !== 'resolved' && hint.acknowledged)),
  );
  protected readonly resolved = computed(() =>
    sortHints(this.all().filter((hint) => hint.status === 'resolved')),
  );

  protected readonly showAcknowledged = signal(false);
  /** Schlüssel des Hinweises, der gerade zur Kenntnis genommen wird */
  protected readonly busy = signal<string | undefined>(undefined);
  protected readonly notice = signal<Notice | undefined>(undefined);

  /** Beschriftung, Tooltip und Icon der Schwere (typisiert, die Vorlage kennt den Typ nicht). */
  protected severity(hint: DepotHint): { label: string; tip: string; icon: IconName } {
    return { ...SEVERITY[hint.severity], icon: SEVERITY_ICON[hint.severity] };
  }

  protected subject(hint: DepotHint): string {
    return subjectLabel(hint, this.names());
  }

  protected measure(hint: DepotHint, value: number | null): string {
    return formatMeasure(hint.rule, value, this.locale);
  }

  protected async acknowledge(hint: DepotHint): Promise<void> {
    if (this.busy() || this.readonly()) {
      return;
    }
    this.busy.set(hint.key);
    this.notice.set(undefined);
    const result = await acknowledgeHint({
      path: { depot_id: this.depotId(), key: hint.key },
    });
    this.busy.set(undefined);
    if (result.data) {
      this.resource.set(result.data);
      const subject = this.subject(hint);
      this.notice.set({
        text: `Zur Kenntnis genommen: ${hint.title}${subject ? ` (${subject})` : ''}.`,
      });
      return;
    }
    const status = result.response?.status;
    if (status === 404) {
      this.notice.set({ text: 'Den Hinweis gibt es nicht mehr. Die Liste ist neu geladen.' });
      this.resource.reload();
      return;
    }
    this.notice.set({
      text:
        status === 409
          ? 'Das Depot ist archiviert. Erst wiederherstellen.'
          : 'Das hat nicht geklappt. Ist der Server erreichbar?',
      error: true,
    });
  }

  protected openThresholds(): void {
    this.openSettings(HintParamsDialog, 'Schwellen gespeichert, die Hinweise sind neu gerechnet.');
  }

  protected openTarget(): void {
    this.openSettings(TargetDialog, 'Zielallokation gespeichert, die Hinweise sind neu gerechnet.');
  }

  private openSettings(
    component: typeof HintParamsDialog | typeof TargetDialog,
    done: string,
  ): void {
    const data: SettingsDialogData = { depotId: this.depotId() };
    this.dialog
      .open<unknown, SettingsDialogData, boolean>(component, { data, maxWidth: '48rem' })
      .afterClosed()
      .subscribe((saved) => {
        if (saved) {
          this.notice.set({ text: done });
          this.resource.reload();
        }
      });
  }
}
