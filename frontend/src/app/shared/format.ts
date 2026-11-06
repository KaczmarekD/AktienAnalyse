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
