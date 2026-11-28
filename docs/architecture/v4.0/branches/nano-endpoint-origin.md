# v4/nano-endpoint-origin

**Goal:** the in-browser Nano console must show simulator URLs (the local relay), never the real cloud host.

**Bug (reported on v4.1.2):** SQS queue detail showed `https://sqs.us-east-1.amazonaws.com/123456789012/<queue>`. Reproduced on the 4.1.2 Nano bundle: `CreateQueue`, `GetQueueUrl` and `ListQueues` all returned the AWS host.

**Cause:** `wasm/sw.js` `handleWire` forwards the request headers to the router, but a service worker never sees `Host`, so `core/public_origin.origin()` was empty and `core/sqs_core.py` (and every other `origin() or <real host>` site) fell back to the real host. `scripts/check_endpoint_urls.py` probes the router directly with a Host header, so it could not catch this path.

**Fix:** `handleWire` sets `x-forwarded-host: 127.0.0.1:8090` / `x-forwarded-proto: http` when absent (the same address `consoles/src/common/connect.js` `sdkEndpoint()` gives for Nano). Requests that already carry `x-forwarded-host` are untouched.

**Test:** `wasm/ui-tests/nano-endpoint-origin.mjs` (suite `nano-ui-aws-endpoint-origin`): QueueUrl is not `amazonaws.com`, is on the relay, matches across Create/Get/List, and round-trips into `GetQueueAttributes` and `SendMessage`.

**Not verified:** other services' URLs on Nano (SNS, API Gateway, GCS, ...) share the same origin source and should now follow, but only SQS is asserted. In-page console features that fetch such a URL from the browser (cross-origin to the relay) were not checked.
