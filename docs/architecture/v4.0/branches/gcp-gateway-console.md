# v4/gcp-gateway-console

Owner: gcp-gateway-console session - Started: 2026-11-12 - Base: origin/v4-on-main (ab60bba7f) - Status: in progress

## Purpose
GCP API Gateway v4 console on top of the data plane: invoke URLs + curl, a Try-it panel that sends real requests through the gateway, an API keys page (API Keys v2), config security/quota display; round-trip + validation tests; Nano forwarding design spike.

## Architecture
consoles/src/gcp/services/apigateway/{TryIt,ApiKeys,Policy}.jsx + api.js; control plane adds a `policy` extension on config GET (core/gcp_apigateway_core.py describe_policy). Try-it uses the same-origin wire `/_wire/gcpgw/<id>/...`. See GATEWAY-NANO-FORWARDING.md.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| policy parsed server-side and returned on config GET | YAML parser in the console | console has no YAML dep; control plane already parses+validates |

## Open issues
- [ ] Nano backend forwarding not built (see GATEWAY-NANO-FORWARDING.md)
- [ ] relay CORES fix untested in a real browser
- [ ] path-style URL shown is the wire form (<origin>/_wire/gcpgw/<id>); root /gcpgw/ on a real appliance not verified

## Testing
dev_server: gcp-v4-roundtrip ONLY=apigateway,apigateway-apis,apigateway-keys 27/27; gcp-validation 46/46; test_gcp_apigateway_core/gateway PASS. NOT run: Nano :8099, real appliance, other roundtrip services.
