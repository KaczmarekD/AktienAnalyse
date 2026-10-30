# Regressionstest

> **Status:** Vorschlag vom 19.10.2026. B ist am 30.10.2026 entschieden und wird als
> [P2b.0](implementierungsplan.md#p2b0-replay-regression-über-gespeicherte-wochen) umgesetzt.
> A bleibt ein einmaliger Schritt auf der NAS.

## Was es heute schon gibt

| Ebene | Test | Prüft | Lücke |
|---|---|---|---|
| Mail | Golden-Master (`tests/test_golden_report.py`) | eingefrorener Datensatz → HTML byte-gleich, CSV inhaltlich gleich | 8 erfundene Titel, kein echter Abruf |
| Kennzahlen | Kennzahlen-Golden (`tests/test_metrics_snapshot.py`) | Rohdaten von 7 echten Titeln → Kennzahlen unverändert | Rohdaten von einem Stichtag, kein Scoring |
| Ablauf | Golden-Mail über den Bus (`tests/test_pipeline_bus.py`) | alle Handler und Events ergeben die Golden-Mail | Fakes für Abruf und Speicher |
| Datenbank | `tests/db/test_pipeline_db.py` | kompletter Lauf gegen echtes PostgreSQL | Yahoo-HTTP gepatcht, 4 Titel |
| Echte Wochen (seit P2b.0) | Replay-Regression (`tests/test_replay_fixtures.py`, `make regression`) | gespeicherte Snapshots → Scores, Faktor-Ränge, CSV unverändert | in der CI nur die exportierten Wochen |

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

- Werkzeug `python -m src.regression` (Auswahl mit `--scoring-run N` oder `--fetch-run N`,
  sonst alle Läufe außer Rescores): liest die Snapshots über eine schreibgeschützte Verbindung,
  schickt sie durch die Handler von scoring und notification und vergleicht mit
  `scoring.score_result`, `scoring.factor_score` und der CSV aus `reporting.report` dieses Laufs.
  Es schreibt nichts. Exit 0: gleich, 1: Abweichungen, 2: nichts zu vergleichen oder Fehler.
- `make regression` auf der NAS mit dem neuen Image, bevor `make up` umstellt.
- Für die CI: Wochen als Fixtures exportieren (`make regression-export` bzw. `--export DIR`,
  Datei `<datum>_scoring-run-<id>.json` nach `tests/fixtures/replay/`). Sie enthalten die
  Snapshot-Spalten (öffentliche Marktdaten) und das Ergebnis von damals. Dann läuft die
  Regression über echte Wochen bei jedem Push.
- Importierte Altwochen haben nur Scores (keine Faktor-Ränge, kein Report). Verglichen wird dann
  nur, was gespeichert ist.

Abweichungen sind dort gewollt, wo sich die Methodik ändert (Phase 2b Scoring-Profile, ADR-0011).
Dann zeigt das Werkzeug genau den Unterschied, und die Fixtures werden bewusst neu geschrieben,
wie beim Golden-Master mit `--update-golden`.

## Empfehlung

- **Jetzt A**, bevor Phase 1 auf der NAS läuft. Kein neuer Code nötig, schnell erledigt, und
  echte Daten werden mit dem alten Ergebnis verglichen.
- **B als eigenes Arbeitspaket** vor Phase 2b. Dort soll das Standardprofil das heutige Ranking
  exakt reproduzieren, und genau das kann B prüfen.
