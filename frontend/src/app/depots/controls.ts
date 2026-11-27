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

/** D4.5: Tooltips und Texte der Analyse (docs/architecture/depot/analyse.md, Abschnitt Depot). */
export const ANALYSIS = {
  section:
    'Aus dem neuesten Depotstand, den letzten Kursen, dem jüngsten Bewertungslauf und den Stammdaten, bei jedem Aufruf neu gerechnet. Anteile beziehen sich auf den Wert des Depots.',
  noData: 'keine Daten',
  quality:
    'Wertgewichtet über die Aktien mit Score, eingeordnet in DAX/MDAX. Positionen ohne Score zählen nicht mit.',
  composite: 'Composite der Aktien, gewichtet mit ihrem Wert. 0 bis 1, höher ist besser.',
  value: 'Value-Score der Aktien, gewichtet mit ihrem Wert.',
  qualityScore: 'Quality-Score der Aktien, gewichtet mit ihrem Wert.',
  covered: 'Anteil am Wert der Aktien, für den es einen Composite gibt.',
  valueTraps: 'Zahl der Aktien mit Verdacht auf eine Value-Falle.',
  quintile:
    'Fünftel von DAX/MDAX nach Composite-Perzentil: oberstes = besser als vier Fünftel der Titel.',
  quintileCount: 'Zahl der Aktien in diesem Fünftel.',
  quintileWeight: 'Anteil am Wert der Aktien mit Perzentil.',
  fund: 'ETF im Depot.',
  fundScore:
    'Composite der Positionen des ETF, gewichtet mit ihrem Anteil. Erst ab 50 % bewertetem Gewicht.',
  fundCovered: 'Anteil des ETF, dessen Positionen einen Composite haben.',
  allocation:
    'Verteilung des Depots. Sektor und Land mit Durchschau durch die ETFs, soweit ihre Stammdaten sie nennen.',
  assetClass: 'Aktien, ETFs, Anleihen und Kasse.',
  currency: 'Währung der Wertpapiere; bei ETFs die Fondswährung, nicht die ihrer Positionen.',
  sector: 'Sektor der Aktien; bei ETFs nach ihren Stammdaten.',
  country: 'Land der Aktien und Anleihen nach ISIN (Sitz); bei ETFs nach ihren Stammdaten.',
  share: 'Anteil am Wert des Depots.',
  amount: 'Wert in Euro.',
  concentration: 'Wie stark das Depot an einzelnen Titeln hängt, mit Durchschau durch die ETFs.',
  largest: 'Titel mit dem größten Anteil, direkt gehalten und in ETFs zusammen.',
  top: 'Anteil der fünf größten Titel zusammen.',
  effective:
    'Effektive Zahl der Positionen: 1 / Summe der quadrierten Gewichte. Ein ETF zählt als eine.',
  lowerBound:
    'Mindestens: Ein ETF nennt nur seine größten Positionen oder keine, der Rest fehlt in der Rechnung.',
  costs: 'Laufende Kosten der ETFs aus ihrer TER.',
  ter: 'TER (Total Expense Ratio): laufende Kosten eines ETF in Prozent pro Jahr, gewichtet mit dem Wert.',
  runningCosts: 'Wert der ETFs mal TER: so viel kosten sie etwa im Jahr.',
  costsCovered: 'Anteil am Wert der ETFs, für den eine TER bekannt ist.',
  bonds:
    'Kennzahlen der Anleihen zum letzten Kurs, jährlicher Kupon nach ACT/ACT ICMA wie bei Bundesanleihen.',
  ytm: 'Rendite bis Fälligkeit pro Jahr, gewichtet mit dem Wert.',
  duration:
    'Modifizierte Duration in Jahren: um wie viel Prozent der Kurs etwa fällt, wenn die Rendite um einen Prozentpunkt steigt.',
  bondsCovered: 'Anteil am Wert der Anleihen, für den es eine Rendite gibt.',
  bond: 'Anleihe im Depot.',
  nextCoupon: 'Nächster Kupontermin.',
  bondNote: 'Warum es keine Rendite gibt.',
  maturity: 'Jahr der Fälligkeit.',
  maturityValue: 'Wert der Anleihen, die in diesem Jahr fällig werden.',
  data: 'Woher die Zahlen kommen und wie alt sie sind.',
  valued: 'Positionen mit Kurs von allen Positionen. Ohne Kurs zählt eine Position nicht mit.',
  lookThrough: 'Anteil am Wert der ETFs, deren Positionen bekannt sind.',
  oldestPrice: 'Ältester Kurs, der in die Analyse eingeht.',
  oldestScore: 'Datenstand des ältesten Bewertungslaufs der Aktien.',
  oldestFund: 'Ältester Stand der ETF-Daten.',
  watchlist: 'Eine Beobachtungsliste hat keine Mengen und damit keine Analyse.',
} as const;

/** D4.5: Anlageklassen und Schlüssel ohne Zuordnung der Allokation. */
export const SLICE = {
  equity: 'Aktien',
  etf: 'ETFs',
  bond: 'Anleihen',
  other: 'Sonstige',
  cash: 'Kasse',
  bonds: 'Anleihen',
  unknown: 'ohne Angabe',
  no_look_through: 'ohne Durchschau',
} as const satisfies Record<string, string>;

/** D4.5: Warum eine Anleihe keine Rendite hat (``special`` der API). */
export const BOND_SPECIAL: Record<string, string> = {
  floating: 'variabel verzinst',
  convertible: 'Wandelanleihe',
  perpetual: 'ohne Fälligkeit',
  no_terms: 'ohne Kupon in den Stammdaten',
  matured: 'fällig',
  out_of_range: 'Kurs unplausibel',
};

const regions = new Intl.DisplayNames(['de'], { type: 'region' });

/** Land aus dem ISO-Code (ISIN-Präfix); XS = internationale Anleihe, Unbekanntes bleibt. */
export function countryName(code: string): string {
  if (code in SLICE) {
    return SLICE[code as keyof typeof SLICE];
  }
  if (code === 'XS') {
    return 'international';
  }
  if (!/^[A-Z]{2}$/.test(code)) {
    return code;
  }
  try {
    return regions.of(code) ?? code;
  } catch {
    return code;
  }
}

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
