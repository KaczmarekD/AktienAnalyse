import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatTooltipModule } from '@angular/material/tooltip';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import { healthResource } from './api/@angular/common.gen';
import { RealtimeService } from './shared/realtime/realtime.service';
import { loaded } from './shared/resource';
import { AppIcon, IconName } from './shared/ui/icon';

interface NavItem {
  path: string;
  label: string;
  icon: IconName;
  tip: string;
  /** Weitere Routen, die zu diesem Bereich gehören, z. B. das Titel-Detail zum Ranking. */
  also: readonly string[];
}

// Texte aus dem Katalog der Spec (App-Leiste); mit G2 ziehen sie ins Glossar
const NAV: readonly NavItem[] = [
  {
    path: '/ranking',
    label: 'Ranking',
    icon: 'leaderboard',
    tip: 'Alle Titel nach Composite, mit Filtern und Kennzahlen.',
    also: ['/instruments'],
  },
  {
    path: '/runs',
    label: 'Läufe',
    icon: 'history',
    tip: 'Verlauf aller Läufe, neuen Lauf starten, Mails ansehen.',
    also: [],
  },
  {
    path: '/profiles',
    label: 'Profile',
    icon: 'tune',
    tip: 'Gewichte und Faktoren des Scorings ansehen und ändern.',
    also: [],
  },
];

const OFFLINE_TIP =
  'Keine Live-Verbindung zum Server. Die Seite aktualisiert sich erst wieder, wenn er erreichbar ist.';

function belongsTo(url: string, path: string): boolean {
  return url === path || url.startsWith(`${path}/`) || url.startsWith(`${path}?`);
}

/**
 * App-Hülle (Spec, App-Hülle): App-Leiste mit Marke, Navigation und Verbindungs-Chip (P4.6),
 * darunter die Ansicht der Route, unten der Hinweis und die Programmversion.
 */
@Component({
  selector: 'app-root',
  imports: [AppIcon, MatTooltipModule, RouterLink, RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {
  protected readonly realtime = inject(RealtimeService);
  protected readonly nav = NAV;
  protected readonly offlineTip = OFFLINE_TIP;

  private readonly router = inject(Router);
  private readonly url = toSignal(
    this.router.events.pipe(
      filter((event) => event instanceof NavigationEnd),
      map((event) => event.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );
  /** Der Bereich der aktuellen Route; er ist in der Navigation markiert. */
  protected readonly section = computed(() => {
    const url = this.url();
    return NAV.find((item) => [item.path, ...item.also].some((path) => belongsTo(url, path)))?.path;
  });

  private readonly health = healthResource(() => ({}));
  protected readonly version = computed(() => loaded(this.health)?.version);
}
