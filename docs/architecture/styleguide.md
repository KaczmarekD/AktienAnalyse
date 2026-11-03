# Styleguide Frontend

> **Status:** verbindlich seit 03.11.2026. Gilt für jede Ansicht unter `frontend/`. Wer etwas
> braucht, das hier nicht steht, ergänzt zuerst diesen Styleguide und dann den Code.
> Technischer Rahmen: [frontend.md](frontend.md).

## Grundsätze

1. **Farben nur aus `--mat-sys-*`.** Angular Material erzeugt sie in `styles.scss` aus der
   Azure-Palette. Keine Farbliterale im Code; einzige Ausnahme ist der weiße Hintergrund der
   Mail-Vorschau, weil die Mail ihr eigenes helles Layout mitbringt.
2. **Abstände, Schriftgrößen und Radien nur aus `--va-*`.** Die Tokens stehen in
   `src/styles/_tokens.scss`.
3. **Was auf zwei Seiten vorkommt, ist zentral.** Entweder eine Muster-Klasse in
   `src/styles/_patterns.scss` oder eine Komponente in `src/app/shared/ui/`. Die SCSS einer
   Seite enthält nur, was es genau auf dieser Seite gibt.
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
| `src/styles/_tokens.scss` | Abstände, Schriftgröße klein, Radien, Trennlinie |
| `src/styles/_patterns.scss` | Überschriften und alle Muster-Klassen |
| `src/app/shared/ui/` | gemeinsame Komponenten (`app-page-header`, `app-back-link`) |
| `src/app/shared/format.ts` | Zahlen-, Prozent-, Milliarden- und Status-Formate |

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
| `--va-space-xs` | 0,25 rem | innerhalb kleiner Elemente, Navigationsabstand |
| `--va-space-sm` | 0,5 rem | Listenzeilen, Abstand unter dem Seitenkopf |
| `--va-space-md` | 1 rem | Standard-`gap` in Zeilen und Rastern |
| `--va-space-lg` | 1,5 rem | Seitenrand, Abstand vor einer h2 |
| `--va-space-xl` | 2 rem | Spalten großer Raster |
| `--va-text-sm` | 0,8125 rem | Hinweise, Feldfehler, Kürzel |
| `--va-radius-pill` | 0,75 rem | Badges |
| `--va-radius-box` | 0,5 rem | Hinweis-Boxen |
| `--va-divider` | 1 px `outline-variant` | Trennlinien |

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

## Muster-Klassen

| Klasse | Wofür | Beispiel |
|---|---|---|
| `.meta` | gedämpfte Metazeile oder Nebenangabe | „Abruf vom 30.10.2026 · Quelle iShares“ |
| `.message` | Lade-, Leer- und Fehlertext anstelle von Inhalt | „Lade die Läufe …“ |
| `.hint` | erklärender Nebentext, klein | „Aktivieren wirkt ab dem nächsten Lauf.“ |
| `.field-error` | Fehler direkt unter einem Formularfeld | „Wert zwischen 0 und 1“ |
| `.badge` | kurzer neutraler Zustand | Dry-Run, aktiv: v3 |
| `.badge.badge--error` | Warnung, die zum Handeln auffordert | Value-Trap |
| `.notice` | Rückmeldung nach einer Aktion, `role="status"` | „Version 4 gespeichert“ |
| `.notice.notice--error` | Konflikt oder gescheiterte Aktion, `role="alert"` | „Run konnte nicht gestartet werden.“ |
| `[data-status]` | Status eines Laufs; `failed` und `no_data` färben sich rot | Spalte Status |
| `.cluster` | Zeile aus Bedienelementen oder Links, bricht um | Filter über dem Ranking |
| `.kv-list` | Schlüssel/Wert-Liste (`dl`), zweispaltig | Kopfdaten eines Laufs |
| `.kv-list.kv-list--grid` | viele kurze Kennzahlen im Raster | Kennzahlen eines Titels |
| `.divided-list` | Liste (`ul`) mit Trennlinien | Profile, Versionen |
| `.data-table` | schlichte HTML-Tabelle ohne `mat-table` | Vorschau im Profil-Editor |

Tabellen nehmen immer die volle Breite ein.

## Buttons

| Art | Variante | Beispiel |
|---|---|---|
| Hauptaktion einer Seite | `matButton="filled"`, höchstens einer je Ansicht | Run starten, Als neue Version speichern |
| Nebenaktion | `matButton="outlined"` | Neu laden |
| Aktion in einer Liste | `matButton` (Text) | Aktivieren |

Jeder Button hat `type="button"`, außer er schickt wirklich ein Formular ab. Während eine
Aktion läuft, ist er deaktiviert und sagt, was passiert („Startet …“).

## Sprache, Zahlen, Daten

- Deutsch, kurze Sätze, aus Sicht des Nutzers. Meldungen sagen, was passiert ist und was
  zu tun ist.
- Zahlen über die Pipes aus `format.ts`: `num` (Scores, Multiples), `pct` (Anteile),
  `mrd` (Beträge in Milliarden), `runStatus` (Status auf Deutsch).
- Ein fehlender Wert ist ein Gedankenstrich „–“, nie leer und nie „null“.
- Datum `dd.MM.yyyy`, mit Uhrzeit `dd.MM.yyyy HH:mm`.
- Ladetexte enden mit „…“ und nennen, was lädt: „Lade das Profil …“.

## Checkliste für eine neue Ansicht

- [ ] Gerüst aus [Seitenaufbau](#seitenaufbau): `app-page-header`, bei Detailseiten
      `app-back-link`, Lade-, Fehler- und Leerzustand mit `.message`
- [ ] Keine Farbliterale, keine festen Abstände; nur `--mat-sys-*` und `--va-*`
- [ ] Nichts in der Seiten-SCSS, das es schon als Muster-Klasse gibt
- [ ] Zahlen und Daten über die Pipes und Formate oben
- [ ] Testbare Stellen mit `data-*` markiert
- [ ] In hell und dunkel angesehen
