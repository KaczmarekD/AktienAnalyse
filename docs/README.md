# Dokumentation

| Ordner | Inhalt |
|---|---|
| [architecture/](architecture/README.md) | Architektur, Roadmap und Betrieb: Services an NATS, PostgreSQL, Angular-Frontend; [Runbook der NAS](architecture/betrieb-synology.md) |
| [architecture/depot/](architecture/depot/README.md) | Spezifikation (ADRs angenommen, Umsetzung offen): mehrere Nutzer, Depots, Analyse, Hinweise, News, Berichte, nur lesende Bankanbindung |
| [adr/](adr/README.md) | Architecture Decision Records: jede Grundsatzentscheidung mit Kontext, Begründung und verworfenen Alternativen |
| [research/](research/) | Recherche-Notizen mit Quellen, Messwerten und Live-Tests: [Zielarchitektur (09/2026)](research/2026-09-zielarchitektur.md), [DAX/MDAX-Datenquellen (09/2026)](research/dax-mdax-datenquellen/bericht.md), [Langfristige Fundamentalanalyse – SOTA und fundamentale Anker (09/2026)](research/fundamentalanalyse-sota/bericht.md), [Depot-Daten und Bankzugang (11/2026)](research/2026-11-depot-datenquellen-und-bankzugang.md) |

Den Einstieg gibt das [README](../README.md), den Betrieb auf der NAS das [Runbook](architecture/betrieb-synology.md). Methodik und Konventionen des Ist-Stands stehen in [CLAUDE.md](../CLAUDE.md).

## Pflegeregeln

- Neue Grundsatzentscheidungen bekommen ein eigenes ADR. Bestehende ADRs werden nicht umgeschrieben, sondern durch ein neues ADR ersetzt (Status „ersetzt durch …“).
- Die Plan-Dokumente unter `architecture/` werden fortgeschrieben, statt parallele Versionen anzulegen.
- Erledigte Aufgaben in der [Roadmap](architecture/roadmap.md) abhaken.
- Recherchen landen datiert unter `research/`, zusammen mit ihren Quellen.
- Relative Links und Anker prüft `tests/test_doc_links.py` (Teil von `make check`).
