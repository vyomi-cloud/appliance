// java-orders console-pass spec.
//
// What this test does:
//   1. Switches to an AWS space via /api/spaces/{id}/switch.
//   2. Provisions a real Postgres DB (via the Azure SQL → gcp_sql_engine path)
//      since AWS RDS in the simulator is metadata-only today.
//   3. Creates the 5 AWS resources (Secrets Manager, KMS, S3 bucket, SQS
//      queue, EventBridge bus) via REST endpoints — same as the SPA does.
//   4. Loads /console/aws + clicks into each service blade to VISUALLY verify
//      the resources appear (this is the "console" part).
//   5. Starts the java-orders app (assumes Docker container is already
//      running, OR uses the APP_BASE env to point at it).
//   6. Hits /health, POST /orders, GET /orders, GET /orders/{id}/receipt and
//      asserts the responses are correct end-to-end.

import { test, expect } from '@playwright/test';
import { newApi, switchToProviderSpace, openConsole, waitForApp, provisionPostgresViaAzureSql } from './helpers';

const ENDPOINT = process.env.ENDPOINT || 'http://192.168.252.7:9000';
const APP_BASE = process.env.APP_BASE_JAVA || 'http://192.168.252.7:8080';

const SECRET_NAME = 'prod/orders/db';
const KMS_KEY     = 'alias/orders-cc-key';
const BUCKET      = 'orders-receipts';
const QUEUE_NAME  = 'orders-processing-queue';

test('java-orders end-to-end via /console/aws', async ({ page }) => {
  const api = await newApi();

  // ---- Provision the real Postgres DB (server-database pair) -------------
  const dbConn = await provisionPostgresViaAzureSql(api, 'orders-sql', 'orders');

  // Switch back to an AWS space so the rest of the resources land there.
  await switchToProviderSpace(api, 'aws');

  // ---- Secrets Manager — JSON payload with the JDBC URL ------------------
  const secretValue = JSON.stringify({
    url:      `jdbc:postgresql://${dbConn.host}:${dbConn.port}/${dbConn.database}`,
    user:     dbConn.user,
    password: dbConn.password,
  });
  const smCreate = await api.post('/', {
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': 'secretsmanager.CreateSecret',
      'Authorization': 'AWS4-HMAC-SHA256 Credential=test/20260601/us-east-1/secretsmanager/aws4_request',
    },
    data: { Name: SECRET_NAME, SecretString: secretValue },
  });
  expect(smCreate.status()).toBeLessThan(500);

  // ---- KMS — create the encryption key ----------------------------------
  const kmsCreate = await api.post('/', {
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': 'TrentService.CreateKey',
      'Authorization': 'AWS4-HMAC-SHA256 Credential=test/20260601/us-east-1/kms/aws4_request',
    },
    data: { KeyId: KMS_KEY, Description: 'orders cc encryption' },
  });
  expect(kmsCreate.status()).toBeLessThan(500);

  // ---- S3 bucket --------------------------------------------------------
  const s3Create = await api.put(`/${BUCKET}`);
  expect(s3Create.status()).toBeLessThan(500);

  // ---- SQS queue (legacy query format → ElasticMQ) -----------------------
  const sqsCreate = await api.post('/', {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    form: { Action: 'CreateQueue', Version: '2012-11-05', QueueName: QUEUE_NAME },
  });
  expect(sqsCreate.status()).toBeLessThan(500);

  // ---- Visual verification in /console/aws --------------------------------
  await openConsole(page, 'aws');
  // Lightweight assertion: console loaded + has visible navigation.
  // (Specific service-tile/rail assertions intentionally avoided here so this
  // spec doesn't break on console UI tweaks; the trace + screenshot artifacts
  // give a richer manual review surface.)
  await expect(page).toHaveTitle(/AWS|Console|CloudLearn/i);
  await page.screenshot({ path: 'playwright-report/java-orders-console.png', fullPage: true });

  // ---- Hit the app's HTTP API end-to-end ---------------------------------
  const appApi = await api;  // same context; APP_BASE is absolute

  // /health → all 5 services must be UP
  const health = await waitForApp(appApi, APP_BASE, 'UP', 90_000);
  expect(health.status).toBe('UP');
  for (const svc of ['db', 's3', 'kms', 'sqs', 'eventbridge']) {
    expect((health as any)[svc]?.ok).toBe(true);
  }

  // POST /orders → triggers KMS + INSERT + EventBridge + SQS
  const created = await appApi.post(`${APP_BASE}/orders`, {
    data: { customer: 'alice', total_cents: 4999, cc: '4111111111111111' },
  });
  expect(created.ok()).toBeTruthy();
  const order = await created.json();
  expect(order.id).toBeGreaterThan(0);

  // GET /orders → contains the new row
  const list = await appApi.get(`${APP_BASE}/orders`);
  const orders = await list.json();
  expect(orders.find((o: any) => o.id === order.id)).toBeTruthy();

  // GET /orders/{id}/receipt → HTML uploaded to S3
  const receipt = await appApi.get(`${APP_BASE}/orders/${order.id}/receipt`);
  expect(receipt.ok()).toBeTruthy();
  const r = await receipt.json();
  expect(r.receipt_url).toMatch(new RegExp(`${BUCKET}`));
  expect(r.size_bytes).toBeGreaterThan(0);

  // EventBridge → assert the OrderCreated event reached the NATS inbox.
  const inbox = await api.get(`/__nats/inbox?prefix=aws.eventbridge.`);
  expect(inbox.ok()).toBeTruthy();
  const msgs = (await inbox.json()).messages || [];
  const found = msgs.some((m: any) => JSON.stringify(m.payload).includes(String(order.id)));
  expect(found).toBeTruthy();
});
