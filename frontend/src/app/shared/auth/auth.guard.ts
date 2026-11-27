// Guards vor den Seiten (D1.4). Sie warten, bis der AuthStore weiß, wer angemeldet ist.
import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { AuthStore, loginTree, safeNext } from './auth.store';

/** Alle Ansichten: mit Sitzungspflicht nur angemeldet, mit Einmal-Passwort erst das Konto. */
export const authGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthStore);
  const router = inject(Router);
  await auth.whenReady();
  const user = auth.user();
  if (user?.must_change_password) {
    return router.createUrlTree(['/account']);
  }
  return user || !auth.required() ? true : loginTree(router, state.url);
};

/** Das eigene Konto: immer mit echter Sitzung, auch ohne Sitzungspflicht. */
export const sessionGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthStore);
  const router = inject(Router);
  await auth.whenReady();
  return auth.user() ? true : loginTree(router, state.url);
};

/** D3.6: Depots gehören einer Person: nur mit echter Sitzung, mit Einmal-Passwort erst das Konto. */
export const ownerGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthStore);
  const router = inject(Router);
  await auth.whenReady();
  const user = auth.user();
  if (!user) {
    return loginTree(router, state.url);
  }
  return user.must_change_password ? router.createUrlTree(['/account']) : true;
};

/** D3.6: die Startseite. Angemeldet „Meine Depots“, sonst das Ranking (ohne Sitzungspflicht). */
export const startGuard: CanActivateFn = async () => {
  const auth = inject(AuthStore);
  const router = inject(Router);
  await auth.whenReady();
  return router.createUrlTree([auth.user() ? '/depots' : '/ranking']);
};

/** Die Nutzerverwaltung: nur ein Admin mit echter Sitzung und eigenem Passwort. */
export const adminGuard: CanActivateFn = async (_route, state) => {
  const auth = inject(AuthStore);
  const router = inject(Router);
  await auth.whenReady();
  const user = auth.user();
  if (!user) {
    return loginTree(router, state.url);
  }
  if (user.must_change_password) {
    return router.createUrlTree(['/account']);
  }
  return user.role === 'admin' ? true : router.createUrlTree(['/ranking']);
};

/** Die Anmeldeseite: Wer schon angemeldet ist, geht gleich zum Rücksprung. */
export const loginGuard: CanActivateFn = async (route) => {
  const auth = inject(AuthStore);
  const router = inject(Router);
  await auth.whenReady();
  return auth.user() ? router.parseUrl(safeNext(route.queryParamMap.get('next'))) : true;
};
