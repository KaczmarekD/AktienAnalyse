import { ChangeDetectionStrategy, Component, computed } from '@angular/core';
import { RouterLink } from '@angular/router';

import { listProfilesResource } from '../api/@angular/common.gen';
import { errorMessage } from '../shared/api-error';
import { PageHeader } from '../shared/ui/page-header';

/** Die Scoring-Profile (ADR-0009) mit neuester Version; das aktive ist markiert. */
@Component({
  selector: 'app-profiles-page',
  imports: [PageHeader, RouterLink],
  templateUrl: './profiles-page.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfilesPage {
  private readonly resource = listProfilesResource(() => ({}));

  protected readonly profiles = computed(() =>
    this.resource.hasValue() ? this.resource.value() : undefined,
  );
  protected readonly error = computed(() => {
    const error = this.resource.error();
    return error ? errorMessage(error, 'Keine Profile gefunden.') : undefined;
  });
}
