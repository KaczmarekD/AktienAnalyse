# Regressionstest

> **Status:** Vorschlag (19.10.2026), nach Abschluss von Phase 1. Entscheidung offen.

## Was es heute schon gibt

| Ebene | Test | Prüft | Lücke |
|---|---|---|---|
| Mail | Golden-Master (`tests/test_golden_report.py`) | eingefrorener Datensatz → HTML byte-gleich, CSV inhaltlich gleich | 8 erfundene Titel, kein echter Abruf |
| Kennzahlen | Kennzahlen-Golden (`tests/test_metrics_snapshot.py`) | Rohdaten von 7 echten Titeln → Kennzahlen unverändert | Rohdaten von einem Stichtag, kein Scoring |
| Ablauf | Golden-Mail über den Bus (`tests/test_pipeline_bus.py`) | alle Handler und Events ergeben die Golden-Mail | Fakes für Abruf und Speicher |
| Datenbank | `tests/db/test_pipeline_db.py` | kompletter Lauf gegen echtes PostgreSQL | Yahoo-HTTP gepatcht, 4 Titel |

Alles läuft offline und in der CI. Was fehlt: ein Vergleich mit **echten Daten der laufenden
Woche** und mit dem **Ergebnis des alten Codes**. Genau dort steckt das Risiko eines Umbaus wie
Phase 1: echte yfinance-Formen, der Pfad „Abruf vom selben Tag wiederverwenden“ und die
Umgebung auf der NAS.

## Vorschlag A: Alt gegen Neu auf der NAS (einmalig vor dem Umstieg)

Ohne neuen Code. Beide Images liegen in GHCR: alt `sha-8b685ef` (Stand vor Phase 1), neu das
Image des Merge-Commits.

1. Altes Image mit `--dry-run`: holt die Daten von Yahoo, speichert einen `fetch_run`, schreibt
   `preview_latest.html` und `preview_value_ranking_<datum>.csv` nach `DATA_DIR`. Beide Dateien
   nach `regression/alt/` kopieren.
2. Am selben Tag das neue Image mit `--dry-run`: Es nutzt denselben `fetch_run` wieder
   (`find_reusable_fetch`), rechnet also auf **identischen Eingaben**. Vorschau nach
   `regression/neu/`.
3. Vergleichen:
   - CSV inhaltlich gleich (wie im Golden-Master: Gleitkomma mit Toleranz in der letzten
     Stelle).
   - HTML gleich bis auf die Zeile mit der Uhrzeit der Erzeugung.
   - In der DB: Die beiden `scoring_run` auf demselben `fetch_run` haben je Titel dieselben
     Scores und Ränge (`score_result`, Abfrage mit der Rolle `va_read`).
4. Optional das neue Image mit `--dry-run --force-refresh`: Damit läuft auch der Abrufpfad des
   neuen Codes. Kurse ändern sich zwischen den Läufen, deshalb nur Abdeckung (Anzahl Titel mit
   Marktkapitalisierung, Fehlerliste) und die Kennzahlen aus den Abschlüssen vergleichen.

Kosten: zwei bis drei Dry-Runs, je etwa 5–10 Minuten. Die Läufe stehen danach als `dry_run` in
`batch.run`, gelöscht wird nichts. Für Schritt 3 reicht ein kleines Vergleichsskript
(`docker/regression/compare.py`).

## Vorschlag B: Replay-Regression über gespeicherte Wochen (dauerhaft)

Die Datenbank löscht nie und hält jeden Abruf als Snapshot. Damit wird **jede vergangene Woche
zu einem Testfall**:

- Werkzeug `python -m src.regression --fetch-run N`: liest die Snapshots nur (Rolle `va_read`),
  bewertet sie im Speicher neu, baut den Report mit festem Zeitpunkt und vergleicht mit
  `scoring.score_result`, `scoring.factor_score` und der CSV aus `reporting.report` dieses Laufs.
  Es schreibt nichts.
- `make regression` auf der NAS mit dem neuen Image, bevor `make up` umstellt.
- Für die CI: einige Wochen als Fixtures exportieren (`tests/fixtures/replay/<datum>.json`, nur
  Snapshot-Spalten, das sind öffentliche Marktdaten). Dann läuft die Regression über echte
  Wochen bei jedem Push.

Abweichungen sind dort gewollt, wo sich die Methodik ändert (Phase 2b Scoring-Profile, ADR-0011).
Dann zeigt das Werkzeug genau den Unterschied, und die Fixtures werden bewusst neu geschrieben,
wie beim Golden-Master mit `--update-golden`.

## Empfehlung

- **Jetzt A**, bevor Phase 1 auf der NAS läuft. Kein neuer Code nötig, schnell erledigt, und
  echte Daten werden mit dem alten Ergebnis verglichen.
- **B als eigenes Arbeitspaket** vor Phase 2b. Dort soll das Standardprofil das heutige Ranking
  exakt reproduzieren, und genau das kann B prüfen.
