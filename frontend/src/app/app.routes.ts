import { Routes } from '@angular/router';

// Die Ansichten selbst kommen mit P3.7, bis dahin stehen dort Platzhalter
export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'ranking' },
  {
    path: 'ranking',
    title: 'Ranking · Value-Analyzer',
    loadComponent: () => import('./ranking/ranking-page').then((m) => m.RankingPage),
  },
  {
    path: 'runs',
    title: 'Runs · Value-Analyzer',
    loadComponent: () => import('./runs/runs-page').then((m) => m.RunsPage),
  },
  { path: '**', redirectTo: 'ranking' },
];
