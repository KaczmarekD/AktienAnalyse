# Neugestaltung des UI

> **Status:** Entwurf (04.11.2026, Papier-Design seit 06.11.2026). Die Designvorlage G0 hast du
> am 06.11.2026 abgenommen, offen sind die Entscheidungen E1 und E3 bis E7.
> Gilt für alles unter `frontend/`. Klickbare Vorlage: [docs/design/vorlage.html](../design/vorlage.html).
> Nach der Abnahme kommen die neuen Bausteine zuerst in den [Styleguide](styleguide.md), dann in
> den Code, so wie es der Styleguide verlangt. Die Pakete stehen in der Roadmap unter
> [Track G](roadmap.md#track-g--gestaltung-des-ui). Technischer Rahmen:
> [frontend.md](frontend.md).
>
> Grundlage ist der Styleguide mit seiner Ergänzung vom 04.11.2026: `app-run-status`,
> `app-value-trap-badge`, `app-notice`, `loaded`/`loadError`, die Pipes `day`, `dayTime` und
> `orDash` sowie die Breakpoints. Die Spec erweitert diese Bausteine, statt neue daneben zu
> stellen.

## Ziel

Das UI soll ruhig und klar sein und sich ohne Vorwissen verstehen lassen. Wer es öffnet, sieht in
wenigen Sekunden, welche Titel vorn liegen und warum, und ob der letzte Lauf sauber war.

Drei Zusagen:

1. **Jede Ansicht beantwortet eine Frage**, und die Antwort steht oben.
2. **Nichts bleibt unerklärt.** Jeder Button, jede Abkürzung, jeder Status, jeder Spaltenkopf und
   jedes Kennzahl-Label hat einen Tooltip. Er sagt, was es ist und wie man es liest.
3. **Eine Vorlage für alles.** Neue Ansichten entstehen aus denselben Bausteinen, ohne eigene
   Optik.

## Was bleibt

| Rahmen | Warum |
|---|---|
| Angular 22 mit Angular Material (Material 3) | entschieden am 31.10.2026, [frontend.md](frontend.md) |
| Farben nur aus `--mat-sys-*`, Maße nur aus `--va-*` | [Styleguide](styleguide.md): hell und dunkel ohne Zusatzaufwand. Neu ist nur, woher die Werte kommen: aus dem [Papier-Theme](#umsetzung-im-theme) statt aus der Azure-Palette |
| Nichts aus dem Internet: keine Webfonts, keine Icon-Fonts, kein CDN | Betrieb im LAN, CSP `default-src 'self'` |
| Keine neue Laufzeit-Abhängigkeit außer Modulen aus Material und CDK | Bundle-Budget 500 kB Warnung, 1 MB Fehler (`angular.json`) |
| API ändert sich nur additiv, der Client wird erzeugt | `oasdiff breaking`, [CLAUDE.md](../../CLAUDE.md) |
| Routen bleiben (`/ranking`, `/runs`, `/profiles`, `/instruments/:symbol`) | Lesezeichen und E2E-Tests |
| Tests hängen an Rollen und `data-*` | Optik umbauen, ohne Tests anzufassen |
| Methodenbegriffe Value, Quality, Composite und Value-Trap | Mail, CSV und Doku nutzen sie; sie werden erklärt statt übersetzt |
| Mail und Golden-Master | Die Neugestaltung betrifft nur das UI |

## Befund: das UI heute

Durchgesehen am 04.11.2026: App-Hülle und alle sechs Ansichten.

**Überall**

- Kein einziger Tooltip. Unerklärt bleiben EV/EBIT, KBV, KGV, ROIC, FCF, EPS, Marktkap., ISIN,
  Exit, „v3“ und Dry-Run.
- Die Sprache ist gemischt. Die Navigation sagt „Runs“, die Seiten sagen „Läufe“. Sektoren kommen
  englisch von Yahoo („Financial Services“), die Lauf-Art roh (`batch`).
- Die Faktortexte aus der API haben Ersatz-Umlaute („Gewinnstabilitaet“, „Verhaeltnis“). Sichtbar
  sind sie im Profil-Editor.
- Zahlen stehen in Tabellen linksbündig und lassen sich schlecht vergleichen.
- Es gibt keine Icons. Status erscheint nur als Text und Farbe, „offline“ als kleines Wort.
- Der Inhalt nutzt die volle Breite, auf großen Bildschirmen werden die Zeilen sehr lang.
- Geladen wird mit dem Text „Lade …“, ohne Fortschrittsanzeige.
- Nirgends steht, dass das Ranking keine Anlageempfehlung ist.

**Ranking**

- Zwölf Spalten zugleich. Drei Faktoren stehen unerklärt da, die anderen sechs fehlen ganz.
- Ein Score wie 0,78 hat keine Skala. Unklar ist, dass er ein Perzentil ist und 1 das Beste.
- Value-Traps sind doppelt rot markiert (Zeile und Badge), die Regel dahinter steht nirgends.
- Titel unter der Größenschwelle sind nur halb durchsichtig. Titel ohne Composite (Banken) zeigen
  „–“ ohne Grund.
- Die Metazeile ist dicht und technisch („Bewertungslauf 42 · Quelle Deka“). Ein Überblick fehlt:
  wie viele bewertet, wie viele Value-Traps.
- Ein älterer Bewertungslauf (`/ranking/:id`) sieht aus wie der aktuelle.

**Titel-Detail**

- 15 Kennzahlen stehen ohne Gruppen in einem Raster. Unklar ist, welche in den Score eingehen; KGV,
  Dividendenrendite und Wachstum zählen nicht.
- Rang und Scores stehen erst unten im Verlauf.
- Der Verlauf ist nur eine Tabelle.

**Läufe und Lauf-Detail**

- Die Start-Optionen stehen dauerhaft über der Liste. „Dry-Run“ und „Mail verschicken“
  überschneiden sich: Beide verhindern den Versand (`deliver = notify and not dry_run` im Handler
  von notification).
- Die Spalten „Art“ (`batch`) und „Exit“ sind technisch.
- Der Leerzustand nennt `make local-run` und NATS.
- Exit-Code und Programmversion stehen gleichrangig neben dem Status, der Fehler als roher
  Stacktrace.

**Profile und Editor**

- „v3“ und „aktiv: v3“ sind knapp. Unklar bleibt, dass es eine neuere, nicht aktive Version geben
  kann.
- Gewicht und Anteile sind Dezimalzahlen von 0 bis 1. Die Mindest-Marktkapitalisierung wird in
  Euro mit acht Nullen eingegeben (Schrittweite 50 000 000).
- „Mindestanteil Value-Faktoren“ und die Value-Trap-Schwellen sind unerklärt.
- Der Speichern-Button steht am Ende einer langen Spalte, und niemand sagt, warum er gesperrt ist.
- In der Vorschau zeigt die Spalte „vorher“ Pfeile ohne Legende.

## Leitlinien

1. **Eine Frage je Ansicht.**

   | Ansicht | Frage |
   |---|---|
   | Ranking | Welche Titel sind günstig und solide? |
   | Titel-Detail | Warum steht dieser Titel dort? |
   | Läufe | Lief der letzte Lauf sauber? |
   | Profile | Womit wird gerechnet, und was ändert eine Anpassung? |
   | Begriffe | Was bedeutet das? |

2. **Erst das Ergebnis, dann die Details.** Oben Kennzahlkarten, darunter die Tabelle, Technisches
   eingeklappt.
3. **Ein Begriff, eine Erklärung.** Dieselbe Abkürzung hat überall denselben Tooltip, aus einer
   Quelle.
4. **Nur Graustufen, Bedeutung über Deckung.** Das UI kennt keinen Farbton. Was Aufmerksamkeit
   braucht, steht in voller Tinte, mit Icon und Text. Rot gibt es nicht mehr, und keine
   Information steckt in einer Farbe allein.
5. **Ruhe wie auf Papier.** Blätter mit Haarlinie statt Schatten, Tabellen im Buchsatz, viel
   Weißraum. Höchstens eine Hauptaktion je Ansicht.
6. **Zahlen zum Vergleichen.** Rechtsbündig, mit tabellarischen Ziffern, die Einheit am Wert.
7. **Deutsch durchgängig.** Die Methodenbegriffe bleiben (siehe [Was bleibt](#was-bleibt)), alles
   andere ist deutsch: Läufe, Sektoren, Status, Art.

## Visuelle Sprache: Papier

> Entschieden am 04.11.2026 (deine Vorgabe): Papier-Design, nur Graustufen und Papierfarbe.

Das UI sieht aus wie ein gut gesetzter Bericht. Warmes Papier ist der Untergrund, Inhalte liegen
auf hellen Blättern, Text und Daten stehen in Tinte, Nebensachen in Bleistift. Es gibt nur
Grautöne, einen Farbton gibt es nicht. Die Töne stammen aus der Palette von Archivar, damit beide
Apps zusammenpassen. Sein Rot, Grün und Gelb übernimmt der Value-Analyzer nicht.

Die klickbare Vorlage dazu liegt unter [docs/design/vorlage.html](../design/vorlage.html)
(Paket G0, mit echten Daten vom 30.10.2026).

### Palette

| Rolle | Token | Hell | Dunkel | Wofür |
|---|---|---|---|---|
| Schreibtisch | `surface` | `#f5f4f0` | `#100f0d` | Hintergrund der Seite, App-Leiste |
| Blatt | `surface-container-lowest` | `#fdfcfa` | `#191816` | Karten, Tabellen, Dialoge, Menüs |
| Vertiefung 1 | `surface-container-low` | `#f3f1ec` | `#1d1c19` | Zeile unter dem Zeiger |
| Vertiefung 2 | `surface-container` | `#efede8` | `#22211e` | neutrale Badges, Tabellenkopf beim Scrollen |
| Vertiefung 3 | `surface-container-high` | `#e7e4dd` | `#2a2925` | aktiver Navigationseintrag, Hinweis-Box |
| Vertiefung 4 | `surface-container-highest` | `#dcd8cf` | `#34322e` | Spur der Score-Balken, Status „teilweise“ |
| Haarlinie | `outline-variant` | `#e2dfd7` | `#2e2c28` | Trennlinien, Rand der Blätter |
| Rand | `outline` | `#8a847a` | `#77726a` | Eingabefelder, Outlined-Buttons |
| Bleistift | `on-surface-variant` | `#67625a` | `#a39e94` | Metazeilen, Labels, Hinweise |
| Tinte | `on-surface` | `#1d1b18` | `#f0eee8` | Text und Zahlen |
| Volle Tinte | `primary`, `error` | `#24221e`, `#12110f` | `#f0eee8`, `#fdfcfa` | Hauptaktion, Score-Balken, Warnungen |
| Auf Tinte | `on-primary`, `on-error` | `#fdfcfa` | `#100f0d` | Text auf voller Tinte |
| Gedämpfte Warnung | `error-container` | `#cbc7bd` | `#3f3c37` | „keine Daten“, Konflikt-Box |
| Tooltip | `inverse-surface`, `inverse-on-surface` | `#24221e` auf `#f5f4f0` | `#f0eee8` auf `#100f0d` | Tooltips, Snackbar |

Die übrigen Rollen von Material (`secondary`, `tertiary` und ihre Container) zeigen auf dieselben
Stufen. Die vollständige Liste steht in `_paper.scss`.

**Kontraste** (WCAG, nachgerechnet): Tinte auf Papier 15,6 : 1 (dunkel 16,5 : 1), Bleistift auf
Papier 5,5 : 1 (dunkel 7,2 : 1), Bleistift auf Vertiefung 3 4,8 : 1 (dunkel 5,5 : 1), Rand auf
Blatt mindestens 3 : 1. Damit hält jeder Text Stufe AA ein, jeder Rand die 3 : 1 für
Bedienelemente.

### Umsetzung im Theme

- `mat.theme()` bleibt für Schrift und Dichte. Die Farben setzt `mat.theme-overrides()` mit
  `light-dark()` in der neuen Datei `src/styles/_paper.scss`. Sie ist neben der Mail-Vorschau die
  einzige Stelle mit Farbwerten.
- Komponenten nutzen weiter nur `--mat-sys-*`. Wer `primary` oder `error` schreibt, bekommt
  automatisch Tinte. Am Code der Seiten ändert das Theme nichts.
- Karten, Dialoge und Menüs liegen als Blatt auf dem Schreibtisch. `mat.card-overrides` (für
  `appearance="outlined"`), `mat.dialog-overrides` und `mat.menu-overrides` setzen Fläche,
  Haarlinie und Radius und nehmen den Schatten weg.
- Ein Test liest `_paper.scss`: Jeder Farbwert ist ein Grauton, der größte und der kleinste
  RGB-Kanal liegen höchstens 16 auseinander. Außerhalb dieser Datei gibt es kein Farbliteral.

### Bedeutung ohne Farbe

| Was | Wie | Beispiel |
|---|---|---|
| Hauptaktion | volle Tinte als Fläche (`matButton="filled"`) | Lauf starten |
| Warnung, die zum Handeln auffordert | volle Tinte als Fläche, Icon, Text | Value-Trap?, fehlgeschlagen |
| gedämpfte Warnung | `error-container`, Icon | keine Daten, Konflikt beim Speichern |
| Hinweis | Vertiefung 4, Icon | teilweise, Probelauf |
| Erfolg | ohne Fläche, nur Häkchen-Icon: Erfolg ist der Normalfall | erfolgreich |
| Feldfehler | Rand in voller Tinte, Meldung mit Icon `error` | Wert zwischen 0 und 1 |
| Score | Balken in Tinte auf Vertiefung 4, ohne Ampel | Composite 0,78 |
| Fokus | Ring aus 2 px Tinte mit 2 px Abstand | jedes Bedienelement |
| aktiver Navigationseintrag | Vertiefung 3 als Pille, Schrift stärker | Ranking |

**Status eines Laufs:**

| Status | Fläche | Icon |
|---|---|---|
| läuft | Blatt mit Rand | `progress_activity`, dreht sich (außer bei `prefers-reduced-motion`) |
| erfolgreich | keine | `check_circle` |
| teilweise | Vertiefung 4 | `info` |
| keine Daten | `error-container` | `error` |
| fehlgeschlagen | volle Tinte, Text `on-error` | `error` |

**Value-Trap:** `app-value-trap-badge` heißt wie in der Mail „Value-Trap?“, steht in voller Tinte
und bekommt Warn-Icon und Tooltip. Die eingefärbte Zeile entfällt.

### Flächen und Linien

- Inhalte liegen auf Blättern: `mat-card appearance="outlined"` mit Fläche Blatt, Rand Haarlinie,
  ohne Schatten, Radius `--va-radius-card`.
- **Tabellen im Buchsatz:** eine Linie in Tinte unter dem Kopf (`--va-rule`), Haarlinien zwischen
  den Zeilen, keine senkrechten Linien, keine Streifen. Unter dem Zeiger wird eine Zeile zu
  Vertiefung 1.
- Die App-Leiste liegt auf dem Schreibtisch und endet mit einer Haarlinie. Sie ist keine farbige
  Fläche.
- Die Mail-Vorschau bleibt weiß: Sie ist ein eigenes Dokument und liegt als Blatt im Blatt.

### Typografie und Zahlen

- **Überschriften in Serifenschrift aus dem System.** `brand-family` im Theme wird
  „Iowan Old Style“, „Palatino Linotype“, Palatino, „Book Antiqua“, Georgia, serif. Windows hat
  Palatino Linotype und Georgia, macOS Iowan und Palatino. Geladen wird nichts.
- **Alles andere in `system-ui`** (`plain-family`): Fließtext, Labels, Tabellen und vor allem alle
  Zahlen. Georgia setzt Mediävalziffern, die in Spalten springen. Deshalb nutzen auch große
  Kennzahlen die Schrift aus `--va-font-figures`.

| Stufe | Token | Schrift | Verwendung |
|---|---|---|---|
| h1 | `--mat-sys-headline-small` | Serif | genau eine je Seite |
| h2 | `--mat-sys-title-large` | Serif | Abschnitte |
| Kartentitel | `--mat-sys-title-medium` | Serif | Überschrift einer Karte |
| Kennzahl | Größe von `--mat-sys-headline-medium` | `--va-font-figures` | Wert in einer Kennzahlkarte |
| Label | `--mat-sys-label-large` | System | Spaltenköpfe, Labels in Karten |
| Fließtext | `--mat-sys-body-medium` | System | alles Übrige |
| Klein | `--mat-sys-body-small` | System | Hinweise, Nebenzeilen |

Zahlen in Tabellen und Karten stehen rechtsbündig (Muster-Klasse `.num`) mit
`font-variant-numeric: tabular-nums`.

### Icons

- Kein Icon-Font: Material Symbols käme sonst von Google oder als Datei von mehreren Megabyte.
- Stattdessen gibt es `app-icon`, eine Komponente mit einer festen Liste von SVG-Pfaden aus
  Material Icons (Lizenz Apache 2.0). Die Farbe ist `currentColor`, also Tinte oder Bleistift,
  die Größe `--va-icon-sm` oder `--va-icon-md`. Inline-SVG erlaubt die CSP.
- Erste Liste: `leaderboard` (Ranking), `history` (Läufe), `tune` (Profile), `help` (Begriffe),
  `info`, `warning`, `error`, `check_circle`, `progress_activity`, `play_arrow`, `download`,
  `content_copy`, `search`, `view_column`, `arrow_back`, `arrow_upward`, `arrow_downward`,
  `cloud_off`, `close`.
- Ein Icon steht nur in einem Icon-Button allein, und dort immer mit `aria-label` und Tooltip.

### Neue Tokens

| Token | Wert | Wofür |
|---|---|---|
| `--va-space-2xl` | 3 rem | Abstand zwischen großen Abschnitten |
| `--va-content-max` | 90 rem | maximale Breite des Inhalts, zentriert |
| `--va-radius-card` | `var(--mat-sys-corner-small)` | Karten: kleine Ecken wie bei Papier |
| `--va-rule` | 1 px `on-surface` | Linie in Tinte unter Tabellenköpfen |
| `--va-focus-ring` | 2 px `primary`, 2 px Abstand | Fokus jedes Bedienelements |
| `--va-font-figures` | `var(--mat-sys-body-large-font)` | Schrift großer Zahlen, immer ohne Serifen |
| `--va-tooltip-max` | 20 rem | maximale Breite eines Tooltips |
| `--va-bar-height` | 0,375 rem | Score-Balken |
| `--va-icon-sm`, `--va-icon-md` | 1,125 rem, 1,5 rem | Icons |

Dazu kommt neben `breakpoints.$narrow` (900 px) der Breakpoint `breakpoints.$compact` (600 px)
für Handys, siehe [Schmale Bildschirme](#schmale-bildschirme).

## Tooltips und Begriffe

### Was einen Tooltip bekommt

| Element | Der Tooltip sagt | Beispiel |
|---|---|---|
| Icon-Button | die Aktion, zusätzlich als `aria-label` | „ISIN kopieren“ |
| Text-Button | was passiert und was danach gilt | Lauf starten |
| gesperrter Button | warum er gesperrt ist | „Erst speichern, wenn alle Felder gültig sind.“ |
| Umschalter, Checkbox, Auswahl | was die Option bewirkt | Daten neu abrufen |
| Spaltenkopf, Kennzahl-Label | was es ist, wie man es liest, ob es im Score steckt | EV/EBIT |
| Abkürzung im Text | Ausschreibung und Bedeutung | ISIN |
| Badge, Status | Bedeutung und Folge | Value-Trap |
| Wert, der Einordnung braucht | die Einordnung | Score 0,78 |
| Navigationseintrag | was die Seite zeigt | Läufe |
| Formularfeld | über ein ⓘ neben dem Label, nicht am Eingabefeld selbst | Größenschwelle |

Keinen Tooltip bekommen Fließtext und Links, deren Text das Ziel nennt, etwa der Name eines Titels.
Ein Tooltip, der nur das Label wiederholt, ist Rauschen.

### Regeln für die Texte

- Höchstens zwei Sätze, etwa 160 Zeichen. Was länger ist, steht auf der Seite „Begriffe“.
- Reihenfolge: **Was ist das?** Dann **Wie lesen?** (Skala, „niedriger ist besser“). Dann, wo es
  passt, **Rolle im Score:** Value-Faktor, Quality-Faktor oder nur zur Information.
- Eine Abkürzung wird zuerst ausgeschrieben: „Kurs-Buchwert-Verhältnis: …“.
- Im Tooltip steht kein neuer Fachbegriff, der selbst eine Erklärung bräuchte.
- Werte kommen aus den Daten, nicht als feste Zahl in den Text: Gewichte, Schwellen und
  Größenschwelle des Profils.
- Wichtiges steht nie nur im Tooltip. Fehler, Warnungen und die Folgen einer Aktion stehen auch
  sichtbar auf der Seite. Tooltips ergänzen, denn auf dem Handy erscheinen sie erst nach langem
  Drücken.

### Technik

- `matTooltip` aus Angular Material: erscheint bei Hover, bei Tastaturfokus und bei langem Drücken
  auf Touch-Geräten. Es setzt `aria-describedby` selbst.
- Die Standardwerte stehen einmal in `app.config.ts` über `MAT_TOOLTIP_DEFAULT_OPTIONS`:
  `showDelay` 400 ms, `hideDelay` 0 ms, `touchendHideDelay` 2500 ms, Position oben.
- Das Aussehen regelt `mat.tooltip-overrides` in `styles.scss` mit Tokens. Tooltips sind
  mehrzeilig (`white-space: pre-line`) und höchstens `--va-tooltip-max` breit.
- Gesperrte Buttons bekommen `disabledInteractive`, damit Hover und Fokus den Grund zeigen.
- Native Tooltips über `title` entfallen, etwa am Fortschritt in `app-run-status`. Sie erscheinen
  nicht bei Tastaturfokus und sehen anders aus.
- Begriffe in Spaltenköpfen und Labels sind fokussierbar (`tabindex="0"`), gepunktet
  unterstrichen, mit Cursor `help`. Bei sortierbaren Spalten hängt der Tooltip am Sortierkopf.
- Tooltips enthalten keine Links, denn Material-Tooltips sind nicht interaktiv. Zur langen
  Erklärung führen das Icon „Begriffe“ in der App-Leiste und der Link „Was bedeuten die Spalten?“
  unter Tabellen.

### Eine Quelle für alle Texte

- `frontend/src/app/shared/glossary/glossary.ts` enthält die typisierte Liste `GLOSSARY`. Jeder
  Eintrag hat Schlüssel, Label, Kurzlabel (für Spaltenköpfe), Tooltip, lange Erklärung, Gruppe
  und Rolle im Score. Kürzel tragen `abbr: true`, damit der Test sie findet.
- **Faktortexte bleiben bei scoring** (`FACTOR_INFO`). So bleibt der Weg „Neuer Scoring-Faktor“
  aus [CLAUDE.md](../../CLAUDE.md) unverändert. Das UI lädt sie über
  `GET /api/v1/scoring/factors`, den Endpunkt gibt es schon. Ein `GlossaryStore` holt sie einmal
  beim Start und mischt sie mit den Einträgen aus `glossary.ts`. Den Satz „Niedriger ist besser.“
  bzw. „Höher ist besser.“ ergänzt er aus dem Feld `better`. Antwortet die API nicht, zeigen
  Faktoren nur ihr Label.
- Die Felder der Zeilen heißen teils anders als die Faktoren (`pb_ratio` gegenüber `pb`). Die
  Zuordnung steht einmal in `glossary.ts`, ein Test prüft sie gegen die Faktor-Schlüssel des
  erzeugten Clients.
- Texte mit Werten aus den Daten sind Funktionen, etwa
  `valueTrap(params)` → „… Value ≥ 0,70 und Quality ≤ 0,30 …“.
- `FACTOR_INFO` bekommt echte Umlaute und die Texte aus dem Katalog unten. Die Mail nutzt diese
  Texte nicht, der Golden-Master bleibt also gleich.

### Katalog der Texte

Erste Fassung. Platzhalter in geschweiften Klammern kommen aus den Daten.

**Scores und Ranking**

| Schlüssel | Anzeige | Tooltip |
|---|---|---|
| `rank` | Rang | Platz nach Composite unter allen bewerteten Titeln. Bei Gleichstand entscheidet das Symbol. |
| `composite` | Composite | Gesamtscore aus {v} % Value und {q} % Quality. 0 bis 1, höher ist besser. Nur Titel mit beiden Teilscores bekommen ihn. |
| `value_score` | Value | Wie günstig der Titel im Vergleich zu den anderen ist, gemessen an den Value-Faktoren. 0 bis 1, höher heißt günstiger. |
| `quality_score` | Quality | Wie solide das Geschäft im Vergleich ist, gemessen an den Quality-Faktoren. 0 bis 1, höher ist besser. |
| Wert eines Scores | 0,78 | Im Schnitt seiner Faktoren besser als etwa 78 % der bewerteten Titel. |
| `value_trap` | Value-Trap? | Verdacht auf eine Value-Falle: günstig (Value ≥ {a}), aber schwache Qualität (Quality ≤ {b}). Solche Titel sind oft zu Recht billig. |
| `no_composite` | ohne Composite | Kein Composite, weil der Value- oder der Quality-Score fehlt. Meist liefert Yahoo keine Margen oder keinen ROIC, etwa bei Banken. Der Titel steht deshalb am Ende. |
| `below_threshold` | unter Größenschwelle | Börsenwert unter {x} Mio. €, deshalb nicht bewertet. Bei kleinen Werten sind die Yahoo-Daten oft lückenhaft. |
| `scoring_run` | Bewertungslauf #{n} | Eine Berechnung des Rankings auf einem Datenabruf. Jede Neuberechnung bekommt eine eigene Nummer. |
| `fetched_on` | Abruf | Tag, an dem die Daten bei Yahoo Finance abgerufen wurden. |
| `universe_source` | Indexliste | Woher die Zusammensetzung von DAX und MDAX stammt: iShares, Deka oder die geprüfte Ersatzliste. |
| `scoring_profile` | Profil {name} v{n} | Gewichte, Faktoren und Schwellen, mit denen dieses Ranking gerechnet wurde. |

**Value-Faktoren** (Texte für `FACTOR_INFO`, die Richtung hängt der `GlossaryStore` an)

| Schlüssel | Anzeige | Tooltip |
|---|---|---|
| `ev_ebit` | EV/EBIT | Unternehmenswert (Börsenwert plus Nettoschulden) geteilt durch den operativen Gewinn. Negative Werte zählen nicht. |
| `pb` | KBV | Kurs-Buchwert-Verhältnis: Börsenwert geteilt durch das Eigenkapital laut Bilanz. Negative Werte zählen nicht. |
| `p_fcf` | Kurs/FCF | Börsenwert geteilt durch den Free Cashflow, also das Geld, das nach Investitionen übrig bleibt. Schwerer zu schönen als der Gewinn. |
| `shareholder_yield` | Shareholder Yield | Dividenden plus Aktienrückkäufe im Verhältnis zum Börsenwert: Wie viel fließt an die Aktionäre zurück? |

**Quality-Faktoren**

| Schlüssel | Anzeige | Tooltip |
|---|---|---|
| `roic` | ROIC | Return on Invested Capital: Rendite nach Steuern auf das eingesetzte Eigen- und Fremdkapital. |
| `fcf_margin` | FCF-Marge | Free Cashflow je Euro Umsatz. |
| `operating_margin` | Operative Marge | Operativer Gewinn (EBIT) je Euro Umsatz. |
| `net_debt_ebitda` | Net Debt/EBITDA | Nettoschulden geteilt durch den Gewinn vor Zinsen, Steuern und Abschreibungen: in wie vielen Jahren die Schulden getilgt wären. |
| `earnings_stability` | Gewinnstabilität | Wie wenig der Nettogewinn über die letzten fünf Geschäftsjahre schwankt. 1 heißt sehr stabil. |

**Nur zur Information** (der Tooltip endet mit „Nicht im Score.“, wo nichts anderes steht)

| Schlüssel | Anzeige | Tooltip |
|---|---|---|
| `price` | Kurs | Letzter Kurs beim Abruf, in Handelswährung. |
| `market_cap` | Marktkap. | Marktkapitalisierung: Börsenwert aller Aktien. Entscheidet über die Größenschwelle. |
| `pe_ratio` | KGV | Kurs-Gewinn-Verhältnis. Nicht im Score, weil Einmaleffekte den Gewinn stark verzerren. |
| `dividend_yield` | Dividendenrendite | Dividende je Aktie im Verhältnis zum Kurs. Im Score steckt sie im Shareholder Yield. |
| `revenue_growth_5y` | Umsatzwachstum 5 J. | Durchschnittliches jährliches Wachstum des Umsatzes (CAGR) über die verfügbaren Geschäftsjahre, höchstens fünf. |
| `eps_growth_5y` | EPS-Wachstum 5 J. | Wachstum des Gewinns je Aktie (Earnings per Share), berechnet wie das Umsatzwachstum. |

**Stammdaten**

| Schlüssel | Anzeige | Tooltip |
|---|---|---|
| `symbol` | Symbol | Kürzel bei Yahoo Finance. „.DE“ steht für den Handel auf Xetra. |
| `isin` | ISIN | Internationale Wertpapierkennnummer, weltweit eindeutig je Aktie. |
| `dax` | DAX | Die 40 größten Aktiengesellschaften an der Frankfurter Börse. |
| `mdax` | MDAX | Die 50 nächstgrößeren Werte nach dem DAX. |
| `sector` | Sektor | Branche laut Yahoo Finance, ins Deutsche übersetzt. |

**Läufe**

| Schlüssel | Anzeige | Tooltip |
|---|---|---|
| `run` | Lauf | Ein Durchgang: Indexliste laden, Daten abrufen, bewerten, Mail erstellen. |
| `status.running` | läuft | Der Lauf arbeitet noch. Der Balken zeigt, wie viele Titel schon abgerufen sind. |
| `status.success` | erfolgreich | Alle Titel abgerufen und bewertet, die Mail ist erstellt. |
| `status.partial` | teilweise | Fertig, aber einzelne Titel ließen sich nicht abrufen. Das Ranking gilt für die übrigen. |
| `status.no_data` | keine Daten | Kein Titel war bewertbar, es gibt kein Ranking. Meist war Yahoo nicht erreichbar. |
| `status.failed` | fehlgeschlagen | Der Lauf ist abgebrochen. Den Grund zeigt das Lauf-Detail. |
| `dry_run` | Probelauf | Die Mail wurde erstellt und gespeichert, aber nicht verschickt. |
| `force_refresh` | neu abgerufen | Die Daten wurden neu geholt, obwohl es vom selben Tag schon einen Abruf gab. |
| `kind.batch` | Abruf und Bewertung | Normaler Lauf: Daten abrufen und bewerten. |
| `kind.rescore` | Neu bewertet | Ein vorhandener Abruf, mit einem Profil neu berechnet. Ohne Mail. |
| `kind.import` | Import | Altdaten aus dem früheren Batch übernommen. |
| `scored` | Bewertet | Titel mit Score, von allen Titeln der Indexliste. |
| `failed_count` | fehlgeschlagen | Titel, deren Abruf scheiterte. |
| `duration` | Dauer | Zeit vom Start bis zum Ende des Laufs. |
| `exit_code` | Exit-Code | Technischer Rückgabewert: 0 in Ordnung, 1 Fehler im Lauf, 2 Konfiguration, 3 keine bewertbaren Daten, 4 Datenbank nicht erreichbar. |
| `app_version` | Programmversion | Version des Value-Analyzers, mit der der Lauf lief. |

**Profile**

| Schlüssel | Anzeige | Tooltip |
|---|---|---|
| `profile` | Profil | Legt fest, welche Faktoren zählen und wie Value und Quality gewichtet werden. |
| `version` | Version | Jedes Speichern legt eine neue Version an. Alte Versionen bleiben erhalten. |
| `active` | aktiv | Mit dieser Version rechnet der nächste Lauf. |
| `value_weight` | Gewichtung | Anteil von Value am Composite. Der Rest ist Quality. |
| `min_market_cap` | Größenschwelle | Titel mit kleinerem Börsenwert werden nicht bewertet. |
| `min_value_factor_share` | Mindestabdeckung Value | Anteil der aktiven Value-Faktoren, für die Daten vorliegen müssen, damit ein Titel einen Value-Score bekommt. |
| `min_quality_factor_share` | Mindestabdeckung Quality | Dasselbe für die Quality-Faktoren. |
| `value_trap_value_threshold` | Value-Trap ab Value | Ab diesem Value-Score kann ein Titel als Value-Trap gelten. |
| `value_trap_quality_threshold` | Value-Trap bis Quality | Bis zu diesem Quality-Score gilt ein günstiger Titel als Value-Trap. |
| `drop_negative_value_metrics` | Negative Multiples ausschließen | Negatives EV/EBIT, KBV oder Kurs/FCF entsteht durch Verluste. Solche Werte zählen bei dem Faktor nicht, statt als Schnäppchen zu erscheinen. |
| `preview` | Vorschau | Rechnet den letzten Abruf mit deinen Änderungen neu, ohne etwas zu speichern. |
| `rank_delta` | ↑ 2 | Zwei Plätze besser als mit dem aktiven Profil. „neu“: vorher nicht in den Top {n}. |

**Bedienelemente**

| Ansicht | Element | Tooltip |
|---|---|---|
| App-Leiste | Ranking | Alle Titel nach Composite, mit Filtern und Kennzahlen. |
| App-Leiste | Läufe | Verlauf aller Läufe, neuen Lauf starten, Mails ansehen. |
| App-Leiste | Profile | Gewichte und Faktoren des Scorings ansehen und ändern. |
| App-Leiste | Begriffe (Icon) | Alle Begriffe und Abkürzungen erklärt. |
| App-Leiste | offline | Keine Live-Verbindung zum Server. Die Seite aktualisiert sich erst wieder, wenn er erreichbar ist. |
| Ranking | Alle | Alle Titel aus DAX und MDAX. |
| Ranking | Unter Größenschwelle zeigen | Zeigt auch Titel mit zu kleinem Börsenwert. Sie haben keinen Rang und stehen am Ende. |
| Ranking | Kennzahlkarte Ohne Composite | Zeigt nur die Titel, denen der Value- oder der Quality-Score fehlt. |
| Ranking | Spalten (Icon) | Weitere Faktoren ein- oder ausblenden. |
| Ranking | Kennzahlkarte Value-Traps | Zeigt nur die Titel mit Value-Trap-Verdacht. |
| Ranking | Zum aktuellen Ranking | Wechselt zum jüngsten Bewertungslauf. |
| Ranking | Filter zurücksetzen | Index auf „Alle“, Suche leeren. |
| Titel-Detail | ISIN kopieren (Icon) | ISIN in die Zwischenablage kopieren. |
| Läufe | Lauf starten | Startet einen Lauf mit den Optionen, die du im nächsten Schritt wählst. Es läuft immer nur einer. |
| Läufe | Lauf starten, gesperrt | Es läuft schon ein Lauf (#{n}). |
| Start-Dialog | Mail verschicken | Die Mail mit dem Ranking geht an den eingestellten Empfänger. |
| Start-Dialog | Probelauf | Die Mail wird erstellt und gespeichert, aber nicht verschickt. |
| Start-Dialog | Daten neu abrufen | Holt die Daten neu von Yahoo, auch wenn es heute schon einen Abruf gab. Dauert länger. |
| Lauf-Detail | Ranking ansehen | Das Ranking, das dieser Lauf berechnet hat. |
| Lauf-Detail | CSV herunterladen | Alle Titel mit Scores und Kennzahlen als CSV mit Semikolon und Dezimalkomma, öffnet direkt in Excel. |
| Lauf-Detail | Technische Details | Exit-Code, Programmversion, Nummern von Abruf und Bewertungslauf, vollständige Fehlermeldung. |
| Profile | Bearbeiten | Parameter ändern und als neue Version speichern. Aktiv wird sie erst mit „Aktivieren“. |
| Profil-Editor | Als neue Version speichern | Legt Version {n} an. Aktiv wird sie erst mit „Aktivieren“. |
| Profil-Editor | Speichern, gesperrt | Nennt den Grund: ungültiges Feld, Regel verletzt (z. B. zu wenige Faktoren) oder nichts geändert. |
| Profil-Editor | Verwerfen | Setzt alle Felder auf Version {n} zurück. |
| Profil-Editor | Aktivieren | Ab dem nächsten Lauf rechnet Version {n}. Eine ältere Version zu aktivieren heißt zurückrollen. |
| Profil-Editor | Neu laden (Konflikt) | Lädt die neueste Version. Deine Änderungen hier gehen verloren. |

## App-Hülle

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ◆ Value-Analyzer    ▤ Ranking   ↺ Läufe   ⚙ Profile          ⊘ offline   ?  │
├──────────────────────────────────────────────────────────────────────────────┤
│             ┌────────────── Inhalt, höchstens 90 rem, zentriert ─────────┐   │
│             │                                                            │   │
│             └────────────────────────────────────────────────────────────┘   │
│  Quantitative Vorauswahl, keine Anlageempfehlung. · Version {app_version}    │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **App-Leiste** auf dem Schreibtisch, unten eine Haarlinie: Marke als kleines SVG in Tinte mit
  Namen in Serifenschrift, sie führt zum Ranking. Navigation mit Icon und Text, der aktive
  Eintrag als Pille in Vertiefung 3.
  Rechts der Verbindungs-Chip, nur offline sichtbar und mit Icon, und der Icon-Button „Begriffe“.
- **Fußzeile:** Hinweis „Quantitative Vorauswahl, keine Anlageempfehlung.“ und die Programmversion
  aus `GET /api/v1/health`.
- „Runs“ heißt überall „Läufe“, auch im Titel des Browser-Tabs („Läufe · Value-Analyzer“). Die
  Route bleibt `/runs`.

## Ansichten

### Ranking

Route `/ranking` und `/ranking/:scoringRunId`. Frage: Welche Titel sind günstig und solide?

```text
Ranking
Abruf 30.10.2026 · Profil Standard v3 (60 % Value, 40 % Quality) · Indexliste Deka

┌ Bewertet ──────┐ ┌ Spitzenreiter ─────┐ ┌ Value-Traps ──┐ ┌ Ohne Composite ─┐
│ 88 von 90      │ │ Allianz     0,78   │ │ 1             │ │ 2               │
└────────────────┘ └────────────────────┘ └───────────────┘ └─────────────────┘

[Alle | DAX | MDAX]   [⌕ Name oder Symbol       ]   ○ Unter Größenschwelle zeigen    [▥]

 Rang  Titel                  Sektor       Composite          Value  Quality  Hinweis          Marktkap.
    1  Allianz                Finanzen     0,78  ▇▇▇▇▇▇▇▇░░    0,78     0,77                   166,4 Mrd
       ALV.DE · DAX
   16  BMW                    …                                               ⚠ Value-Trap?
   90  Deutsche Bank          Finanzen        –                0,82        –  ohne Composite
       DBK.DE · DAX

Was bedeuten die Spalten? → Begriffe
```

- **Metazeile:** Abruf, Profil und Indexliste als Begriffe mit Tooltip. Die Indexliste heißt
  deutsch („Ersatzliste“ statt des Namens der Fallback-Quelle). Name und Version des Profils
  brauchen [G3](#arbeitspakete); bis dahin stehen dort die Gewichte wie heute.
- **Kennzahlkarten** (`app-stat-card`), aus den Zeilen im Browser berechnet:
  - Bewertet: Titel mit Composite von allen Zeilen.
  - Spitzenreiter: Name als Link und Composite.
  - Value-Traps: Anzahl. Ein Klick filtert auf diese Titel, der Tooltip sagt das.
  - Ohne Composite: Titel, denen ein Teilscore fehlt. Sie haben einen Rang, aber erst nach allen
    Titeln mit Composite. Ein Klick filtert auf sie. Titel unter der Größenschwelle zählen nicht
    mit; sie haben gar keinen Rang und erscheinen nur mit „Unter Größenschwelle zeigen“.
- **Filterleiste:** Index, Suche und Umschalter wie heute. Neu ist die Spaltenwahl
  (`app-column-picker`, ein `mat-menu` mit Checkboxen, gruppiert nach Value- und
  Quality-Faktoren). Die Auswahl bleibt im `localStorage`, Lesen und Schreiben in `try/catch`.
- **Spalten:** Standard sind Rang, Titel, Sektor, Composite, Value, Quality, Hinweis und
  Marktkap. Wählbar sind alle neun Faktoren, ihre Felder hat `RankingRow` schon. Die Spalte
  „Index“ entfällt: Er steht klein unter dem Namen und ist ohnehin Filter.
- **Composite** zeigt `app-score` mit Zahl und Balken. Value und Quality zeigen nur die Zahl, das
  hält die Tabelle ruhig. Alle drei haben den Tooltip mit der Einordnung („besser als etwa 78 %“).
- **Hinweis:** `app-value-trap-badge` mit Icon. „ohne Composite“ und „unter Größenschwelle“ als
  neutrale Badges, alle mit Tooltip. Die eingefärbte Zeile und die halbe Transparenz entfallen.
- **Zahlen** stehen rechtsbündig. Der Tabellenkopf klebt wie heute, auf schmalen Bildschirmen auch
  Rang und Titel am linken Rand.
- **Älterer Bewertungslauf:** oben eine `.notice` „Bewertungslauf vom 23.10.2026, nicht der
  aktuelle.“ mit Button „Zum aktuellen Ranking“.
- **Leer nach Filter:** „Kein Titel passt zum Filter.“ mit Button „Filter zurücksetzen“.
- **Sektoren auf Deutsch:** Die Pipe `sector` in `format.ts` bildet die elf Sektoren von Yahoo ab
  (Basic Materials → Grundstoffe, Communication Services → Kommunikation, Consumer Cyclical →
  Zyklischer Konsum, Consumer Defensive → Basiskonsum, Energy → Energie, Financial Services →
  Finanzen, Healthcare → Gesundheit, Industrials → Industrie, Real Estate → Immobilien,
  Technology → Technologie, Utilities → Versorger). Was sie nicht kennt, bleibt wie geliefert.
  Sortiert wird nach dem deutschen Namen.

### Titel-Detail

Route `/instruments/:symbol`. Frage: Warum steht dieser Titel dort, wo er steht?

```text
← Ranking
Allianz
ALV.DE · ISIN DE0008404005 ⧉ · DAX · Finanzen · Versicherung

┌ Rang ─────────┐ ┌ Composite ────────────┐ ┌ Value ────────┐ ┌ Quality ──────┐
│ 1             │ │ 0,78  ▇▇▇▇▇▇▇▇░░      │ │ 0,81          │ │ 0,72          │
│ ↑ 2 seit 23.10│ │ 60 % Value, 40 % Qual.│ │               │ │               │
└───────────────┘ └───────────────────────┘ └───────────────┘ └───────────────┘

Kennzahlen · Stand 30.10.2026
┌ Bewertung (Value) ───────────┐ ┌ Qualität (Quality) ──────────┐ ┌ Markt und Wachstum ────────┐
│ EV/EBIT                9,8   │ │ ROIC                 12,3 %  │ │ Kurs            340,10 EUR │
│ KBV                    1,6   │ │ FCF-Marge            14,0 %  │ │ Marktkap.        140,0 Mrd │
│ Kurs/FCF               8,2   │ │ Operative Marge      11,2 %  │ │ Umsatzwachstum 5 J.  4,1 % │
│ Shareholder Yield     6,1 %  │ │ Net Debt/EBITDA        0,9   │ │ EPS-Wachstum 5 J.    7,9 % │
│ nur zur Information          │ │ Gewinnstabilität      0,93   │ │                            │
│ KGV                   11,4   │ │                              │ │                            │
│ Dividendenrendite     4,8 %  │ │                              │ │                            │
└──────────────────────────────┘ └──────────────────────────────┘ └────────────────────────────┘

Score-Verlauf      Composite  ╱‾‾╲__╱‾  (Sparkline)
 Bewertet     Rang   Composite   Value   Quality   Hinweis
 30.10.2026      1        0,78    0,81      0,72
```

- **Kennzahlkarten oben** aus dem neuesten Punkt des Score-Verlaufs. Die Veränderung zum Punkt
  davor steht als kleiner Pfeil mit Tooltip („2 Plätze besser als am 23.10.2026“). „1 von 84“
  braucht [G3](#arbeitspakete), bis dahin nur der Rang.
- **Kennzahlen in drei Karten:** Bewertung (die vier Value-Faktoren, darunter abgesetzt KGV und
  Dividendenrendite als „nur zur Information“), Qualität (die fünf Quality-Faktoren), Markt und
  Wachstum. Jedes Label ist ein Begriff mit Tooltip.
- **Mit [G3](#arbeitspakete):** Jede Faktorzeile zeigt zusätzlich einen kleinen Balken mit dem
  Perzentil im neuesten Bewertungslauf („besser als 81 % der Titel“). Das beantwortet das „Warum“
  direkt. Faktoren, die das Profil dieses Laufs nicht nutzt, erscheinen gedämpft mit „nicht
  aktiv“.
- **Score-Verlauf:** `app-sparkline` (Inline-SVG, ohne Diagramm-Bibliothek) für den Composite,
  darunter die Tabelle wie heute, neueste Bewertung zuerst.
- **Hinweise vom Abruf** und „Abruf unvollständig“ als `.notice` mit Icon über den Kennzahlen.
- **ISIN kopieren** über `Clipboard` aus dem CDK. `navigator.clipboard` allein ginge im LAN nicht,
  denn es braucht HTTPS. Rückmeldung als Snackbar „ISIN kopiert“.
- **Platz für F3.2:** Anker, Wertlinie und Renditezerlegung aus Track F kommen später als eigene
  Karte unter die Kennzahlen.

### Läufe

Route `/runs`. Frage: Lief der letzte Lauf sauber?

```text
Läufe                                                                [▶ Lauf starten]

┌ Letzter Lauf ─────────────────────────────────────────────────────────────────────┐
│ ✓ erfolgreich   #57 · 30.10.2026 06:02 · 12 min · 88 von 90 bewertet, 2 fehlgeschl.│
│                                                                  Ranking ansehen  │
└───────────────────────────────────────────────────────────────────────────────────┘

 Lauf               Gestartet          Dauer    Status                      Bewertet   Art
 #58                04.11.2026 10:12   –        ◌ läuft  ▇▇▇▇░░░░  45/90          –    Abruf und Bewertung
 #57                30.10.2026 06:02   12 min   ✓ erfolgreich               88/90     Abruf und Bewertung
 #56  Probelauf     29.10.2026 21:40   11 min   ⓘ teilweise                 85/90     Abruf und Bewertung
```

- **Lauf starten** ist die Hauptaktion im Seitenkopf und öffnet einen Dialog (`mat-dialog`):

  ```text
  Lauf starten
   Mail    (•) verschicken
           ( ) Probelauf: Mail nur erstellen und speichern
   ☐ Daten neu abrufen  ⓘ
                                            [Abbrechen]  [Lauf starten]
  ```

  Abbildung auf `RunStart`: „verschicken“ ist `dry_run: false, notify: true`, „Probelauf“ ist
  `dry_run: true, notify: false`. Die dritte Kombination von heute (keine Mail, aber kein
  Probelauf) entfällt im UI, die API bleibt gleich. Die Meldungen bei 409 und 503 zeigt der
  Dialog wie heute die Seite.
- **Während ein Lauf läuft,** ist der Button gesperrt (`disabledInteractive`), der Tooltip nennt
  den laufenden Lauf.
- **Karte „Letzter Lauf“:** der neueste abgeschlossene Lauf mit Status, Zeit, Dauer, Zählern und
  dem Link zu seinem Ranking.
- **Fortschritt** als `mat-progress-bar` mit `done/total` aus dem `LiveStore`. Der Tooltip nennt
  den zuletzt abgerufenen Titel.
- **Spalten:** Lauf (Nummer, Badges „Probelauf“ und „neu abgerufen“), Gestartet, Dauer (aus
  `started_at` und `finished_at`), Status (`app-run-status`), Bewertet (Tooltip mit der Zahl der
  fehlgeschlagenen), Art (deutsch über die Pipe `runKind`). Der Exit-Code steht nur noch im
  Lauf-Detail.
- **Leer:** „Noch keine Läufe. Der erste startet mit ‚Lauf starten‘ oder zum geplanten Termin.“

### Lauf-Detail

Route `/runs/:runId`.

```text
← Alle Läufe
Lauf #57   ✓ erfolgreich   Probelauf                  [Ranking ansehen]  [⤓ CSV herunterladen]

┌ Überblick ─────────────────────────────────────┐
│ Gestartet      30.10.2026 06:02                │
│ Beendet        30.10.2026 06:14                │
│ Dauer          12 min                          │
│ Bewertet       88 von 90, 2 fehlgeschlagen     │
│ Art            Abruf und Bewertung, neu abgerufen │
└────────────────────────────────────────────────┘
⚠ Fehler: erste Zeile der Fehlermeldung         (nur bei einem Fehler)
▸ Technische Details

Mail
Betreff: {Betreff der Mail}
So sah die Mail aus. Bei einem Probelauf wurde sie nur gespeichert.
┌ Vorschau der Mail (iframe, sandbox) ┐
```

- Aktionen als `outlined`-Buttons im Seitenkopf. Eine Hauptaktion braucht die Seite nicht.
- Ein Fehler zeigt seine erste Zeile über `app-notice` (`error: true`). Die vollständige Meldung steht mit
  Exit-Code, Programmversion und den Nummern von Abruf und Bewertungslauf unter „Technische
  Details“ (`mat-expansion-panel`, geschlossen).
- Die Mail bleibt im iframe mit leerem `sandbox`, wie heute.

### Profile

Route `/profiles`.

```text
Scoring-Profile
Ein Profil legt fest, welche Faktoren zählen und wie Value und Quality gewichtet werden.
Der nächste Lauf rechnet mit der aktiven Version.

┌────────────────────────────────────────────────────────────────────────────────┐
│ Standard     aktiv: Version 3     neueste: Version 4, nicht aktiv ⓘ   [Bearbeiten] │
│ angelegt am 01.11.2026                                                         │
└────────────────────────────────────────────────────────────────────────────────┘
```

- Je Profil eine Karte. „neueste: Version 4, nicht aktiv“ erscheint nur, wenn sie von der aktiven
  abweicht. Der Tooltip sagt, dass sie erst mit „Aktivieren“ zählt.

### Profil-Editor

Route `/profiles/:profileId`.

```text
← Alle Profile
Standard   aktiv: Version 3
Grundlage: Version 4. Speichern legt Version 5 an.

┌ Parameter ─────────────────────────────┐  ┌ Vorschau: Was ändert sich? ⓘ ─────────────┐
│ Gewichtung ⓘ                           │  │ Abruf 30.10.2026, verglichen mit          │
│ Value ━━━━━━━━━●━━━━━━ Quality         │  │ Standard v3                               │
│ 60 % Value · 40 % Quality              │  │ [3 neu in den Top 20] [2 raus] [1 Trap ±] │
│                                        │  │                                           │
│ Größenschwelle ⓘ   [   300 ] Mio. €    │  │ Rang   Δ      Titel          Composite    │
│                                        │  │   1    –      Allianz             0,78    │
│ ▸ Erweitert                            │  │   2    ↑ 3    …                           │
│   Mindestabdeckung Value ⓘ     50 %    │  │   3    neu    …                           │
│   Mindestabdeckung Quality ⓘ   50 %    │  └───────────────────────────────────────────┘
│   Value-Trap ab Value ⓘ        0,70    │
│   Value-Trap bis Quality ⓘ     0,30    │
│   ☑ Negative Multiples ausschließen ⓘ  │
│                                        │
│ Value-Faktoren                         │
│ ☑ EV/EBIT        niedriger ist besser  │
│   Unternehmenswert geteilt durch …     │
│ Quality-Faktoren                       │
│ ☑ ROIC           höher ist besser      │
└────────────────────────────────────────┘
┌ klebt unten, sobald etwas geändert ist ────────────────────────────────────────────┐
│ Kommentar [                                    ]     [Verwerfen] [Als neue Version speichern] │
└────────────────────────────────────────────────────────────────────────────────────┘

Versionen
 Version 4   03.11.2026 21:10   auf Basis von v3   „ROIC stärker“             [Aktivieren]
 Version 3   01.11.2026 18:02   aktiv
```

- **Gewichtung** als `mat-slider` von 0 bis 100 % in Schritten von 5 %. Das Formular-Modell
  bleibt 0 bis 1, die Ansicht rechnet um.
- **Größenschwelle** in Mio. € (Schritt 50), das Modell bleibt in Euro.
- **Mindestabdeckung** als Prozent.
- Selten geänderte Felder liegen unter „Erweitert“ (`mat-expansion-panel`, geschlossen).
- Die Hinweise unter den Faktoren bleiben sichtbar. Sie sind kurz und für die Entscheidung nötig.
- **Vorschau** bleibt rechts und klebt beim Scrollen (`position: sticky`). Oben stehen drei
  Badges als Zusammenfassung, die Spalte Δ zeigt Pfeil-Icons mit Tooltip.
- **Speichern-Leiste** klebt unten, sobald sich etwas geändert hat: Kommentar, „Verwerfen“ (zurück
  zur Grundlage) und „Als neue Version speichern“ mit dem Grund im Tooltip, wenn er gesperrt ist.
- **Versionen** als Liste, die aktive mit Badge. Aktivieren braucht keinen Bestätigungsdialog,
  denn es lässt sich mit einer anderen Version umkehren. Rückmeldung als `.notice` wie heute.

### Begriffe (neu)

Route `/glossary`, Titel „Begriffe“.

- Alle Einträge aus dem Glossar nach Gruppen: Scores, Value-Faktoren, Quality-Faktoren, nur zur
  Information, Stammdaten, Läufe, Profile. Je Eintrag Label, Ausschreibung, lange Erklärung und
  Rolle im Score.
- Jeder Begriff hat einen Anker (`/glossary#roic`), ein Suchfeld oben filtert die Liste.
- Ein kurzer Abschnitt „So entsteht das Ranking“: Perzentile je Faktor, Mittelwert je Gruppe,
  Gewichtung, warum KGV nicht zählt, die Value-Trap-Regel und der Hinweis, dass das Ranking keine
  Anlageempfehlung ist.

## Neue Bausteine

Alle unter `frontend/src/app/shared/ui/`, jeder mit Test wie in `ui.spec.ts`.

**Erweitert werden:**

| Baustein | Neu |
|---|---|
| `app-run-status` | Icon und Fläche je Status (siehe [Bedeutung ohne Farbe](#bedeutung-ohne-farbe)), Tooltip aus dem Glossar; der Fortschritt als `mat-progress-bar` mit `matTooltip` statt `title` |
| `app-value-trap-badge` | Warn-Icon, Tooltip mit den Schwellen des Profils (`[params]`, ohne sie der allgemeine Text) |
| `app-notice` | bleibt; auch Fehler im Lauf-Detail und die Meldungen des Start-Dialogs laufen darüber |
| `app-page-header` | Platz für Badges und Status rechts neben der h1, wie im Lauf-Detail skizziert |

**Neu:**

| Baustein | Wofür | Grundlage |
|---|---|---|
| `app-icon` | SVG-Icon aus der festen Liste | Inline-SVG |
| `app-term` | Begriff mit Tooltip aus dem Glossar, `<app-term key="ev_ebit" />`, Varianten kurz und lang | `matTooltip` |
| `app-info-tip` | ⓘ als Icon-Button mit Tooltip, neben Formular-Labels und Abschnittsköpfen | `matIconButton`, `matTooltip` |
| `app-score` | Score als Zahl, auf Wunsch mit Balken, Tooltip mit Einordnung | – |
| `app-stat-card` | Kennzahlkarte: Begriff, großer Wert, Nebenzeile, auf Wunsch klickbar | `mat-card` |
| `app-section` | Karte mit Überschrift, optional ⓘ und Aktionen | `mat-card` |
| `app-state` | Laden (Balken und Text), leer (Icon, Satz, nächster Schritt), Fehler (`role="alert"`). Nimmt die Signale aus `loaded` und `loadError` und ersetzt die `.message`-Zweige | `mat-progress-bar` |
| `app-sparkline` | Verlauf als kleine Linie | Inline-SVG |
| `app-column-picker` | Spaltenwahl einer Tabelle | `mat-menu` |

Dazu kommen Muster-Klassen in `_patterns.scss` (`.num`, `.card-grid`, `.stat-grid`, `.term`,
`.sticky-bar`) und neben `day`, `dayTime` und `orDash` die Pipes `sector`, `runKind`, `duration`
und `indexSource` in `format.ts`.

Neu genutzte Module aus Material und CDK: Tooltip, Card, Menu, Dialog, Slider, Progress Bar,
Expansion, Snack Bar und Clipboard. Alle stecken in den Paketen, die schon da sind. Die Seiten
laden weiter einzeln (`loadComponent`), das Budget wird je Paket geprüft.

## Zustände

- **Laden:** `app-state` mit Balken ohne Ende und Text („Lade das Ranking …“). Er erscheint erst
  nach 300 ms, damit schnelle Antworten nicht flackern. Lädt eine Seite wegen eines
  WebSocket-Ereignisses neu, bleiben die alten Daten stehen, bis die neuen da sind.
- **Leer:** Icon, ein Satz und der nächste Schritt.
- **Fehler:** `.notice--error` mit `role="alert"`. Die Texte in `api-error.ts` verlieren den
  Fachjargon: „Der Server oder seine Datenbank ist nicht erreichbar.“ statt „Das web-api …“.

## Barrierefreiheit

Ziel ist WCAG 2.2, Stufe AA.

- Kontraste kommen aus der Papier-Palette und sind nachgerechnet (siehe [Palette](#palette)).
  Seiten setzen keine eigenen Farben.
- Alles geht per Tastatur. Tooltips erscheinen auch beim Fokus, Begriffe sind fokussierbar, der
  Fokusring ist sichtbar (2 px `primary`).
- Information steckt nie nur in der Farbe: Status und Value-Trap tragen Icon und Text.
- Icon-Buttons haben ein `aria-label`, das dem Tooltip entspricht.
- Tabellen haben `th` mit `scope`, Material kündigt die Sortierung an.
- Animationen nur bei `prefers-reduced-motion: no-preference`.
- Klickflächen mindestens 24 × 24 px (WCAG 2.5.8). Die Material-Dichte 0 liefert 40 bis 48 px.
- Geprüft wird mit axe-core im Browser-Test (`@axe-core/playwright`, nur als devDependency).

## Schmale Bildschirme

| Breite | Verhalten |
|---|---|
| unter `$compact` (600 px) | Navigation nur mit Icons (mit Tooltip und `aria-label`). Kennzahlkarten 2 × 2. Tabellen scrollen waagrecht, Rang und Titel kleben links, Faktorspalten sind aus. |
| unter `$narrow` (900 px) | Zweispaltiges steht untereinander, wie heute im Profil-Editor: Vorschau unter dem Formular, Kennzahlkarten im Titel-Detail untereinander. |
| ab 900 px | wie in den Skizzen |

## Tests

1. **Tooltip-Abdeckung** (Vitest, je Ansicht): Jede Seite wird mit den Daten aus
   `testing/fixtures.ts` gerendert. Jedes `button`, `a[matButton]`, `mat-button-toggle`,
   `mat-slide-toggle`, `mat-checkbox`, jeder Spaltenkopf, jedes `dt` und jedes `.badge` braucht
   eine `MatTooltip`-Direktive mit Text (`By.directive(MatTooltip)`). Ausnahmen stehen mit Grund
   in einer Liste im Test, etwa die Links mit dem Namen eines Titels.
2. **Kein Kürzel ohne Erklärung:** Im gerenderten Text jeder Seite steht keines der Kürzel aus dem
   Glossar (`abbr: true`, etwa KBV, KGV, ROIC, EV/EBIT, FCF, EPS, ISIN, Marktkap.) außerhalb
   eines Elements mit Tooltip.
3. **Glossar vollständig:** Jeder Faktor-Schlüssel des erzeugten Clients ist einer Spalte
   zugeordnet. Jeder Run-Status, jede Lauf-Art und jeder Sektor aus den Fixtures hat einen Text.
   Kein Tooltip ist leer oder länger als 200 Zeichen.
4. **Bausteine:** Unit-Tests je Komponente in `shared/ui/`.
5. **Browser-Tests** (Playwright): Die bestehenden Tests bleiben. Neu: Der Tooltip erscheint bei
   Hover auf „EV/EBIT“ und beim Tastaturfokus, die Seite „Begriffe“ ist über die App-Leiste
   erreichbar, axe findet nichts der Stufen „serious“ und „critical“, die Konsole bleibt leer.
   Der Test des Profil-Editors ändert sich bewusst: Die Gewichtung wird in Prozent eingegeben.
6. **Nur Tokens, nur Grau:** Ein Test sucht in `frontend/src/**/*.scss` nach Farbliteralen
   (`#…`, `rgb(`, `hsl(`). Erlaubt sind sie nur in `_paper.scss` und als weißer Hintergrund der
   Mail-Vorschau. In `_paper.scss` muss jeder Wert ein Grauton sein (Kanäle höchstens 16
   auseinander).

## Arbeitspakete

Jedes Paket folgt dem Zyklus aus dem [Implementierungsplan](implementierungsplan.md): Tests
zuerst, dann Code, dann `make ui-check` und `make check`, dann Review. Ab G1 läuft auch
`make local-e2e`.

| Paket | Inhalt | Braucht |
|---|---|---|
| G0 Designvorlage | Klickbarer Entwurf aller Ansichten im Papier-Design als statische HTML-Seite ([docs/design/vorlage.html](../design/vorlage.html)), mit echten Daten aus der Replay-Fixture, hell und dunkel. Deine Abnahme legt die Optik fest, bevor Code entsteht. | – |
| G1 Fundament und Hülle | Baut auf der Ergänzung des Styleguides vom 04.11.2026 auf (`676ae81`). Papier-Theme `_paper.scss` mit Serifen für Überschriften, Tokens, Breakpoint `$compact`, Overrides für Karte, Dialog, Menü und Tooltip, `MAT_TOOLTIP_DEFAULT_OPTIONS`, `app-icon`, `app-section`, `app-state`. App-Leiste mit Icons, „Läufe“ statt „Runs“, Offline-Chip, Fußzeile mit Hinweis und Version, Inhaltsbreite. Styleguide ergänzt, Test 6. | G0 |
| G2 Begriffe und Tooltips | `glossary.ts` mit dem ganzen Katalog, `GlossaryStore`, `app-term`, `app-info-tip`, Seite „Begriffe“, Pipes `sector`, `runKind`, `duration`, `indexSource`. `FACTOR_INFO` mit Umlauten und neuen Texten. Gerüst der Tests 1 bis 3. | G1 |
| G3 API-Ergänzungen (additiv) | `Ranking`: Profil (Name, Version) und Parameter des Bewertungslaufs (`scoring_run.config`). `ScorePoint`: Zahl der bewerteten Titel. `Instrument`: Perzentil je Faktor aus dem neuesten Bewertungslauf (`percentile_rank` liegt schon in der DB). Optional: der nächste geplante Lauf. Neuer Snapshot, neuer Client, `oasdiff` grün. | – |
| G4 Ranking | wie [oben](#ranking) beschrieben | G1, G2; G3 für Profil und Schwellen im Text |
| G5 Titel-Detail | wie [oben](#titel-detail) beschrieben | G1, G2; G3 für Faktor-Balken |
| G6 Läufe und Lauf-Detail | wie [oben](#läufe) beschrieben | G1, G2 |
| G7 Profile und Editor | wie [oben](#profil-editor) beschrieben | G1, G2 |
| G8 Abschluss | axe, hell und dunkel, schmale Bildschirme, Tooltip-Tests im Browser, Doku (Styleguide, [frontend.md](frontend.md)), Review des Ganzen | G4 bis G7 |

**Parallelität:** G3 ist Backend und kann neben G1 und G2 laufen. G4 bis G7 ändern je einen
Ordner unter `frontend/src/app/` und können nach G2 in getrennten Worktrees laufen. Deshalb legt
G2 den ganzen Katalog auf einmal an: Sonst kämen sich vier Pakete in `glossary.ts` in die Quere.

## Abnahmekriterien

- Jede Ansicht beantwortet ihre Frage im ersten Bildschirm, ohne Scrollen, bei 1920 × 1080 und
  1366 × 768.
- Die Tooltip-Tests sind grün, jede Ausnahme ist begründet.
- Nur Grautöne: Farbwerte stehen nur in `_paper.scss` (und weiß in der Mail-Vorschau), Maße
  nur aus `--va-*`.
- Hell und dunkel durchgesehen, Screenshots im Review.
- axe meldet nichts der Stufen „serious“ und „critical“.
- E2E grün, Konsole leer, keine Anfrage an fremde Hosts.
- Das Bundle bleibt unter der Warnschwelle von 500 kB.
- Der Styleguide beschreibt jeden neuen Baustein, seine Checkliste fragt nach Tooltips.

## Entscheidungen

E2 hast du am 04.11.2026 entschieden. Die übrigen sind Vorschläge, offen bis zu deiner Abnahme:

| Nr. | Frage | Vorschlag |
|---|---|---|
| E1 | Methodenbegriffe übersetzen? | Nein. Value, Quality, Composite und Value-Trap bleiben, wie in Mail und CSV, und werden per Tooltip erklärt. Alles andere wird deutsch. |
| E2 | Farbpalette | **Entschieden:** Papier-Design, nur Graustufen und Papierfarbe, Töne wie Archivar. Warnungen stehen in voller Tinte statt in Rot. |
| E3 | Optionen beim Start eines Laufs | Zwei Mail-Optionen statt zwei Checkboxen. „Keine Mail, aber kein Probelauf“ entfällt im UI. |
| E4 | Designvorlage vorab (G0)? | Ja, damit die Optik feststeht, bevor vier Pakete parallel bauen. |
| E5 | API-Ergänzungen (G3)? | Ja, additiv. Ohne G3 bleiben die Tooltips allgemein (ohne Schwellen), und das Titel-Detail zeigt keine Faktor-Balken. |
| E6 | Eingefärbte Zeile bei Value-Trap? | Nein, nur das Badge in voller Tinte mit Icon. |
| E7 | Tooltip auf Links mit sprechendem Text? | Nein, er würde nur den Text wiederholen. |

## Nicht Teil dieser Spec

- Neue Fachfunktionen: Watchlists, Diagramme über die Sparkline hinaus, Login. Sie stehen in der
  Roadmap unter „Danach“.
- Ein Umschalter für hell und dunkel. Die Systemeinstellung bleibt maßgeblich.
- Änderungen an Methodik oder Mail.
- Anker, Wertlinie und Renditezerlegung im Titel-Detail (F3.2). Sie bekommen einen Platz, kommen
  aber mit Track F.
