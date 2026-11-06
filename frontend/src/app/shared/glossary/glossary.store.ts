import { computed, Injectable } from '@angular/core';

import { listFactorsResource } from '../../api/@angular/common.gen';
import type { Factor } from '../../api/types.gen';
import { loaded } from '../resource';
import {
  GLOSSARY,
  termTip,
  GlossaryEntry,
  GlossaryGroup,
  GROUPS,
  ROLES,
  TermKey,
  TipParams,
} from './glossary';

/** Ein Begriff, wie ihn die Seite „Begriffe“ zeigt. */
export interface GlossaryItem {
  key: TermKey;
  label: string;
  tip: string;
  long?: string;
  role?: { label: string; tip: string };
}

/**
 * Texte aus dem Glossar und die Faktortexte von scoring (GET /api/v1/scoring/factors, einmal je
 * App geladen). Faktoren bekommen die Richtung („Niedriger ist besser.“) und ihre Rolle angehängt;
 * antwortet die API nicht, zeigen sie nur ihr Label.
 */
@Injectable({ providedIn: 'root' })
export class GlossaryStore {
  private readonly factorsResource = listFactorsResource(() => ({}));
  private readonly factors = computed(
    () => new Map<string, Factor>((loaded(this.factorsResource) ?? []).map((f) => [f.key, f])),
  );

  label(key: TermKey, variant: 'long' | 'short' = 'long'): string {
    const entry: GlossaryEntry = GLOSSARY[key];
    return variant === 'short' ? (entry.short ?? entry.label) : entry.label;
  }

  tip(key: TermKey, params: TipParams = {}): string {
    const entry: GlossaryEntry = GLOSSARY[key];
    if (entry.factor) {
      const factor = this.factors().get(key);
      if (!factor) {
        return '';
      }
      const direction = factor.better === 'low' ? 'Niedriger' : 'Höher';
      const role = entry.role === 'value' ? 'Value' : 'Quality';
      return `${factor.hint} ${direction} ist besser. ${role}-Faktor.`;
    }
    return termTip(entry, params);
  }

  /** Alle Begriffe nach Gruppen, gefiltert nach dem Suchtext (Label, Tooltip, Erklärung). */
  groups(search = '', params: TipParams = {}): { name: GlossaryGroup; items: GlossaryItem[] }[] {
    const needle = search.trim().toLowerCase();
    const items = (Object.keys(GLOSSARY) as TermKey[]).map((key) => {
      const entry: GlossaryEntry = GLOSSARY[key];
      const item: GlossaryItem = {
        key,
        label: entry.label,
        tip: this.tip(key, params),
        long: entry.long,
        role: entry.role ? ROLES[entry.role] : undefined,
      };
      return { group: entry.group, item };
    });
    return GROUPS.map((name) => ({
      name,
      items: items
        .filter(({ group }) => group === name)
        .map(({ item }) => item)
        .filter(
          (item) =>
            !needle ||
            `${item.label} ${item.tip} ${item.long ?? ''}`.toLowerCase().includes(needle),
        ),
    })).filter((group) => group.items.length > 0);
  }
}
