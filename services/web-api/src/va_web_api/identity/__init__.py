"""Konten, Anmeldung und Sitzungen des web-api (D1.1, ADR-0012).

``domain``: reine Regeln. ``ports``: was der Dienst vom Speicher braucht. ``service``: Anmelden,
Sitzung pruefen, Abmelden, Konto anlegen. ``memory``: Speicher im Prozess fuer Tests. Der
Postgres-Speicher liegt unter ``va_web_api.adapters.postgres.identity_store``.
"""
