"""Persistenz in PostgreSQL.

Grundregel: Daten werden niemals geloescht oder ueberschrieben. Die Datenbank
erzwingt das selbst (Trigger + Rollenrechte, siehe ``ddl.py``); dieses Paket
bietet deshalb nur ``get_*``- und ``write_*``-Zugriffe.

Schemas entsprechen den spaeteren Services: ``batch`` (Ablaufsteuerung),
``market_data``, ``scoring``, ``reporting``. Fremdschluessel gibt es nur
innerhalb eines Schemas; zwischen Schemas wird per ID verwiesen.
"""
