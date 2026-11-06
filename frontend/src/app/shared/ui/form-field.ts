import { MAT_FORM_FIELD_DEFAULT_OPTIONS } from '@angular/material/form-field';

/**
 * Eingabefelder mit Rand wie in der Designvorlage. Ansichten mit Formularfeldern nehmen das in ihre
 * providers auf. Es steht nicht in app.config.ts, sonst käme das Formularfeld von Material samt
 * Angular Forms ins Start-Bundle (rund 150 kB, Grenze 500 kB).
 */
export const FORM_FIELD_DEFAULTS = {
  provide: MAT_FORM_FIELD_DEFAULT_OPTIONS,
  useValue: { appearance: 'outline' },
};
