// Lade- und Fehlerzustand einer Resource fuer die Ansichten (Gerüst im Styleguide).
import { HttpErrorResponse } from '@angular/common/http';
import { ApplicationRef, resource, Resource, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { keptValue, loaded, loadError } from './resource';

async function settled<T>(loader: () => Promise<T>): Promise<Resource<T | undefined>> {
  const ref = TestBed.runInInjectionContext(() => resource({ loader }));
  await TestBed.inject(ApplicationRef).whenStable();
  return ref;
}

describe('loaded and loadError', () => {
  it('give the value once it is there', async () => {
    const ref = await settled(() => Promise.resolve({ id: 3 }));
    expect(loaded(ref)).toEqual({ id: 3 });
    expect(loadError(ref, 'Lauf nicht gefunden.')).toBeUndefined();
  });

  it('give neither while loading', () => {
    const ref = TestBed.runInInjectionContext(() =>
      resource({ loader: () => new Promise<number>(() => undefined) }),
    );
    expect(loaded(ref)).toBeUndefined();
    expect(loadError(ref, 'Lauf nicht gefunden.')).toBeUndefined();
  });

  it('turn a 404 into the given message', async () => {
    const ref = await settled(() =>
      Promise.reject(new HttpErrorResponse({ status: 404, statusText: 'Not Found' })),
    );
    expect(loaded(ref)).toBeUndefined();
    expect(loadError(ref, 'Lauf nicht gefunden.')).toBe('Lauf nicht gefunden.');
  });

  it('name the server when it is not reachable', async () => {
    const ref = await settled(() => Promise.reject(new HttpErrorResponse({ status: 0 })));
    expect(loadError(ref, 'Lauf nicht gefunden.')).toBe(
      'Der Server oder seine Datenbank ist nicht erreichbar.',
    );
  });
});

async function tick(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve));
  TestBed.tick();
}

describe('keptValue', () => {
  it('keeps the old value while new data loads and drops it after an error', async () => {
    const id = signal(1);
    let resolveSecond: (value: number) => void = () => undefined;
    const ref = TestBed.runInInjectionContext(() =>
      resource({
        params: () => id(),
        loader: ({ params }) => {
          if (params === 1) {
            return Promise.resolve(10);
          }
          if (params === 2) {
            return new Promise<number>((resolve) => (resolveSecond = resolve));
          }
          return Promise.reject(new HttpErrorResponse({ status: 500 }));
        },
      }),
    );
    const value = keptValue(() => ref);
    await tick();
    expect(value()).toBe(10);

    // Neue Anfrage, etwa nach einem Ereignis über den WebSocket: Die alten Daten bleiben stehen
    id.set(2);
    TestBed.tick();
    expect(loaded(ref)).toBeUndefined();
    expect(value()).toBe(10);
    resolveSecond(20);
    await tick();
    expect(value()).toBe(20);

    // Nach einem Fehler zeigt die Ansicht den Fehler, nicht die alten Daten
    id.set(3);
    await tick();
    expect(value()).toBeUndefined();
  });
});
