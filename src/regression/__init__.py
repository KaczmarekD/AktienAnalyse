"""Replay-Regression ueber gespeicherte Wochen (P2b.0, docs/architecture/regressionstest.md).

Bewertet gespeicherte Abrufe mit dem aktuellen Code neu und vergleicht mit dem Ergebnis
von damals: ``case`` laedt einen Bewertungslauf (Datenbank oder Fixture), ``replay`` schickt
ihn durch die Handler, ``compare`` vergleicht, ``cli`` ist die Kommandozeile.
"""
