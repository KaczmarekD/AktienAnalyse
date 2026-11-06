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
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';

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
import { DayPipe, DayTimePipe, MISSING, MrdPipe, NumPipe, PctPipe } from '../shared/format';
import { loaded, loadError } from '../shared/resource';
import { BackLink } from '../shared/ui/back-link';
import { Notice, NoticeBox } from '../shared/ui/notice';
import { PageHeader } from '../shared/ui/page-header';
import { ValueTrapBadge } from '../shared/ui/value-trap-badge';
import '../shared/zod-de';

/** Wartezeit der Live-Vorschau nach der letzten Aenderung (ms); Tests setzen 0. */
export const PREVIEW_DEBOUNCE_MS = new InjectionToken<number>('PREVIEW_DEBOUNCE_MS', {
  factory: () => 300,
});

const TOP = 20;

type Params = Required<ProfileParamsV1Input>;
type ValueKey = Params['value_factors'][number];
type QualityKey = Params['quality_factors'][number];

/** Parameter aus der API, ergaenzt um die Standardwerte des Schemas, als Formular-Modell. */
function toModel(params: ProfileParamsV1Input | ProfileParamsV1Output): Params {
  const parsed = zProfileParamsV1Input.parse(params);
  return {
    ...parsed,
    value_factors: parsed.value_factors ?? [],
    quality_factors: parsed.quality_factors ?? [],
  };
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
 * Editor eines Scoring-Profils (ADR-0009, P3.7 mit den Endpunkten aus P3.3).
 *
 * Grundlage ist immer die neueste Version. Jede Aenderung zeigt nach kurzer Pause die
 * Vorschau gegen das aktive Profil. Speichern legt eine neue Version an (If-Match = Grundlage),
 * aktiv wird sie erst mit "Aktivieren".
 */
@Component({
  selector: 'app-profile-editor-page',
  imports: [
    BackLink,
    DayPipe,
    DayTimePipe,
    FormField,
    MatButtonModule,
    MatCheckboxModule,
    MatFormFieldModule,
    MatInputModule,
    MrdPipe,
    NoticeBox,
    NumPipe,
    PageHeader,
    PctPipe,
    ValueTrapBadge,
  ],
  templateUrl: './profile-editor-page.html',
  styleUrl: './profile-editor-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProfileEditorPage {
  readonly profileId = input<number | undefined, unknown>(undefined, {
    transform: optionalNumber,
  });

  private readonly delay = inject(PREVIEW_DEBOUNCE_MS);

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

  /** Die Version, auf der die Aenderung beruht (If-Match beim Speichern). */
  protected readonly basedOn = signal<number | undefined>(undefined);
  protected readonly model = signal<Params>(toModel({}));
  protected readonly form = form(this.model, (path) => {
    validateStandardSchema(path, zProfileParamsV1Input);
  });
  protected readonly comment = signal('');
  protected readonly quality = computed(() => 1 - this.model().value_weight);

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
  /** 422: eine Regel ueber mehrere Felder, die nur der Server prueft (z. B. 2 Faktoren). */
  protected readonly ruleViolation = computed(() => {
    const error = this.previewResource.error();
    return error instanceof HttpErrorResponse && error.status === 422
      ? validationMessage(error)
      : undefined;
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
  protected readonly canSave = computed(
    () =>
      this.basedOn() !== undefined &&
      this.form().valid() &&
      this.ruleViolation() === undefined &&
      !this.busy(),
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
          this.model.set(toModel(newest.params));
          this.basedOn.set(newest.version);
        }
      });
    });
    // Live-Vorschau: erst nach einer Pause und nur mit gueltigem Formular
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
    this.comment.set((event.target as HTMLTextAreaElement).value);
  }

  protected errorsOf(field: keyof Params): string[] {
    return this.form[field]()
      .errors()
      .map((error) => error.message ?? (error as { issue?: { message?: string } }).issue?.message)
      .filter((message): message is string => !!message);
  }

  protected nameOf(symbol: string): string {
    return this.preview()?.rows.find((row) => row.symbol === symbol)?.name ?? symbol;
  }

  protected delta(rank: number | null, before: number | null): string {
    if (rank === null) {
      return MISSING;
    }
    if (before === null) {
      return 'neu';
    }
    const moved = before - rank;
    return moved > 0 ? `↑ ${moved}` : moved < 0 ? `↓ ${-moved}` : MISSING;
  }

  protected direction(factor: Factor): string {
    return factor.better === 'low' ? 'niedriger ist besser' : 'höher ist besser';
  }

  protected async save(): Promise<void> {
    const id = this.profileId();
    const basedOn = this.basedOn();
    if (id === undefined || basedOn === undefined) {
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

  /** Nach einem Konflikt: neueste Version laden, eigene Aenderungen verwerfen. */
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
