// Tooltips und feste Texte der Depot-Seiten (D3.6). Eigene Datei wie shared/auth/controls.ts:
// Sie gehört zu den Ansichten, nicht ins Start-Bundle.

export const DEPOT_CONTROLS = {
  create: 'Legt ein neues Depot oder eine Beobachtungsliste an.',
  open: 'Öffnet das Depot mit allen Positionen, dem Verlauf und der Datei.',
  showArchived:
    'Zeigt auch archivierte Depots. Sie sind schreibgeschützt, bis du sie wiederherstellst.',
  archived: 'Archiviert: schreibgeschützt und nicht in der Liste. Gelöscht ist nichts.',
  kindDepot: 'Wertpapiere mit Menge und Kasse. Das Depot hat einen Wert.',
  kindWatchlist: 'Wertpapiere ohne Menge, nur zum Beobachten. Sie hat keinen Wert.',
  cancel: 'Schließt den Dialog, ohne etwas zu ändern.',
  confirmCreate: 'Legt das Depot an und öffnet es.',
  confirmRename: 'Speichert Name und Beschreibung.',
  edit: 'Positionen und Kasse ändern. Gespeichert wird ein neuer Depotstand, der alte bleibt.',
  rename: 'Name und Beschreibung ändern.',
  archive: 'Archiviert das Depot. Es wird schreibgeschützt, gelöscht wird nichts.',
  restore: 'Holt das Depot aus dem Archiv zurück, danach lässt es sich wieder ändern.',
  archiveConfirm: 'Archiviert das Depot. Du kannst es jederzeit wiederherstellen.',
  archiveCancel: 'Lässt das Depot, wie es ist.',
  save: 'Speichert die Positionen und die Kasse als neuen Depotstand.',
  saveBlocked: 'Erst die markierten Felder korrigieren.',
  discard: 'Verwirft deine Änderungen und zeigt wieder den gespeicherten Stand.',
  reload: 'Lädt den neuesten Depotstand. Deine Änderungen gehen dabei verloren.',
  remove: 'Entfernt die Position aus dem Depot.',
  add: 'Fügt das Wertpapier dem Depot hinzu.',
  addDisabled: 'Ohne ISIN lässt sich das Wertpapier nicht hinzufügen. Suche nach ISIN oder WKN.',
  addPresent: 'Das Wertpapier steht schon im Depot.',
  search: 'Sucht nach ISIN, WKN, Name oder Symbol; ab zwei Zeichen.',
  unit: 'Stück; bei Anleihen der Nennwert in Euro.',
  csv: 'Lädt die Positionen des neuesten Depotstands als CSV-Datei im eigenen Format herunter.',
  chooseFile:
    'Wählt eine CSV-Datei im eigenen Format (isin;menge;einstand;notiz) und zeigt den Abgleich. Gespeichert wird erst mit „Übernehmen“.',
  apply: 'Übernimmt die Datei als neuen Depotstand. Die Kasse bleibt, wie sie ist.',
  applyBlocked: 'Erst die abgelehnten Zeilen in der Datei korrigieren und sie neu wählen.',
  cancelImport: 'Verwirft den Abgleich, ohne etwas zu speichern.',
} as const;

/** Warum eine Position keinen Wert hat (``missing`` der API). */
export const MISSING_VALUE = {
  price: { label: 'Kurs fehlt', tip: 'Für dieses Wertpapier gibt es noch keinen Schlusskurs.' },
  fx: {
    label: 'Währungskurs fehlt',
    tip: 'Der Kurs ist in fremder Währung, und der Kurs zum Euro fehlt noch.',
  },
  unit: {
    label: 'Einheit passt nicht',
    tip: 'Der Kurs ist je Stück, die Menge ein Nennwert, oder umgekehrt. Prüfe die Einheit.',
  },
} as const;

/** D4.2: Woher die Scores einer Aktie kommen (``reference`` der API). */
export const SCORE_REFERENCE = {
  universe: {
    label: 'DAX/MDAX',
    tip: 'Titel des Rankings: dieselben Scores wie dort. Der Name führt ins Titel-Detail.',
  },
  below_size_filter: {
    label: 'unter dem Größenfilter',
    tip: 'Titel aus DAX/MDAX, zu klein für das Ranking. Eingeordnet, als stünde er allein dabei.',
  },
  outside: {
    label: 'außerhalb DAX/MDAX',
    tip: 'Eingeordnet in DAX/MDAX: die Ränge, die die Aktie dort hätte. Die übrigen Titel bleiben, wie sie sind.',
  },
} as const;

/** D4.2: Warum eine Aktie keinen Composite hat (``reason`` der API). */
export const SCORE_REASON = {
  no_quality: { label: 'ohne Quality', tip: 'Es fehlen Quality-Kennzahlen, etwa bei Banken.' },
  no_value: { label: 'ohne Value', tip: 'Es fehlen Value-Kennzahlen.' },
  no_data: { label: 'ohne Daten', tip: 'Es fehlen Value- und Quality-Kennzahlen.' },
} as const;

/** D4.2: Tooltip, wenn eine Position keine Scores hat. */
export const NO_SCORE =
  'Scores gibt es für Aktien, sobald ein Bewertungslauf sie kennt. ETFs und Anleihen haben keine.';

/** Herkunft eines Depotstands. */
export const SOURCE = {
  manual: 'von Hand',
  import: 'aus einer Datei',
  bank: 'von der Bank',
} as const;

/** Status einer ISIN im Abgleich einer Datei. */
export const IMPORT_STATUS = {
  new: { label: 'neu', tip: 'Steht in der Datei, aber noch nicht im Depot.' },
  changed: { label: 'geändert', tip: 'Menge, Einstand, Einheit oder Notiz ändern sich.' },
  unchanged: { label: 'gleich', tip: 'Steht unverändert im Depot und in der Datei.' },
  removed: {
    label: 'entfällt',
    tip: 'Steht im Depot, aber nicht in der Datei. Die Position entfällt.',
  },
} as const;

/** Einheit einer Menge. */
export const UNIT = { pieces: 'Stück', nominal: 'Nennwert' } as const;

/** Art eines Depots. */
export const KIND = { depot: 'Depot', watchlist: 'Beobachtungsliste' } as const;

/**
 * Eine Zahl aus einem Eingabefeld (Dezimalkomma, Tausenderpunkte erlaubt) als Text für die API
 * ("1.500,25" → "1500.25"). Leer ergibt null, keine Zahl undefined. `signed` erlaubt ein Minus,
 * etwa für eine Kasse im Dispo.
 */
export function parseAmount(text: string, signed = false): string | null | undefined {
  const value = text.trim().replace(/\s/g, '');
  if (value === '') {
    return null;
  }
  const normal = value.includes(',') ? value.replace(/\./g, '').replace(',', '.') : value;
  const pattern = signed ? /^-?\d+(\.\d+)?$/ : /^\d+(\.\d+)?$/;
  return pattern.test(normal) ? normal : undefined;
}

/** Eine Zahl der API für ein Eingabefeld: ohne Nullen am Ende, mit Dezimalkomma ("12.50" → "12,5"). */
export function toInput(value: string | number | null | undefined): string {
  if (value == null || value === '') {
    return '';
  }
  let text = String(value);
  if (text.includes('.')) {
    text = text.replace(/0+$/, '').replace(/\.$/, '');
  }
  return text.replace('.', ',');
}
