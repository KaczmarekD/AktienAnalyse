// Lade- und Fehlerzustand einer Resource, wie ihn das Gerüst jeder Ansicht braucht
// (docs/architecture/styleguide.md, Seitenaufbau).
import type { Resource } from '@angular/core';

import { errorMessage } from './api-error';

/** Der Wert, sobald er da ist; beim Laden und nach einem Fehler undefined. */
export function loaded<T>(resource: Resource<T>): T | undefined {
  return resource.hasValue() ? resource.value() : undefined;
}

/** Meldung nach einem Fehler, notFound bei 404; sonst undefined. */
export function loadError(resource: Resource<unknown>, notFound: string): string | undefined {
  const error = resource.error();
  return error ? errorMessage(error, notFound) : undefined;
}
