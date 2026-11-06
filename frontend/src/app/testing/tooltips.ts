// Gerüst der Tests 1 und 2 der Neugestaltung (docs/architecture/ui-neugestaltung.md, Tests):
// Jedes Bedienelement, jeder Spaltenkopf, jedes Label und jede Badge hat einen Tooltip, und kein
// Kürzel aus dem Glossar steht ohne Erklärung im Text. Jede Ansicht ruft beide in ihrem Test auf.
import { DebugElement } from '@angular/core';
import { ComponentFixture } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { ENTRIES } from '../shared/glossary/glossary';

/** Was einen Tooltip braucht (Spec, „Was einen Tooltip bekommt“). */
const NEEDS_TOOLTIP = [
  'button',
  'a[matButton]',
  'mat-button-toggle',
  'mat-slide-toggle',
  'mat-checkbox',
  'th',
  'dt',
  '.badge',
].join(', ');

/** Eine begründete Ausnahme: Elemente, deren Text so beginnt, brauchen keinen Tooltip. */
export interface TooltipException {
  text: string;
  reason: string;
}

function tooltipHosts(fixture: ComponentFixture<unknown>): Map<Element, string> {
  const hosts = new Map<Element, string>();
  for (const debug of fixture.debugElement.queryAll(By.directive(MatTooltip))) {
    const tooltip = debug.injector.get(MatTooltip);
    if (!tooltip.disabled && tooltip.message.trim()) {
      hosts.set(debug.nativeElement as Element, tooltip.message);
    }
  }
  return hosts;
}

function describeElement(element: Element): string {
  const text = (element.getAttribute('aria-label') ?? element.textContent ?? '').trim();
  return `${element.tagName.toLowerCase()} „${text.replace(/\s+/g, ' ').slice(0, 40)}“`;
}

/** Bedienelemente ohne Tooltip, weder am Element noch an einem Kind (z. B. app-term im Kopf). */
export function controlsWithoutTooltip(
  fixture: ComponentFixture<unknown>,
  exceptions: readonly TooltipException[] = [],
): string[] {
  const hosts = tooltipHosts(fixture);
  const covers = (element: Element) =>
    hosts.has(element) || Array.from(hosts.keys()).some((host) => element.contains(host));
  // Die inneren Buttons von Umschaltern gehören zu ihrem Material-Element, das den Tooltip trägt
  const covered = (element: Element) => {
    const owner = element.closest('mat-button-toggle, mat-slide-toggle');
    return covers(element) || (owner !== null && covers(owner));
  };
  return fixture.debugElement
    .queryAll(By.css(NEEDS_TOOLTIP))
    .map((debug: DebugElement) => debug.nativeElement as Element)
    .filter((element) => !covered(element))
    .filter((element) => {
      const text = (element.getAttribute('aria-label') ?? element.textContent ?? '').trim();
      return !exceptions.some((exception) => text.startsWith(exception.text));
    })
    .map(describeElement);
}

const ABBREVIATIONS = Object.values(ENTRIES)
  .filter((entry) => entry.abbr)
  .flatMap((entry) => [entry.label, ...(entry.short ? [entry.short] : [])]);

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
}

/** Kürzel aus dem Glossar, die im Text stehen, ohne dass ein Element darum einen Tooltip hat. */
export function abbreviationsWithoutExplanation(fixture: ComponentFixture<unknown>): string[] {
  const root = fixture.nativeElement as HTMLElement;
  const hosts = tooltipHosts(fixture);
  const explained = (node: Node) => {
    for (let element = node.parentElement; element; element = element.parentElement) {
      if (hosts.has(element)) {
        return true;
      }
      if (element === root) {
        return false;
      }
    }
    return false;
  };
  const found = new Set<string>();
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent ?? '';
    for (const abbreviation of ABBREVIATIONS) {
      const pattern = new RegExp(`(?<![\\w.])${escape(abbreviation)}(?![\\w])`);
      if (pattern.test(text) && !explained(node)) {
        found.add(abbreviation);
      }
    }
  }
  return Array.from(found);
}
