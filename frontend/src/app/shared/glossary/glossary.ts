// Eine Quelle für alle Texte des UI (docs/architecture/ui-neugestaltung.md, Tooltips und Begriffe):
// Label, Tooltip, lange Erklärung und Rolle im Score je Begriff, dazu die Texte der Bedienelemente.
// Die Faktortexte kommen von scoring (FACTOR_INFO über GET /api/v1/scoring/factors), hier stehen
// nur Label, Gruppe und Rolle der Faktoren. Regeln: höchstens zwei Sätze (200 Zeichen), erst „Was
// ist das?“, dann „Wie lesen?“, Abkürzungen zuerst ausgeschrieben.

export const GROUPS = [
  'Scores und Ranking',
  'Value-Faktoren',
  'Quality-Faktoren',
  'Nur zur Information',
  'Stammdaten',
  'Läufe',
  'Profile',
  'Depots',
] as const;

export type GlossaryGroup = (typeof GROUPS)[number];

/** Rolle im Score: Value- oder Quality-Faktor, oder nur zur Information. */
export type ScoreRole = 'value' | 'quality' | 'info';

/** Werte aus dem Profil eines Bewertungslaufs, die in Texte eingesetzt werden. Alle optional. */
export interface TipParams {
  value_weight?: number | null;
  value_trap_value_threshold?: number | null;
  value_trap_quality_threshold?: number | null;
  /** F2.3: Schwellen der Value-Trap-Regel mit Momentum */
  trap_momentum_max_rank?: number | null;
  trap_fscore_max?: number | null;
  min_market_cap?: number | null;
  /** Länge der Liste in der Vorschau des Profil-Editors */
  top?: number | null;
}

export interface GlossaryEntry {
  label: string;
  /** Kürzeres Label für Spaltenköpfe */
  short?: string;
  group: GlossaryGroup;
  /** Text des Tooltips; Funktionen setzen Werte aus dem Profil ein und kommen ohne sie aus. */
  tip?: string | ((params: TipParams) => string);
  /** Längere Erklärung für die Seite „Begriffe“ */
  long?: string;
  role?: ScoreRole;
  /** Abkürzung: darf im Text nicht ohne Erklärung stehen (Test 2) */
  abbr?: boolean;
  /** Faktor des Scorings: Text und Richtung liefert die API */
  factor?: boolean;
}

const NBSP = ' ';
const numbers = new Intl.NumberFormat('de-DE', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const whole = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 0 });

function percent(share: number): string {
  return `${whole.format(share * 100)}${NBSP}%`;
}

function score(value: number): string {
  return numbers.format(value);
}

function millions(euro: number): string {
  return `${whole.format(euro / 1e6)}${NBSP}Mio.${NBSP}€`;
}

export const GLOSSARY = {
  // Scores und Ranking
  rank: {
    group: 'Scores und Ranking',
    label: 'Rang',
    tip: 'Platz nach Composite unter allen bewerteten Titeln. Bei Gleichstand entscheidet das Symbol. Titel ohne Composite stehen am Ende.',
  },
  composite: {
    group: 'Scores und Ranking',
    label: 'Composite',
    tip: ({ value_weight: weight }) =>
      weight != null
        ? `Gesamtscore aus ${percent(weight)} Value und ${percent(1 - weight)} Quality. 0 bis 1, höher ist besser. Nur Titel mit beiden Teilscores bekommen ihn.`
        : 'Gesamtscore aus Value und Quality nach den Gewichten des Profils. 0 bis 1, höher ist besser. Nur Titel mit beiden Teilscores bekommen ihn.',
    long: 'Der Composite fasst beide Teilscores nach den Gewichten des Profils zusammen. Ein Titel ohne Value- oder Quality-Score bekommt keinen, sonst stünde ein Titel ohne Quality-Daten besser da als einer mit mittelmäßiger Quality.',
  },
  // D4.2: für Schwellen und Aussagen wie „unteres Fünftel“; der Composite streut eng um 0,5
  composite_percentile: {
    group: 'Scores und Ranking',
    label: 'Perzentil',
    tip: 'Rang des Composite unter allen Titeln mit Composite, 0 bis 100 %. 80 % heißt: besser als vier Fünftel.',
  },
  value_score: {
    group: 'Scores und Ranking',
    label: 'Value',
    tip: 'Wie günstig der Titel im Vergleich zu den anderen ist, gemessen an den Value-Faktoren. 0 bis 1, höher heißt günstiger.',
  },
  quality_score: {
    group: 'Scores und Ranking',
    label: 'Quality',
    tip: 'Wie solide das Geschäft im Vergleich ist, gemessen an den Quality-Faktoren. 0 bis 1, höher ist besser.',
    long: 'Quality soll Value-Fallen aussortieren: Die billigsten Aktien sind oft zu Recht billig.',
  },
  value_trap: {
    group: 'Scores und Ranking',
    label: 'Value-Trap?',
    tip: ({ value_trap_value_threshold: high, value_trap_quality_threshold: low }) =>
      high != null && low != null
        ? `Verdacht auf eine Value-Falle: günstig (Value ≥ ${score(high)}), aber schwache Qualität (Quality ≤ ${score(low)}). Solche Titel sind oft zu Recht billig.`
        : 'Verdacht auf eine Value-Falle: günstig (hoher Value-Score), aber schwache Qualität (niedriger Quality-Score). Solche Titel sind oft zu Recht billig.',
  },
  // F2.3 (ADR-0011): die zweite Regel, im Profil v1 aus
  value_trap_momentum: {
    group: 'Scores und Ranking',
    label: 'Value-Trap? (Momentum)',
    tip: ({
      value_trap_value_threshold: high,
      trap_momentum_max_rank: rank,
      trap_fscore_max: max,
    }) =>
      high != null && rank != null && max != null
        ? `Verdacht auf ein fallendes Messer: günstig (Value ≥ ${score(high)}), aber schwaches Momentum (Momentum-Rang ≤ ${score(rank)}) und keine fundamentale Stütze (F-Score ≤ ${max}).`
        : 'Verdacht auf ein fallendes Messer: günstig (hoher Value-Score), aber schwaches Momentum und keine fundamentale Stütze (niedriger F-Score).',
  },
  no_composite: {
    group: 'Scores und Ranking',
    label: 'ohne Composite',
    tip: 'Kein Composite, weil der Value- oder der Quality-Score fehlt. Meist liefert Yahoo keine Margen oder keinen ROIC, etwa bei Banken. Der Titel steht deshalb am Ende.',
  },
  below_threshold: {
    group: 'Scores und Ranking',
    label: 'unter Größenschwelle',
    tip: ({ min_market_cap: limit }) =>
      limit != null
        ? `Börsenwert unter ${millions(limit)}, deshalb nicht bewertet. Bei kleinen Werten sind die Yahoo-Daten oft lückenhaft.`
        : 'Börsenwert unter der Größenschwelle des Profils, deshalb nicht bewertet. Bei kleinen Werten sind die Yahoo-Daten oft lückenhaft.',
  },
  percentile: {
    group: 'Scores und Ranking',
    label: 'Perzentil',
    tip: 'Anteil der bewerteten Titel, die bei dieser Kennzahl schlechter abschneiden. 0,81 heißt: besser als 81 % der Titel.',
  },
  scoring_run: {
    group: 'Scores und Ranking',
    label: 'Bewertungslauf',
    tip: 'Eine Berechnung des Rankings auf einem Datenabruf. Jede Neuberechnung bekommt eine eigene Nummer.',
  },
  fetched_on: {
    group: 'Scores und Ranking',
    label: 'Abruf',
    tip: 'Tag, an dem die Daten bei Yahoo Finance abgerufen wurden.',
  },
  universe_source: {
    group: 'Scores und Ranking',
    label: 'Indexliste',
    tip: 'Woher die Zusammensetzung von DAX und MDAX stammt: iShares, Deka oder die geprüfte Ersatzliste.',
  },
  scoring_profile: {
    group: 'Scores und Ranking',
    label: 'Profil',
    tip: 'Gewichte, Faktoren und Schwellen, mit denen dieses Ranking gerechnet wurde.',
  },
  hint: {
    group: 'Scores und Ranking',
    label: 'Hinweis',
    tip: 'Value-Trap-Verdacht oder fehlender Composite. Leer heißt: nichts Auffälliges.',
  },

  // Value-Faktoren: Text und Richtung von scoring (FACTOR_INFO)
  ev_ebit: {
    group: 'Value-Faktoren',
    label: 'EV/EBIT',
    role: 'value',
    abbr: true,
    factor: true,
    long: 'Enterprise Value zu Earnings Before Interest and Taxes. Greenblatt-Logik: unabhängig davon, wie ein Unternehmen finanziert ist.',
  },
  pb: { group: 'Value-Faktoren', label: 'KBV', role: 'value', abbr: true, factor: true },
  p_fcf: { group: 'Value-Faktoren', label: 'Kurs/FCF', role: 'value', abbr: true, factor: true },
  shareholder_yield: {
    group: 'Value-Faktoren',
    label: 'Shareholder Yield',
    role: 'value',
    factor: true,
  },
  // F2.2 (ADR-0011): im Katalog, im Profil v1 abgeschaltet; Text aus FACTOR_INFO (API)
  net_share_issuance: {
    group: 'Value-Faktoren',
    label: 'Netto-Emission',
    role: 'value',
    factor: true,
  },

  // Quality-Faktoren
  roic: { group: 'Quality-Faktoren', label: 'ROIC', role: 'quality', abbr: true, factor: true },
  fcf_margin: {
    group: 'Quality-Faktoren',
    label: 'FCF-Marge',
    role: 'quality',
    abbr: true,
    factor: true,
  },
  operating_margin: {
    group: 'Quality-Faktoren',
    label: 'Operative Marge',
    role: 'quality',
    factor: true,
  },
  net_debt_ebitda: {
    group: 'Quality-Faktoren',
    label: 'Net Debt/EBITDA',
    role: 'quality',
    abbr: true,
    factor: true,
  },
  earnings_stability: {
    group: 'Quality-Faktoren',
    label: 'Gewinnstabilität',
    role: 'quality',
    factor: true,
  },
  // F2.1 (ADR-0011): im Katalog, im Profil v1 abgeschaltet; Texte aus FACTOR_INFO (API)
  f_score: { group: 'Quality-Faktoren', label: 'F-Score', role: 'quality', factor: true },
  operating_accruals: {
    group: 'Quality-Faktoren',
    label: 'Accruals',
    role: 'quality',
    factor: true,
  },
  cfo_assets: {
    group: 'Quality-Faktoren',
    label: 'CFO/Bilanzsumme',
    role: 'quality',
    abbr: true,
    factor: true,
  },

  // Nur zur Information (der Store hängt „Nicht im Score.“ an, wo der Text nichts dazu sagt)
  price: {
    group: 'Nur zur Information',
    label: 'Kurs',
    role: 'info',
    tip: 'Letzter Kurs beim Abruf, in Handelswährung.',
  },
  market_cap: {
    group: 'Nur zur Information',
    label: 'Marktkap.',
    role: 'info',
    abbr: true,
    tip: 'Marktkapitalisierung: Börsenwert aller Aktien. Entscheidet über die Größenschwelle.',
  },
  pe_ratio: {
    group: 'Nur zur Information',
    label: 'KGV',
    role: 'info',
    abbr: true,
    tip: 'Kurs-Gewinn-Verhältnis. Nicht im Score, weil Einmaleffekte den Gewinn stark verzerren.',
  },
  dividend_yield: {
    group: 'Nur zur Information',
    label: 'Dividendenrendite',
    role: 'info',
    tip: 'Dividende je Aktie im Verhältnis zum Kurs. Im Score steckt sie im Shareholder Yield.',
  },
  // F2.3 (ADR-0011): prüft den fundamentalen Anker, zählt nicht im Score
  momentum_12_1: {
    group: 'Nur zur Information',
    label: 'Momentum 12-1',
    short: 'Momentum',
    role: 'info',
    tip: 'Kursrendite mit Dividenden über zwölf Monate, ohne den letzten Monat. Zählt nicht im Score, dient nur der Value-Trap-Regel als Prüfung des fundamentalen Ankers.',
  },
  // F3.1 (ADR-0011): fundamentale Anker im Titel-Detail (F3.2a), nicht im Score
  epv_per_share: {
    group: 'Nur zur Information',
    label: 'Ertragskraftwert je Aktie',
    short: 'EPV je Aktie',
    role: 'info',
    tip: 'Earnings Power Value: mittlerer operativer Gewinn nach Steuern geteilt durch die Kapitalkosten, minus Nettoschulden, je Aktie. Der Wert ohne Wachstum. Nicht im Score.',
  },
  price_to_epv: {
    group: 'Nur zur Information',
    label: 'Preis/EPV',
    role: 'info',
    abbr: true,
    tip: 'Börsenwert geteilt durch den Ertragskraftwert (Earnings Power Value). Über 1 heißt: Der Kurs setzt Wachstum voraus. Nicht im Score.',
  },
  implied_fcf_growth: {
    group: 'Nur zur Information',
    label: 'Implizites FCF-Wachstum',
    short: 'Impl. Wachstum',
    role: 'info',
    abbr: true,
    tip: 'Jährliches Wachstum des Free Cashflow, das der heutige Börsenwert unterstellt (Reverse DCF). Nicht im Score.',
  },
  revenue_growth_5y: {
    group: 'Nur zur Information',
    label: 'Umsatzwachstum 5 J.',
    short: 'Umsatz 5 J.',
    role: 'info',
    tip: 'Durchschnittliches jährliches Wachstum des Umsatzes (CAGR) über die verfügbaren Geschäftsjahre, höchstens fünf.',
  },
  eps_growth_5y: {
    group: 'Nur zur Information',
    label: 'EPS-Wachstum 5 J.',
    short: 'EPS 5 J.',
    role: 'info',
    abbr: true,
    tip: 'Wachstum des Gewinns je Aktie (Earnings per Share), berechnet wie das Umsatzwachstum.',
  },

  // Stammdaten
  symbol: {
    group: 'Stammdaten',
    label: 'Symbol',
    tip: 'Kürzel bei Yahoo Finance. „.DE“ steht für den Handel auf Xetra.',
  },
  isin: {
    group: 'Stammdaten',
    label: 'ISIN',
    abbr: true,
    tip: 'Internationale Wertpapierkennnummer, weltweit eindeutig je Aktie.',
  },
  DAX: {
    group: 'Stammdaten',
    label: 'DAX',
    abbr: true,
    tip: 'Die 40 größten Aktiengesellschaften an der Frankfurter Börse.',
  },
  MDAX: {
    group: 'Stammdaten',
    label: 'MDAX',
    abbr: true,
    tip: 'Die 50 nächstgrößeren Werte nach dem DAX.',
  },
  sector: {
    group: 'Stammdaten',
    label: 'Sektor',
    tip: 'Branche laut Yahoo Finance, ins Deutsche übersetzt.',
  },
  industry: {
    group: 'Stammdaten',
    label: 'Branche',
    tip: 'Genauere Einordnung laut Yahoo Finance, wie geliefert.',
  },
  title: {
    group: 'Stammdaten',
    label: 'Titel',
    tip: 'Die Aktie eines Unternehmens, darunter Symbol und Index. Der Name führt zu Kennzahlen und Verlauf.',
  },

  // Läufe
  run: {
    group: 'Läufe',
    label: 'Lauf',
    tip: 'Ein Durchgang: Indexliste laden, Daten abrufen, bewerten, Mail erstellen.',
  },
  fetch_run: {
    group: 'Läufe',
    label: 'Abruf',
    tip: 'Ein Herunterladen der Daten bei Yahoo für alle Titel. Ein Abruf kann mehrfach bewertet werden, etwa mit einem anderen Profil.',
  },
  status: {
    group: 'Läufe',
    label: 'Status',
    tip: 'Wie der Lauf ausging: läuft, erfolgreich, teilweise, keine Daten oder fehlgeschlagen.',
  },
  'status.running': {
    group: 'Läufe',
    label: 'läuft',
    tip: 'Der Lauf arbeitet noch. Der Balken zeigt, wie viele Titel schon abgerufen sind.',
  },
  'status.success': {
    group: 'Läufe',
    label: 'erfolgreich',
    tip: 'Alle Titel abgerufen und bewertet, die Mail ist erstellt.',
  },
  'status.partial': {
    group: 'Läufe',
    label: 'teilweise',
    tip: 'Fertig, aber einzelne Titel ließen sich nicht abrufen. Das Ranking gilt für die übrigen.',
  },
  'status.no_data': {
    group: 'Läufe',
    label: 'keine Daten',
    tip: 'Kein Titel war bewertbar, es gibt kein Ranking. Meist war Yahoo nicht erreichbar.',
  },
  'status.failed': {
    group: 'Läufe',
    label: 'fehlgeschlagen',
    tip: 'Der Lauf ist abgebrochen. Den Grund zeigt das Lauf-Detail.',
  },
  dry_run: {
    group: 'Läufe',
    label: 'Probelauf',
    tip: 'Die Mail wurde erstellt und gespeichert, aber nicht verschickt.',
  },
  force_refresh: {
    group: 'Läufe',
    label: 'neu abgerufen',
    tip: 'Die Daten wurden neu geholt, obwohl es vom selben Tag schon einen Abruf gab.',
  },
  kind: {
    group: 'Läufe',
    label: 'Art',
    tip: 'Abruf und Bewertung, Neu bewertet oder Import.',
  },
  'kind.batch': {
    group: 'Läufe',
    label: 'Abruf und Bewertung',
    tip: 'Normaler Lauf: Daten abrufen und bewerten.',
  },
  'kind.rescore': {
    group: 'Läufe',
    label: 'Neu bewertet',
    tip: 'Ein vorhandener Abruf, mit einem Profil neu berechnet. Ohne Mail.',
  },
  'kind.import': {
    group: 'Läufe',
    label: 'Import',
    tip: 'Altdaten aus dem früheren Batch übernommen.',
  },
  started: { group: 'Läufe', label: 'Gestartet', tip: 'Zeitpunkt, zu dem der Lauf begann.' },
  finished: {
    group: 'Läufe',
    label: 'Beendet',
    tip: 'Zeitpunkt, zu dem der Lauf fertig war oder abbrach.',
  },
  duration: { group: 'Läufe', label: 'Dauer', tip: 'Zeit vom Start bis zum Ende des Laufs.' },
  scored: {
    group: 'Läufe',
    label: 'Bewertet',
    tip: 'Titel mit Score, von allen Titeln der Indexliste.',
  },
  failed_count: {
    group: 'Läufe',
    label: 'Fehlgeschlagen',
    tip: 'Titel, deren Abruf scheiterte.',
  },
  exit_code: {
    group: 'Läufe',
    label: 'Exit-Code',
    tip: 'Technischer Rückgabewert: 0 in Ordnung, 1 Fehler im Lauf, 2 Konfiguration, 3 keine bewertbaren Daten, 4 Datenbank nicht erreichbar.',
  },
  app_version: {
    group: 'Läufe',
    label: 'Programmversion',
    tip: 'Version des Value-Analyzers, mit der der Lauf lief.',
  },

  // Profile
  profile: {
    group: 'Profile',
    label: 'Profil',
    tip: 'Legt fest, welche Faktoren zählen und wie Value und Quality gewichtet werden.',
  },
  version: {
    group: 'Profile',
    label: 'Version',
    tip: 'Jedes Speichern legt eine neue Version an. Alte Versionen bleiben erhalten.',
  },
  active: { group: 'Profile', label: 'aktiv', tip: 'Mit dieser Version rechnet der nächste Lauf.' },
  value_weight: {
    group: 'Profile',
    label: 'Gewichtung',
    tip: 'Anteil von Value am Composite. Der Rest ist Quality.',
  },
  min_market_cap: {
    group: 'Profile',
    label: 'Größenschwelle',
    tip: 'Titel mit kleinerem Börsenwert werden nicht bewertet.',
  },
  min_value_factor_share: {
    group: 'Profile',
    label: 'Mindestabdeckung Value',
    tip: 'Anteil der aktiven Value-Faktoren, für die Daten vorliegen müssen, damit ein Titel einen Value-Score bekommt.',
  },
  min_quality_factor_share: {
    group: 'Profile',
    label: 'Mindestabdeckung Quality',
    tip: 'Anteil der aktiven Quality-Faktoren, für die Daten vorliegen müssen, damit ein Titel einen Quality-Score bekommt.',
  },
  value_trap_value_threshold: {
    group: 'Profile',
    label: 'Value-Trap ab Value',
    tip: 'Ab diesem Value-Score kann ein Titel als Value-Trap gelten.',
  },
  value_trap_quality_threshold: {
    group: 'Profile',
    label: 'Value-Trap bis Quality',
    tip: 'Bis zu diesem Quality-Score gilt ein günstiger Titel als Value-Trap.',
  },
  drop_negative_value_metrics: {
    group: 'Profile',
    label: 'Negative Multiples ausschließen',
    tip: 'Negatives EV/EBIT, KBV oder Kurs/FCF entsteht durch Verluste. Solche Werte zählen bei dem Faktor nicht, statt als Schnäppchen zu erscheinen.',
  },
  preview: {
    group: 'Profile',
    label: 'Vorschau',
    tip: 'Rechnet den letzten Abruf mit deinen Änderungen neu, ohne etwas zu speichern.',
  },
  rank_delta: {
    group: 'Profile',
    label: 'Δ',
    tip: ({ top }) =>
      `Veränderung des Rangs gegenüber dem aktiven Profil. ↑ 2: zwei Plätze besser. „neu“: vorher nicht in den Top ${top ?? 20}.`,
  },
  // Depots (D3.6)
  depot: {
    group: 'Depots',
    label: 'Depot',
    tip: 'Wertpapiere, die du hältst, mit Menge und Kasse. Nur du siehst deine Depots.',
  },
  watchlist: {
    group: 'Depots',
    label: 'Beobachtungsliste',
    tip: 'Wertpapiere ohne Menge, die du verfolgen willst. Sie zeigt Kurse, hat aber keinen Wert.',
  },
  security: {
    group: 'Depots',
    label: 'Wertpapier',
    tip: 'Aktie, ETF oder Anleihe, erkannt an der ISIN. Name und Art kommen aus den Stammdaten.',
  },
  quantity: {
    group: 'Depots',
    label: 'Menge',
    tip: 'Stückzahl, bei Anleihen der Nennwert in Euro. Bruchstücke aus Sparplänen sind erlaubt.',
  },
  close: {
    group: 'Depots',
    label: 'Schlusskurs',
    short: 'Kurs',
    tip: 'Letzter Schlusskurs in der Währung des Handelsplatzes, bei Anleihen in Prozent vom Nennwert.',
  },
  depot_value: {
    group: 'Depots',
    label: 'Wert',
    tip: 'Menge mal letzter Kurs in Euro, bei Anleihen Nennwert mal Kurs durch 100, dazu die Kasse. Positionen ohne Kurs zählen nicht mit.',
  },
  cash: {
    group: 'Depots',
    label: 'Kasse',
    tip: 'Guthaben auf dem Verrechnungskonto in Euro. Es zählt zum Wert des Depots.',
  },
  cost_basis: {
    group: 'Depots',
    label: 'Einstand',
    tip: 'Was du für die ganze Position bezahlt hast, in Euro. Er dient nur der Differenz.',
  },
  difference: {
    group: 'Depots',
    label: 'Differenz',
    tip: 'Wert minus Einstand, nur für Positionen mit beidem. Keine Rendite pro Jahr.',
  },
  price_date: {
    group: 'Depots',
    label: 'Stand',
    tip: 'Datum des ältesten Kurses, der in den Wert eingeht. So alt ist der Wert höchstens.',
  },
  positions: {
    group: 'Depots',
    label: 'Positionen',
    tip: 'Wertpapiere im neuesten Depotstand, je ISIN eine Zeile.',
  },
  holdings_version: {
    group: 'Depots',
    label: 'Depotstand',
    tip: 'Ein vollständiger Stand der Positionen. Jede Änderung und jede Datei legt einen neuen an, alte bleiben.',
  },
  incomplete: {
    group: 'Depots',
    label: 'unvollständig',
    tip: 'Mindestens eine Position hat keinen Wert, etwa weil der Kurs fehlt. Der Wert zählt nur die übrigen.',
  },
  pending: {
    group: 'Depots',
    label: 'wird geprüft',
    tip: 'Für dieses Wertpapier fehlen noch die Stammdaten. Sie kommen mit dem nächsten Abruf.',
  },
  // D5.4: Hinweise
  depot_hint: {
    group: 'Depots',
    label: 'Hinweis zum Depot',
    tip: 'Beobachtung aus einer festen Regel mit Messwert, Schwelle und Ansatzpunkt. Keine Anlageempfehlung.',
  },
  target_allocation: {
    group: 'Depots',
    label: 'Zielallokation',
    tip: 'Wie sich der Wert auf Aktien, ETFs, Anleihen und Kasse verteilen soll. Abweichungen ergeben Hinweise.',
  },
  acknowledged: {
    group: 'Depots',
    label: 'zur Kenntnis genommen',
    tip: 'Ausgeblendeter Hinweis. Er erscheint wieder, wenn er schwerer wird oder sich der Wert deutlich verschlechtert.',
  },
} satisfies Record<string, GlossaryEntry>;

export type TermKey = keyof typeof GLOSSARY;

/** Das Glossar mit einheitlichem Typ, für Zugriffe über einen beliebigen Schlüssel. */
export const ENTRIES: Readonly<Record<TermKey, GlossaryEntry>> = GLOSSARY;

/** Feld einer Ranking-Zeile → Faktor des Scorings (die Felder heißen teils anders: pb_ratio ↔ pb). */
export const FIELD_FACTOR = {
  ev_ebit: 'ev_ebit',
  pb_ratio: 'pb',
  p_fcf: 'p_fcf',
  shareholder_yield: 'shareholder_yield',
  net_share_issuance: 'net_share_issuance',
  roic: 'roic',
  fcf_margin: 'fcf_margin',
  operating_margin: 'operating_margin',
  net_debt_ebitda: 'net_debt_ebitda',
  earnings_stability: 'earnings_stability',
  f_score: 'f_score',
  operating_accruals: 'operating_accruals',
  cfo_assets: 'cfo_assets',
} as const satisfies Record<string, TermKey>;

/** Was die Rolle im Score heißt, als Tooltip der Badge auf der Seite „Begriffe“. */
export const ROLES: Record<ScoreRole, { label: string; tip: string }> = {
  value: { label: 'Value-Faktor', tip: 'Geht in den Value-Score ein.' },
  quality: { label: 'Quality-Faktor', tip: 'Geht in den Quality-Score ein.' },
  info: { label: 'nur zur Information', tip: 'Wird angezeigt, geht aber nicht in den Score ein.' },
};

/** Einordnung eines Scores für seinen Tooltip; ohne Wert der Grund, warum er fehlt. */
export function scoreTip(value: number | null | undefined): string {
  return value == null
    ? (ENTRIES.no_composite.tip as string)
    : `Im Schnitt seiner Faktoren besser als etwa ${Math.round(value * 100)}${NBSP}% der bewerteten Titel.`;
}

/** Tooltip eines Begriffs, der kein Faktor ist; Faktortexte setzt der GlossaryStore zusammen. */
export function termTip(entry: GlossaryEntry, params: TipParams = {}): string {
  const text = typeof entry.tip === 'function' ? entry.tip(params) : (entry.tip ?? '');
  return entry.role === 'info' && !text.includes('Score') ? `${text} Nicht im Score.` : text;
}
