// Anmeldung in Komponententests (D1.4): ein fester Zustand statt GET /health und /me.
import { computed, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import type { Me } from '../api/types.gen';
import { AuthStore } from '../shared/auth/auth.store';

export function me(values: Partial<Me> = {}): Me {
  return {
    id: 2,
    username: 'anna',
    role: 'user',
    display_name: 'Anna',
    email: null,
    must_change_password: false,
    ...values,
  };
}

export const ADMIN = me({ id: 1, username: 'dennis', role: 'admin', display_name: 'Dennis' });

/** Was eine Seite vom AuthStore sieht; refresh, signedOut und logout zählen ihre Aufrufe. */
export class FakeAuthStore {
  readonly calls = { refresh: 0, signedOut: 0, logout: 0 };
  readonly ready = signal(true);
  readonly required = signal(true);
  readonly user = signal<Me | undefined>(undefined);
  readonly version = signal<string | undefined>(undefined);
  readonly notice = signal<string | undefined>(undefined);
  readonly isAdmin = computed(() => !this.required() || this.user()?.role === 'admin');
  readonly canManageUsers = computed(() => this.user()?.role === 'admin');
  /** Was refresh als neues Konto liefert (sonst bleibt es). */
  next: Me | undefined;

  whenReady(): Promise<void> {
    return Promise.resolve();
  }

  async refresh(): Promise<Me | undefined> {
    this.calls.refresh += 1;
    if (this.next) {
      this.user.set(this.next);
    }
    return this.user();
  }

  signedOut(): void {
    this.calls.signedOut += 1;
    this.user.set(undefined);
  }

  async logout(): Promise<void> {
    this.calls.logout += 1;
    this.user.set(undefined);
  }

  sessionEnded(): void {
    this.user.set(undefined);
  }
}

/** Provider: angemeldet als user (oder niemand), mit oder ohne Sitzungspflicht. */
export function provideAuthTesting(state: { required?: boolean; user?: Me } = {}) {
  const fake = new FakeAuthStore();
  fake.required.set(state.required ?? true);
  fake.user.set(state.user);
  return { provide: AuthStore, useValue: fake };
}

/** Der Ersatz aus provideAuthTesting. */
export function fakeAuth(): FakeAuthStore {
  return TestBed.inject(AuthStore) as unknown as FakeAuthStore;
}
