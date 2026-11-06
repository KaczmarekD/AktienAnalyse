import { ChangeDetectionStrategy, Component, computed } from '@angular/core';
import { RouterLink } from '@angular/router';

import { listProfilesResource } from '../api/@angular/common.gen';
import { OrDashPipe } from '../shared/format';
import { loaded, loadError } from '../shared/resource';
import { PageHeader } from '../shared/ui/page-header';

/** Die Scoring-Profile (ADR-0009) mit neuester Version; das aktive ist markiert. */
@Component({
  selector: 'app-profiles-page',
  imports: [OrDashPipe, PageHeader, RouterLink],
  templateUrl: './profiles-page.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfilesPage {
  private readonly resource = listProfilesResource(() => ({}));

  protected readonly profiles = computed(() => loaded(this.resource));
  protected readonly error = computed(() => loadError(this.resource, 'Keine Profile gefunden.'));
}
