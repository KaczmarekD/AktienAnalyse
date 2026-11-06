import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  InjectionToken,
  input,
  signal,
  untracked,
} from '@angular/core';
import { FormField, form, validateStandardSchema } from '@angular/forms/signals';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSliderModule } from '@angular/material/slider';
import { MatTooltipModule } from '@angular/material/tooltip';

import {
  getProfileResource,
  listFactorsResource,
  previewProfileResource,
} from '../api/@angular/common.gen';
import { activateProfileVersion, saveProfileVersion } from '../api/sdk.gen';
import type {
  Factor,
  Preview,
  ProfileParamsV1Input,
  ProfileParamsV1Output,
} from '../api/types.gen';
import { zProfileParamsV1Input } from '../api/zod.gen';
import { optionalNumber } from '../shared/api-error';
import { DayPipe, DayTimePipe, MISSING, NumPipe } from '../shared/format';
import { AuthStore } from '../shared/auth/auth.store';
import { CONTROLS } from '../shared/glossary/controls';
import { ENTRIES, termTip } from '../shared/glossary/glossary';
import { loaded, loadError } from '../shared/resource';
import { BackLink } from '../shared/ui/back-link';
import { FORM_FIELD_DEFAULTS } from '../shared/ui/form-field';
import { AppIcon, IconName } from '../shared/ui/icon';
import { InfoTip } from '../shared/ui/info-tip';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { PageHeader } from '../shared/ui/page-header';
import { AppSection } from '../shared/ui/section';
import { AppState } from '../shared/ui/state';
import { Term } from '../shared/ui/term';
import { ValueTrapBadge } from '../shared/ui/value-trap-badge';
import '../shared/zod-de';

/** Wartezeit der Live-Vorschau nach der letzten Änderung (ms); Tests setzen 0. */
export const PREVIEW_DEBOUNCE_MS = new InjectionToken<number>('PREVIEW_DEBOUNCE_MS', {
  factory: () => 300,
});

const TOP = 20;
const MIO = 1_000_000;

type Params = Required<ProfileParamsV1Input>;
type ValueKey = Params['value_factors'][number];
type QualityKey = Params['quality_factors'][number];
type ShareField = 'min_value_factor_share' | 'min_quality_factor_share';

/** Feldfehler in der Einheit, die das Feld zeigt (Prozent, Mio. €), statt der Meldung von Zod. */
const FIELD_RANGE: Partial<Record<keyof Params, string>> = {
  value_weight: 'Wert zwischen 0 und 100 %.',
  min_market_cap: 'Wert ab 0 Mio. €.',
  min_value_factor_share: 'Wert zwischen 0 und 100 %.',
  min_quality_factor_share: 'Wert zwischen 0 und 100 %.',
  value_trap_value_threshold: 'Wert zwischen 0 und 1.',
  value_trap_quality_threshold: 'Wert zwischen 0 und 1.',
};

/** Veränderung eines Rangs gegenüber dem aktiven Profil, für die Spalte Δ. */
interface Delta {
  icon?: IconName;
  text: string;
  tip: string;
}

/** Parameter aus der API, ergänzt um die Standardwerte des Schemas, als Formular-Modell. */
function toModel(params: ProfileParamsV1Input | ProfileParamsV1Output): Params {
  const parsed = zProfileParamsV1Input.parse(params);
  return {
    ...parsed,
    value_factors: parsed.value_factors ?? [],
    quality_factors: parsed.quality_factors ?? [],
  };
}

/** Gleiche Parameter, unabhängig von der Reihenfolge der Faktoren. */
function sameParams(a: Params, b: Params): boolean {
  const normal = (params: Params) =>
    JSON.stringify(
      Object.entries({
        ...params,
        value_factors: [...params.value_factors].sort(),
        quality_factors: [...params.quality_factors].sort(),
      }).sort(([x], [y]) => x.localeCompare(y)),
    );
  return normal(a) === normal(b);
}

/** Zahl aus einem Eingabefeld; leer oder ungültig ergibt NaN, das die Prüfung meldet. */
function inputNumber(event: Event): number {
  return (event.target as HTMLInputElement).valueAsNumber;
}

/** Rundet für die Anzeige, damit 0,55 als 55 erscheint und nicht als 55,000000000000001. */
function round(value: number, digits = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

/** Meldungen einer Antwort mit 422 (FastAPI: detail als Liste) als ein Text. */
function validationMessage(error: HttpErrorResponse): string {
  const detail = (error.error as { detail?: unknown } | null)?.detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => String((item as { msg?: unknown }).msg ?? '').replace(/^Value error, /, ''))
      .join('; ');
  }
  return typeof detail === 'string' ? detail : 'Die Parameter sind ungültig.';
}

/**
 * Editor eines Scoring-Profils (/profiles/:profileId, ADR-0009, P3.7, neu gestaltet mit
 * Track G, G7).
 *
 * Grundlage ist immer die neueste Version. Die Ansicht zeigt Gewichte und Abdeckung in Prozent
 * und die Größenschwelle in Mio. €, das Modell bleibt bei 0 bis 1 und Euro. Jede Änderung zeigt
 * nach kurzer Pause die Vorschau gegen das aktive Profil. Speichern legt eine neue Version an
 * (If-Match = Grundlage), aktiv wird sie erst mit „Aktivieren“.
 */
@Component({
  selector: 'app-profile-editor-page',
  imports: [
    AppIcon,
    AppSection,
    AppState,
    BackLink,
    DayPipe,
    DayTimePipe,
    FormField,
    InfoTip,
    MatButtonModule,
    MatCheckboxModule,
    MatExpansionModule,
    MatFormFieldModule,
    MatInputModule,
    MatSliderModule,
    MatTooltipModule,
    NoticeBox,
    NumPipe,
    PageHeader,
    Term,
    ValueTrapBadge,
  ],
  providers: [FORM_FIELD_DEFAULTS],
  templateUrl: './profile-editor-page.html',
  styleUrl: './profile-editor-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileEditorPage {
  readonly profileId = input<number | undefined, unknown>(undefined, {
    transform: optionalNumber,
  });

  private readonly delay = inject(PREVIEW_DEBOUNCE_MS);
  /** D1.4: Speichern und Aktivieren nur für Admins; die Vorschau dürfen alle. */
  protected readonly admin = inject(AuthStore).isAdmin;
  protected readonly controls = CONTROLS;
  protected readonly tips = {
    active: termTip(ENTRIES.active),
    dropNegative: termTip(ENTRIES.drop_negative_value_metrics),
  };

  private readonly profileResource = getProfileResource(() => {
    const id = this.profileId();
    return id === undefined ? undefined : { path: { profile_id: id } };
  });
  private readonly factorsResource = listFactorsResource(() => ({}));

  protected readonly profile = computed(() => loaded(this.profileResource));
  protected readonly error = computed(() =>
    loadError(this.profileResource, 'Profil nicht gefunden.'),
  );
  protected readonly valueFactors = computed(() => this.factorsOf('value'));
  protected readonly qualityFactors = computed(() => this.factorsOf('quality'));

  /** Die Version, auf der die Änderung beruht (If-Match beim Speichern). */
  protected readonly basedOn = signal<number | undefined>(undefined);
  /** Ihre Parameter: „Verwerfen“ kehrt zu ihnen zurück. */
  private readonly base = signal<Params>(toModel({}));
  protected readonly model = signal<Params>(toModel({}));
  protected readonly form = form(this.model, (path) => {
    validateStandardSchema(path, zProfileParamsV1Input);
  });
  protected readonly comment = signal('');

  // Die Ansicht in Prozent und Mio. €
  protected readonly weightPct = computed(() => round(this.model().value_weight * 100, 1));
  protected readonly mio = computed(() => round(this.model().min_market_cap / MIO));
  protected readonly sharePct = computed(() => ({
    min_value_factor_share: round(this.model().min_value_factor_share * 100, 1),
    min_quality_factor_share: round(this.model().min_quality_factor_share * 100, 1),
  }));
  protected readonly percentLabel = (value: number) => `${value} %`;
  protected readonly shareFields: { key: ShareField; label: string }[] = [
    { key: 'min_value_factor_share', label: 'Mindestabdeckung Value' },
    { key: 'min_quality_factor_share', label: 'Mindestabdeckung Quality' },
  ];
  /** Schwellen des Formulars für den Tooltip der Value-Trap in der Vorschau */
  protected readonly trapParams = computed(() => ({
    value_trap_value_threshold: this.model().value_trap_value_threshold,
    value_trap_quality_threshold: this.model().value_trap_quality_threshold,
  }));

  protected readonly notice = signal<Notice | undefined>(undefined);
  protected readonly conflict = signal(false);
  protected readonly busy = signal(false);
  protected readonly saving = signal(false);
  private forceReset = false;

  private readonly debounced = signal<Params | undefined>(undefined);
  private readonly previewResource = previewProfileResource(() => {
    const params = this.debounced();
    return params === undefined ? undefined : { body: params, query: { top: TOP } };
  });
  protected readonly preview = computed<Preview | undefined>(() => loaded(this.previewResource));
  /** 422: eine Regel über mehrere Felder, die nur der Server prüft (z. B. 2 Faktoren). */
  protected readonly ruleViolation = computed(() => {
    const error = this.previewResource.error();
    return error instanceof HttpErrorResponse && error.status === 422
      ? validationMessage(error)
      : undefined;
  });
  protected readonly ruleNotice = computed<Notice | undefined>(() => {
    const rule = this.ruleViolation();
    return rule ? { text: rule, error: true } : undefined;
  });
  protected readonly previewError = computed(() =>
    this.ruleViolation()
      ? undefined
      : loadError(
          this.previewResource,
          'Noch kein Bewertungslauf, mit dem sich vergleichen ließe.',
        ),
  );
  protected readonly topRows = computed(() =>
    (this.preview()?.rows ?? []).filter((row) => row.rank !== null).slice(0, TOP),
  );

  /** Die Parameter weichen von der Grundlage ab. */
  protected readonly changed = computed(() => !sameParams(this.model(), this.base()));
  /** Etwas ist geändert, auch nur der Kommentar: Die Speichern-Leiste klebt unten. */
  protected readonly dirty = computed(() => this.changed() || this.comment().trim() !== '');
  protected readonly nextVersion = computed(() => (this.basedOn() ?? 0) + 1);
  /** Warum Speichern gesperrt ist, sonst undefined. */
  private readonly blocked = computed(() => {
    if (!this.form().valid()) {
      return CONTROLS['editor.blocked.invalid'];
    }
    if (this.ruleViolation() !== undefined) {
      return CONTROLS['editor.blocked.rule'];
    }
    if (!this.changed()) {
      return CONTROLS['editor.blocked.unchanged'];
    }
    return undefined;
  });
  protected readonly canSave = computed(
    () => this.basedOn() !== undefined && this.blocked() === undefined && !this.busy(),
  );
  protected readonly saveTip = computed(
    () => this.blocked() ?? CONTROLS['editor.save'](this.nextVersion()),
  );
  protected readonly discardTip = computed(() =>
    CONTROLS['editor.discard'](this.basedOn() ?? this.nextVersion() - 1),
  );

  constructor() {
    // Grundlage: die neueste Version, beim Laden und nach Speichern oder Neu laden
    effect(() => {
      const detail = this.profile();
      const newest = detail?.versions[0];
      if (detail === undefined || newest === undefined) {
        return;
      }
      untracked(() => {
        if (this.forceReset || this.basedOn() !== newest.version) {
          this.forceReset = false;
          const params = toModel(newest.params);
          this.base.set(params);
          this.model.set(params);
          this.basedOn.set(newest.version);
        }
      });
    });
    // Live-Vorschau: erst nach einer Pause und nur mit gültigem Formular
    effect((onCleanup) => {
      const params = this.basedOn() !== undefined && this.form().valid() ? this.model() : undefined;
      if (this.delay === 0) {
        this.debounced.set(params);
        return;
      }
      const timer = setTimeout(() => this.debounced.set(params), this.delay);
      onCleanup(() => clearTimeout(timer));
    });
  }

  protected setWeight(event: Event): void {
    const percent = inputNumber(event);
    this.model.update((model) => ({ ...model, value_weight: round(percent / 100, 4) }));
  }

  protected setMio(event: Event): void {
    const mio = inputNumber(event);
    this.model.update((model) => ({ ...model, min_market_cap: Math.round(mio * MIO) }));
  }

  protected setShare(field: ShareField, event: Event): void {
    const percent = inputNumber(event);
    this.model.update((model) => ({ ...model, [field]: round(percent / 100, 4) }));
  }

  protected isActive(group: 'value' | 'quality', key: string): boolean {
    const factors: readonly string[] =
      group === 'value' ? this.model().value_factors : this.model().quality_factors;
    return factors.includes(key);
  }

  protected toggleFactor(group: 'value' | 'quality', key: string, on: boolean): void {
    this.model.update((model) => {
      if (group === 'value') {
        const keys = model.value_factors.filter((k) => k !== key);
        return { ...model, value_factors: on ? [...keys, key as ValueKey].sort() : keys };
      }
      const keys = model.quality_factors.filter((k) => k !== key);
      return { ...model, quality_factors: on ? [...keys, key as QualityKey].sort() : keys };
    });
  }

  protected setDropNegative(on: boolean): void {
    this.model.update((model) => ({ ...model, drop_negative_value_metrics: on }));
  }

  protected onComment(event: Event): void {
    this.comment.set((event.target as HTMLInputElement).value);
  }

  /** Feldfehler in der Einheit des Felds; ein Feld zeigt höchstens eine Meldung. */
  protected errorsOf(field: keyof Params): string[] {
    const errors = this.form[field]().errors();
    if (errors.length === 0) {
      return [];
    }
    const message =
      FIELD_RANGE[field] ??
      errors[0].message ??
      (errors[0] as { issue?: { message?: string } }).issue?.message;
    return message ? [message] : [];
  }

  protected nameOf(symbol: string): string {
    return this.preview()?.rows.find((row) => row.symbol === symbol)?.name ?? symbol;
  }

  /** Tooltip einer Zusammenfassung der Vorschau mit den Namen der Titel. */
  protected namesTip(intro: string, symbols: string[]): string {
    return `${intro}: ${symbols.map((symbol) => this.nameOf(symbol)).join(', ')}.`;
  }

  protected delta(rank: number | null, before: number | null): Delta {
    if (rank === null) {
      return { text: MISSING, tip: 'Mit diesen Parametern ohne Rang.' };
    }
    if (before === null) {
      return { text: 'neu', tip: 'Mit dem aktiven Profil ohne Rang.' };
    }
    const moved = before - rank;
    if (moved === 0) {
      return { text: MISSING, tip: 'Gleicher Rang wie mit dem aktiven Profil.' };
    }
    const places = Math.abs(moved) === 1 ? 'Platz' : 'Plätze';
    const way = moved > 0 ? 'besser' : 'schlechter';
    return {
      icon: moved > 0 ? 'arrow_upward' : 'arrow_downward',
      text: String(Math.abs(moved)),
      tip: `${Math.abs(moved)} ${places} ${way} als mit dem aktiven Profil (Rang ${before}).`,
    };
  }

  protected direction(factor: Factor): string {
    return factor.better === 'low' ? 'niedriger ist besser' : 'höher ist besser';
  }

  protected factorTip(factor: Factor): string {
    return `${factor.label} ein- oder ausschalten. Ausgeschaltet zählt der Faktor in diesem Profil nicht.`;
  }

  protected activateTip(version: number): string {
    return CONTROLS['editor.activate'](version);
  }

  /** Zurück zur Grundlage: Parameter und Kommentar. */
  protected discard(): void {
    if (!this.dirty()) {
      return;
    }
    this.model.set(this.base());
    this.comment.set('');
  }

  protected async save(): Promise<void> {
    const id = this.profileId();
    const basedOn = this.basedOn();
    // disabledInteractive: Der gesperrte Button bleibt klickbar, der Klick darf nichts tun
    if (id === undefined || basedOn === undefined || !this.canSave()) {
      return;
    }
    this.busy.set(true);
    this.saving.set(true);
    this.notice.set(undefined);
    this.conflict.set(false);
    const comment = this.comment().trim();
    const result = await saveProfileVersion({
      path: { profile_id: id },
      body: { params: this.model(), comment: comment === '' ? null : comment },
      headers: { 'if-match': `"${basedOn}"` },
    });
    this.busy.set(false);
    this.saving.set(false);
    if (result.data) {
      this.notice.set({ text: `Version ${result.data.version} gespeichert, noch nicht aktiv.` });
      this.comment.set('');
      this.profileResource.reload();
    } else if (result.response?.status === 409) {
      this.conflict.set(true);
    } else {
      this.notice.set({ text: 'Speichern hat nicht geklappt.', error: true });
    }
  }

  /** Nach einem Konflikt: neueste Version laden, eigene Änderungen verwerfen. */
  protected reload(): void {
    this.conflict.set(false);
    this.forceReset = true;
    this.profileResource.reload();
  }

  protected async activate(version: number): Promise<void> {
    const id = this.profileId();
    if (id === undefined) {
      return;
    }
    this.busy.set(true);
    this.notice.set(undefined);
    const result = await activateProfileVersion({ path: { profile_id: id }, body: { version } });
    this.busy.set(false);
    if (result.data) {
      this.notice.set({ text: `Version ${version} ist aktiv. Der nächste Lauf rechnet damit.` });
      this.profileResource.reload();
    } else {
      this.notice.set({ text: 'Aktivieren hat nicht geklappt.', error: true });
    }
  }

  private factorsOf(group: 'value' | 'quality'): Factor[] {
    return (loaded(this.factorsResource) ?? []).filter((factor) => factor.group === group);
  }
}
