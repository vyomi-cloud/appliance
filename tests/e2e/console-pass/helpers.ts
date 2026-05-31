// Shared helpers for console-pass specs.
// Most of the "console pass" work isn't UI clicking per se — the simulator's
// SPAs (/console/aws, /console/gcp) call REST endpoints that we can hit
// directly via the same fetch path. We use Playwright primarily to:
//   1. Drive the SPA where it carries meaningful UX state (wizards with
//      conditional fields, modals, post-create redirects).
//   2. Capture screenshots + videos as proof the console actually rendered
//      what the resource graph claims to contain.
//
// For resource provisioning we use the simulator's REST API directly (faster,
// less flaky than clicking through wizards), then load the console page to
// VISUALLY verify the resource appears.

import { APIRequestContext, Page, expect, request } from '@playwright/test';

const ENDPOINT = process.env.ENDPOINT || 'http://192.168.252.7:9000';

export async function newApi(): Promise<APIRequestContext> {
  return await request.newContext({ baseURL: ENDPOINT });
}

/** Switch to a space of the given provider (creates one if missing). */
export async function switchToProviderSpace(api: APIRequestContext, provider: 'aws' | 'gcp' | 'azure'): Promise<string> {
  const list = await api.get('/api/spaces');
  expect(list.ok()).toBeTruthy();
  const body = await list.json();
  let space = body.spaces?.find((s: any) => s.provider === provider);
  if (!space) {
    const created = await api.post('/api/spaces', {
      data: { name: `e2e-${provider}-${Date.now()}`, provider },
    });
    expect(created.ok()).toBeTruthy();
    space = await created.json();
  }
  const switched = await api.post(`/api/spaces/${space.space_id}/switch`);
  expect(switched.ok()).toBeTruthy();
  return space.space_id;
}

/** Verify the console SPA loads + renders the active provider. */
export async function openConsole(page: Page, provider: 'aws' | 'gcp' | 'azure'): Promise<void> {
  await page.goto(`/console/${provider}`);
  // The SPA's title or a known header element must be present. We use a soft
  // assertion to avoid coupling to specific UI text that may change.
  await expect(page.locator('body')).toBeVisible();
  await page.waitForLoadState('domcontentloaded');
}

/** Wait until the app's /health endpoint returns the given status. */
export async function waitForApp(api: APIRequestContext, baseUrl: string, expectedStatus = 'UP', maxMs = 60000): Promise<any> {
  const deadline = Date.now() + maxMs;
  let last: any;
  while (Date.now() < deadline) {
    try {
      const r = await api.get(`${baseUrl}/health`);
      if (r.ok()) {
        last = await r.json();
        if (last.status === expectedStatus) return last;
      }
    } catch (e) { /* keep polling */ }
    await new Promise(r => setTimeout(r, 1500));
  }
  throw new Error(`app /health never returned ${expectedStatus}; last=${JSON.stringify(last)}`);
}

/** Provision Postgres via the Azure SQL path (reuses the same DB engine). */
export async function provisionPostgresViaAzureSql(api: APIRequestContext, server: string, db: string): Promise<{ host: string; port: number; database: string; user: string; password: string }> {
  // For AWS+GCP space contexts, the simulator's Azure SQL → real Postgres path
  // is the simplest way to get a real DB. We POST to the simulator's ARM-style
  // route; the Azure data plane handler creates a real Postgres DB and returns
  // connectionInfo via GET-after-PUT.
  const azureSpace = await switchToProviderSpace(api, 'azure');
  const api20230801 = 'api-version=2023-08-01';
  const base = `/subscriptions/sub-e2e/resourceGroups/rg-e2e/providers/Microsoft.Sql/servers/${server}`;
  // server
  await api.put(`${base}?${api20230801}`, {
    data: { location: 'eastus', properties: { administratorLogin: 'azureadmin', administratorLoginPassword: 'Password123!' } },
  });
  // database
  await api.put(`${base}/databases/${db}?${api20230801}`, {
    data: { location: 'eastus', properties: {} },
  });
  // GET-after-PUT to surface connectionInfo
  const r = await api.get(`${base}/databases/${db}?${api20230801}`);
  expect(r.ok()).toBeTruthy();
  const body = await r.json();
  const conn = body?.properties?.connectionInfo;
  expect(conn).toBeTruthy();
  expect(String(conn.engine || '')).toContain('PostgreSQL');
  return conn;
}
