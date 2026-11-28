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

## Open issues
- No simulator data plane exists for: ELB (`DNSName`), CloudFront (`DomainName`), ECR registry (`/v2/`), DAX, Cloud Run `*.run.app`; a rewritten URL would not work, so they keep the realistic name until a data plane is built.
- Not bridged: Redshift, ElastiCache/Memorystore, Azure SQL (MSSQL), Cosmos.
- Original note (display-format question) below.
- Hostname-style endpoints with no simulator route yet (RDS/Redshift/OpenSearch/ELB/CloudFront/ECR/DAX, Cloud Run `*.run.app`, Azure blob/Service Bus/SQL hosts): display format undecided (`<tunnel-host>:<port>` vs realistic name + "connect via" hint).
