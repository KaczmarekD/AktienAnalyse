import { Routes } from '@angular/router';

import { adminGuard, authGuard, loginGuard, sessionGuard } from './shared/auth/auth.guard';

// Routenparameter kommen als Inputs in die Seiten (withComponentInputBinding, app.config.ts).
// D1.4: Die Ansichten schützt authGuard (mit Sitzungspflicht nur angemeldet), das eigene Konto
// und die Nutzerverwaltung brauchen immer eine echte Sitzung.
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'ranking' },
  {
    path: 'ranking',
    title: 'Ranking · Value-Analyzer',
    canActivate: [authGuard],
    loadComponent: () => import('./ranking/ranking-page').then((m) => m.RankingPage),
  },
  {
    path: 'ranking/:scoringRunId',
    title: 'Ranking · Value-Analyzer',
    canActivate: [authGuard],
    loadComponent: () => import('./ranking/ranking-page').then((m) => m.RankingPage),
  },
  {
    path: 'runs',
    title: 'Läufe · Value-Analyzer',
    canActivate: [authGuard],
    loadComponent: () => import('./runs/runs-page').then((m) => m.RunsPage),
  },
  {
    path: 'runs/:runId',
    title: 'Lauf · Value-Analyzer',
    canActivate: [authGuard],
    loadComponent: () => import('./runs/run-detail-page').then((m) => m.RunDetailPage),
  },
  {
    path: 'profiles',
    title: 'Profile · Value-Analyzer',
    canActivate: [authGuard],
    loadComponent: () => import('./profiles/profiles-page').then((m) => m.ProfilesPage),
  },
  {
    path: 'profiles/:profileId',
    title: 'Profil · Value-Analyzer',
    canActivate: [authGuard],
    loadComponent: () => import('./profiles/profile-editor-page').then((m) => m.ProfileEditorPage),
  },
  {
    path: 'instruments/:symbol',
    title: 'Titel · Value-Analyzer',
    canActivate: [authGuard],
    loadComponent: () => import('./instruments/instrument-page').then((m) => m.InstrumentPage),
  },
  {
    path: 'glossary',
    title: 'Begriffe · Value-Analyzer',
    canActivate: [authGuard],
    loadComponent: () => import('./glossary/glossary-page').then((m) => m.GlossaryPage),
  },
  {
    path: 'login',
    title: 'Anmelden · Value-Analyzer',
    canActivate: [loginGuard],
    loadComponent: () => import('./login/login-page').then((m) => m.LoginPage),
  },
  {
    path: 'account',
    title: 'Konto · Value-Analyzer',
    canActivate: [sessionGuard],
    loadComponent: () => import('./account/account-page').then((m) => m.AccountPage),
  },
  {
    // D1.6: der Link aus der Bestätigungsmail, ohne Anmeldung (das Token ist der Nachweis)
    path: 'confirm-email',
    title: 'Mail-Adresse bestätigen · Value-Analyzer',
    loadComponent: () => import('./account/confirm-email-page').then((m) => m.ConfirmEmailPage),
  },
  {
    path: 'admin/users',
    title: 'Nutzer · Value-Analyzer',
    canActivate: [adminGuard],
    loadComponent: () => import('./admin/users-page').then((m) => m.UsersPage),
  },
  { path: '**', redirectTo: 'ranking' },
];
