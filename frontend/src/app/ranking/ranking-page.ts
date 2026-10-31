import { ChangeDetectionStrategy, Component } from '@angular/core';

/** Platzhalter, bis P3.7 das Ranking zeigt. */
@Component({
  selector: 'app-ranking-page',
  template: `<h1>Ranking</h1>
    <p>Die Ansicht kommt mit P3.7.</p>`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RankingPage {}
