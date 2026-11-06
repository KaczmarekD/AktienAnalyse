import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { AppIcon } from './icon';

/** Rückmeldung nach einer Aktion; error für eine gescheiterte. */
export interface Notice {
  text: string;
  error?: boolean;
}

/**
 * Rückmeldung nach einer Aktion: Erfolg als Status mit Häkchen, Fehler als Alarm mit Fehler-Icon
 * auf gedämpfter Fläche (Spec, „Bedeutung ohne Farbe“). Ohne Rückmeldung zeigt sie nichts.
 */
@Component({
  selector: 'app-notice',
  imports: [AppIcon],
  template: `
    @if (notice(); as notice) {
      <p
        class="notice"
        [class.notice--error]="notice.error"
        [attr.role]="notice.error ? 'alert' : 'status'"
      >
        <app-icon [name]="notice.error ? 'error' : 'check_circle'" />
        {{ notice.text }}
      </p>
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NoticeBox {
  readonly notice = input<Notice | undefined>();
}
