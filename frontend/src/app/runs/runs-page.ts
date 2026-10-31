import { ChangeDetectionStrategy, Component } from '@angular/core';

/** Platzhalter, bis P3.7 die Laeufe zeigt. */
@Component({
  selector: 'app-runs-page',
  template: `<h1>Runs</h1>
    <p>Die Ansicht kommt mit P3.7.</p>`,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RunsPage {}
