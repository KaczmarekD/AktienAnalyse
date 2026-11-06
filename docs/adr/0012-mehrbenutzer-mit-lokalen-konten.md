# ADR-0012: Mehrere Nutzer mit lokalen Konten, Sitzungs-Cookie und HTTPS

- **Status:** akzeptiert (06.11.2026)
- **Datum:** 2026-11-04
- **Ersetzt:** [ADR-0007](0007-lan-only-ohne-login.md) („zum Start ohne Login“). Die
  Schutzregeln von ADR-0007 bleiben gültig.

## Kontext

Das UI soll mehrere Nutzer bedienen, jeder mit eigenen Depots, Berichten und Bankverbindungen
([Depot-Spezifikation](../architecture/depot/README.md)). Damit werden die Daten sensibel:
Bestände, Einstandswerte, Mail-Adressen, beim Bankabruf eine PIN. ADR-0007 hat für diesen Fall
einen Login vorgesehen.

Rahmen: wenige Nutzer (Familie), nur im LAN oder per VPN, Synology mit J4125, kein zusätzlicher
schwerer Dienst.

## Entscheidung

- **Lokale Konten im web-api.** Benutzername und Passwort, Hash mit argon2id (Ausweichlösung:
  `hashlib.scrypt`, falls argon2 die J4125-Prüfung nicht besteht).
- **Sitzungen auf dem Server**, im Cookie nur eine zufällige ID (`HttpOnly`, `Secure`,
  `SameSite=Strict`). Abmelden widerruft die Sitzung sofort.
- **Zwei Rollen:** Admin (System: Nutzer, Runs, Scoring-Profile) und Nutzer (eigene Inhalte). Der
  Admin sieht fremde Depots nicht.
- **HTTPS ist Pflicht**, sobald es Logins gibt, über den Reverse-Proxy von DSM (entschieden am
  06.11.2026). Port 8080 bindet dann nur an `127.0.0.1`. Ausnahme ist nur der lokale
  Entwicklungs-Stack.
- **Eigenes Schema `identity`** mit eigener Rolle `va_identity`. Persönliche Daten liegen nur in
  eigenen Schemas (`identity`, `portfolio`, `bank`, `digest`) außerhalb von `SCHEMAS`, ohne Rechte
  für `va_read` und `va_app`. NATS bekommt Nutzer je Dienst.
- **Zusätzliche Schutzregeln:** `Origin`-Prüfung bei jeder schreibenden Anfrage, Sperre nach
  Fehlversuchen, kein Passwort, keine PIN und keine Sitzungs-ID in Logs und Traces.
- **Die Anmeldung steht hinter einem Port** (`IdentityProvider`). OIDC, z. B. mit dem SSO Server
  von DSM, kann später als Adapter dazukommen.
- **Löschen personenbezogener Daten:** Standard ist Deaktivieren und Archivieren
  ([ADR-0003](0003-postgresql-schema-pro-service.md)). Auf ausdrücklichen Wunsch einer Person
  löscht ein Admin-Kommando mit `va_owner` alle ihre Daten. Das ist die einzige Ausnahme vom
  Löschverbot und wird protokolliert.

Details: [nutzer.md](../architecture/depot/nutzer.md).

## Konsequenzen

- ✅ Persönliche Daten sind in UI und API getrennt, auch vom Admin. Wer die NAS verwaltet
  (`va_owner`, `.env`, Backups), kann sie trotzdem lesen.
- ✅ Kein weiterer Container, keine externe Abhängigkeit.
- ⚠️ HTTPS braucht ein Zertifikat im LAN (Reverse-Proxy von DSM oder Zertifikat im
  `frontend`-Container). Das ist neuer Betriebsaufwand.
- ⚠️ Mit Cookies kehrt CSRF als Angriffsweg zurück. `SameSite=Strict`, JSON-only und die
  `Origin`-Prüfung decken das ab, Tests müssen es belegen.
- ⚠️ Jeder bestehende Endpunkt verlangt danach eine Sitzung. Die Tests von API und E2E brauchen
  einen Testnutzer, und `oasdiff breaking` meldet die neuen Sicherheitsangaben womöglich als
  Bruch.
- ⚠️ Das Löschkommando weicht vom Grundsatz aus ADR-0003 ab. Ohne es lassen sich Daten einer
  Person aber nicht auf Wunsch entfernen.

## Verworfene Alternativen

- **Weiter ohne Login:** Jeder im Heimnetz sähe alle Depots. Nicht vertretbar.
- **OIDC mit Authelia oder Authentik:** zusätzlicher Container und Konfiguration für eine Handvoll
  Nutzer. Bleibt als Adapter möglich.
- **SSO Server von DSM von Anfang an:** keine eigenen Passwörter, aber Abhängigkeit von der
  DSM-Konfiguration, und der lokale Stack und die CI bräuchten einen Ersatz-Identitätsdienst.
- **JWT ohne Sitzung auf dem Server:** Abmelden und Sperren wirken erst mit Ablauf des Tokens.
- **HTTP Basic Auth in nginx:** keine Rollen, kein Abmelden, Passwort bei jeder Anfrage.
