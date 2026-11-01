import { Routes } from '@angular/router';

// Routenparameter kommen als Inputs in die Seiten (withComponentInputBinding, app.config.ts)
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'ranking' },
  {
    path: 'ranking',
    title: 'Ranking · Value-Analyzer',
    loadComponent: () => import('./ranking/ranking-page').then((m) => m.RankingPage),
  },
  {
    path: 'ranking/:scoringRunId',
    title: 'Ranking · Value-Analyzer',
    loadComponent: () => import('./ranking/ranking-page').then((m) => m.RankingPage),
  },
  {
    path: 'runs',
    title: 'Runs · Value-Analyzer',
    loadComponent: () => import('./runs/runs-page').then((m) => m.RunsPage),
  },
  {
    path: 'runs/:runId',
    title: 'Lauf · Value-Analyzer',
    loadComponent: () => import('./runs/run-detail-page').then((m) => m.RunDetailPage),
  },
  {
    path: 'profiles',
    title: 'Profile · Value-Analyzer',
    loadComponent: () => import('./profiles/profiles-page').then((m) => m.ProfilesPage),
  },
  {
    path: 'profiles/:profileId',
    title: 'Profil · Value-Analyzer',
    loadComponent: () => import('./profiles/profile-editor-page').then((m) => m.ProfileEditorPage),
  },
  {
    path: 'instruments/:symbol',
    title: 'Titel · Value-Analyzer',
    loadComponent: () => import('./instruments/instrument-page').then((m) => m.InstrumentPage),
  },
  { path: '**', redirectTo: 'ranking' },
];
