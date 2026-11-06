// Lade- und Fehlerzustand einer Resource fuer die Ansichten (Gerüst im Styleguide).
import { HttpErrorResponse } from '@angular/common/http';
import { ApplicationRef, resource, Resource } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { loaded, loadError } from './resource';

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

  it('name the web-api when it is not reachable', async () => {
    const ref = await settled(() => Promise.reject(new HttpErrorResponse({ status: 0 })));
    expect(loadError(ref, 'Lauf nicht gefunden.')).toBe(
      'Das web-api oder seine Datenbank ist nicht erreichbar.',
    );
  });
});
