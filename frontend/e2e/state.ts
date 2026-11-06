// Wo auth.setup.ts die Anmeldung für die Browser-Tests ablegt (D1.4). Eigene Datei, damit
// playwright.config.ts den Pfad kennt, ohne die Setup-Datei mit ihrem Test zu laden.
export const STORAGE_STATE = 'test-results/.auth/state.json';
