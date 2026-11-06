// Lade- und Fehlerzustand einer Resource, wie ihn das Gerüst jeder Ansicht braucht
// (docs/architecture/styleguide.md, Seitenaufbau).
import { linkedSignal, type Resource, type Signal } from '@angular/core';

import { errorMessage } from './api-error';

/** Der Wert, sobald er da ist; beim Laden und nach einem Fehler undefined. */
export function loaded<T>(resource: Resource<T>): T | undefined {
  return resource.hasValue() ? resource.value() : undefined;
}

/**
 * Wie loaded, aber beim Nachladen bleibt der bisherige Wert stehen, bis der neue da ist (Spec,
 * Zustände): Ein Ereignis über den WebSocket lässt die Ansicht nicht flackern. Nach einem Fehler
 * undefined, damit die Ansicht den Fehler zeigt. Für Ansichten, die live nachladen.
 */
export function keptValue<T>(source: () => Resource<T>): Signal<T | undefined> {
  return linkedSignal<{ value: T | undefined; failed: boolean }, T | undefined>({
    source: () => {
      const resource = source();
      return { value: loaded(resource), failed: resource.error() !== undefined };
    },
    computation: (current, previous) =>
      current.failed ? undefined : (current.value ?? previous?.value),
  });
}

/** Meldung nach einem Fehler, notFound bei 404; sonst undefined. */
export function loadError(resource: Resource<unknown>, notFound: string): string | undefined {
  const error = resource.error();
  return error ? errorMessage(error, notFound) : undefined;
}
