// Deutsche Zahlen- und Datumsformate (0,78; 12,3 %; 30.10.2026)
import { registerLocaleData } from '@angular/common';
import localeDe from '@angular/common/locales/de';
import * as z from 'zod';

registerLocaleData(localeDe);
// Meldungen der Pruefung im Formular (Zod aus dem erzeugten Client) auf Deutsch
z.config(z.locales.de());
