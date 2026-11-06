# Styleguide Frontend

> **Status:** verbindlich seit 03.11.2026, ergänzt am 04.11.2026 (Bausteine für Status, Value-Trap
> und Rückmeldungen, Formate für Datum und fehlende Werte, Lade-Helfer) und am 06.11.2026 mit G1
> der [Neugestaltung](ui-neugestaltung.md): Papier-Design, Serifen für Überschriften, Icons,
> App-Hülle, `app-icon`, `app-section`, `app-state`; mit G2 Glossar, Tooltips, `app-term` und
> `app-info-tip`. Gilt für jede Ansicht unter `frontend/`. Wer
> etwas braucht, das hier nicht steht, ergänzt zuerst diesen Styleguide und dann den Code.
> Technischer Rahmen: [frontend.md](frontend.md).

## Grundsätze

1. **Farben nur aus `--mat-sys-*`.** Die Werte setzt allein die Papier-Palette in
   `src/styles/_paper.scss`: nur Grautöne und Papierfarbe, hell und dunkel. Sonst gibt es kein
   Farbliteral, einzige Ausnahme ist der weiße Hintergrund der Mail-Vorschau, weil die Mail ihr
   eigenes helles Layout mitbringt. `tests/test_frontend_styles.py` prüft beides.
2. **Abstände, Schrift, Radien und wiederkehrende Maße nur aus `--va-*`.** Die Tokens stehen in
   `src/styles/_tokens.scss`, Breakpoints in `src/styles/_breakpoints.scss`. Maße, die nur das
   Layout einer einzigen Seite betreffen (Spaltenbreiten des Profil-Editors, Höhe der
   Mail-Vorschau), stehen mit Kommentar in deren SCSS.
3. **Was auf zwei Seiten vorkommt, ist zentral.** Entweder eine Muster-Klasse in
   `src/styles/_patterns.scss` oder eine Komponente in `src/app/shared/ui/`. Die SCSS einer
   Seite enthält nur, was es genau auf dieser Seite gibt. Eine Komponente lohnt sich, sobald
   Markup, Text oder Logik mitwandern (Status, Value-Trap); reines Aussehen bleibt eine Klasse.
4. **Angular Material zuerst.** Tabellen sind `mat-table`, Buttons `matButton`, Eingaben
   `mat-form-field`, Karten `mat-card`. Eigene Bausteine nur, wo Material nichts anbietet.
5. **Hell und dunkel ohne Zusatzaufwand.** Das UI folgt der Systemeinstellung
   (`color-scheme: light dark`, die Palette nutzt `light-dark()`). Wer nur Tokens benutzt, ist in
   beiden Modi richtig.
6. **Tests hängen an `data-*` und Rollen, nie an Stilklassen.** So bleibt ein Umbau der Optik
   ohne Teständerung möglich.
7. **Das Start-Bundle bleibt unter 500 kB**, darüber bricht der Build. Was nur eine Ansicht
   braucht, importiert die Ansicht, nicht `app.config.ts` (Beispiel: `FORM_FIELD_DEFAULTS`).

## Dateien

| Datei | Inhalt |
|---|---|
| `src/styles.scss` | Material-Theme für Schrift und Dichte, Fokusringe, `body`, Einbinden der Dateien unten |
| `src/styles/_paper.scss` | Papier-Palette und Overrides für Karte, Dialog, Menü, Tooltip, Tabelle, aufklappbaren Abschnitt |
| `src/styles/_tokens.scss` | Abstände, Schrift, Radien, Maße, Linien, Fokusring |
| `src/styles/_breakpoints.scss` | Breakpoints als Sass-Variablen (erzeugt kein CSS) |
| `src/styles/_patterns.scss` | Überschriften, Links, Fokus und alle Muster-Klassen |
| `src/app/shared/ui/` | gemeinsame Komponenten, siehe [Komponenten](#komponenten) |
| `src/app/shared/format.ts` | Pipes für Zahlen, Prozent, Milliarden, Datum, fehlende Werte, Status |
| `src/app/shared/resource.ts` | `loaded`, `keptValue` und `loadError` für den Lade- und Fehlerzustand |
| `src/app/shared/glossary/` | alle Texte: Begriffe (`glossary.ts`), Bedienelemente (`controls.ts`), `GlossaryStore` |

## Farben

Das UI sieht aus wie ein gut gesetzter Bericht: Papier als Untergrund, Inhalte auf hellen
Blättern, Text in Tinte, Nebensachen in Bleistift. Es gibt nur Grautöne. Bedeutung entsteht durch
Fläche, Icon und Text, nicht durch Farbe. Die Werte stehen in der
[Spec](ui-neugestaltung.md#palette).

| Rolle | Token | Wofür |
|---|---|---|
| Schreibtisch | `surface` | Hintergrund der Seite, App-Leiste |
| Blatt | `surface-container-lowest` | Karten, Tabellen, Dialoge, Menüs |
| Vertiefung 1 | `surface-container-low` | Zeile unter dem Zeiger, Hover |
| Vertiefung 2 | `surface-container` | neutrale Badges |
| Vertiefung 3 | `surface-container-high` | aktiver Navigationseintrag, Hinweis-Box |
| Vertiefung 4 | `surface-container-highest` | Spur der Balken, Badge `--muted` |
| Haarlinie | `outline-variant` | Trennlinien, Rand der Blätter |
| Rand | `outline` | Eingabefelder, Outlined-Buttons, Unterstreichung von Links |
| Bleistift | `on-surface-variant` | Metazeilen, Labels, Hinweise, Lade- und Leertexte |
| Tinte | `on-surface` | Text und Zahlen |
| Volle Tinte | `primary`, `error` | Hauptaktion, Warnungen, die zum Handeln auffordern |
| Gedämpfte Warnung | `error-container` | Konflikt, Fehler einer Anfrage, „keine Daten“ |
| Tooltip | `inverse-surface` | Tooltips, Snackbar |

Volle Tinte als Fläche (`error`) heißt immer: Hier muss jemand hinsehen. Für reine Information ist
sie tabu. `secondary` und `tertiary` zeigen auf dieselben Stufen, neue Stellen nehmen die Rollen
oben.

## Abstände, Größen, Radien

| Token | Wert | Wofür |
|---|---|---|
| `--va-space-2xs` | 0,125 rem | innen oben und unten in Badges, Unterstreichung von Links |
| `--va-space-xs` | 0,25 rem | innerhalb kleiner Elemente, Navigationsabstand |
| `--va-space-sm` | 0,5 rem | Listenzeilen, Abstand unter dem Seitenkopf |
| `--va-space-md` | 1 rem | Standard-`gap` in Zeilen, Listen und Rastern |
| `--va-space-lg` | 1,5 rem | Seitenrand, Innenabstand einer Karte |
| `--va-space-xl` | 2 rem | Spalten großer Raster, Abstand vor einer h2 |
| `--va-space-2xl` | 3 rem | Abstand zwischen großen Abschnitten, unter dem Inhalt |
| `--va-text-sm` | 0,8125 rem | Hinweise, Feldfehler, Kürzel |
| `--va-weight-emphasis` | 500 | Hervorhebung ohne Fettdruck: Werte im Raster, Status, Betreff |
| `--va-weight-strong` | 600 | Ausgewählt: aktiver Navigationseintrag, gewähltes Segment |
| `--va-font-figures` | Systemschrift | große Zahlen, nie in Serifen |
| `--va-radius-pill` | 0,75 rem | Badges |
| `--va-radius-box` | 0,5 rem | Hinweis-Boxen |
| `--va-radius-card` | `corner-small` | Karten und Tabellen-Blätter: kleine Ecken wie bei Papier |
| `--va-size-figure` | 11 rem | Mindestbreite einer Kennzahl in `.kv-list--grid` |
| `--va-size-control` | 2,5 rem | Bedienfeld einer Checkbox (Text darunter rückt so weit ein), Höhe der Navigations-Pille |
| `--va-content-max` | 90 rem | höchste Breite des Inhalts, zentriert |
| `--va-appbar-height` | 3,5 rem | App-Leiste; klebende Tabellenköpfe beginnen darunter |
| `--va-tooltip-max` | 20 rem | höchste Breite eines Tooltips |
| `--va-bar-height` | 0,375 rem | Score-Balken |
| `--va-icon-sm`, `--va-icon-md`, `--va-icon-lg` | 1,125 / 1,5 / 1,75 rem | Icons; `lg` nur für die Marke |
| `--va-divider` | 1 px `outline-variant` | Haarlinie |
| `--va-rule` | 1 px `on-surface` | Linie in Tinte unter Tabellenköpfen und über der Speichern-Leiste |
| `--va-focus-ring`, `--va-focus-width`, `--va-focus-offset` | 2 px `primary`, 2 px Abstand | Fokus jedes Bedienelements |

| Breakpoint | Wert | Wofür |
|---|---|---|
| `breakpoints.$narrow` | 900 px | darunter stehen zweispaltige Layouts untereinander, Tabellen-Blätter scrollen |
| `breakpoints.$compact` | 600 px | Handys: Navigation nur mit Icons, Kennzahlkarten 2 × 2 |

CSS-Variablen gelten in Media Queries nicht, deshalb sind Breakpoints Sass-Variablen:

```scss
@use '../../styles/breakpoints';

@media (max-width: breakpoints.$narrow) {
  // …
}
```

Abstände zwischen Geschwistern entstehen mit `gap` in Flex oder Grid, nicht mit Margins.

## Typografie

Schriften aus dem System, geladen wird nichts, weil das UI im LAN läuft. Überschriften stehen in
Serifen (`brand-family`: Iowan Old Style, Palatino Linotype, Palatino, Book Antiqua, Georgia),
alles andere in `system-ui` (`plain-family`).

| Stufe | Quelle | Schrift | Verwendung |
|---|---|---|---|
| h1 | `--mat-sys-headline-small` | Serif | genau eine je Seite, immer über `app-page-header` |
| h2 | `--mat-sys-title-large` | Serif | Abschnitte einer Seite |
| Kartentitel | `--mat-sys-title-medium` | Serif | Überschrift in `app-section` |
| Kennzahl | `--va-font-figures` | System | große Werte, etwa in Kennzahlkarten |
| Label | `--mat-sys-label-large` | System | Spaltenköpfe, Navigation |
| Fließtext | `--mat-sys-body-medium` (am `body`) | System | alles Übrige |
| Klein | `--mat-sys-body-small` | System | Fußzeile, Nebenzeilen |
| Badge | `--mat-sys-label-medium` | System | Badges |

Zahlen stehen nie in Serifen: Georgia setzt Mediävalziffern, die in Spalten springen. Ziffern in
Tabellen sind tabellarisch, das setzt `_patterns.scss` für jede Tabelle, `.num` dazu rechtsbündig.

## Icons

- Kein Icon-Font. `app-icon` zeichnet SVG-Pfade aus einer festen Liste (`ICONS` in
  `shared/ui/icon.ts`, Material Icons, Apache 2.0) in `currentColor`.
- Liste: `leaderboard`, `history`, `tune`, `help`, `info`, `warning`, `error`, `check_circle`,
  `progress_activity`, `play_arrow`, `download`, `content_copy`, `search`, `view_column`,
  `arrow_back`, `arrow_upward`, `arrow_downward`, `cloud_off`, `close`, `expand_more`, `edit`,
  seit D1.4 `person`, `logout`, `login`, `group`. Ein neues Icon kommt zuerst in diese Liste.
- Icons sind Schmuck (`aria-hidden`). Steht eins allein in einem Icon-Button, braucht der Button
  `aria-label` und Tooltip mit demselben Text.

## App-Hülle

Die Hülle (`app.html`) setzt jede Ansicht in denselben Rahmen:

- **App-Leiste** auf dem Schreibtisch mit Haarlinie, klebt oben: Marke (führt zum Ranking),
  Navigation mit Icon, Text und Tooltip, der aktive Bereich als Pille in Vertiefung 3. Das
  Titel-Detail gehört zum Bereich Ranking. Rechts der Chip „offline“, nur wenn der WebSocket
  getrennt ist. Unter `$compact` nur Icons.
- **Inhalt** höchstens `--va-content-max` breit, zentriert.
- **Fußzeile:** „Quantitative Vorauswahl, keine Anlageempfehlung.“ und die Version aus
  `GET /api/v1/health`.
- „Läufe“ heißt überall „Läufe“, auch im Titel des Tabs; die Route bleibt `/runs`.

## Tooltips und Begriffe

Nichts bleibt unerklärt: Jeder Button, jede Abkürzung, jeder Status, jeder Spaltenkopf und jedes
Kennzahl-Label hat einen Tooltip, der sagt, was es ist und wie man es liest. Fließtext und Links,
deren Text das Ziel nennt, bekommen keinen.

- **Eine Quelle:** Begriffe stehen in `shared/glossary/glossary.ts` (`GLOSSARY`: Label, Kurzlabel,
  Tooltip, lange Erklärung, Gruppe, Rolle im Score, `abbr` für Kürzel), die Texte der
  Bedienelemente in `controls.ts` (`CONTROLS`). Die Faktortexte liefert scoring
  (`FACTOR_INFO`, `GET /api/v1/scoring/factors`); der `GlossaryStore` hängt Richtung und Rolle an.
- **Werte aus den Daten:** Texte mit Gewichten, Schwellen oder Größenschwelle sind Funktionen von
  `TipParams` und kommen ohne die Werte allgemein aus.
- **Texte:** höchstens zwei Sätze (200 Zeichen), erst „Was ist das?“, dann „Wie lesen?“, dann die
  Rolle im Score. Eine Abkürzung wird zuerst ausgeschrieben. Wichtiges steht nie nur im Tooltip.
- **Technik:** `matTooltip` mit den Voreinstellungen aus `app.config.ts`; gesperrte Buttons mit
  `disabledInteractive`, damit der Tooltip den Grund zeigt; keine nativen `title`.
- **Seite „Begriffe“** (`/glossary`, Icon in der App-Leiste): alle Einträge nach Gruppen, mit Anker
  je Begriff (`/glossary#roic`) und Suche.
- **Tests 1 und 2:** `controlsWithoutTooltip` und `abbreviationsWithoutExplanation` aus
  `testing/tooltips.ts` laufen im Test jeder Ansicht; Ausnahmen stehen mit Grund im Test.
  Wörtlich zitierter Text aus den Daten, etwa der Betreff einer Mail, steht in einem Element mit
  `data-verbatim` und zählt nicht als Beschriftung.

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

@if (data(); as data) {
  <!-- Inhalt -->
} @else {
  <app-state [error]="error()" loading="Lade … " />
}
```

Die Signale dazu kommen aus `shared/resource.ts`. `loaded` gibt den Wert, sobald er da ist,
`loadError` die Meldung nach einem Fehler, mit eigenem Text für 404:

```ts
private readonly resource = getRunResource(() => ({ path: { run_id: this.runId() } }));
protected readonly data = computed(() => loaded(this.resource));
protected readonly error = computed(() => loadError(this.resource, 'Lauf nicht gefunden.'));
```

Lädt eine Ansicht live nach (Ranking und Läufe nach einem Ereignis über den WebSocket), nimmt sie
`keptValue(() => this.resource)` statt `loaded`: Der bisherige Wert bleibt stehen, bis der neue da
ist, nach einem Fehler gilt der Fehler.

Steht der Titel erst nach dem Laden fest (Titel-Detail, Lauf, Profil), kommt
`app-page-header` in den Zweig mit den Daten. Laden, Fehler und leer zeigt `app-state`.

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

### `app-section`

Abschnitt als Blatt (`mat-card` outlined): ein Bereich, den Screenreader über seine Überschrift
ansagen. Neben dem Titel ist Platz für ein ⓘ (`sectionInfo`), rechts für Aktionen
(`sectionActions`). `[level]="3"` für Abschnitte innerhalb eines Abschnitts.

```html
<app-section heading="Kennzahlen">
  <button sectionActions matButton type="button">ISIN kopieren</button>
  <dl class="kv-list">…</dl>
</app-section>
```

### `app-state`

Was eine Ansicht zeigt, solange sie keine Daten zeigen kann: einen Fehler sofort als
`.notice--error` mit `role="alert"`, den leeren Zustand mit Icon, Satz und nächstem Schritt
(projizierter Inhalt), sonst nach 300 ms den Ladebalken mit Text. Schnelle Antworten flackern so
nicht.

```html
@if (runs(); as runs) {
  @if (runs.length === 0) {
    <app-state empty="Noch keine Läufe." emptyIcon="history">
      <button matButton="filled" type="button">Lauf starten</button>
    </app-state>
  } @else {
    <!-- Tabelle -->
  }
} @else {
  <app-state [error]="error()" loading="Lade die Läufe …" />
}
```

### `app-term`

Begriff mit Tooltip aus dem Glossar, gepunktet unterstrichen und mit der Tastatur erreichbar. Eigener
Text ersetzt das Label, `variant="short"` nimmt das Kurzlabel, `[params]` setzt Werte ein.
`[focusable]="false"` nimmt den Tab-Stopp weg, wo der Begriff in jeder Zeile steht (Index unter dem
Namen eines Titels); erklärt wird er dann auch an einem fokussierbaren Element der Seite.

```html
<th mat-header-cell *matHeaderCellDef><app-term key="ev_ebit" /></th>
<app-term key="scoring_run">Bewertungslauf #{{ run.scoring_run_id }}</app-term>
<app-term key="value_trap" [params]="params()" />
```

### `app-info-tip`

ⓘ als Icon-Button neben Formular-Labels und Abschnittsköpfen, mit `aria-label` („Was heißt
Größenschwelle?“) und Tooltip. Text aus dem Glossar (`key`) oder direkt (`text`, `label`).

```html
<app-info-tip key="min_market_cap" />
```

### `app-score`

Score als Zahl, auf Wunsch mit Balken in Tinte (`bar`, nur beim Composite); der Tooltip ordnet ihn
ein („besser als etwa 78 % der bewerteten Titel“), ohne Wert steht ein Strich mit dem Grund.

```html
<app-score [value]="row.composite_score" bar />
```

### `app-stat-card`

Kennzahlkarte über einer Tabelle: Label, großer Wert (Inhalt), Nebenzeile (`statSub`) und
Tooltip. Mit `link` führt sie zu einer Ansicht, mit `pressed` ist sie ein Schalter, der filtert.

```html
<app-stat-card label="Value-Traps" [tip]="text" [pressed]="focus() === 'traps'" (toggled)="…">
  {{ traps }}
  <span statSub>günstig, aber schwache Quality</span>
</app-stat-card>
```

### `app-column-picker`

Spaltenwahl einer Tabelle (Button „Spalten“ mit Menü, Checkboxen nach Gruppen). Die Ansicht hält
die gewählten Schlüssel und merkt sie sich im `localStorage` (Lesen und Schreiben in try/catch).

```html
<app-column-picker [groups]="columnGroups()" [(selected)]="selected" />
```

### `app-sparkline`

Verlauf als kleine Linie in Tinte (Inline-SVG, ohne Diagramm-Bibliothek), ältester Punkt zuerst;
Punkte ohne Wert fehlen. Jeder Punkt hat einen Tooltip, das SVG eine Beschreibung für
Screenreader („Verlauf des Composite von 0,71 auf 0,78“). Unter zwei Werten steht ein Satz.

```html
<app-sparkline [points]="spark()" label="Composite" />
```

### `app-icon`

SVG-Icon aus der festen Liste, siehe [Icons](#icons). `size="md"` für 1,5 rem, `spin` dreht es
(nicht bei `prefers-reduced-motion`).

```html
<app-icon name="warning" />
<app-icon name="progress_activity" size="md" spin />
```

### `app-run-status`

Status eines Laufs auf Deutsch mit Icon und Fläche je Status (Spec, „Bedeutung ohne Farbe“):
läuft mit drehendem Icon auf Blatt mit Rand, erfolgreich nur mit Häkchen, teilweise auf
Vertiefung 4, keine Daten auf `error-container`, fehlgeschlagen in voller Tinte. Der Tooltip kommt
aus dem Glossar (`status.*`), das Element trägt `data-status`. Während eines Abrufs steht der
Fortschritt daneben (`data-progress`): Balken und „57/90“, der zuletzt abgerufene Titel im
Tooltip.

```html
<app-run-status [status]="run.status" [progress]="progress()[run.id]" />
```

### `app-value-trap-badge`

Badge „Value-Trap?“ in voller Tinte mit Warn-Icon für Titel mit Value-Trap-Flag, sonst nichts. Das
Fragezeichen steht wie in der Mail: Das Flag ist ein Hinweis, genauer hinzusehen, kein Urteil. Der
Tooltip nennt die Schwellen des Profils, wenn die Ansicht sie mitgibt.

```html
<app-value-trap-badge [flagged]="row.value_trap_flag" [params]="params()" />
```

### `app-notice`

Rückmeldung nach einer Aktion. `{ text }` erscheint neutral mit Häkchen und `role="status"`,
`{ text, error: true }` als gedämpfte Warnung mit Fehler-Icon und `role="alert"`. Ohne
Rückmeldung zeigt sie nichts. Auch der Fehler im Lauf-Detail und die Meldungen des Start-Dialogs
laufen darüber.

```html
<app-notice [notice]="notice()" />
```

```ts
this.notice.set({ text: `Lauf #${id} gestartet.` });
this.notice.set({ text: 'Der Lauf konnte nicht gestartet werden.', error: true });
```

Braucht die Box eine eigene Schaltfläche (Konflikt mit „Neu laden“), wird sie direkt mit
`.notice.notice--error` gebaut.

### Voreinstellungen

- **Tooltips:** `MAT_TOOLTIP_DEFAULT_OPTIONS` in `app.config.ts`: `showDelay` 400 ms,
  `hideDelay` 0 ms, `touchendHideDelay` 2500 ms, Position oben. Aussehen über die Palette,
  mehrzeilig und höchstens `--va-tooltip-max` breit.
- **Formularfelder mit Rand:** Ansichten mit `mat-form-field` nehmen `FORM_FIELD_DEFAULTS` aus
  `shared/ui/form-field.ts` in ihre `providers`. In `app.config.ts` stünde es auch richtig, käme
  dann aber mit Angular Forms ins Start-Bundle.
- **Einheiten im Formular:** Die Ansicht zeigt Werte so, wie man sie liest: Anteile in Prozent,
  Geld in Mio. € (`matTextSuffix`). Das Modell und die API bleiben bei 0 bis 1 und Euro, die
  Ansicht rechnet um und rundet für die Anzeige. Ein Anteil, den man abwägt (Value gegen
  Quality), ist ein `mat-slider` in Schritten von 5 %. Feldfehler nennen den erlaubten Bereich in
  der Einheit des Felds, mit Icon `error`.
- **Selten geänderte Felder** liegen in einem geschlossenen `mat-expansion-panel` „Erweitert“.

## Muster-Klassen

| Klasse | Wofür | Beispiel |
|---|---|---|
| `.meta` | gedämpfte Metazeile oder Nebenangabe | „Abruf vom 30.10.2026 · Quelle iShares“ |
| `.term` | Begriff mit Tooltip, gepunktet unterstrichen (setzt `app-term`) | EV/EBIT im Spaltenkopf |
| `.message` | Lade-, Leer- und Fehlertext anstelle von Inhalt (bis zum Wechsel auf `app-state`) | „Lade die Läufe …“ |
| `.hint` | erklärender Nebentext oder Kürzel, klein und gedämpft | „Aktivieren wirkt ab dem nächsten Lauf.“, Symbol im Ranking |
| `.field-error` | Fehler direkt unter einem Formularfeld | „Wert zwischen 0 und 1“ |
| `.num` | Zahl rechtsbündig mit tabellarischen Ziffern | Spalten mit Scores |
| `.bar` | Balken in Tinte auf Vertiefung 4, innen ein `span` mit der Breite in Prozent | Composite, Perzentil eines Faktors |
| `.badge` | kurzer neutraler Zustand, Vertiefung 2, Icon vorne erlaubt | neu abgerufen, aktiv: Version 3 |
| `.badge.badge--muted` | Hinweis, Vertiefung 4 | offline, teilweise |
| `.badge.badge--error` | Warnung, die zum Handeln auffordert, volle Tinte | nur über `app-value-trap-badge` |
| `.notice` | Rückmeldung nach einer Aktion, Vertiefung 3 | über `app-notice` |
| `.notice.notice--error` | Konflikt oder gescheiterte Aktion, gedämpfte Warnung | über `app-notice` oder `app-state`, mit Schaltfläche direkt |
| `.cluster` | Zeile aus Bedienelementen oder Links, bricht um | Filter über dem Ranking, Lauf starten |
| `.card-grid` | Karten in drei Spalten, unter `$narrow` untereinander | Abschnitte im Titel-Detail |
| `.stat-grid` | Kennzahlkarten in vier Spalten, unter `$narrow` zwei | Kopf des Rankings |
| `.sticky-bar` | Leiste, die unten klebt, mit Linie in Tinte; im Editor erst nach einer Änderung (`[class.sticky-bar]`) | Speichern im Profil-Editor |
| `.kv-list` | Schlüssel/Wert-Liste (`dl`), zweispaltig | Kopfdaten eines Laufs |
| `.kv-list.kv-list--grid` | viele kurze Kennzahlen im Raster | Kennzahlen eines Titels |
| `.divided-list` | Liste (`ul`) mit Trennlinien | Profile, Versionen |
| `.table-sheet` | legt eine Tabelle als Blatt auf den Tisch, scrollt unter `$narrow` waagrecht | Ranking |
| `.data-table` | schlichte HTML-Tabelle ohne `mat-table` | Vorschau im Profil-Editor |

Sortierbare Spaltenköpfe tragen den Tooltip am Kopf selbst (Text aus dem Glossar plus „Klick
sortiert.“), nicht sortierbare ein `app-term`. Zahlenspalten sind `.num`. Klebt der Kopf, beginnt er
unter der App-Leiste (`--va-appbar-height`); `.table-sheet` schneidet mit `overflow: clip`, damit
das Kleben am Fenster bleibt.

Tabellen nehmen immer die volle Breite ein und stehen im Buchsatz: eine Linie in Tinte unter dem
Kopf, Haarlinien zwischen den Zeilen, keine senkrechten Linien, unter dem Zeiger Vertiefung 1. Das
regeln Palette und Muster für jede `mat-table`.

## Buttons

| Art | Variante | Beispiel |
|---|---|---|
| Hauptaktion einer Seite | `matButton="filled"` (volle Tinte), höchstens einer je Ansicht | Lauf starten, Als neue Version speichern |
| Nebenaktion | `matButton="outlined"` | Neu laden |
| Aktion in einer Liste | `matButton` (Text) | Aktivieren |

Ein Dialog (`MatDialog`, z. B. „Lauf starten“) hat den Titel als `h2 mat-dialog-title`, die
Aktionen rechts: „Abbrechen“ als Text, die Aktion des Dialogs `filled`. Er erledigt seine Aktion
selbst, zeigt Fehler über `app-notice` und schließt sich erst bei Erfolg.

Jeder Button hat `type="button"`, außer er schickt wirklich ein Formular ab. Während eine
Aktion läuft, ist er deaktiviert und sagt, was passiert („Startet …“, „Speichert …“). Den Fokus
zeigt ein Ring in Tinte (`mat.strong-focus-indicators`), Links und fokussierbare Elemente ohne
Material bekommen denselben Ring aus `_patterns.scss`.

## Sprache, Zahlen, Daten

- Deutsch, kurze Sätze, aus Sicht des Nutzers. Meldungen sagen, was passiert ist und was
  zu tun ist. Technische Namen wie „web-api“ stehen nicht im UI, es heißt „der Server“.
- Werte nur über die Pipes aus `format.ts`, nicht über Angulars `date` oder `percent`:

  | Pipe | Wofür | Beispiel |
  |---|---|---|
  | `num` | Scores, Multiples | 0,78; mit `num: '1.1-1'` 14,4 |
  | `pct` | Anteile; Gewichte mit `pct: '1.0-0'` | 12,3 %; 60 % |
  | `mrd` | Beträge in Milliarden | 140,0 Mrd |
  | `day` | Datum | 30.10.2026 |
  | `dayTime` | Zeitpunkt | 30.10.2026 06:00 |
  | `orDash` | sonstige Werte, die fehlen können | Rang, Exit-Code |
  | `sector` | Sektor von Yahoo auf Deutsch | Finanzen |
  | `runKind` | Art eines Laufs | Abruf und Bewertung |
  | `duration` | Dauer zwischen zwei Zeitpunkten (`start \| duration: end`) | 12 min |
  | `indexSource` | Herkunft der Indexliste | Deka, Ersatzliste |
  | `runStatus` | Status auf Deutsch (meist über `app-run-status`) | erfolgreich |

- Ein fehlender Wert ist ein Gedankenstrich „–“ (`MISSING`), nie leer und nie „null“. Alle
  Pipes oben zeigen ihn von selbst.
- Ladetexte enden mit „…“ und nennen, was lädt: „Lade das Profil …“.

## Checkliste für eine neue Ansicht

- [ ] Gerüst aus [Seitenaufbau](#seitenaufbau): `app-page-header`, bei Detailseiten
      `app-back-link`, Laden, Fehler und leer über `app-state`, Signale über `loaded`
      und `loadError`
- [ ] Abschnitte als `app-section`, Status, Value-Trap und Rückmeldungen über die
      [Komponenten](#komponenten)
- [ ] Keine Farbliterale, keine festen Abstände; nur `--mat-sys-*`, `--va-*` und Breakpoints
- [ ] Nichts in der Seiten-SCSS, das es schon als Muster-Klasse gibt
- [ ] Werte über die Pipes aus [Sprache, Zahlen, Daten](#sprache-zahlen-daten)
- [ ] Jedes Bedienelement, Label und Kürzel mit Tooltip aus dem Glossar; Tests 1 und 2 im Test
      der Ansicht
- [ ] Icon-Buttons mit `aria-label` und Tooltip
- [ ] Spaltenköpfe mit `scope="col"` (`headersWithoutScope` im Test der Ansicht)
- [ ] Neue Route in die axe-Prüfung von `frontend/e2e/design.spec.ts` aufnehmen
- [ ] Testbare Stellen mit `data-*` markiert
- [ ] In hell und dunkel und bei 375 px Breite angesehen
- [ ] Start-Bundle unter 500 kB (`npm run build`)
