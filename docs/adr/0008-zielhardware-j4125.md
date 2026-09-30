# ADR-0008: Zielhardware J4125: nur amd64, Build in CI, kein AVX2

- **Status:** akzeptiert
- **Datum:** 2026-09-30

## Kontext

Zielsystem ist eine Synology mit Intel Celeron J4125 und 18 GB RAM. Die Eckdaten (verifiziert am
30.09.2026):

- x86_64, 4 Kerne, 2,0–2,7 GHz,
- Befehlssatz bis SSE4.2, also x86-64-v2, **ohne AVX/AVX2**,
- DSM 7.x auf der Plattform geminilake mit **Kernel 4.4**,
- Container Manager mit Docker 24 und Compose.

Bekannte Fallen auf genau dieser Kombination:

- **Kernel 4.4:** Es fehlen neuere Systemaufrufe wie `statx` (erst ab 4.11). Moderne Build-Tools
  brechen daran ab. Für Bun ist das auf einer DS920+ dokumentiert.
- **Fehlendes AVX2:** Binaries, die x86-64-v3 voraussetzen, stürzen mit `Illegal instruction` ab.
- **NumPy:** setzt seit Version 2.4 x86-64-v2 voraus. Das schafft der J4125 gerade noch.

## Entscheidung

- **Images nur für `linux/amd64`**, gebaut **ausschließlich in GitHub Actions** und von dort nach
  GHCR geschoben. Die NAS baut nichts, sie lädt nur fertige Images.
- **Node, npm und Bun laufen nie auf der NAS.** Das Frontend kommt fertig gebaut im nginx-Image.
- **Keine Dependencies mit x86-64-v3-Pflicht.** Nach jedem Dependency-Upgrade läuft auf der NAS ein
  Import-Test (`python -c "import numpy, pandas"`), bevor die Container starten.
- **Keine Kernel-Features jenseits von 4.4:** kein `io_uring` für Postgres, keine
  cgroup-v2-Features.
- **RAM ist kein Engpass.** Speicherlimits in Compose dienen nur als Sicherheitsnetz.

Details: [betrieb-synology.md](../architecture/betrieb-synology.md).

## Konsequenzen

- ✅ Builds sind reproduzierbar, Deployments schnell (nur Pull), und der alte Kernel bringt keine
  Überraschungen.
- ✅ Multi-Arch-Builds sind unnötig.
- ⚠️ Das Deployment hängt an GitHub Actions und GHCR. Sind die Images privat, braucht die NAS ein
  Token mit `read:packages`.
- ⚠️ Neue Pakete mit C- oder Rust-Erweiterungen müssen auf der NAS getestet werden, bevor man sich
  auf sie verlässt.

## Verworfene Alternativen

- **Build auf der NAS (wie bisher):** langsam und anfällig für die Kernel-4.4-Probleme.
- **Multi-Arch-Images (amd64 + arm64):** ohne ARM-Zielsystem unnötiger Aufwand.
