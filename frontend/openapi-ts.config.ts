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
    { name: 'zod', compatibilityVersion: 4 },
    { name: '@hey-api/sdk', validator: 'zod' },
    // httpResource: Signals statt Observables, laedt neu, wenn sich Parameter aendern
    { name: '@angular/common', httpRequests: true, httpResources: true },
  ],
});
