// Gemeinsames fuer Komponententests: echte Komponenten, Antworten des web-api aus
// HttpTestingController statt eines Servers (P3.7).
import { provideHttpClient, withFetch } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
  TestRequest,
} from '@angular/common/http/testing';
import { LOCALE_ID } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { client } from '../api/client.gen';
import { provideHeyApiClient } from '../api/client/client.gen';
import '../locale';

export function apiTestingProviders() {
  return [
    provideHttpClient(withFetch()),
    provideHttpClientTesting(),
    provideHeyApiClient(client),
    provideRouter([]),
    { provide: LOCALE_ID, useValue: 'de-DE' },
  ];
}

/** Beantwortet die eine erwartete Anfrage und wartet, bis die Ansicht neu gezeichnet ist. */
export async function respond(
  fixture: ComponentFixture<unknown>,
  url: string,
  body: Parameters<TestRequest['flush']>[0],
  status = 200,
): Promise<void> {
  // Nicht whenStable: Die offene Anfrage haelt die App instabil, bis sie beantwortet ist.
  // tick() fuehrt Effects und Change Detection aus, dann ist die Anfrage gestellt.
  TestBed.tick();
  const request = TestBed.inject(HttpTestingController).expectOne((r) => r.urlWithParams === url);
  if (status === 200) {
    request.flush(body);
  } else {
    request.flush(body, { status, statusText: 'Fehler' });
  }
  // Auch hier nicht whenStable: Eine Antwort kann die naechste Anfrage ausloesen (Lauf -> Report)
  await new Promise((resolve) => setTimeout(resolve));
  TestBed.tick();
}

export function text(fixture: ComponentFixture<unknown>): string {
  return (fixture.nativeElement as HTMLElement).textContent?.replace(/\s+/g, ' ') ?? '';
}

export function query<T extends Element = HTMLElement>(
  fixture: ComponentFixture<unknown>,
  selector: string,
): T[] {
  return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<T>(selector));
}
