// Rechnen und Beschriften rund um die Hinweise (D5.4): Messwerte in ihrer Einheit, Gegenstand
// eines Hinweises, Reihenfolge, Schwellen als Eingabe und zurück. Texte stehen in controls.ts.
import { formatNumber, formatPercent } from '@angular/common';

import type { DepotHint, HintParamsV1 } from '../api/types.gen';
import { sectorName } from '../shared/format';
import {
  countryName,
  HINT_UNIT,
  HintUnit,
  parseAmount,
  SLICE,
  THRESHOLDS,
  Threshold,
  ThresholdField,
  toInput,
} from './controls';

const NBSP = ' ';
const ISIN = /^[A-Z]{2}[A-Z0-9]{9}\d$/;
const SEVERITY_ORDER: Record<DepotHint['severity'], number> = { critical: 0, warning: 1, info: 2 };

/** Einheit der Messwerte einer Regel, wie die ihrer Schwelle; Regeln ohne Schwelle haben keine. */
export function unitOf(rule: string): HintUnit | undefined {
  return THRESHOLDS.find((threshold) => threshold.rule === rule)?.unit;
}

/** Ein Messwert oder eine Schwelle in der Einheit der Regel (15 %, 3 Prozentpunkte, 45 Tage). */
export function formatMeasure(rule: string, value: number | null, locale: string): string {
  const unit = unitOf(rule);
  if (value === null || unit === undefined) {
    return '';
  }
  switch (unit) {
    case 'share':
      return formatPercent(value, locale, '1.0-1');
    case 'points':
      return `${formatNumber(value * 100, locale, '1.0-1')}${NBSP}${HINT_UNIT.points}`;
    case 'score':
      return formatNumber(value, locale, '1.2-2');
    case 'percent':
      return `${formatNumber(value, locale, '1.0-2')}${NBSP}%`;
    case 'mio':
      return `${formatNumber(value, locale, '1.0-0')}${NBSP}${HINT_UNIT.mio}`;
    default:
      return `${formatNumber(value, locale, '1.0-0')}${NBSP}${HINT_UNIT[unit]}`;
  }
}

/** Worauf sich ein Hinweis bezieht, lesbar: Name des Wertpapiers, Sektor, Land, Anlageklasse. */
export function subjectLabel(hint: DepotHint, names: Record<string, string>): string {
  const subject = hint.subject;
  switch (hint.rule) {
    case 'HIN-K03':
      return sectorName(subject);
    case 'HIN-K04':
      return countryName(subject);
    case 'HIN-K06':
      return `Emittent ${subject}`;
    case 'HIN-A01':
      return subject in SLICE ? SLICE[subject as keyof typeof SLICE] : subject;
    case 'HIN-E02':
      return subject
        .split('+')
        .map((isin) => names[isin] ?? isin)
        .join(' und ');
    case 'HIN-B03':
      return `fällig ${subject}`;
  }
  if (subject === 'depot') {
    return '';
  }
  return ISIN.test(subject) ? (names[subject] ?? subject) : subject;
}

/** Schwerste zuerst, dann neue vor bestehenden, dann nach Regel und Gegenstand. */
export function sortHints(hints: readonly DepotHint[]): DepotHint[] {
  return [...hints].sort(
    (a, b) =>
      SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
      Number(b.status === 'new') - Number(a.status === 'new') ||
      a.rule.localeCompare(b.rule) ||
      a.subject.localeCompare(b.subject),
  );
}

/** Wert einer Schwelle für ihr Eingabefeld: Anteile und Punkte in Prozent, Dezimalkomma. */
export function thresholdInput(threshold: Threshold, value: number | undefined): string {
  if (value === undefined) {
    return '';
  }
  const scaled = threshold.unit === 'share' || threshold.unit === 'points' ? value * 100 : value;
  return toInput(Math.round(scaled * 10000) / 10000);
}

/** Eingabe einer Schwelle als Wert für ``HintParamsV1``, oder der Grund, warum sie nicht passt. */
export function parseThreshold(
  threshold: Threshold,
  text: string,
): { value: number } | { error: string } {
  const parsed = parseAmount(text);
  if (parsed === null) {
    return { error: 'Wert fehlt.' };
  }
  if (parsed === undefined) {
    return { error: 'Keine Zahl.' };
  }
  const number = Number(parsed);
  const whole = threshold.unit === 'days' || threshold.unit === 'tradingDays';
  if (whole && !Number.isInteger(number)) {
    return { error: 'Nur ganze Zahlen.' };
  }
  const low = whole ? number < threshold.min : number <= threshold.min;
  if (low || number > threshold.max) {
    const from = whole ? `von ${threshold.min}` : `über ${threshold.min}`;
    return { error: `Wert ${from} bis ${toInput(threshold.max)}.` };
  }
  const scaled = threshold.unit === 'share' || threshold.unit === 'points' ? number / 100 : number;
  return { value: Math.round(scaled * 1e9) / 1e9 };
}

/** Die Felder der Schwellen aus gespeicherten Parametern, fehlende mit dem Standardwert. */
export function thresholdValues(params: HintParamsV1): Record<ThresholdField, string> {
  return Object.fromEntries(
    THRESHOLDS.map((threshold) => [
      threshold.field,
      thresholdInput(threshold, params[threshold.field]),
    ]),
  ) as Record<ThresholdField, string>;
}
