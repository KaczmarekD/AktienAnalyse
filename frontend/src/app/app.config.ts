import { provideHttpClient, withFetch } from '@angular/common/http';
import {
  ApplicationConfig,
  inject,
  LOCALE_ID,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { MAT_TOOLTIP_DEFAULT_OPTIONS, MatTooltipDefaultOptions } from '@angular/material/tooltip';
import { provideRouter, withComponentInputBinding, withInMemoryScrolling } from '@angular/router';

import { client } from './api/client.gen';
import { provideHeyApiClient } from './api/client/client.gen';
import { routes } from './app.routes';
import { RealtimeService } from './shared/realtime/realtime.service';
import './locale';

// Tooltips (Spec, Tooltips und Begriffe): erscheinen bei Hover, Fokus und langem Drücken
const TOOLTIPS: MatTooltipDefaultOptions = {
  showDelay: 400,
  hideDelay: 0,
  touchendHideDelay: 2500,
  position: 'above',
};

// Formularfelder mit Rand setzen die Ansichten selbst (shared/ui/form-field.ts), damit das
// Formularfeld nicht ins Start-Bundle kommt.

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    // Anker wie /glossary#roic springen zum Begriff
    provideRouter(
      routes,
      withComponentInputBinding(),
      withInMemoryScrolling({ anchorScrolling: 'enabled', scrollPositionRestoration: 'enabled' }),
    ),
    // Relative Pfade (/api/v1/...): lokal leitet ng serve sie ans web-api weiter, auf der NAS
    // nginx (P3.6). Deshalb gibt es keine API-URL im Build und kein CORS.
    provideHttpClient(withFetch()),
    provideHeyApiClient(client),
    // Zahlen und Datum im deutschen Format (0,78; 12,3 %; 30.10.2026)
    { provide: LOCALE_ID, useValue: 'de-DE' },
    // P4.6: WebSocket beim Start; Aenderungen melden sich, REST liefert den Zustand
    provideAppInitializer(() => inject(RealtimeService).start()),
    { provide: MAT_TOOLTIP_DEFAULT_OPTIONS, useValue: TOOLTIPS },
  ],
};
