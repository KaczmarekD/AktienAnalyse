import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/** Rückmeldung nach einer Aktion; error für eine gescheiterte. */
export interface Notice {
  text: string;
  error?: boolean;
}

/**
 * Rückmeldung nach einer Aktion: Erfolg als Status, Fehler als Alarm (rot). Ohne Rückmeldung
 * zeigt sie nichts.
 */
@Component({
  selector: 'app-notice',
  template: `
    @if (notice(); as notice) {
      <p
        class="notice"
        [class.notice--error]="notice.error"
        [attr.role]="notice.error ? 'alert' : 'status'"
      >
        {{ notice.text }}
      </p>
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NoticeBox {
  readonly notice = input<Notice | undefined>();
}
