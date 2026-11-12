# v4/mesh-gateway-eventbus-ready

Owner: <session / person> - Started: 2026-11-12 - Base: origin/v4-on-main (2a48912d7) - Status: in progress

## Purpose
Make the v4.0.0 shared gateway + event-bus backends provably work on the REAL appliance stack (what Mesh runs), not only on Nano / the dev server.

## Architecture
`routes/gateway_eventbus_unified.py` (registered first in server.py) routes GCP API Gateway / API Keys v2 / Eventarc native paths, `/gcpgw/<id>`, any
`*.gateway.dev` Host, `{id}.execute-api.*` Host and the Azure APIM data plane to the same AwsWireRouter Nano uses. Supporting fixes: router GCP project =
the appliance's (core/wire_ingress), Cloud Run slot pinned to its provider (routes/gcp_run), GCS + Pub/Sub events feed the Eventarc core, dead-letter publish
under the GCP provider, REST v1 `/apigw/<id>/<stage>` handoff, JWKS fetch honours VYOMI_GATEWAY_BACKEND_OVERRIDES. Test: tests/conformance/nightly/gcp-gateway-eventbus-real.mjs. Runbook: MESH-GATEWAY-EVENTBUS-RUNBOOK.md.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| New early route module delegating to the Nano router | Rewrite legacy handlers one by one | One engine, same behaviour on Nano and appliance |
| Operator override hook also covers JWKS | self-signed https JWKS | control plane needs https; hook is explicit, opt-in |

## Open issues
- [ ] Mesh image must be rebuilt/published by the owner (stale image lacks all of this)
- [ ] Legacy Cloud SQL validation (3 gcp-validation cases) fails on the real appliance: pre-existing, not touched
