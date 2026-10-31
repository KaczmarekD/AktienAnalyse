import { HttpErrorResponse } from '@angular/common/http';

/** Verstaendliche Meldung fuer eine fehlgeschlagene Anfrage an das web-api. */
export function errorMessage(error: unknown, notFound: string): string {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 404) {
      return notFound;
    }
    if (error.status === 0 || error.status >= 500) {
      return 'Das web-api oder seine Datenbank ist nicht erreichbar.';
    }
  }
  return 'Die Daten konnten nicht geladen werden.';
}

/** Routenparameter als Zahl; fehlt er, bleibt er leer. */
export function optionalNumber(value: unknown): number | undefined {
  if (value === undefined || value === null || value === '') {
    return undefined;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : undefined;
}
