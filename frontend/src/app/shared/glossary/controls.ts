// Tooltips der Bedienelemente (docs/architecture/ui-neugestaltung.md, Katalog „Bedienelemente“).
// Eigene Datei neben glossary.ts, damit die App-Hülle nur diese wenigen Texte ins Start-Bundle
// holt und nicht das ganze Glossar.

export type ControlText = string | ((n: number) => string);

/** Tooltips der Bedienelemente (Spec, Katalog „Bedienelemente“); {n} kommt aus den Daten. */
export const CONTROLS = {
  'nav.ranking': 'Alle Titel nach Composite, mit Filtern und Kennzahlen.',
  'nav.runs': 'Verlauf aller Läufe, neuen Lauf starten, Mails ansehen.',
  'nav.profiles': 'Gewichte und Faktoren des Scorings ansehen und ändern.',
  'nav.glossary': 'Alle Begriffe und Abkürzungen erklärt.',
  // D1.4: Anmeldung in der App-Leiste
  'nav.users': 'Konten anlegen, deaktivieren und Einmal-Passwörter setzen.',
  'nav.account': 'Dein Konto: Anzeigename, Passwort und Sitzungen.',
  'nav.logout': 'Beendet deine Sitzung auf diesem Gerät.',
  'nav.login': 'Anmelden, um Konten zu verwalten. Ansehen geht hier auch ohne Anmeldung.',
  'profiles.view': 'Profil und Vorschau ansehen. Nur Admins speichern und aktivieren Profile.',
  brand: 'Zum Ranking',
  offline:
    'Keine Live-Verbindung zum Server. Die Seite aktualisiert sich erst wieder, wenn er erreichbar ist.',
  'ranking.all': 'Alle Titel aus DAX und MDAX.',
  'ranking.showFiltered':
    'Zeigt auch Titel mit zu kleinem Börsenwert. Sie haben keinen Rang und stehen am Ende.',
  'ranking.cardNoComposite': 'Zeigt nur die Titel, denen der Value- oder der Quality-Score fehlt.',
  'ranking.cardTraps': 'Zeigt nur die Titel mit Value-Trap-Verdacht.',
  'ranking.columns': 'Weitere Faktoren ein- oder ausblenden.',
  'ranking.toLatest': 'Wechselt zum jüngsten Bewertungslauf.',
  'ranking.resetFilter': 'Index auf „Alle“, Suche leeren.',
  'instrument.copyIsin': 'ISIN in die Zwischenablage kopieren.',
  'runs.start':
    'Startet einen Lauf mit den Optionen, die du im nächsten Schritt wählst. Es läuft immer nur einer.',
  'runs.startBlocked': (n: number) => `Es läuft schon ein Lauf (#${n}). Es läuft immer nur einer.`,
  'start.send': 'Die Mail mit dem Ranking geht an den eingestellten Empfänger.',
  'start.dry': 'Die Mail wird erstellt und gespeichert, aber nicht verschickt.',
  'start.force':
    'Holt die Daten neu von Yahoo, auch wenn es heute schon einen Abruf gab. Dauert länger.',
  'start.cancel': 'Schließt den Dialog, ohne einen Lauf zu starten.',
  'start.confirm': 'Startet den Lauf. Fortschritt und Ergebnis erscheinen in der Liste.',
  'run.ranking': 'Das Ranking, das dieser Lauf berechnet hat.',
  'run.csv':
    'Alle Titel mit Scores und Kennzahlen als CSV mit Semikolon und Dezimalkomma, öffnet direkt in Excel.',
  'run.details':
    'Exit-Code, Programmversion, Nummern von Abruf und Bewertungslauf, vollständige Fehlermeldung.',
  'profiles.edit':
    'Parameter ändern und als neue Version speichern. Aktiv wird sie erst mit „Aktivieren“.',
  'profiles.latest': 'Die neueste Version zählt erst, wenn du sie im Editor aktivierst.',
  'editor.save': (n: number) => `Legt Version ${n} an. Aktiv wird sie erst mit „Aktivieren“.`,
  'editor.blocked.invalid': 'Erst speichern, wenn alle Felder gültig sind.',
  'editor.blocked.rule': 'Erst speichern, wenn die Regel oben erfüllt ist, etwa genug Faktoren.',
  'editor.blocked.unchanged': 'Nichts zu speichern: Die Parameter gleichen der Grundlage.',
  'editor.discard': (n: number) => `Setzt alle Felder auf Version ${n} zurück.`,
  'editor.activate': (n: number) =>
    `Ab dem nächsten Lauf rechnet Version ${n}. Eine ältere Version zu aktivieren heißt zurückrollen.`,
  'editor.reload': 'Lädt die neueste Version. Deine Änderungen hier gehen verloren.',
} satisfies Record<string, ControlText>;
