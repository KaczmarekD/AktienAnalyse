import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatToolbarModule } from '@angular/material/toolbar';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { RealtimeService } from './shared/realtime/realtime.service';

/** App-Huelle: Toolbar mit Navigation und Verbindungsstatus, darunter die Ansicht der Route. */
@Component({
  selector: 'app-root',
  imports: [MatButtonModule, MatToolbarModule, RouterLink, RouterLinkActive, RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {
  /** P4.6: "offline" in der Toolbar, solange der WebSocket getrennt ist. */
  protected readonly realtime = inject(RealtimeService);
}
