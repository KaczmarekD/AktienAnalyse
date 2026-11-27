// Ein Depot (D3.6, DEP-02 bis 07, 09, 13): Kennzahlen, Positionen mit Kurs, Datum und Quelle,
// fehlender Wert mit Grund, Bearbeiten mit If-Match und Konflikt, Suche, Datei mit Abgleich,
// Verlauf, Archivieren mit Rückfrage.
import { HttpTestingController, TestRequest } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MATERIAL_ANIMATIONS } from '@angular/material/core';
import { MatDialog } from '@angular/material/dialog';

import type { HistoryEntry, ImportPreview } from '../api/types.gen';
import { apiTestingProviders, query, respond, text } from '../testing/api';
import { me, provideAuthTesting } from '../testing/auth';
import {
  APPLE,
  BUND,
  depot,
  DETAIL,
  HOLDINGS,
  position,
  SAP,
  score,
  valuation,
} from '../testing/depots';
import {
  abbreviationsWithoutExplanation,
  controlsWithoutTooltip,
  headersWithoutScope,
} from '../testing/tooltips';
import { DepotPage } from './depot-page';
import { SEARCH_DEBOUNCE_MS } from './holdings-editor';
import { fileBase64 } from './import-panel';

const DEPOT = '/api/v1/depots/3';
const HISTORY = '/api/v1/depots/3/history';
const HOLDINGS_URL = '/api/v1/depots/3/holdings';

const ENTRIES: HistoryEntry[] = [
  {
    version: 2,
    source: 'import',
    created_at: '2026-11-22T11:00:00Z',
    created_by: 1,
    positions: 2,
    added: 1,
    changed: 1,
    removed: 0,
  },
  {
    version: 1,
    source: 'manual',
    created_at: '2026-11-22T10:00:00Z',
    created_by: 1,
    positions: 1,
    added: 1,
    changed: 0,
    removed: 0,
  },
];

type Fixture = ComponentFixture<DepotPage>;

function http(): HttpTestingController {
  return TestBed.inject(HttpTestingController);
}

async function settle(fixture: Fixture): Promise<void> {
  for (let i = 0; i < 4; i++) {
    await new Promise((resolve) => setTimeout(resolve));
    TestBed.tick();
    fixture.detectChanges();
  }
}

async function render(body = DETAIL): Promise<Fixture> {
  TestBed.configureTestingModule({
    providers: [
      ...apiTestingProviders(),
      provideAuthTesting({ user: me() }),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      { provide: SEARCH_DEBOUNCE_MS, useValue: 0 },
    ],
  });
  const fixture = TestBed.createComponent(DepotPage);
  fixture.componentRef.setInput('depotId', '3');
  await respond(fixture, DEPOT, body);
  await respond(fixture, HISTORY, ENTRIES);
  fixture.detectChanges();
  return fixture;
}

function click(fixture: Fixture, selector: string): void {
  const element = query(fixture, selector)[0];
  expect(element, selector).toBeDefined();
  element.click();
  fixture.detectChanges();
}

function type(fixture: Fixture, selector: string, value: string): void {
  const input = query<HTMLInputElement>(fixture, selector)[0];
  input.value = value;
  input.dispatchEvent(new Event('input'));
  fixture.detectChanges();
}

function expectRequest(url: string, method: string): TestRequest {
  return http().expectOne((r) => r.url === url && r.method === method);
}

async function edit(fixture: Fixture): Promise<void> {
  click(fixture, 'button[data-action="edit"]');
  await settle(fixture);
  expectRequest(HOLDINGS_URL, 'GET').flush(HOLDINGS);
  await settle(fixture);
}

describe('DepotPage', () => {
  afterEach(() => TestBed.inject(MatDialog).closeAll());

  it('shows value, cash, cost basis and difference', async () => {
    const fixture = await render();
    const stat = (name: string) =>
      (query(fixture, `[data-stat-${name}]`)[0].textContent ?? '').replace(/\s+/g, ' ');
    expect(stat('value')).toContain('2.565,10 €');
    expect(stat('value')).toContain('unvollständig: 1 Position ohne Wert');
    expect(stat('cash')).toContain('250,10 €');
    expect(stat('cost')).toContain('2.000,00 €');
    expect(stat('difference')).toContain('315,00 €');
    expect(stat('difference')).toContain('Stand 20.11.2026');
  });

  it('shows each position with price, date and value', async () => {
    const fixture = await render();
    const sap = query(fixture, `tr[data-position="${SAP}"]`)[0].textContent?.replace(/\s+/g, ' ');
    expect(sap).toContain('SAP SE');
    expect(sap).toContain(SAP);
    expect(sap).toContain('231,50 EUR');
    expect(sap).toContain('20.11.2026');
    expect(sap).toContain('2.315,00 €');
  });

  it('names why a position has no value and that it waits for master data', async () => {
    const fixture = await render();
    const row = query(fixture, `tr[data-position="${APPLE}"]`)[0];
    expect(row.querySelector('[data-missing]')?.textContent).toContain('Kurs fehlt');
    expect(row.querySelector('[data-pending]')?.textContent).toContain('wird geprüft');
  });

  describe('scores (D4.2)', () => {
    it('shows composite, percentile, value and quality like the ranking', async () => {
      const fixture = await render();
      const row = query(fixture, `tr[data-position="${SAP}"]`)[0];
      const cell = (name: string) => (row.querySelector(name)?.textContent ?? '').trim();
      expect(cell('[data-composite]')).toContain('0,58');
      expect(cell('[data-composite]')).toContain('Perzentil 71');
      expect(cell('[data-value-score]')).toContain('0,41');
      expect(cell('[data-quality-score]')).toContain('0,83');
    });

    it('links a DAX/MDAX stock to its detail page', async () => {
      const fixture = await render();
      const link = query(fixture, `tr[data-position="${SAP}"] a[data-instrument]`)[0];
      expect(link.getAttribute('href')).toBe('/instruments/SAP.DE');
    });

    it('names a stock placed from outside and its value trap', async () => {
      const fixture = await render();
      const row = query(fixture, `tr[data-position="${APPLE}"]`)[0];
      expect(row.querySelector('[data-reference]')?.textContent).toContain('außerhalb DAX/MDAX');
      expect(row.querySelector('a[data-instrument]')).toBeNull();
      expect(row.querySelector('[data-composite]')?.textContent).toContain('Value-Trap?');
    });

    it('says why there is no composite, and that a bond has no scores', async () => {
      const bank = position({
        isin: 'DE000CBK1001',
        name: 'Commerzbank',
        score: score({
          symbol: 'CBK.DE',
          value_score: 0.9,
          quality_score: null,
          composite_score: null,
          composite_percentile: null,
          reason: 'no_quality',
        }),
      });
      const bond = position({ isin: BUND, name: 'Bund 2033', unit: 'nominal' });
      const fixture = await render(
        depot({ id: 3, name: 'DKB', valuation: valuation({ positions: [bank, bond] }) }),
      );
      const reason = query(fixture, 'tr[data-position="DE000CBK1001"] [data-reason]')[0];
      expect(reason.textContent).toContain('ohne Quality');
      expect(query(fixture, `tr[data-position="${BUND}"] [data-no-score]`)).toHaveLength(1);
    });
  });

  it('shows a watchlist with prices only', async () => {
    const fixture = await render(
      depot({ id: 3, name: 'Ideen', kind: 'watchlist', valuation: valuation({ positions: [] }) }),
    );
    expect(query(fixture, '[data-stat-value]')).toHaveLength(0);
    expect(text(fixture)).toContain('Beobachtungsliste');
  });

  it('lists the history with source and changes', async () => {
    const fixture = await render();
    const entry = query(fixture, '[data-version="2"]')[0].textContent?.replace(/\s+/g, ' ');
    expect(entry).toContain('Depotstand 2');
    expect(entry).toContain('aus einer Datei');
    expect(entry).toContain('1 neu, 1 geändert, 0 entfallen');
  });

  it('says when the depot does not exist', async () => {
    TestBed.configureTestingModule({
      providers: [...apiTestingProviders(), provideAuthTesting({ user: me() })],
    });
    const fixture = TestBed.createComponent(DepotPage);
    fixture.componentRef.setInput('depotId', '9');
    await respond(fixture, '/api/v1/depots/9', { detail: 'Depot nicht gefunden' }, 404);
    expect(text(fixture)).toContain('Depot nicht gefunden.');
  });

  describe('editing', () => {
    it('starts from the saved holdings and saves with If-Match', async () => {
      const fixture = await render();
      await edit(fixture);
      const quantity = query<HTMLInputElement>(
        fixture,
        `tr[data-row="${SAP}"] [data-field="quantity"]`,
      )[0];
      expect(quantity.value).toBe('10');
      expect(query<HTMLInputElement>(fixture, '[data-field="cash"]')[0].value).toBe('250,1');
      type(fixture, `tr[data-row="${SAP}"] [data-field="quantity"]`, '12,5');
      type(fixture, `tr[data-row="${SAP}"] [data-field="cost"]`, '2.500,25');
      click(fixture, 'button[data-action="save"]');
      await settle(fixture);
      const request = expectRequest(HOLDINGS_URL, 'PUT');
      expect(request.request.headers.get('if-match')).toBe('"2"');
      expect(request.request.body).toEqual({
        lines: [
          { isin: SAP, quantity: '12.5', unit: 'pieces', cost_basis_eur: '2500.25', note: 'Kauf' },
          { isin: APPLE, quantity: '3', unit: 'pieces', cost_basis_eur: null, note: null },
        ],
        cash: [{ amount: '250.1' }],
      });
      request.flush({ ...HOLDINGS, version: 3 });
      await settle(fixture);
      expect(text(fixture)).toContain('Gespeichert: Depotstand 3.');
      expect(query(fixture, '[data-editor]')).toHaveLength(0);
      expectRequest(DEPOT, 'GET');
      expectRequest(HISTORY, 'GET');
    });

    it('marks a missing quantity and does not save', async () => {
      const fixture = await render();
      await edit(fixture);
      type(fixture, `tr[data-row="${SAP}"] [data-field="quantity"]`, '');
      click(fixture, 'button[data-action="save"]');
      await settle(fixture);
      expect(query(fixture, '[data-error="quantity"]')[0].textContent).toContain(
        'Die Menge fehlt.',
      );
      http().expectNone((r) => r.method === 'PUT');
    });

    it('says when someone else saved in between and offers to reload', async () => {
      const fixture = await render();
      await edit(fixture);
      click(fixture, 'button[data-action="save"]');
      await settle(fixture);
      expectRequest(HOLDINGS_URL, 'PUT').flush(
        { detail: 'Der Depotstand ist nicht mehr der neueste (aktuell: 3)' },
        { status: 409, statusText: 'Conflict' },
      );
      await settle(fixture);
      expect(query(fixture, '[data-conflict]')[0].textContent).toContain('neueren Depotstand');
      click(fixture, '[data-conflict] button[data-action="reload"]');
      await settle(fixture);
      expectRequest(DEPOT, 'GET');
      expectRequest(HISTORY, 'GET');
      expectRequest(HOLDINGS_URL, 'GET').flush({ ...HOLDINGS, version: 3 });
      await settle(fixture);
      expect(query(fixture, '[data-conflict]')).toHaveLength(0);
    });

    it('adds a security from the search, a bond with nominal value', async () => {
      const fixture = await render();
      await edit(fixture);
      type(fixture, '[data-field="search"]', 'bund');
      await settle(fixture);
      http()
        .expectOne((r) => r.urlWithParams === '/api/v1/securities/search?q=bund')
        .flush([
          {
            isin: 'DE0001102580',
            name: 'Bund 2033',
            asset_class: 'bond',
            listings: [],
            source: 'catalog',
          },
          { isin: null, name: 'Bund ETF', asset_class: 'etf', listings: [], source: 'yahoo' },
        ]);
      await settle(fixture);
      const hits = query(fixture, '[data-hits] button[data-action="add"]') as HTMLButtonElement[];
      expect(hits[1].disabled).toBe(true); // ohne ISIN
      hits[0].click();
      await settle(fixture);
      const row = query(fixture, 'tr[data-row="DE0001102580"]')[0];
      expect(row.textContent).toContain('Bund 2033');
      expect(row.querySelector<HTMLSelectElement>('[data-field="unit"]')?.value).toBe('nominal');
    });

    it('keeps the input when the depot reloads in between, e.g. after renaming', async () => {
      const fixture = await render();
      await edit(fixture);
      type(fixture, `tr[data-row="${SAP}"] [data-field="quantity"]`, '99');
      (fixture.componentInstance as unknown as { reload(): void }).reload();
      await respond(fixture, DEPOT, { ...DETAIL, name: 'Rente' });
      await respond(fixture, HISTORY, ENTRIES);
      const quantity = query<HTMLInputElement>(
        fixture,
        `tr[data-row="${SAP}"] [data-field="quantity"]`,
      )[0];
      expect(quantity.value).toBe('99');
    });

    it('removes a position', async () => {
      const fixture = await render();
      await edit(fixture);
      click(fixture, `tr[data-row="${APPLE}"] button[data-action="remove"]`);
      expect(query(fixture, `tr[data-row="${APPLE}"]`)).toHaveLength(0);
    });

    it('discards the changes', async () => {
      const fixture = await render();
      await edit(fixture);
      click(fixture, 'button[data-action="discard"]');
      expect(query(fixture, '[data-editor]')).toHaveLength(0);
      expect(query(fixture, `tr[data-position="${SAP}"]`)).toHaveLength(1);
    });
  });

  describe('file', () => {
    const PREVIEW: ImportPreview = {
      base_version: 2,
      entries: [
        {
          isin: SAP,
          status: 'changed',
          before: { isin: SAP, quantity: '10', unit: 'pieces', cost_basis_eur: null, note: null },
          after: { isin: SAP, quantity: '12.5', unit: 'pieces', cost_basis_eur: null, note: null },
          pending: false,
        },
        {
          isin: APPLE,
          status: 'removed',
          before: { isin: APPLE, quantity: '3', unit: 'pieces', cost_basis_eur: null, note: null },
          after: null,
          pending: false,
        },
      ],
      rejected: [],
    };

    async function choose(fixture: Fixture, content: string): Promise<void> {
      const input = query<HTMLInputElement>(fixture, '[data-field="file"]')[0];
      const file = new File([content], 'depot.csv', { type: 'text/csv' });
      Object.defineProperty(input, 'files', { value: [file], configurable: true });
      input.dispatchEvent(new Event('change'));
      await settle(fixture);
    }

    it('links the download of the positions', async () => {
      const fixture = await render();
      const link = query(fixture, 'a[data-action="csv"]')[0];
      expect(link.getAttribute('href')).toBe('/api/v1/depots/3/holdings/csv');
      expect(link.hasAttribute('download')).toBe(true);
    });

    it('shows the comparison and applies it with If-Match', async () => {
      const fixture = await render();
      await choose(fixture, `${SAP};12,5\n`);
      const preview = expectRequest('/api/v1/depots/3/import/preview', 'POST');
      expect(preview.request.body).toEqual({
        filename: 'depot.csv',
        content_base64: btoa(`${SAP};12,5\n`),
      });
      preview.flush(PREVIEW);
      await settle(fixture);
      expect(query(fixture, '[data-summary]')[0].textContent?.replace(/\s+/g, ' ')).toContain(
        '0 neu, 1 geändert, 0 gleich, 1 entfällt, 0 nicht erkannt',
      );
      expect(query(fixture, `tr[data-entry="${APPLE}"]`)[0].textContent).toContain('entfällt');
      click(fixture, 'button[data-action="apply"]');
      await settle(fixture);
      const apply = expectRequest('/api/v1/depots/3/import', 'POST');
      expect(apply.request.headers.get('if-match')).toBe('"2"');
      apply.flush({ ...HOLDINGS, version: 3, source: 'import' });
      await settle(fixture);
      expect(text(fixture)).toContain('Datei übernommen: Depotstand 3.');
      expectRequest(DEPOT, 'GET');
      expectRequest(HISTORY, 'GET');
    });

    it('does not apply a file with rejected rows', async () => {
      const fixture = await render();
      await choose(fixture, 'kaputt;1\n');
      expectRequest('/api/v1/depots/3/import/preview', 'POST').flush({
        ...PREVIEW,
        rejected: [{ line: 1, reason: "Keine gueltige ISIN: 'kaputt'" }],
      });
      await settle(fixture);
      expect(query(fixture, '[data-rejected]')[0].textContent).toContain(
        'Zeile 1: Keine gueltige ISIN',
      );
      expect(query<HTMLButtonElement>(fixture, 'button[data-action="apply"]')[0].disabled).toBe(
        true,
      );
    });

    it('names the reason when the file is not readable', async () => {
      const fixture = await render();
      await choose(fixture, 'x');
      expectRequest('/api/v1/depots/3/import/preview', 'POST').flush(
        { detail: 'Die Datei enthaelt keine Position' },
        { status: 422, statusText: 'x' },
      );
      await settle(fixture);
      expect(text(fixture)).toContain('Die Datei enthaelt keine Position');
    });

    it('encodes any file as base64', async () => {
      const bytes = new Uint8Array([0xef, 0xbb, 0xbf, 0x41, 0xe4]);
      expect(await fileBase64(new Blob([bytes]))).toBe(btoa(String.fromCharCode(...bytes)));
    });
  });

  describe('archive', () => {
    it('asks first and archives', async () => {
      const fixture = await render();
      click(fixture, 'button[data-action="archive"]');
      await settle(fixture);
      document
        .querySelector<HTMLButtonElement>('mat-dialog-container button[data-action="confirm"]')!
        .click();
      await settle(fixture);
      expectRequest('/api/v1/depots/3/archive', 'POST').flush({ ...DETAIL, status: 'archived' });
      await settle(fixture);
      expect(text(fixture)).toContain('Depot archiviert.');
      expectRequest(DEPOT, 'GET').flush({ ...DETAIL, status: 'archived' });
      expectRequest(HISTORY, 'GET').flush(ENTRIES);
      await settle(fixture);
      expect(query(fixture, '[data-archived-notice]')).toHaveLength(1);
      expect(query(fixture, 'button[data-action="edit"]')).toHaveLength(0);
      expect(query(fixture, 'button[data-action="choose"]')).toHaveLength(0);
    });

    it('restores an archived depot', async () => {
      const fixture = await render({ ...DETAIL, status: 'archived' });
      click(fixture, 'button[data-action="restore"]');
      await settle(fixture);
      expectRequest('/api/v1/depots/3/restore', 'POST').flush(DETAIL);
      await settle(fixture);
      expect(text(fixture)).toContain('Depot wiederhergestellt.');
    });
  });

  it('explains every control, header and badge (tests 1 and 2)', async () => {
    const fixture = await render();
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(headersWithoutScope(fixture)).toEqual([]);
    expect(abbreviationsWithoutExplanation(fixture)).toEqual([]);
    await edit(fixture);
    expect(controlsWithoutTooltip(fixture)).toEqual([]);
    expect(headersWithoutScope(fixture)).toEqual([]);
  });
});
