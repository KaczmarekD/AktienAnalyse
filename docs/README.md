# Dokumentation

| Ordner | Inhalt |
|---|---|
| [architecture/](architecture/README.md) | Zielarchitektur und Roadmap für den Umbau zu Microservices mit Angular-Frontend |
| [adr/](adr/README.md) | Architecture Decision Records: jede Grundsatzentscheidung mit Kontext, Begründung und verworfenen Alternativen |
| [research/](research/) | Recherche-Notizen mit Quellen, Messwerten und Live-Tests: [Zielarchitektur (09/2026)](research/2026-09-zielarchitektur.md), [DAX/MDAX-Datenquellen (09/2026)](research/dax-mdax-datenquellen/bericht.md), [Langfristige Fundamentalanalyse – SOTA und fundamentale Anker (09/2026)](research/fundamentalanalyse-sota/bericht.md) |

Der Betrieb des heutigen Wochen-Batches steht im [README](../README.md), die Methodik und die Konventionen des Ist-Stands stehen in [CLAUDE.md](../CLAUDE.md).

## Pflegeregeln

- Neue Grundsatzentscheidungen bekommen ein eigenes ADR. Bestehende ADRs werden nicht umgeschrieben, sondern durch ein neues ADR ersetzt (Status „ersetzt durch …“).
- Die Plan-Dokumente unter `architecture/` werden fortgeschrieben, statt parallele Versionen anzulegen.
- Erledigte Aufgaben in der [Roadmap](architecture/roadmap.md) abhaken.
- Recherchen landen datiert unter `research/`, zusammen mit ihren Quellen.
