# v4/real-endpoint-urls

**Goal:** every URL / connection string the simulator hands out points at the simulator (the host the client reached, incl. a tunnel), never at the real cloud (e.g. SQS `QueueUrl` was `https://sqs.us-east-1.amazonaws.com/...` on Nano).

## Architecture
- `core/public_origin.py` (ContextVar, stdlib, vendored to Nano): set per request by `AwsWireRouter.handle` and the offline middleware from `X-Forwarded-Host`/`Host` + `X-Forwarded-Proto`; cores call `origin()` and fall back to the real hostname only with no request.
- Done: SQS QueueUrl (+ console list recomputed live, not the stored create-time value), SNS signing/unsubscribe URLs, API Gateway `invokeUrl` + OpenAPI export, GCS `selfLink`/`mediaLink`.
- Offline SQS already used `request_base()` via the `queue_url_for` hook; that hook still wins.

## Release check
`scripts/check_endpoint_urls.py` (wired into `release-checks.yml`): runtime probe through the router with a tunnel Host + a ratchet (`scripts/endpoint_urls.baseline.json`) so no file gains a hardcoded real-cloud URL. Lower the baseline with `--update` after each fix.

## Design decisions
- Path-addressable endpoints (SQS, SNS, API GW, GCS) -> `<origin>/<path>`.
- Control-plane identifiers (Cloud SQL/Compute selfLinks, `cloudfront.amazonaws.com/2020-05-31` Location headers) stay: clients treat them as ids.

## Open issues
- Hostname-style endpoints with no simulator route yet (RDS/Redshift/OpenSearch/ELB/CloudFront/ECR/DAX, Cloud Run `*.run.app`, Azure blob/Service Bus/SQL hosts): display format undecided (`<tunnel-host>:<port>` vs realistic name + "connect via" hint).
