"""Gemeinsame Infrastruktur ohne Fachlogik.

- ``bus``: Event-Bus (``EventBus``, ``InProcessBus``), ab Phase 4 auch ueber NATS.
- ``db``: deklarative Basis, Engine/Session und DDL-Helfer fuer den Loeschschutz.
- ``serialization``: pandas-/numpy-Werte in DB- und JSON-taugliche Python-Werte.
"""
