"""Persistenz in PostgreSQL.

Grundregel: Daten werden niemals geloescht oder ueberschrieben. Die Datenbank
erzwingt das selbst (Trigger + Rollenrechte, siehe ``va_platform.db.ddl``); die
Repositories bieten deshalb nur ``get_*``- und ``write_*``-Zugriffe.

Schemas entsprechen den spaeteren Services: ``batch`` (Ablaufsteuerung),
``market_data``, ``scoring``, ``reporting``. Fremdschluessel gibt es nur
innerhalb eines Schemas; zwischen Schemas wird per ID verwiesen.

Modelle und Repositories liegen bei ihrem Modul (``adapters/postgres``, P1.7). Hier
bleiben ``batch``, der ``BatchRecorder`` und der Altdaten-Import.
"""
