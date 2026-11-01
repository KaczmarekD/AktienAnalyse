import { ChangeDetectionStrategy, Component, computed } from '@angular/core';
import { RouterLink } from '@angular/router';

import { listProfilesResource } from '../api/@angular/common.gen';
import { errorMessage } from '../shared/api-error';

/** Die Scoring-Profile (ADR-0009) mit neuester Version; das aktive ist markiert. */
@Component({
  selector: 'app-profiles-page',
  imports: [RouterLink],
  templateUrl: './profiles-page.html',
  styleUrl: './profiles-page.scss',
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
