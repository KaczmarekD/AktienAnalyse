// Die Prüfungen der Tests 1 und 2 finden, was sie finden sollen (sonst prüften sie ins Leere).
import { ChangeDetectionStrategy, Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatTooltipModule } from '@angular/material/tooltip';

import { abbreviationsWithoutExplanation, controlsWithoutTooltip } from './tooltips';

@Component({
  imports: [MatTooltipModule],
  template: `
    <button type="button" matTooltip="Startet einen Lauf.">Lauf starten</button>
    <button type="button">Ohne Tooltip</button>
    <button type="button">Titelname</button>
    <table>
      <tr>
        <th><span matTooltip="Kurs-Buchwert-Verhältnis.">KBV</span></th>
        <th>Spalte ohne</th>
      </tr>
    </table>
    <span class="badge">Badge ohne</span>
    <p>Im Text steht KGV ohne Erklärung, <span matTooltip="Rendite.">ROIC</span> mit, MDAX ohne.</p>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
class Host {}

function render() {
  const fixture = TestBed.createComponent(Host);
  fixture.detectChanges();
  return fixture;
}

describe('controlsWithoutTooltip', () => {
  it('finds controls, headers and badges without tooltip and honours exceptions', () => {
    const missing = controlsWithoutTooltip(render(), [
      { text: 'Titelname', reason: 'Link mit sprechendem Text' },
    ]);
    expect(missing).toEqual(['button „Ohne Tooltip“', 'th „Spalte ohne“', 'span „Badge ohne“']);
  });
});

describe('abbreviationsWithoutExplanation', () => {
  it('finds abbreviations outside an element with tooltip', () => {
    expect(abbreviationsWithoutExplanation(render()).sort()).toEqual(['KGV', 'MDAX']);
  });
});
