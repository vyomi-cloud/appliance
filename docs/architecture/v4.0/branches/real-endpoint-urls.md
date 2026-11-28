# v4/real-endpoint-urls

**Goal:** every URL / connection string the simulator hands out points at the simulator (the host the client reached, incl. a tunnel), never at the real cloud (e.g. SQS `QueueUrl` was `https://sqs.us-east-1.amazonaws.com/...` on Nano).

## Architecture
- `core/public_origin.py` (ContextVar, stdlib, vendored to Nano): set per request by `AwsWireRouter.handle` and the offline middleware from `X-Forwarded-Host`/`Host` + `X-Forwarded-Proto`; cores call `origin()` and fall back to the real hostname only with no request.
- Done (SDK-verified in `scripts/check_endpoint_sdk.py`): Azure Storage `primaryEndpoints` (blob/queue/table, path-style `/azure-data/<svc>/<acct>/`, only when empty and no `VYOMI_AZURE_STORAGE_SUFFIX`), OpenSearch domain `Endpoint` + serverless collection endpoints (data plane is the origin root).
- Done: SQS QueueUrl (+ console list recomputed live, not the stored create-time value), SNS signing/unsubscribe URLs, API Gateway `invokeUrl` + OpenAPI export, GCS `selfLink`/`mediaLink`.
- Offline SQS already used `request_base()` via the `queue_url_for` hook; that hook still wins.

## Release check
`scripts/check_endpoint_urls.py` (wired into `release-checks.yml`): runtime probe through the router with a tunnel Host + a ratchet (`scripts/endpoint_urls.baseline.json`) so no file gains a hardcoded real-cloud URL. Lower the baseline with `--update` after each fix.

## Design decisions
- Path-addressable endpoints (SQS, SNS, API GW, GCS) -> `<origin>/<path>`.
- Control-plane identifiers (Cloud SQL/Compute selfLinks, `cloudfront.amazonaws.com/2020-05-31` Location headers) stay: clients treat them as ids.

## Already working (not touched)
- Databases: `vyomi-tunnel` `db-tcp` bridge (RDS + Cloud SQL, Postgres/MySQL) and `DbConnect.jsx` show `postgresql://user:pw@127.0.0.1:5432/db`; Service Bus over the tunnel's `amqp` bridge; EC2/GCE/Azure VMs over `vm-tcp` SSH.

## Data planes added so the URL works through the tunnel (all SDK/HTTP-verified by `scripts/check_endpoint_sdk.py`)
- ECR: `repositoryUri` / `proxyEndpoint` / `downloadUrl` = request host (the registry `/v2/` API already served any host for `AWS:<token>`).
- Cosmos: ARM `documentEndpoint` + `listConnectionStrings` AccountEndpoint = origin (SQL API is served at the origin root).
- CloudFront: `DomainName` = `<host>/_cf/<distId>`; `cloudfront_dist_core.edge()` serves GET/HEAD from the S3 origin (cache behavior by PathPattern, OriginPath, DefaultRootObject). Custom origins answer 502 with the reason.
- ALB: `DNSName` = `<host>/_elb/<name>`; `elbv2_core.serve()` evaluates listener rules (path/host/method/header/query) -> fixed-response / redirect / forward to a LAMBDA target group. Instance/ip targets answer 503 (no network path).
- Cloud Run: `*.run.app` -> `<origin>/_run/<region>/<svc>-<projnum>` (response rewrite `gcp_run_core.public_urls`); `serve()` -> `invoke_service` (IAM invoker check; Python-source runs, container images answer 202 + reason).

## Known gaps (no data plane in the simulator; listed in every release report)
- DAX (proprietary protocol), Redshift (no SQL engine), ElastiCache/Memorystore Redis (no engine), Azure SQL (no TDS engine), Service Bus/Key Vault host-style endpoints (tunnel `amqp` bridge / `*.vault.localtest.me` exist).

## Open issues
- GCP control-plane selfLinks (Cloud SQL/Compute/GKE/BigQuery) intentionally unchanged (resource identifiers).


## Round 2 (v4/real-endpoint-urls-2): remaining core lines + console strings
- Core: App Service host names -> `<host>/azure-data/site/<app>` (response rewrite `public_origin.rewrite_app_hosts`), Event Grid blob url, secondaryEndpoints, Cosmos dedicated gateway, Azure OpenAI agent target, Cloud Functions console URL, Infra Manager bucket selfLink.
- Ratchet now separates EXEMPT lines (JWT issuers, audit text, `//svc.googleapis.com/..` names, control-plane selfLinks, internal artifact locations, no-request fallbacks) from KNOWN GAPS (55 lines, no data plane) and also counts bare `location.origin` in `consoles/src`.
- Console (`consoles/src/common/connect.js` `extUrl` / `isNano`): Azure blob/queue/table/website/secondary endpoints, routing endpoints, Cosmos `AccountEndpoint`, Grafana data-source URL, GCP API Gateway invoke base, AgentCore MCP URL + Lambda onboarding prompt use the host the user's CLI reaches (the tunnel on Nano; `/nano/_wire` is a service-worker path). Service Bus SAS connection string on Nano = `Endpoint=sb://127.0.0.1;...;UseDevelopmentEmulator=true;` (tunnel raw AMQP :5672). Bundles rebuilt into `wasm/v4`.
- Left (no engine / no route): Azure SQL `tcp:<server>.database.windows.net` strings, Monitor DCE ingestion endpoints, scm/Kudu host, Bastion/Public-IP FQDNs, DAX, Redshift, RDS `Endpoint.Address` (the console's DbConnect string is the working one), host-style Service Bus/Key Vault outside Nano, `jobRunUri` (internal scheduler target).
