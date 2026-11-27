// API-Client aus dem OpenAPI-Snapshot des web-api (P3.5, frontend.md).
// Quelle ist das Golden-File tests/golden/openapi/v1.json, nicht ein laufender Server:
// Der Build braucht so kein Backend, und jede API-Aenderung zeigt sich als Diff im Review.
// Neu erzeugen: npm run generate:api (die CI prueft, dass der Client zum Snapshot passt).
import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../tests/golden/openapi/v1.json',
  output: { path: 'src/app/api', postProcess: ['prettier'] },
  plugins: [
    '@hey-api/client-angular',
    '@hey-api/typescript',
    // Zeitpunkte nach RFC 3339 mit Offset: Postgres liefert sie in der Zeitzone der Sitzung
    // (Europe/Berlin, +01:00), nicht nur mit Z
    { name: 'zod', compatibilityVersion: 4, dates: { offset: true } },
    { name: '@hey-api/sdk', validator: 'zod' },
    // httpResource: Signals statt Observables, laedt neu, wenn sich Parameter aendern
    { name: '@angular/common', httpRequests: true, httpResources: true },
  ],
});
