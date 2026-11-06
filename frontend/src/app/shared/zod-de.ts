// Meldungen der Pruefung im Formular (Zod aus dem erzeugten Client) auf Deutsch. Nur Ansichten mit
// Formular importieren diese Datei: So laedt zod mit ihnen und nicht im Start-Bundle (500 kB).
import { config } from 'zod';
import { de } from 'zod/locales';

config(de());
