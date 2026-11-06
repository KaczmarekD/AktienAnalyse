// Deutsche Zahlen- und Datumsformate (0,78; 12,3 %; 30.10.2026). Die Meldungen von Zod stehen
// in shared/zod-de.ts, damit zod nicht ins Start-Bundle kommt.
import { registerLocaleData } from '@angular/common';
import localeDe from '@angular/common/locales/de';

registerLocaleData(localeDe);
