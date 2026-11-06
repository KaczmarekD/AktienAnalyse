# Styleguide Frontend

> **Status:** verbindlich seit 03.11.2026, ergänzt am 04.11.2026 (Bausteine für Status, Value-Trap
> und Rückmeldungen, Formate für Datum und fehlende Werte, Lade-Helfer). Gilt für jede Ansicht
> unter `frontend/`. Wer etwas braucht, das hier nicht steht, ergänzt zuerst diesen Styleguide und
> dann den Code. Technischer Rahmen: [frontend.md](frontend.md).

## Grundsätze

1. **Farben nur aus `--mat-sys-*`.** Angular Material erzeugt sie in `styles.scss` aus der
   Azure-Palette. Keine Farbliterale im Code; einzige Ausnahme ist der weiße Hintergrund der
   Mail-Vorschau, weil die Mail ihr eigenes helles Layout mitbringt.
2. **Abstände, Schrift, Radien und wiederkehrende Maße nur aus `--va-*`.** Die Tokens stehen in
   `src/styles/_tokens.scss`, Breakpoints in `src/styles/_breakpoints.scss`. Maße, die nur das
   Layout einer einzigen Seite betreffen (Spaltenbreiten des Profil-Editors, Höhe der
   Mail-Vorschau), stehen mit Kommentar in deren SCSS.
3. **Was auf zwei Seiten vorkommt, ist zentral.** Entweder eine Muster-Klasse in
   `src/styles/_patterns.scss` oder eine Komponente in `src/app/shared/ui/`. Die SCSS einer
   Seite enthält nur, was es genau auf dieser Seite gibt. Eine Komponente lohnt sich, sobald
   Markup, Text oder Logik mitwandern (Status, Value-Trap); reines Aussehen bleibt eine Klasse.
4. **Angular Material zuerst.** Tabellen sind `mat-table`, Buttons `matButton`, Eingaben
   `mat-form-field`. Eigene Bausteine nur, wo Material nichts anbietet.
5. **Hell und dunkel ohne Zusatzaufwand.** Das UI folgt der Systemeinstellung
   (`color-scheme: light dark`). Wer nur Tokens benutzt, ist in beiden Modi richtig.
6. **Tests hängen an `data-*` und Rollen, nie an Stilklassen.** So bleibt ein Umbau der Optik
   ohne Teständerung möglich.

## Dateien

| Datei | Inhalt |
|---|---|
| `src/styles.scss` | Material-Theme, `body`, Einbinden von Tokens und Mustern |
| `src/styles/_tokens.scss` | Abstände, Schriftgröße und -stärke, Radien, Maße, Trennlinie |
| `src/styles/_breakpoints.scss` | Breakpoints als Sass-Variablen (erzeugt kein CSS) |
| `src/styles/_patterns.scss` | Überschriften und alle Muster-Klassen |
| `src/app/shared/ui/` | gemeinsame Komponenten, siehe [Komponenten](#komponenten) |
| `src/app/shared/format.ts` | Pipes für Zahlen, Prozent, Milliarden, Datum, fehlende Werte, Status |
| `src/app/shared/resource.ts` | `loaded` und `loadError` für den Lade- und Fehlerzustand |

## Farben

Bedeutung entscheidet über die Farbe, nicht der Geschmack.

| Rolle | Token | Wofür |
|---|---|---|
| Primär | `primary` | Links, Hauptaktion |
| Sekundär | `secondary-container` | aktiver Navigationseintrag, neutrale Hinweis-Box |
| Tertiär | `tertiary-container` | neutrale Badges: Dry-Run, aktive Version |
| Fehler | `error`, `error-container` | Value-Trap, fehlgeschlagener Lauf, Konflikt |
| Fläche | `surface`, `on-surface` | Hintergrund und Text |
| Gedämpft | `on-surface-variant` | Metazeilen, Lade- und Leertexte, Hinweise |
| Linie | `outline-variant` | Trennlinien in Listen und Tabellen |

Rot (`error`) bedeutet immer: Hier muss jemand hinsehen. Für reine Information ist es tabu.

## Abstände, Größen, Radien

| Token | Wert | Wofür |
|---|---|---|
| `--va-space-2xs` | 0,125 rem | innen oben und unten in Badges |
| `--va-space-xs` | 0,25 rem | innerhalb kleiner Elemente, Navigationsabstand |
| `--va-space-sm` | 0,5 rem | Listenzeilen, Abstand unter dem Seitenkopf |
| `--va-space-md` | 1 rem | Standard-`gap` in Zeilen, Listen und Rastern |
| `--va-space-lg` | 1,5 rem | Seitenrand, Abstand vor einer h2 |
| `--va-space-xl` | 2 rem | Spalten großer Raster |
| `--va-text-sm` | 0,8125 rem | Hinweise, Feldfehler, Kürzel |
| `--va-weight-emphasis` | 500 | Hervorhebung ohne Fettdruck: Werte im Raster, roter Status, Betreff |
| `--va-radius-pill` | 0,75 rem | Badges |
| `--va-radius-box` | 0,5 rem | Hinweis-Boxen |
| `--va-size-figure` | 11 rem | Mindestbreite einer Kennzahl in `.kv-list--grid` |
| `--va-size-control` | 2,5 rem | Breite des Bedienfelds einer Checkbox; Text darunter rückt so weit ein |
| `--va-divider` | 1 px `outline-variant` | Trennlinien |

| Breakpoint | Wert | Wofür |
|---|---|---|
| `breakpoints.$narrow` | 900 px | darunter stehen zweispaltige Layouts untereinander |

CSS-Variablen gelten in Media Queries nicht, deshalb sind Breakpoints Sass-Variablen:

```scss
@use '../../styles/breakpoints';

@media (max-width: breakpoints.$narrow) {
  // …
}
```

Abstände zwischen Geschwistern entstehen mit `gap` in Flex oder Grid, nicht mit Margins.

## Typografie

Systemschrift (`system-ui`), weil das UI im LAN läuft und nichts von außen lädt.

| Stufe | Quelle | Verwendung |
|---|---|---|
| h1 | `--mat-sys-headline-small` | genau eine je Seite, immer über `app-page-header` |
| h2 | `--mat-sys-title-large` | Abschnitte einer Seite |
| Fließtext | `--mat-sys-body-medium` (am `body`) | alles Übrige |
| Badge | `--mat-sys-label-medium` | Badges |

Ziffern in Tabellen sind tabellarisch (`font-variant-numeric: tabular-nums`), das setzt
`_patterns.scss` für jede Tabelle.

## Seitenaufbau

Jede Ansicht folgt diesem Gerüst:

```html
<!-- nur Detailseiten -->
<app-back-link to="/ranking">Ranking</app-back-link>

<app-page-header>
  Titel der Seite
  <button pageAction matButton="filled" type="button">Hauptaktion</button>
</app-page-header>
<p class="meta">Stand, Quelle, Kennung …</p>

@if (error(); as message) {
  <p class="message">{{ message }}</p>
} @else if (data(); as data) {
  <!-- Inhalt -->
} @else {
  <p class="message">Lade … </p>
}
```

Die Signale dazu kommen aus `shared/resource.ts`. `loaded` gibt den Wert, sobald er da ist,
`loadError` die Meldung nach einem Fehler, mit eigenem Text für 404:

```ts
private readonly resource = getRunResource(() => ({ path: { run_id: this.runId() } }));
protected readonly data = computed(() => loaded(this.resource));
protected readonly error = computed(() => loadError(this.resource, 'Lauf nicht gefunden.'));
```

Steht der Titel erst nach dem Laden fest (Titel-Detail, Lauf, Profil), kommt
`app-page-header` in den Zweig mit den Daten.

## Komponenten

### `app-page-header`

Kopf jeder Seite. Der Inhalt wird zur h1, Badges dürfen mit hinein. Elemente mit dem Attribut
`pageAction` stehen rechts daneben und brechen auf schmalen Bildschirmen um.

```html
<app-page-header>
  Lauf {{ run.id }}
  @if (run.dry_run) {
    <span class="badge">Dry-Run</span>
  }
</app-page-header>
```

### `app-back-link`

Zurück zur übergeordneten Ansicht. Nur auf Detailseiten, immer als erstes Element. Der Text ist
das Ziel, nicht „Zurück“.

```html
<app-back-link to="/runs">Alle Läufe</app-back-link>
```

### `app-run-status`

Status eines Laufs auf Deutsch, `failed` und `no_data` in Rot. Das Element trägt
`data-status`. Während eines Abrufs steht der Fortschritt daneben (`data-progress`, das Symbol
des letzten Titels im Tooltip).

```html
<app-run-status [status]="run.status" [progress]="progress()[run.id]" />
```

### `app-value-trap-badge`

Rote Badge „Value-Trap?“ für Titel mit Value-Trap-Flag, sonst nichts. Das Fragezeichen steht
wie in der Mail: Das Flag ist ein Hinweis, genauer hinzusehen, kein Urteil.

```html
<app-value-trap-badge [flagged]="row.value_trap_flag" />
```

### `app-notice`

Rückmeldung nach einer Aktion. `{ text }` erscheint neutral mit `role="status"`,
`{ text, error: true }` rot mit `role="alert"`. Ohne Rückmeldung zeigt sie nichts.

```html
<app-notice [notice]="notice()" />
```

```ts
this.notice.set({ text: `Lauf #${id} gestartet.` });
this.notice.set({ text: 'Der Lauf konnte nicht gestartet werden.', error: true });
```

Braucht die Box eine eigene Schaltfläche (Konflikt mit „Neu laden“), wird sie direkt mit
`.notice.notice--error` gebaut.

## Muster-Klassen

| Klasse | Wofür | Beispiel |
|---|---|---|
| `.meta` | gedämpfte Metazeile oder Nebenangabe | „Abruf vom 30.10.2026 · Quelle iShares“ |
| `.message` | Lade-, Leer- und Fehlertext anstelle von Inhalt | „Lade die Läufe …“ |
| `.hint` | erklärender Nebentext oder Kürzel, klein und gedämpft | „Aktivieren wirkt ab dem nächsten Lauf.“, Symbol im Ranking |
| `.field-error` | Fehler direkt unter einem Formularfeld | „Wert zwischen 0 und 1“ |
| `.badge` | kurzer neutraler Zustand | Dry-Run, aktiv: v3 |
| `.badge.badge--error` | Warnung, die zum Handeln auffordert | nur über `app-value-trap-badge` |
| `.notice` | Rückmeldung nach einer Aktion | über `app-notice` |
| `.notice.notice--error` | Konflikt oder gescheiterte Aktion | über `app-notice`, mit Schaltfläche direkt |
| `.cluster` | Zeile aus Bedienelementen oder Links, bricht um | Filter über dem Ranking, Lauf starten |
| `.kv-list` | Schlüssel/Wert-Liste (`dl`), zweispaltig | Kopfdaten eines Laufs |
| `.kv-list.kv-list--grid` | viele kurze Kennzahlen im Raster | Kennzahlen eines Titels |
| `.divided-list` | Liste (`ul`) mit Trennlinien | Profile, Versionen |
| `.data-table` | schlichte HTML-Tabelle ohne `mat-table` | Vorschau im Profil-Editor |

Tabellen nehmen immer die volle Breite ein.

## Buttons

| Art | Variante | Beispiel |
|---|---|---|
| Hauptaktion einer Seite | `matButton="filled"`, höchstens einer je Ansicht | Lauf starten, Als neue Version speichern |
| Nebenaktion | `matButton="outlined"` | Neu laden |
| Aktion in einer Liste | `matButton` (Text) | Aktivieren |

Jeder Button hat `type="button"`, außer er schickt wirklich ein Formular ab. Während eine
Aktion läuft, ist er deaktiviert und sagt, was passiert („Startet …“, „Speichert …“).

## Sprache, Zahlen, Daten

- Deutsch, kurze Sätze, aus Sicht des Nutzers. Meldungen sagen, was passiert ist und was
  zu tun ist.
- Werte nur über die Pipes aus `format.ts`, nicht über Angulars `date` oder `percent`:

  | Pipe | Wofür | Beispiel |
  |---|---|---|
  | `num` | Scores, Multiples | 0,78; mit `num: '1.1-1'` 14,4 |
  | `pct` | Anteile; Gewichte mit `pct: '1.0-0'` | 12,3 %; 60 % |
  | `mrd` | Beträge in Milliarden | 140,0 Mrd |
  | `day` | Datum | 30.10.2026 |
  | `dayTime` | Zeitpunkt | 30.10.2026 06:00 |
  | `orDash` | sonstige Werte, die fehlen können | Rang, Sektor, Exit-Code |
  | `runStatus` | Status auf Deutsch (meist über `app-run-status`) | erfolgreich |

- Ein fehlender Wert ist ein Gedankenstrich „–“ (`MISSING`), nie leer und nie „null“. Alle
  Pipes oben zeigen ihn von selbst.
- Ladetexte enden mit „…“ und nennen, was lädt: „Lade das Profil …“.

## Checkliste für eine neue Ansicht

- [ ] Gerüst aus [Seitenaufbau](#seitenaufbau): `app-page-header`, bei Detailseiten
      `app-back-link`, Lade-, Fehler- und Leerzustand mit `.message`, Signale über `loaded`
      und `loadError`
- [ ] Status, Value-Trap und Rückmeldungen über die [Komponenten](#komponenten)
- [ ] Keine Farbliterale, keine festen Abstände; nur `--mat-sys-*`, `--va-*` und Breakpoints
- [ ] Nichts in der Seiten-SCSS, das es schon als Muster-Klasse gibt
- [ ] Werte über die Pipes aus [Sprache, Zahlen, Daten](#sprache-zahlen-daten)
- [ ] Testbare Stellen mit `data-*` markiert
- [ ] In hell und dunkel angesehen
