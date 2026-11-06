import { provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';
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
import { authInterceptor, jsonWritesInterceptor } from './shared/auth/auth.interceptor';
import { AuthStore } from './shared/auth/auth.store';
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
    // nginx (P3.6). Deshalb gibt es keine API-URL im Build und kein CORS. D1.4: Schreiben nur
    // als JSON, ein 401 beendet die Sitzung im UI.
    provideHttpClient(withFetch(), withInterceptors([jsonWritesInterceptor, authInterceptor])),
    provideHeyApiClient(client),
    // Zahlen und Datum im deutschen Format (0,78; 12,3 %; 30.10.2026)
    { provide: LOCALE_ID, useValue: 'de-DE' },
    // D1.4: fragt beim Start, wer angemeldet ist; startet den WebSocket (P4.6), sobald er darf
    provideAppInitializer(() => void inject(AuthStore)),
    { provide: MAT_TOOLTIP_DEFAULT_OPTIONS, useValue: TOOLTIPS },
  ],
};
