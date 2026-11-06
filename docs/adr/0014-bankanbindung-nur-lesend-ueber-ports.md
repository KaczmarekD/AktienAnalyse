# ADR-0014: Bankanbindung nur lesend, über einen generischen Port im Dienst `depot-gateway`, DKB per FinTS

- **Status:** akzeptiert (06.11.2026)
- **Datum:** 2026-11-04
- **Ergänzt:** [ADR-0001](0001-microservices-ueber-modularen-monolithen.md) um einen Dienst für
  Depotbestände von außen

## Kontext

Depotbestände sollen später direkt von der Bank kommen. Der Zugang darf nur lesen. Er soll über
eine generische Schnittstelle laufen, an die sich beliebige Banken und Formate anschließen lassen.
Zuerst kommt die DKB ([Depot-Spezifikation](../architecture/depot/README.md)).

Die Recherche vom 04.11.2026
([DKB-Zugangswege](../research/2026-11-depot-datenquellen-und-bankzugang.md#dkb-zugangswege))
ergab:

- FinTS 3.0 liefert den Bestand (HKWPD). Die DKB verlangt aber bei jedem Abruf eine Freigabe in
  ihrer App.
- PSD2 deckt keine Depots ab. Die Banking-Seite ist seit 11/2025 durch Captcha geschützt.
  Aggregatoren kosten ab 60 EUR im Monat.
- Die DKB bietet keinen Export des Bestands als Datei und keinen lesenden Zugang. Die PIN erlaubt
  technisch auch Aufträge.
- FinTS verlangt eine registrierte Produktnummer (kostenlos, 10–15 Arbeitstage).
- Die DKB zieht ihre Wertpapierabwicklung 2026/27 zu Upvest um.

## Entscheidung

- **Port `DepotSource`** ohne schreibende Operationen. Jeder Adapter meldet Fähigkeiten und
  Anmeldeart und liefert das normierte `HoldingsStatementV1`. Der Ablauf ist eine
  Zustandsmaschine mit Freigabeschritten (App oder TAN).
- **Eigener Dienst `depot-gateway`** mit Schema `bank` und Rolle `va_bank`, in einem eigenen
  Container und in genau einer Instanz. Er läuft nicht im gemeinsamen Worker-Prozess. Er besitzt
  alle Adapter für fremde Formate und Banken, kennt keine anderen Schemas und meldet Bestände per
  Event an portfolio.
- **Adapter in dieser Reihenfolge:**
  1. Dateien ohne Anmeldung in fremden Formaten, zuerst der Export von Portfolio Performance. Das
     eigene CSV-Format gehört zu portfolio.
  2. DKB über FinTS mit python-fints 5.x, eigener Parser für MT535 (Einstand). Der Adapter ist
     generisch für FinTS-Banken, die DKB ist das erste Bankprofil.
- **Nur lesen in mehreren Schichten:** Port ohne Schreibmethoden, Erlaubnisliste der
  FinTS-Vorfälle vor dem Senden, nur ein Modul darf `fints` importieren, Tests für beides.
- **PIN und TAN werden nie gespeichert.** Die PIN geht je Abruf per Request/Reply an den Dienst und
  bleibt nur im Speicher. NATS bekommt Nutzer je Dienst: Nur das web-api darf `rpc.va.bank.>`
  senden, nur depot-gateway empfangen. Gespeichert wird der Zustand von python-fints ohne PIN,
  verschlüsselt.
- **Abruf nur durch den Nutzer**, nie im Zeitplan, ohne automatische Wiederholung bei der
  Anmeldung, höchstens einer je Verbindung. Das folgt aus der Freigabe bei jedem Abruf und der
  Sperre nach Fehlversuchen.
- **Bestände mit Beträgen** laufen über einen eigenen Stream `VA_PRIVATE` (nur im Speicher, 24 h)
  und ohne Outbox, damit sie nicht dauerhaft im Schema `bank` liegen.
- **Nicht gebaut:** Scraping der Banking-Seite, PSD2, Aggregatoren.

Details: [bankanbindung.md](../architecture/depot/bankanbindung.md).

## Konsequenzen

- ✅ Eine neue Bank oder ein neues Format ist ein neuer Adapter. portfolio, UI und Berichte bleiben
  gleich.
- ✅ Bankcode und Zugangsdaten sind vom Rest getrennt, auch auf Prozess- und NATS-Ebene.
- ✅ Der Datei-Adapter funktioniert ohne Bank und bleibt Rückfallweg, wenn sich bei der DKB etwas
  ändert.
- ⚠️ Der User muss die FinTS-Produktregistrierung selbst beantragen.
- ⚠️ Kein automatischer Abgleich mit der Bank. Berichte nutzen den letzten abgerufenen Stand mit
  aktuellen Kursen und nennen sein Datum.
- ⚠️ Bewusste Ausnahme von „Jeder externe Call hat Retry+Fallback“ (CLAUDE.md): Bei der
  Bank-Anmeldung wird nicht wiederholt.
- ⚠️ Ohne HTTPS ginge die PIN im Klartext durchs LAN, ohne NATS-Anmeldung durchs Docker-Netz. Die
  Stufe setzt beides aus ADR-0012 voraus.
- ⚠️ Geht depot-gateway oder NATS während eines Abrufs neu los, ist der Abruf verloren und wird
  neu gestartet.
- ⚠️ python-fints steht unter LGPL-3.0. Für die private Nutzung ist das unkritisch. Ein eigener
  Patch an der Bibliothek wäre bei Weitergabe offenzulegen.
- ⚠️ Der Umzug zu Upvest kann HKWPD ändern oder abschalten. Den Adapter dann erneut prüfen.
- ⚠️ Ein Dienst und ein Container mehr.

## Verworfene Alternativen

- **Adapter direkt in portfolio:** weniger Container, aber Bankbibliothek und PIN lägen im Dienst
  mit den Depots aller Nutzer.
- **PIN verschlüsselt speichern für automatische Abrufe:** bringt bei der DKB nichts, weil jede
  Sitzung ohnehin eine Freigabe braucht. Erhöht nur das Risiko.
- **dkb-robo (Banking-Seite):** umgeht Captcha und Bot-Schutz, dazu GPL-3.0 und ein Browser im
  Container.
- **finAPI oder andere Aggregatoren:** 720 bis 2.400 EUR im Jahr, Freigabe trotzdem bei jedem
  Abruf, Bestände bei einem Dritten.
- **PSD2/XS2A:** keine Depots, Erlaubnis der BaFin nötig.
