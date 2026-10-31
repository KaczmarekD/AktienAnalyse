# Frontend (Angular)

Angular 22 mit Angular Material, zoneless, Tests mit Vitest
([docs/architecture/frontend.md](../docs/architecture/frontend.md)).

```bash
make ui-install   # Abhaengigkeiten exakt aus package-lock.json
make api          # web-api auf 127.0.0.1:8000 (oder make local-up)
make ui           # UI mit Reload unter http://localhost:4200
make ui-check     # Format, Lint, Tests und Build wie in der CI
```

- **API-Client** unter `src/app/api/`: von hey-api aus dem OpenAPI-Snapshot
  `tests/golden/openapi/v1.json` erzeugt (`make ui-api`). Nie von Hand ändern. Die CI prüft,
  dass er zum Snapshot passt.
- **Relative Pfade:** Das UI ruft `/api/v1/...` auf. Lokal leitet `ng serve` das an das web-api
  weiter (`proxy.conf.json`), auf der NAS nginx (P3.6). Es gibt keine API-URL im Build und
  kein CORS.
- **Nichts von außen:** keine Schriften oder Icons aus dem Internet, das UI läuft im LAN.
- Node läuft nur lokal und in der CI, nie auf der NAS.
