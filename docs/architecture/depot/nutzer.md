# Nutzer, Anmeldung und Rechte

> **Status:** Spezifikation, Entwurf vom 04.11.2026. Teil der
> [Depot-Spezifikation](README.md), Stufe D1. Grundsatzentscheidung:
> [ADR-0012](../../adr/0012-mehrbenutzer-mit-lokalen-konten.md) (vorgeschlagen).

## Ausgangslage

Heute gibt es keinen Login ([ADR-0007](../../adr/0007-lan-only-ohne-login.md)). Jede Person im
Heimnetz kann Runs starten und Profile ändern. Das war vertretbar, weil die Daten nicht sensibel
sind. Mit Depots ändert sich das:

- Bestände, Einstandswerte und Bankverbindungen sind persönliche Finanzdaten.
- Berichte gehen an persönliche Mail-Adressen.
- Für die Bankanbindung wird eine PIN eingegeben.

ADR-0007 nennt diesen Fall selbst als Auslöser für einen Login.

## Anforderungen

| ID | Prio | Anforderung |
|---|---|---|
| NUT-01 | Muss | Anmeldung mit Benutzername und Passwort. Die Sitzung hält ein Cookie (`HttpOnly`, `Secure`, `SameSite=Strict`). Ablauf nach 12 h ohne Aktivität, spätestens nach 30 Tagen (einstellbar). Abmelden beendet die Sitzung auf dem Server. |
| NUT-02 | Muss | Zwei Rollen: **Admin** und **Nutzer** (Rechte siehe unten). |
| NUT-03 | Muss | Datentrennung in UI und API: Ein Nutzer sieht nur eigene Depots, Hinweise, Berichte und Bankverbindungen. Auch der Admin sieht fremde Depots dort nicht. Er verwaltet das System, nicht die Inhalte. Wer Zugriff auf die NAS hat (`va_owner`, `.env`, Backups), kann trotzdem alles lesen. |
| NUT-04 | Muss | Den ersten Admin legt ein Kommando im Container an (`python -m va_web_api.admin create-user --admin`). Es gibt kein Standardpasswort und keinen Admin aus einer ENV-Variable. |
| NUT-05 | Muss | Passwörter: mindestens 12 Zeichen, Abgleich mit einer mitgelieferten Liste häufiger Passwörter. Gespeichert wird nur ein Hash mit argon2id. Besteht `argon2-cffi` die J4125-Prüfung nicht, dann `hashlib.scrypt` aus der Standardbibliothek. |
| NUT-06 | Muss | Schutz gegen Durchprobieren: Nach 5 Fehlversuchen je Konto oder je IP-Adresse 15 Minuten Sperre. Die IP-Adresse kommt über eine Vertrauenskette der Proxys (Regel 10), sonst sperrt die Regel alle. Jeder Anmeldeversuch wird protokolliert. |
| NUT-07 | Muss | HTTPS für jeden Zugriff mit Login. Ohne HTTPS setzt der Browser kein `Secure`-Cookie. Nur der lokale Stack (`make local-*`) darf ohne HTTPS laufen, per Setting. |
| NUT-08 | Muss | WebSocket: Der Handshake prüft Sitzung und `Origin`. Topics mit Nutzerbezug (`depot:<id>`, `bank-sync:<id>`, `user:<id>`) bekommt nur, wer berechtigt ist. Endet die Sitzung, trennt der Hub die Verbindung. |
| NUT-09 | Muss | Jeder Endpunkt verlangt eine Sitzung, außer `GET /api/v1/health`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout` (löscht nur das Cookie), `GET /api/v1/auth/session` (sagt ohne 401, wer angemeldet ist, D1.4), `POST /api/v1/auth/confirm-email` (dort ist das Token der Nachweis) und der API-Beschreibung (OpenAPI, keine Daten). Ein fremdes Depot ergibt 404, nicht 403. So lässt sich nicht ausprobieren, welche IDs es gibt. Übergang auf der NAS bis D1.5: `WEB_API_AUTH_REQUIRED=false` schaltet die Sitzungspflicht ab (Verhalten wie unter ADR-0007); das eigene Konto und die Nutzerverwaltung brauchen trotzdem eine echte Sitzung. |
| NUT-10 | Soll | Der Admin hinterlegt die Mail-Adresse beim Anlegen, sie gilt als bestätigt. Ändert ein Nutzer sie selbst, gilt die neue erst nach Bestätigung: Mail mit Link auf eine Seite des UI, die das Token per `POST /api/v1/auth/confirm-email` schickt. |
| NUT-11 | Soll | Ein Nutzer ändert selbst Passwort und Anzeigename, sieht seine Sitzungen und beendet sie („überall abmelden“). |
| NUT-12 | Soll | Ein Nutzer exportiert alle seine Daten als JSON (Depots, Verlauf, Abos, Hinweise). |
| NUT-13 | Kann | Depot mit einem anderen Nutzer teilen, nur lesend. |
| NUT-14 | Kann | Zweiter Faktor (TOTP) oder Passkeys. |
| NUT-15 | Kann | Anmeldung über OIDC, z. B. den SSO Server von DSM. Dafür steht die Anmeldung hinter dem Port `IdentityProvider`. |

## Rollen

| Aktion | Admin | Nutzer |
|---|---|---|
| Ranking, Runs, Titel-Detail, Scoring-Profile ansehen | ✅ | ✅ |
| Run starten, Scoring-Profil speichern oder aktivieren | ✅ | – |
| Nutzer anlegen, deaktivieren, Einmal-Passwort setzen | ✅ | – |
| Eigene Depots, Hinweise, News, Berichte, Bankverbindungen | ✅ | ✅ |
| Fremde Depots | – | – (nur geteilt, NUT-13) |

Scoring-Profile bleiben zunächst global. Ob jeder Nutzer eigene Profile bekommt, ist eine offene
Frage ([README](README.md#offene-fragen)).

## Abläufe

**Anmelden:**

1. `POST /api/v1/auth/login` mit `{"username", "password"}` (JSON wie jeder schreibende
   Endpunkt).
2. Das web-api prüft Sperre, Konto-Status und Hash.
3. Es legt eine Sitzung an. Das Cookie enthält nur eine zufällige ID mit 256 Bit, in der
   Datenbank steht ihr SHA-256.
4. Antwort: 204 mit `Set-Cookie`. Das UI lädt danach `GET /api/v1/me`.

**Jede Anfrage:** Middleware im web-api liest das Cookie und sucht die Sitzung. Die
Inaktivitätsfrist zählt ab der jüngsten Zeile in `session_seen`. Eine neue Zeile schreibt das
web-api höchstens alle 10 Minuten je Sitzung. Der Nutzer steht dann als `CurrentUser` über
`Depends` bereit.

**Abmelden:** `POST /api/v1/auth/logout` schreibt einen Widerruf. Das Cookie wird gelöscht, der
Hub trennt die WebSocket-Verbindungen dieser Sitzung.

**Mail-Adresse bestätigen (NUT-10):** Das web-api legt ein Token an (24 h gültig, nur der Hash
wird gespeichert) und meldet `priv.va.identity.email_confirmation.requested`. notification
verschickt die Mail an die neue Adresse.

## Sicherheitsregeln

Die vier Regeln aus [ADR-0007](../../adr/0007-lan-only-ohne-login.md) bleiben: nur JSON bei
schreibenden Endpunkten, `Origin`-Prüfung am WebSocket, nur bekannte Hostnamen in nginx,
Firewall auf das eigene Subnetz. Dazu kommen:

5. **Cookie:** `HttpOnly`, `Secure`, `SameSite=Strict`, Pfad `/`. Mit HTTPS heißt es
   `__Host-va_session`.
6. **`Origin`-Prüfung bei jeder schreibenden Anfrage**, nicht nur am WebSocket. Mit Cookies
   reicht der Preflight allein nicht mehr als Schutz gegen CSRF.
7. **Keine Geheimnisse und Adressen in Logs und Traces:** Passwort, PIN, TAN, Tokens,
   Sitzungs-ID und Mail-Adressen nie loggen. Das Logging (heute stdlib `logging`,
   `src/logging_setup.py`) bekommt einen Filter, der diese Felder schwärzt. Ein Test prüft ihn.
   Betroffen ist auch eine bestehende Stelle: `va_notification.adapters.smtp` loggt heute den
   Empfänger.
8. **Rate-Limit** für Login und Bank-Sync, im Speicher des web-api. Es gibt nur eine Instanz.
9. **HTTPS über den Reverse-Proxy von DSM** (entschieden am 06.11.2026). DSM terminiert TLS und
   leitet an den `frontend`-Container weiter. Port 8080 ist danach nicht mehr per HTTP im LAN
   erreichbar: `UI_LAN_BIND=127.0.0.1`. Der Proxy setzt HSTS. Offen ist nur das Zertifikat
   (eigene Domain oder eigene CA, [README](README.md#offene-fragen)); das Runbook beschreibt beide
   Wege ([betrieb-synology.md](../betrieb-synology.md#https-über-den-reverse-proxy-von-dsm)).
   Umgesetzt mit D1.5.
10. **Vertrauenskette der Proxys:** nginx übernimmt die Client-Adresse nur vom DSM-Proxy
    (`set_real_ip_from`), uvicorn nur von nginx (`forwarded_allow_ips`). Sonst sieht das web-api
    für alle Anfragen dieselbe Adresse, und ein Angreifer könnte `X-Forwarded-For` fälschen.
    Umgesetzt mit D1.5 (`VA_TRUSTED_PROXY`, `FORWARDED_ALLOW_IPS`; nginx reicht genau die erkannte
    Adresse weiter, nicht die Kette).
11. **NATS mit Anmeldung:** Jeder Dienst hat einen eigenen NATS-Nutzer mit Rechten nur auf seine
    Subjects und seine Inbox (seit D1.5, [events.md](../events.md#nats-nutzer-und-rechte-seit-d15)).
    Ab D8 sind die Bank-Subjects (`rpc.va.bank.>`) nur für web-api und depot-gateway
    erlaubt, `VA_PRIVATE` nur für die Dienste, die ihn brauchen
    ([README](README.md#events-im-überblick)).

## Datenmodell

Neues Schema `identity`, Besitzer ist das web-api. Es bekommt eine eigene Rolle `va_identity`.
Die Projektionen des web-api (Rolle `va_web`) sehen die Hashes damit nie. In `identity` liegen
auch die Berichts-Abos ([berichte.md](berichte.md#datenmodell)), weil sie persönlich sind.

| Tabelle | Inhalt | Schreibweise |
|---|---|---|
| `user_account` | id, username (eindeutig), role (`admin`/`user`), created_at | anfügen |
| `user_profile_version` | user_id, display_name, email, email_confirmed_at, created_at | anfügen, gültig ist die jüngste Zeile |
| `user_status` | user_id, status (`active`/`disabled`), reason, at | anfügen, gültig ist die jüngste Zeile |
| `password_credential` | user_id, hash, algorithm, must_change, created_at | anfügen, gültig ist die jüngste Zeile |
| `email_confirmation` | user_id, email, token_hash, expires_at, created_at | anfügen |
| `email_confirmation_used` | token_hash, at: die Bestätigung, einmalig (D1.6) | anfügen |
| `session` | id_hash, user_id, created_at, expires_at, user_agent | anfügen |
| `session_seen` | id_hash, seen_at | anfügen, höchstens alle 10 Minuten je Sitzung |
| `session_revocation` | id_hash, at, reason (`logout`, `admin`, `password_changed`) | anfügen |
| `login_event` | username, user_id, ip, ok, reason, at | anfügen |
| `erasure_log` | user_key (SHA-256 der user_id), at, by_admin, Zeilenzahlen je Tabelle, keine Inhalte | anfügen |
| `outbox`, `inbox` | wie in den anderen Schemas | wie dort |

Rechte: `va_identity` darf in `identity` lesen und anfügen, sonst nichts. Alles bleibt eine
Anfüge-Tabelle, es gibt keine neue Ausnahme für `UPDATE`.

## Persönliche Schemas und `va_read`

Persönliche Daten liegen nur in eigenen Schemas: `identity` (web-api), `portfolio`, `bank`
(depot-gateway) und `digest` (notification). Keines davon steht in `SCHEMAS` von
`va_platform.db.ddl`. Dort vergibt `ALTER DEFAULT PRIVILEGES` heute jede neue Tabelle automatisch an
`va_read` und `va_app`. Ein späteres `REVOKE` würde beim nächsten Lauf der Grants wieder
zurückgedreht. Die persönlichen Schemas bekommen deshalb eine eigene Grant-Funktion nur für ihre
Besitzer-Rolle.

Ein DB-Test prüft, dass `va_read` und `va_app` keine Tabelle eines persönlichen Schemas lesen
können, die Outboxen eingeschlossen.

## Personenbezogene Daten und das Löschverbot

[ADR-0003](../../adr/0003-postgresql-schema-pro-service.md) verbietet Löschen. Für Marktdaten ist
das richtig. Für die persönlichen Schemas gilt:

- **Standard:** Konten werden deaktiviert, Depots archiviert. Nichts verschwindet.
- **Auf ausdrücklichen Wunsch einer Person** löscht ein Admin-Kommando alle ihre Daten. Jeder
  Besitzer-Dienst bietet dafür `erase_user(user_id)` für alle seine Tabellen an, Outbox und Inbox
  eingeschlossen. Das Kommando läuft mit der Rolle `va_owner` und schaltet den Schutz nur für diese
  Transaktion ab. Protokolliert wird in `identity.erasure_log`, ohne Inhalte.
- **NATS:** `VA_PRIVATE` liegt nur im Speicher und nicht im Backup-Ordner `natsdata`
  ([README](README.md#events-im-überblick)).
- **Backups** enthalten die Daten weiter, bis sie nach der Aufbewahrungsfrist von Hyper Backup
  herausfallen. Hyper Backup bekommt clientseitige Verschlüsselung.

Das Löschkommando hat der User mit ADR-0012 am 06.11.2026 angenommen.

## API

| Methode und Pfad | Zweck | Rolle |
|---|---|---|
| `POST /api/v1/auth/login` | anmelden | – |
| `POST /api/v1/auth/logout` | abmelden | angemeldet |
| `GET /api/v1/auth/session` | wer angemeldet ist (`{"user": …}` oder `null`), ohne 401 (D1.4) | – |
| `POST /api/v1/auth/confirm-email` | Mail-Adresse mit Token bestätigen | – (Token) |
| `GET /api/v1/me` | eigenes Konto, Rolle, `must_change_password` | angemeldet |
| `PUT /api/v1/me/password` | Passwort ändern (altes Passwort nötig, Fehlversuche zählen wie beim Anmelden) | angemeldet |
| `PUT /api/v1/me/profile` | Anzeigename (D1.4), Mail mit Bestätigung (D1.6) | angemeldet |
| `GET /api/v1/me/sessions`, `POST /api/v1/me/sessions/revoke-all` | Sitzungen, überall abmelden (auch diese) | angemeldet |
| `GET /api/v1/me/export` | alle eigenen Daten als JSON (NUT-12) | angemeldet |
| `GET /api/v1/admin/users`, `POST /api/v1/admin/users` | Nutzer auflisten, mit Einmal-Passwort anlegen | Admin |
| `POST /api/v1/admin/users/{id}/disable`, `…/enable`, `…/reset-password` | verwalten (nicht am eigenen Konto) | Admin |

Alles umgesetzt (D1.4, `confirm-email`, Mail-Adresse und Export seit D1.6). `/me` und `/admin`
brauchen auch im Übergang eine echte Sitzung. Das Einmal-Passwort
vergibt der Admin, das UI schlägt ein zufälliges vor; der Server schickt nie ein Passwort zurück.
Mit Einmal-Passwort antworten alle anderen Endpunkte mit 403, bis es ersetzt ist.

Schützt das web-api bestehende Endpunkte neu, meldet `oasdiff breaking` das womöglich als Bruch,
weil sich die Sicherheitsangaben ändern. Das Paket D1 klärt, ob das als gewollter Bruch
durchgeht oder ob der Login als `/api/v2` kommt.

## Tests und Abnahme

- Für jeden Endpunkt mit Nutzerbezug ein Test „anderer Nutzer bekommt 404“. Eine Tabelle aller
  Routen stellt sicher, dass kein neuer Endpunkt ohne diesen Test entsteht.
- Ohne Sitzung: 401 auf jedem Endpunkt außer den drei Ausnahmen aus NUT-09 (ein Test geht alle
  Routen durch).
- Sperre nach Fehlversuchen, auch hinter zwei Proxys; gefälschtes `X-Forwarded-For` von außen
  wirkt nicht.
- Ablauf und Widerruf einer Sitzung.
- WebSocket: ohne Sitzung kein Handshake, fremdes Topic ergibt `error`.
- Log-Filter: Ein Login mit Passwort und ein Bericht an eine Mail-Adresse tauchen in keinem Log
  auf.
- DB: `va_read` und `va_app` lesen keine persönliche Tabelle (siehe oben).
- NATS: Ein Dienst ohne Recht kann `rpc.va.bank.>` und `priv.va.>` weder senden noch lesen
  (Integrationstest mit `TEST_NATS_URL`).
- E2E (Playwright): anmelden, Ranking sehen, abmelden. Der E2E-Stack legt dafür einen Testnutzer
  an.
- `/security-review` ist Pflicht (Paket mit 🔒).
