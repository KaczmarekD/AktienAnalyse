import { provideHttpClient, withFetch } from '@angular/common/http';
import {
  ApplicationConfig,
  inject,
  LOCALE_ID,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';

import { client } from './api/client.gen';
import { provideHeyApiClient } from './api/client/client.gen';
import { routes } from './app.routes';
import { RealtimeService } from './shared/realtime/realtime.service';
import './locale';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    // Relative Pfade (/api/v1/...): lokal leitet ng serve sie ans web-api weiter, auf der NAS
    // nginx (P3.6). Deshalb gibt es keine API-URL im Build und kein CORS.
    provideHttpClient(withFetch()),
    provideHeyApiClient(client),
    // Zahlen und Datum im deutschen Format (0,78; 12,3 %; 30.10.2026)
    { provide: LOCALE_ID, useValue: 'de-DE' },
    // P4.6: WebSocket beim Start; Aenderungen melden sich, REST liefert den Zustand
    provideAppInitializer(() => inject(RealtimeService).start()),
  ],
};
