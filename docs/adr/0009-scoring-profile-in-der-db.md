# ADR-0009: Scoring-Profile versioniert in der DB, im UI editierbar

- **Status:** akzeptiert
- **Datum:** 2026-09-30
- **Ändert:** die CLAUDE.md-Konventionen „Konfiguration kommt aus Pydantic Settings“ (für
  Scoring-Parameter) und „Magic Numbers gehören in `ScoringConfig`“

## Kontext

Gewichte und Schwellen des Scorings kommen heute aus ENV-Variablen (`VALUE_WEIGHT`,
`MIN_MARKET_CAP`, …) und aus `ScoringConfig`. Jede Änderung braucht ein Deployment, und es ist
nicht festgehalten, mit welchen Parametern ein altes Ranking entstanden ist. Das Scoring soll
künftig im UI anpassbar sein.

## Entscheidung

- **Der `scoring`-Service besitzt die Profile.**
- **Jedes Speichern erzeugt eine neue, unveränderliche Version.** Aktiv ist genau eine, nämlich
  die jüngste Zeile einer Aktivierungs-Tabelle. Das passt zum Schreibschutz aus
  [ADR-0003](0003-postgresql-schema-pro-service.md).
- **Reproduzierbarkeit:** Jeder Bewertungslauf speichert seine Profil-Version.
- **Im UI änderbar:**
  - Value/Quality-Gewichtung (ein Schieberegler),
  - Mindest-Marktkapitalisierung,
  - Faktoren an oder aus,
  - Mindestanteil vorhandener Faktoren,
  - Value-Trap-Schwellen,
  - Ausschluss negativer Multiples.
- **Nicht änderbar:** der Faktor-Katalog und die Richtung der Faktoren. Neue Faktoren bleiben
  Code-Änderungen.
- **Live-Vorschau** per Request/Reply, ohne zu speichern. Eine Aktivierung löst einen Rescore des
  letzten Snapshots aus, ohne Mail.
- **Validierung aus einer Quelle:** Pydantic → OpenAPI → Zod → Angular Signal Forms. Regeln über
  mehrere Felder meldet die Vorschau als `422`.
- **ENV-Werte dienen nur einmal als Startwerte** für das Profil „Standard“.

Details: [scoring-profile.md](../architecture/scoring-profile.md).

## Konsequenzen

- ✅ Man kann ohne Deployment experimentieren, jedes Ranking ist reproduzierbar, und jede Änderung
  ist umkehrbar.
- ⚠️ Methodik-Parameter sind nicht mehr im Code-Review sichtbar. Versionskommentare und die
  Anzeige im Mail-Footer gleichen das aus.
- ⚠️ Zwei CLAUDE.md-Konventionen ändern sich. „Konfiguration aus Settings“ gilt nur noch für
  Werte, die vom Deployment abhängen, und neue Schwellen kommen in `ScoringProfileParams`.

## Verworfene Alternativen

- **Weiter nur über ENV:** kein UI, keine Nachvollziehbarkeit alter Rankings.
- **Überschreibbares Profil ohne Versionen:** einfacher, aber nicht reproduzierbar und im
  Widerspruch zum Schreibschutz.
- **Frei definierbare Faktoren im UI:** hohes Methodik-Risiko. Faktoren brauchen Extraktion, Tests
  und eine Begründung, und das gehört in den Code.
