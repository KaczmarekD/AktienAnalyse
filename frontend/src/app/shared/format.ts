// Formate der Ansichten im deutschen Stil (docs/architecture/styleguide.md); fehlende Werte
// erscheinen als Gedankenstrich.
import { formatDate, formatNumber, formatPercent } from '@angular/common';
import { inject, LOCALE_ID, Pipe, PipeTransform } from '@angular/core';

export const MISSING = '–';

/** Datum und Zeitpunkt, wie sie jede Ansicht zeigt. */
export const DAY = 'dd.MM.yyyy';
export const DAY_TIME = 'dd.MM.yyyy HH:mm';

type DateInput = string | number | Date | null | undefined;

/** Fehlender Wert als Gedankenstrich, alles andere unverändert, z. B. Rang oder Exit-Code. */
@Pipe({ name: 'orDash' })
export class OrDashPipe implements PipeTransform {
  transform<T>(value: T | null | undefined): T | string {
    return value == null || value === '' ? MISSING : value;
  }
}

/** Datum, z. B. Abruf vom 30.10.2026. */
@Pipe({ name: 'day' })
export class DayPipe implements PipeTransform {
  private readonly locale = inject(LOCALE_ID);

  transform(value: DateInput): string {
    return value == null || value === '' ? MISSING : formatDate(value, DAY, this.locale);
  }
}

/** Zeitpunkt, z. B. Start eines Laufs (30.10.2026 06:00). */
@Pipe({ name: 'dayTime' })
export class DayTimePipe implements PipeTransform {
  private readonly locale = inject(LOCALE_ID);

  transform(value: DateInput): string {
    return value == null || value === '' ? MISSING : formatDate(value, DAY_TIME, this.locale);
  }
}

/** Zahl mit festen Nachkommastellen, z. B. Scores (0,78) oder Multiples (14,38). */
@Pipe({ name: 'num' })
export class NumPipe implements PipeTransform {
  private readonly locale = inject(LOCALE_ID);

  transform(value: number | null | undefined, digits = '1.2-2'): string {
    return value == null ? MISSING : formatNumber(value, this.locale, digits);
  }
}

/** Anteil als Prozent, Standard mit einer Nachkommastelle (ROIC 12,3 %); Gewichte mit '1.0-0'. */
@Pipe({ name: 'pct' })
export class PctPipe implements PipeTransform {
  private readonly locale = inject(LOCALE_ID);

  transform(value: number | null | undefined, digits = '1.1-1'): string {
    return value == null ? MISSING : formatPercent(value, this.locale, digits);
  }
}

/** Betrag in Milliarden, z. B. Marktkapitalisierung (140,0 Mrd). */
@Pipe({ name: 'mrd' })
export class MrdPipe implements PipeTransform {
  private readonly locale = inject(LOCALE_ID);

  transform(value: number | null | undefined): string {
    return value == null ? MISSING : `${formatNumber(value / 1e9, this.locale, '1.1-1')} Mrd`;
  }
}

const RUN_STATUS: Record<string, string> = {
  running: 'läuft',
  success: 'erfolgreich',
  partial: 'teilweise',
  no_data: 'keine Daten',
  failed: 'fehlgeschlagen',
};

/** Status eines Laufs auf Deutsch. */
@Pipe({ name: 'runStatus' })
export class RunStatusPipe implements PipeTransform {
  transform(status: string): string {
    return RUN_STATUS[status] ?? status;
  }
}

/** Alle Status eines Laufs, für Glossar und Tests. */
export const RUN_STATUSES = Object.keys(RUN_STATUS);

const RUN_KIND: Record<string, string> = {
  batch: 'Abruf und Bewertung',
  rescore: 'Neu bewertet',
  import: 'Import',
};

/** Alle Arten eines Laufs (RUN_KINDS in src/db/models/batch.py). */
export const RUN_KINDS = Object.keys(RUN_KIND);

/** Art eines Laufs auf Deutsch, z. B. „Abruf und Bewertung“ statt batch. */
@Pipe({ name: 'runKind' })
export class RunKindPipe implements PipeTransform {
  transform(kind: string): string {
    return RUN_KIND[kind] ?? kind;
  }
}

/** Die elf Sektoren von Yahoo Finance auf Deutsch; sortiert wird nach dem deutschen Namen. */
export const SECTORS: Record<string, string> = {
  'Basic Materials': 'Grundstoffe',
  'Communication Services': 'Kommunikation',
  'Consumer Cyclical': 'Zyklischer Konsum',
  'Consumer Defensive': 'Basiskonsum',
  Energy: 'Energie',
  'Financial Services': 'Finanzen',
  Healthcare: 'Gesundheit',
  Industrials: 'Industrie',
  'Real Estate': 'Immobilien',
  Technology: 'Technologie',
  Utilities: 'Versorger',
};

/** Sektor auf Deutsch; was die Liste nicht kennt, bleibt wie geliefert. */
export function sectorName(sector: string | null | undefined): string {
  return sector ? (SECTORS[sector] ?? sector) : MISSING;
}

@Pipe({ name: 'sector' })
export class SectorPipe implements PipeTransform {
  transform(sector: string | null | undefined): string {
    return sectorName(sector);
  }
}

/** Herkunft der Indexliste: die Live-Quellen mit Namen, sonst die geprüfte Ersatzliste. */
@Pipe({ name: 'indexSource' })
export class IndexSourcePipe implements PipeTransform {
  transform(source: string | null | undefined): string {
    if (source == null || source === '') {
      return MISSING;
    }
    return source === 'Deka' || source === 'iShares' ? source : 'Ersatzliste';
  }
}

const NBSP = '\u00a0';

/** Dauer von start bis end, z. B. 12 min oder 1 h 5 min; ohne Ende ein Strich. */
@Pipe({ name: 'duration' })
export class DurationPipe implements PipeTransform {
  transform(start: DateInput, end: DateInput): string {
    if (start == null || start === '' || end == null || end === '') {
      return MISSING;
    }
    const minutes = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60_000);
    if (minutes < 1) {
      return `<${NBSP}1${NBSP}min`;
    }
    return minutes < 60
      ? `${minutes}${NBSP}min`
      : `${Math.floor(minutes / 60)}${NBSP}h ${minutes % 60}${NBSP}min`;
  }
}
