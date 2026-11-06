import type { RunSummary } from '../api/types.gen';
import { MISSING } from '../shared/format';

type Counts = Pick<RunSummary, 'scored_count' | 'universe_size' | 'failed_count'>;

/**
 * Zähler eines Laufs als Satz, z. B. „88 von 90 bewertet, 2 fehlgeschlagen“ (verb „bewertet“)
 * oder „88 von 90, 2 fehlgeschlagen“. Ohne Zähler „–“.
 */
export function scoredText(run: Counts, verb?: string): string {
  if (run.scored_count === null) {
    return MISSING;
  }
  const total = run.universe_size === null ? '' : ` von ${run.universe_size}`;
  const failed = run.failed_count ? `, ${run.failed_count} fehlgeschlagen` : '';
  return `${run.scored_count}${total}${verb ? ` ${verb}` : ''}${failed}`;
}

/** Erste Zeile einer Fehlermeldung, für den Hinweis über den technischen Details. */
export function firstLine(error: string | null): string | undefined {
  const line = error?.split('\n').find((part) => part.trim() !== '');
  return line?.trim();
}
