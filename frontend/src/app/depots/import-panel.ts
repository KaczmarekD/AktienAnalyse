import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';

import { importHoldings, previewImport } from '../api/sdk.gen';
import type { Holdings, ImportEntry, ImportPreview } from '../api/types.gen';
import { DecPipe } from '../shared/format';
import { ENTRIES, termTip } from '../shared/glossary/glossary';
import { AppIcon } from '../shared/ui/icon';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { AppSection } from '../shared/ui/section';
import { Term } from '../shared/ui/term';
import { DEPOT_CONTROLS, IMPORT_STATUS } from './controls';

/** Wie portfolio (D3.5): höchstens 640 KiB. */
export const MAX_FILE_BYTES = 640 * 1024;

/** Inhalt einer Datei als Base64, ohne den Kopf einer data:-URL. */
export async function fileBase64(file: Blob): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = '';
  const chunk = 0x8000;
  for (let start = 0; start < bytes.length; start += chunk) {
    binary += String.fromCharCode(...bytes.subarray(start, start + chunk));
  }
  return btoa(binary);
}

/** Meldung einer abgelehnten Anfrage (422, 413: Text des Servers). */
function detailOf(error: unknown): string | undefined {
  const detail = (error as { detail?: unknown } | null)?.detail;
  return typeof detail === 'string' ? detail : undefined;
}

/**
 * Datei im eigenen Format (D3.6, DEP-05): Download der Positionen als CSV und Import mit
 * Abgleich. Eine gewählte Datei zeigt je ISIN neu, geändert, gleich oder entfällt und die Zeilen,
 * die nicht erkannt wurden. „Übernehmen“ geht nur ohne abgelehnte Zeilen, mit `If-Match` auf den
 * Depotstand des Abgleichs.
 */
@Component({
  selector: 'app-import-panel',
  imports: [AppIcon, AppSection, DecPipe, MatButtonModule, MatTooltipModule, NoticeBox, Term],
  template: `
    <app-section heading="Datei" data-import>
      <p class="hint">
        Eigenes Format: <code>isin;menge;einstand;notiz</code>, Trennzeichen Semikolon,
        Dezimalkomma. Die Kasse steht nicht in der Datei.
      </p>
      <div class="cluster">
        <a
          matButton="outlined"
          data-action="csv"
          download
          [href]="csvUrl()"
          [matTooltip]="controls.csv"
          ><app-icon name="download" />Als CSV herunterladen</a
        >
        @if (!readonly()) {
          <button
            matButton="outlined"
            type="button"
            data-action="choose"
            [disabled]="busy()"
            [matTooltip]="controls.chooseFile"
            (click)="picker.click()"
          >
            <app-icon name="upload" />
            Datei wählen
          </button>
          <input
            #picker
            class="picker"
            type="file"
            accept=".csv,text/csv,text/plain"
            data-field="file"
            (change)="choose($event)"
          />
        }
      </div>

      @if (preview(); as preview) {
        <p class="meta" data-summary>
          {{ filename() }}: {{ count('new') }} neu, {{ count('changed') }} geändert,
          {{ count('unchanged') }} gleich, {{ count('removed') }} entfällt,
          {{ preview.rejected.length }} nicht erkannt
        </p>
        @if (preview.rejected.length > 0) {
          <ul class="divided-list rejected" data-rejected>
            @for (row of preview.rejected; track row.line) {
              <li>Zeile {{ row.line }}: {{ row.reason }}</li>
            }
          </ul>
        }
        @if (preview.entries.length > 0) {
          <table class="data-table" data-entries>
            <thead>
              <tr>
                <th scope="col"><app-term key="isin" /></th>
                <th scope="col"><span tabindex="0" [matTooltip]="statusTip">Abgleich</span></th>
                <th scope="col" class="num">
                  <span tabindex="0" [matTooltip]="beforeTip">vorher</span>
                </th>
                <th scope="col" class="num">
                  <span tabindex="0" [matTooltip]="afterTip">nachher</span>
                </th>
              </tr>
            </thead>
            <tbody>
              @for (entry of preview.entries; track entry.isin) {
                <tr [attr.data-entry]="entry.isin" [attr.data-status]="entry.status">
                  <td>
                    {{ entry.isin }}
                    @if (entry.pending) {
                      <span class="badge badge--muted" tabindex="0" [matTooltip]="pendingTip"
                        >wird geprüft</span
                      >
                    }
                  </td>
                  <td>
                    <span class="badge" tabindex="0" [matTooltip]="statuses[entry.status].tip">{{
                      statuses[entry.status].label
                    }}</span>
                  </td>
                  <td class="num">{{ entry.before?.quantity | dec }}</td>
                  <td class="num">{{ entry.after?.quantity | dec }}</td>
                </tr>
              }
            </tbody>
          </table>
        }
        <div class="cluster actions">
          <button
            matButton="filled"
            type="button"
            data-action="apply"
            [disabled]="busy() || preview.rejected.length > 0"
            [matTooltip]="preview.rejected.length > 0 ? controls.applyBlocked : controls.apply"
            (click)="apply()"
          >
            {{ busy() ? 'Übernimmt …' : 'Übernehmen' }}
          </button>
          <button
            matButton
            type="button"
            data-action="cancel-import"
            [matTooltip]="controls.cancelImport"
            (click)="reset()"
          >
            Verwerfen
          </button>
        </div>
      }
      <app-notice [notice]="notice()" />
    </app-section>
  `,
  styles: `
    .picker {
      display: none;
    }

    .rejected {
      margin: var(--va-space-sm) 0;
    }

    .actions {
      margin-top: var(--va-space-md);
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ImportPanel {
  readonly depotId = input.required<number>();
  /** Archiviert: nur der Download */
  readonly readonly = input(false);
  readonly imported = output<Holdings>();

  protected readonly controls = DEPOT_CONTROLS;
  protected readonly statuses = IMPORT_STATUS;
  protected readonly statusTip = 'Was die Datei mit der Position macht.';
  protected readonly beforeTip = 'Menge im aktuellen Depotstand.';
  protected readonly afterTip = 'Menge laut Datei.';
  protected readonly pendingTip = termTip(ENTRIES.pending);

  protected readonly csvUrl = computed(() => `/api/v1/depots/${this.depotId()}/holdings/csv`);
  protected readonly preview = signal<ImportPreview | undefined>(undefined);
  protected readonly filename = signal('');
  protected readonly busy = signal(false);
  protected readonly notice = signal<Notice | undefined>(undefined);
  private content = '';

  protected count(status: ImportEntry['status']): number {
    return this.preview()?.entries.filter((entry) => entry.status === status).length ?? 0;
  }

  protected async choose(event: Event): Promise<void> {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = ''; // dieselbe Datei nach einer Korrektur noch einmal wählen
    if (!file) {
      return;
    }
    this.reset();
    if (file.size > MAX_FILE_BYTES) {
      this.notice.set({ text: 'Die Datei ist größer als 640 KiB.', error: true });
      return;
    }
    this.busy.set(true);
    this.content = await fileBase64(file);
    this.filename.set(file.name);
    const result = await previewImport({
      path: { depot_id: this.depotId() },
      body: { filename: file.name, content_base64: this.content },
    });
    this.busy.set(false);
    if (result.data) {
      this.preview.set(result.data);
      return;
    }
    const status = result.response?.status;
    this.notice.set({
      text:
        status === 422 || status === 413 || status === 409
          ? (detailOf(result.error) ?? 'Die Datei ist nicht lesbar.')
          : 'Die Datei ließ sich nicht prüfen. Ist der Server erreichbar?',
      error: true,
    });
  }

  protected async apply(): Promise<void> {
    const preview = this.preview();
    if (!preview || preview.rejected.length > 0 || this.busy()) {
      return;
    }
    this.busy.set(true);
    const result = await importHoldings({
      path: { depot_id: this.depotId() },
      body: { filename: this.filename(), content_base64: this.content },
      headers: { 'if-match': `"${preview.base_version}"` },
    });
    this.busy.set(false);
    if (result.data) {
      const version = result.data.version;
      this.reset();
      this.notice.set({ text: `Datei übernommen: Depotstand ${version}.` });
      this.imported.emit(result.data);
      return;
    }
    const status = result.response?.status;
    this.notice.set({
      text:
        status === 409
          ? 'Der Depotstand hat sich inzwischen geändert. Wähle die Datei noch einmal, um neu abzugleichen.'
          : status === 422
            ? (detailOf(result.error) ?? 'Die Datei passt nicht.')
            : 'Übernehmen hat nicht geklappt. Ist der Server erreichbar?',
      error: true,
    });
  }

  protected reset(): void {
    this.preview.set(undefined);
    this.filename.set('');
    this.notice.set(undefined);
    this.content = '';
  }
}
