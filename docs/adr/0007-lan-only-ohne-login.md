# ADR-0007: Nur im LAN erreichbar, zum Start ohne Login

- **Status:** akzeptiert
- **Datum:** 2026-09-30

## Kontext

Das System läuft auf einer Synology im Heimnetz und soll nur dort erreichbar sein. Die Daten
(Kennzahlen, Rankings) sind nicht sensibel. Folgende Aktionen sind im UI möglich:

- einen Run starten,
- Scoring-Profile ändern oder aktivieren (versioniert und damit umkehrbar),
- Mails und Runs ansehen.

Auch im LAN gibt es aber einen realen Angriffsweg: Eine fremde Webseite im Browser eines Nutzers
kann Anfragen an Adressen im Heimnetz schicken, per Formular, `fetch`, WebSocket oder
DNS-Rebinding.

## Entscheidung

- **Kein Login, kein OIDC, kein HTTPS-Zwang** zum Start. Zugriff über `http://<nas>:8080`.
- **Vier Schutzregeln** sind Pflicht:
  1. Schreibende Endpunkte nehmen nur JSON an, CORS bleibt aus. Der Preflight des Browsers blockt
     fremde Seiten.
  2. `Origin`-Prüfung beim WebSocket-Aufbau, denn für WebSockets gibt es keinen Preflight.
  3. nginx beantwortet nur bekannte Hostnamen (Default-Server mit `return 444`) gegen DNS-Rebinding.
  4. Die DSM-Firewall gibt Port 8080 nur für das eigene Subnetz frei.
- **Secrets sind nie über die API erreichbar.**
- HTTPS ist optional über den DSM-Reverse-Proxy möglich, dann mit WebSocket-Headern.

Details: [web-api-realtime.md](../architecture/web-api-realtime.md#sicherheitsregeln-lan-ohne-login).

## Konsequenzen

- ✅ Das UI ist schneller fertig. Es braucht keine Nutzerverwaltung, keine Sessions und kein
  Zertifikats-Handling.
- ⚠️ Jede Person im Heimnetz kann Runs starten und Profile ändern. Durch die Versionierung ist das
  umkehrbar.
- ⚠️ Ein einfacher Login (ein Nutzer, Session-Cookie) wird nachgezogen, sobald einer dieser Fälle
  eintritt:
  - Das UI darf heikle Einstellungen ändern, z. B. Mail-Empfänger.
  - Der Zugriff soll von außerhalb möglich sein. Dann bevorzugt per VPN (z. B. Tailscale) statt
    Portfreigabe.

## Verworfene Alternativen

- **Einfacher Login sofort:** sauber, aber im LAN mit nicht sensiblen Daten zunächst ohne Mehrwert.
- **OIDC (Authelia/Authentik):** für einen Nutzer im LAN überdimensioniert.
- **Gar keine Schutzregeln:** Wegen des Angriffswegs über den Browser nicht vertretbar, zumal die
  Regeln kaum Aufwand machen.
