# v4/gateway-unify

Owner: <session / person> - Started: 2026-11-12 - Base: origin/v4-on-main (ab60bba7f) - Status: in progress

## Purpose
V4.0.0 blocker 1 (gateways): one shared set of gateway primitives for every cloud, and a real invoke data plane for AWS REST API v1 (which previously had routing + integrations but no auth/key/quota enforcement and no host-style reachability).

## Architecture
core/gateway_common.py (Throttle, window_take, jwt_validate, make_rs256_verifier, strip_hop, build_backend_url, default_http_fetch) <- imported by core/apigatewayv2_gateway.py, providers/aws_apigatewayv2_gateway.py, core/gcp_apigateway_gateway.py, core/azure_apim_gateway_core.py, core/apigateway_core.py. core/apigateway_gateway.py enforces stage throttle, authorizers, API key + usage plan for v1; core/aws_wire_router.py apigw-invoke branch sends REST ids there.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| <what was chosen> | <what was not> | <reason> |

## Open issues
- [ ] <unfinished, unverified or deferred item> (owner: <who>)

## Testing
<what was run, where (Nano on :8099 / headless Docker), and the result; what was NOT run>
