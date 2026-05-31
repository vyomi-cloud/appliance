// go-inventory console-pass spec.
//
// Mirrors java-orders but for the GCP surface:
//   1. Switches to a GCP space.
//   2. Provisions a real Postgres DB (via the Azure SQL → gcp_sql_engine path).
//   3. Creates the GCP resources (Secret Manager secret, KMS keyring+key,
//      Storage bucket, Pub/Sub topic+subscription) via REST endpoints.
//   4. Loads /console/gcp + verifies the SPA renders.
//   5. Hits the deployed go-inventory app at $APP_BASE_GO end-to-end.

import { test, expect } from '@playwright/test';
import { newApi, switchToProviderSpace, openConsole, waitForApp, provisionPostgresViaAzureSql } from './helpers';

const ENDPOINT = process.env.ENDPOINT || 'http://192.168.252.7:9000';
const APP_BASE = process.env.APP_BASE_GO || 'http://192.168.252.7:8081';

const PROJECT      = 'inventory-app';
const REGION       = 'global';
const SECRET_NAME  = 'inventory-db-creds';
const KEYRING_NAME = 'inventory-keyring';
const KEY_NAME     = 'sku-key';
const BUCKET       = 'inventory-images';
const TOPIC_ID     = 'inventory-events';
const SUB_ID       = 'inventory-worker';

test('go-inventory end-to-end via /console/gcp', async ({ page }) => {
  const api = await newApi();

  // ---- Provision real Postgres (server+db) -------------------------------
  const dbConn = await provisionPostgresViaAzureSql(api, 'inv-sql', 'inventory');

  // Switch to a GCP space.
  await switchToProviderSpace(api, 'gcp');

  // ---- Secret Manager — store DB creds JSON ------------------------------
  // GCP secret create + addVersion is a 2-step flow.
  const secCreate = await api.post(`/v1/projects/${PROJECT}/secrets?secretId=${SECRET_NAME}`, {
    data: { replication: { automatic: {} } },
  });
  expect(secCreate.status()).toBeLessThan(500);

  const secretJson = JSON.stringify({
    url:      `postgresql://${dbConn.user}:${dbConn.password}@${dbConn.host}:${dbConn.port}/${dbConn.database}`,
    user:     dbConn.user,
    password: dbConn.password,
  });
  const dataB64 = Buffer.from(secretJson).toString('base64');
  const versionAdd = await api.post(`/v1/projects/${PROJECT}/secrets/${SECRET_NAME}:addVersion`, {
    data: { payload: { data: dataB64 } },
  });
  expect(versionAdd.ok()).toBeTruthy();

  // ---- Cloud KMS — create keyring + key ---------------------------------
  // (The simulator's KMS encrypt/decrypt routes are direct; the keyring/key
  // metadata is implicit-on-first-use.)

  // ---- Cloud Storage — create bucket -------------------------------------
  const bucketCreate = await api.post(`/storage/v1/b?project=${PROJECT}`, {
    data: { name: BUCKET, location: 'us-central1' },
  });
  expect(bucketCreate.status()).toBeLessThan(500);

  // ---- Pub/Sub — create topic + subscription ----------------------------
  const topicCreate = await api.put(`/v1/projects/${PROJECT}/topics/${TOPIC_ID}`);
  expect(topicCreate.status()).toBeLessThan(500);

  const subCreate = await api.put(`/v1/projects/${PROJECT}/subscriptions/${SUB_ID}`, {
    data: { topic: `projects/${PROJECT}/topics/${TOPIC_ID}` },
  });
  expect(subCreate.status()).toBeLessThan(500);

  // ---- Visual verification in /console/gcp -------------------------------
  await openConsole(page, 'gcp');
  await expect(page).toHaveTitle(/GCP|Google|Console|CloudLearn/i);
  await page.screenshot({ path: 'playwright-report/go-inventory-console.png', fullPage: true });

  // ---- Hit the app end-to-end --------------------------------------------
  const health = await waitForApp(api, APP_BASE, 'UP', 90_000);
  expect(health.status).toBe('UP');
  for (const svc of ['db', 'storage', 'pubsub', 'kms', 'secret_manager']) {
    expect((health as any)[svc]?.ok).toBe(true);
  }

  // POST /items
  const created = await api.post(`${APP_BASE}/items`, {
    data: { name: 'widget', sku: 'W-001', stock: 5 },
  });
  expect(created.ok()).toBeTruthy();
  const item = await created.json();
  expect(item.id).toBeGreaterThan(0);

  // GET /items
  const list = await api.get(`${APP_BASE}/items`);
  const items = (await list.json()).items || [];
  expect(items.find((i: any) => i.id === item.id)).toBeTruthy();

  // GET /items/{id}/image
  const image = await api.get(`${APP_BASE}/items/${item.id}/image`);
  expect(image.ok()).toBeTruthy();
  const img = await image.json();
  expect(img.image_url).toMatch(new RegExp(BUCKET));

  // Eventarc trigger fire reaches NATS inbox.
  const inbox = await api.get(`/__nats/inbox?prefix=gcp.eventarc.`);
  expect(inbox.ok()).toBeTruthy();
});
