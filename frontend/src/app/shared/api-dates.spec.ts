// Zeitpunkte aus der API (D5.4): Postgres liefert sie in der Zeitzone der Sitzung, auf der NAS
// und im E2E-Stack Europe/Berlin (+01:00). Die Prüfung des Clients (zod, aus dem OpenAPI-Snapshot)
// muss sie annehmen, sonst gilt eine erfolgreiche Antwort als Fehler: „Der Depotstand ließ sich
// nicht laden.“ Das stellt openapi-ts.config.ts sicher (zod, dates.offset).
import { zDepotHints, zHoldings } from '../api/zod.gen';

const BERLIN = '2026-11-27T22:13:11.521332+01:00';
const UTC = '2026-11-27T21:13:11Z';

describe('Zeitpunkte der API', () => {
  it('nimmt Zeitpunkte mit Offset und mit Z an', () => {
    for (const at of [BERLIN, UTC]) {
      const holdings = {
        depot_id: 3,
        version: 1,
        source: 'manual',
        created_at: at,
        created_by: 1,
        lines: [],
        cash: [],
      };
      expect(zHoldings.safeParse(holdings).success, at).toBe(true);
      const hints = { analysis_run_id: 7, computed_at: at, version: 1, hints: [] };
      expect(zDepotHints.safeParse(hints).success, at).toBe(true);
    }
  });

  it('lehnt weiter ab, was kein Zeitpunkt ist', () => {
    const hints = { analysis_run_id: 7, computed_at: 'gestern', version: 1, hints: [] };
    expect(zDepotHints.safeParse(hints).success).toBe(false);
  });
});
