import { ChangeDetectionStrategy, Component, computed } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatTooltipModule } from '@angular/material/tooltip';
import { RouterLink } from '@angular/router';

import { listProfilesResource } from '../api/@angular/common.gen';
import { DayPipe } from '../shared/format';
import { CONTROLS } from '../shared/glossary/controls';
import { ENTRIES, termTip } from '../shared/glossary/glossary';
import { loaded, loadError } from '../shared/resource';
import { AppIcon } from '../shared/ui/icon';
import { PageHeader } from '../shared/ui/page-header';
import { AppSection } from '../shared/ui/section';
import { AppState } from '../shared/ui/state';

/**
 * Die Scoring-Profile (/profiles, ADR-0009, Track G, G7): je Profil eine Karte mit der aktiven
 * Version und, wenn sie abweicht, der neuesten. „Bearbeiten“ führt in den Editor.
 */
@Component({
  selector: 'app-profiles-page',
  imports: [
    AppIcon,
    AppSection,
    AppState,
    DayPipe,
    MatButtonModule,
    MatTooltipModule,
    PageHeader,
    RouterLink,
  ],
  templateUrl: './profiles-page.html',
  styleUrl: './profiles-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfilesPage {
  private readonly resource = listProfilesResource(() => ({}));
  protected readonly controls = CONTROLS;
  protected readonly activeTip = termTip(ENTRIES.active);

  protected readonly profiles = computed(() => loaded(this.resource));
  protected readonly error = computed(() => loadError(this.resource, 'Keine Profile gefunden.'));
}
