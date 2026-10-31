// Zahlenformate der Ansichten im deutschen Stil; fehlende Werte erscheinen als Gedankenstrich.
import { formatNumber, formatPercent } from '@angular/common';
import { inject, LOCALE_ID, Pipe, PipeTransform } from '@angular/core';

export const MISSING = '–';

/** Zahl mit festen Nachkommastellen, z. B. Scores (0,78) oder Multiples (14,38). */
@Pipe({ name: 'num' })
export class NumPipe implements PipeTransform {
  private readonly locale = inject(LOCALE_ID);

  transform(value: number | null | undefined, digits = '1.2-2'): string {
    return value == null ? MISSING : formatNumber(value, this.locale, digits);
  }
}

/** Anteil als Prozent mit einer Nachkommastelle, z. B. ROIC (12,3 %). */
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
