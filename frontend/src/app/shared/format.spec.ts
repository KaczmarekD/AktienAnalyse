// Formate der Ansichten (docs/architecture/styleguide.md, Abschnitt Sprache, Zahlen, Daten).
import { LOCALE_ID } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import '../locale';
import {
  DayPipe,
  DayTimePipe,
  DurationPipe,
  IndexSourcePipe,
  MISSING,
  OrDashPipe,
  PctPipe,
  RunKindPipe,
  SECTORS,
  SectorPipe,
} from './format';

function pipe<T>(type: new () => T): T {
  TestBed.configureTestingModule({ providers: [{ provide: LOCALE_ID, useValue: 'de-DE' }] });
  return TestBed.runInInjectionContext(() => new type());
}

/** Formate trennen Zahl und Einheit mit einem geschuetzten Leerzeichen. */
function plain(value: string): string {
  return value.replace(/\s/g, ' ');
}

describe('OrDashPipe', () => {
  it('shows a dash for missing values and keeps everything else', () => {
    const orDash = pipe(OrDashPipe);
    expect(orDash.transform(null)).toBe(MISSING);
    expect(orDash.transform(undefined)).toBe(MISSING);
    expect(orDash.transform('')).toBe(MISSING);
    expect(orDash.transform(0)).toBe(0);
    expect(orDash.transform('DAX')).toBe('DAX');
  });
});

describe('DayPipe', () => {
  it('formats a date as dd.MM.yyyy', () => {
    const day = pipe(DayPipe);
    expect(day.transform('2026-10-30')).toBe('30.10.2026');
    expect(day.transform(new Date(2026, 9, 30, 14, 5))).toBe('30.10.2026');
    expect(day.transform(null)).toBe(MISSING);
  });
});

describe('DayTimePipe', () => {
  it('formats a point in time as dd.MM.yyyy HH:mm', () => {
    const dayTime = pipe(DayTimePipe);
    expect(dayTime.transform(new Date(2026, 9, 30, 14, 5))).toBe('30.10.2026 14:05');
    expect(dayTime.transform(null)).toBe(MISSING);
    expect(dayTime.transform(undefined)).toBe(MISSING);
  });
});

describe('PctPipe', () => {
  it('formats shares with the given digits, e.g. weights without decimals', () => {
    const pct = pipe(PctPipe);
    expect(plain(pct.transform(0.123))).toBe('12,3 %');
    expect(plain(pct.transform(0.6, '1.0-0'))).toBe('60 %');
    expect(pct.transform(null)).toBe(MISSING);
  });
});

describe('SectorPipe', () => {
  it('names the eleven Yahoo sectors in German and keeps unknown ones', () => {
    const sector = pipe(SectorPipe);
    expect(Object.keys(SECTORS)).toHaveLength(11);
    expect(sector.transform('Financial Services')).toBe('Finanzen');
    expect(sector.transform('Consumer Defensive')).toBe('Basiskonsum');
    expect(sector.transform('Something New')).toBe('Something New');
    expect(sector.transform(null)).toBe(MISSING);
  });
});

describe('RunKindPipe', () => {
  it('names the kind of a run in German', () => {
    const kind = pipe(RunKindPipe);
    expect(kind.transform('batch')).toBe('Abruf und Bewertung');
    expect(kind.transform('rescore')).toBe('Neu bewertet');
    expect(kind.transform('import')).toBe('Import');
    expect(kind.transform('other')).toBe('other');
  });
});

describe('DurationPipe', () => {
  it('gives minutes, from one hour on hours and minutes', () => {
    const duration = pipe(DurationPipe);
    expect(plain(duration.transform('2026-10-30T06:02:00Z', '2026-10-30T06:14:20Z'))).toBe('12 min');
    expect(plain(duration.transform('2026-10-30T06:00:00Z', '2026-10-30T07:05:00Z'))).toBe('1 h 5 min');
    expect(plain(duration.transform('2026-10-30T06:00:00Z', '2026-10-30T06:00:20Z'))).toBe('< 1 min');
    expect(duration.transform('2026-10-30T06:00:00Z', null)).toBe(MISSING);
  });
});

describe('IndexSourcePipe', () => {
  it('keeps the live sources and calls the fallback list Ersatzliste', () => {
    const source = pipe(IndexSourcePipe);
    expect(source.transform('Deka')).toBe('Deka');
    expect(source.transform('iShares')).toBe('iShares');
    expect(source.transform('Fallback-CSV')).toBe('Ersatzliste');
    expect(source.transform(null)).toBe(MISSING);
  });
});
