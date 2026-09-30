# ADR-0004: Monorepo mit uv-Workspace

- **Status:** akzeptiert
- **Datum:** 2026-09-30

## Kontext

Heute gibt es ein Python-Paket (`src`) mit pip-tools-Lockfiles (`requirements*.in/.lock`).
Künftig kommen dazu:

- vier Services,
- zwei geteilte Bibliotheken (Contracts, Plattform),
- ein Angular-Frontend.

Die Contracts zwischen den Teilen müssen synchron bleiben, und Änderungen über Grenzen hinweg
sollen in einem Commit möglich sein.

## Entscheidung

- **Ein Repository** für alle Services, Bibliotheken, das Frontend, Deployment und Doku.
- **uv-Workspace** für alle Python-Pakete (`packages/*`, `services/*`) mit einem gemeinsamen
  `uv.lock`. `uv sync --package <name>` installiert je Image nur, was der Service braucht.
- **Python 3.14** für alle Pakete.
- Das Frontend ist ein Angular-Workspace unter `frontend/` mit eigenem npm-Lockfile.
- import-linter erzwingt die Grenzen, die CI arbeitet mit Pfad-Filtern.
- Die Import-Namen tragen das Präfix `va_` (`va_scoring` statt `scoring`), damit es im
  gemeinsamen Environment keine Kollision mit Paketen von PyPI gibt.

Details: [code-struktur.md](../architecture/code-struktur.md).

## Konsequenzen

- ✅ Einheitliche Dependency-Versionen, Änderungen über Grenzen hinweg in einem Commit, schlanke
  Images.
- ✅ uv ersetzt pip-tools, pip und venv-Handling. Lokal und in der CI ist es deutlich schneller.
- ⚠️ Alle Workspace-Mitglieder teilen sich die Dependency-Versionen. Braucht ein Service einmal
  eine abweichende Version, wird er zur Pfad-Abhängigkeit statt Workspace-Mitglied.
- ⚠️ `make`-Targets, CI und README müssen auf uv umgestellt werden (Phase 0).

## Verworfene Alternativen

- **Ein Repository pro Service:** Contracts synchron zu halten wird aufwendig, und Änderungen über
  mehrere Teile brauchen mehrere PRs.
- **Nx oder Bazel:** mächtig, für diese Größe aber zu viel Werkzeug.
- **pip-tools beibehalten:** kein Workspace-Konzept, ein Lockfile pro Paket wäre nötig.
