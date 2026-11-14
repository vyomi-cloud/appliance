# v4/ai-sdk-probe

Owner: Claude session (owner: sudhirganti) - Started: 2026-11-14 - Base: origin/v4-on-main (e140a833e) - Status: in progress

## Purpose
Phase 0 of the enterprise AI plan (v4/ai-enterprise-reference-plan): an SDK probe that calls every in-scope AWS operation with the real boto3 client against the offline wire path and records routed/unimplemented, replacing the crude core_mentions column. Tooling only: no core/consoles/wasm changes.

## Architecture
tools/ai_probe/aws_inventory.py|csv (botocore 1.43.18 operation list, 1632 ops, 27 services); tools/ai_probe/aws_probe.py (in-process uvicorn + wire_ingress.appliance_router, boto3 1.43.18, minimal args from input shapes); output aws_probe.csv.

## Design decisions
| Decision | Alternatives rejected | Why |
|---|---|---|
| <what was chosen> | <what was not> | <reason> |

## Open issues
- [ ] GCP/Azure probes; semantic contract tests; 'routed' only means the wire answered in the service format, a catch-all ResourceNotFound would overstate; MinIO unreachable in this run (S3 bytes not exercised) (owner: this session)

## Testing
Full run 2026-11-14 on trunk e140a833e, offline wire path in-process: 1632 ops -> 173 ok, 443 modeled error, 964 unimplemented, 52 probe_error; routed 37.7%. Not run: Docker stack, Nano.
