// Tooltips der Seiten Anmelden, Konto und Nutzerverwaltung (D1.4). Eigene Datei neben
// shared/glossary/controls.ts: Diese Seiten laden nach, ihre Texte gehören nicht ins Start-Bundle
// (Grenze 500 kB). Texte mit {name} sind Funktionen des Benutzernamens.

export type AccountText = string | ((name: string) => string);

export const ACCOUNT_CONTROLS = {
  'login.submit': 'Meldet dich mit Benutzername und Passwort an.',
  'login.blocked': 'Erst Benutzername und Passwort eingeben.',
  'account.saveName': 'Speichert den Namen, der oben in der App-Leiste steht.',
  'account.changePassword':
    'Ersetzt dein Passwort. Deine anderen Sitzungen enden, diese hier bleibt.',
  'account.changeBlocked':
    'Erst das bisherige Passwort und zweimal dasselbe neue mit mindestens 12 Zeichen eingeben.',
  'account.revokeAll':
    'Beendet alle deine Sitzungen auf allen Geräten, auch diese. Danach meldest du dich neu an.',
  'account.current': 'Mit dieser Sitzung siehst du gerade diese Seite.',
  'account.users': 'Konten anlegen, deaktivieren und Einmal-Passwörter setzen.',
  'account.role':
    'Admins starten Läufe, ändern Profile und verwalten Konten. Nutzer sehen alles an.',
  'sessions.device': 'Browser und Betriebssystem, mit denen die Sitzung angemeldet wurde.',
  'sessions.started': 'Wann die Anmeldung war.',
  'sessions.seen': 'Wann die Sitzung zuletzt etwas abgefragt hat, auf etwa 10 Minuten genau.',
  'sessions.ends':
    'Spätestens dann endet die Sitzung. Nach 12 Stunden ohne Aktivität endet sie schon früher.',
  'users.create':
    'Legt das Konto mit einem zufälligen Einmal-Passwort an. Es steht danach einmal auf dieser Seite.',
  'users.createBlocked': 'Erst einen Benutzernamen eingeben.',
  'users.roleAdmin': 'Darf Läufe starten, Profile ändern und Konten verwalten.',
  'users.roleUser': 'Darf alles ansehen und die Vorschau nutzen, aber nichts am System ändern.',
  'users.username': 'Name zum Anmelden: 3 bis 32 Zeichen, Kleinbuchstaben, Ziffern, Punkt, Strich.',
  'users.displayName': 'Name in der App-Leiste.',
  'users.state': 'Ob sich das Konto anmelden kann.',
  'users.actions': 'Was du mit dem Konto tun kannst.',
  'users.active': 'Das Konto kann sich anmelden.',
  'users.disabled': 'Das Konto kann sich nicht anmelden. Seine Daten bleiben erhalten.',
  'users.mustChange': 'Das Konto hat sein Einmal-Passwort noch nicht durch ein eigenes ersetzt.',
  'users.disable': (name: string) =>
    `Deaktiviert ${name}. Alle Sitzungen enden; anmelden geht erst nach „Aktivieren“ wieder.`,
  'users.enable': (name: string) => `${name} kann sich wieder anmelden.`,
  'users.reset': (name: string) =>
    `Setzt ein neues Einmal-Passwort für ${name}. Alle Sitzungen von ${name} enden.`,
  'users.own': 'Das eigene Konto änderst du unter „Konto“.',
  'users.copy': 'Kopiert das Einmal-Passwort in die Zwischenablage.',
  'confirm.cancel': 'Schließt die Frage, ohne etwas zu ändern.',
  'confirm.disable': (name: string) => `Deaktiviert ${name} jetzt.`,
  'confirm.reset': (name: string) => `Setzt das neue Einmal-Passwort für ${name} jetzt.`,
} satisfies Record<string, AccountText>;
