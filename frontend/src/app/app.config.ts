import { provideHttpClient, withFetch } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';

import { client } from './api/client.gen';
import { provideHeyApiClient } from './api/client/client.gen';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    // Relative Pfade (/api/v1/...): lokal leitet ng serve sie ans web-api weiter, auf der NAS
    // nginx (P3.6). Deshalb gibt es keine API-URL im Build und kein CORS.
    provideHttpClient(withFetch()),
    provideHeyApiClient(client),
  ],
};
