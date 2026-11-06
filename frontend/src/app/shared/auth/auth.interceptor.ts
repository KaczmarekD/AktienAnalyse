// Interceptoren für Anfragen an das web-api (D1.4).
import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject, Injector } from '@angular/core';
import { tap } from 'rxjs';

import { AuthStore } from './auth.store';

const API = /^(?:https?:\/\/[^/]+)?(\/api\/[^?#]*)/;
const WRITES = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
// Ein 401 hier ist Sache der Seite, keine abgelaufene Sitzung
const OWN_401 = new Set(['/api/v1/auth/login', '/api/v1/auth/session']);

function apiPath(url: string): string | undefined {
  return API.exec(url)?.[1];
}

/**
 * Schreibende Anfragen gehen nur als JSON (ADR-0007 Regel 1, JsonOnlyMiddleware), auch ohne
 * Inhalt. Der generierte Client schickt bei Abmelden, Deaktivieren usw. keinen Inhalt und damit
 * keinen Content-Type: Dann geht ein leeres JSON-Objekt mit.
 */
export const jsonWritesInterceptor: HttpInterceptorFn = (req, next) => {
  if (!WRITES.has(req.method) || req.body !== null || apiPath(req.url) === undefined) {
    return next(req);
  }
  return next(req.clone({ body: {}, setHeaders: { 'Content-Type': 'application/json' } }));
};

/** Jedes 401 des web-api heißt: Die Sitzung ist zu Ende (abgelaufen, widerrufen, deaktiviert). */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  // Erst beim Fehler holen: Der AuthStore stellt selbst Anfragen
  const injector = inject(Injector);
  return next(req).pipe(
    tap({
      error: (error: unknown) => {
        const path = apiPath(req.url);
        if (
          error instanceof HttpErrorResponse &&
          error.status === 401 &&
          path !== undefined &&
          !OWN_401.has(path)
        ) {
          injector.get(AuthStore).sessionEnded();
        }
      },
    }),
  );
};
