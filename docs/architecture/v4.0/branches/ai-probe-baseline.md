# v4/ai-probe-baseline

Owner: AI enterprise session (Sudhir) - Started: 2026-11-15 - Base: origin/v4-on-main (770a9814a) - Status: Phase 0 measurement, not merged

## Purpose
Phase 0 of `docs/architecture/v4.0/AI-ENTERPRISE-REFERENCE-PLAN.md` (branch `v4/ai-enterprise-reference-plan`): replace "read from code" claims with measured ones, for all three clouds.

## What is here
- `tools/ai_probe/aws_inventory.*`, `aws_probe.py`: cherry-picked from `v4/ai-sdk-probe` (9ae54466b), now on current trunk.
- `tools/ai_probe/aws_probe_2026-11-15.csv`: fresh AWS run (1632 ops): 145 ok, 415 modeled error, 1020 unimplemented, 52 probe_error = **34.3% routed** (was 37.7% on 2026-11-14). Only S3 differs (103 -> 47 routed) because MinIO was unreachable in this run; the other 26 services are identical, so there is no real regression outside S3. Re-run S3 with MinIO up for a true number.
- `tools/ai_probe/gcp_inventory.py|csv`: 2298 REST methods from Google discovery documents (aiplatform 1144, discoveryengine 278, logging 254, iam 137, cloudkms 87, run 59, monitoring 56, identitytoolkit 50, eventarc 66, pubsub 46, documentai 42, apigateway 30, cloudfunctions 21, modelarmor 15, workflows 11, cloudtrace 2).
- `tools/ai_probe/azure_inventory.py|csv`: 1611 operations from azure-rest-api-specs (APIM 672, ML 217, Event Grid 170, Cognitive Services 146, Logic 106, ...).

## GCP probe result (2026-11-15, `tools/ai_probe/gcp_probe.py`, `gcp_probe.csv`)
REST-level probe of the 2298 inventory methods against the offline wire path as the simulator's active project: **56.3% routed** (216 ok, 1077 modeled error, 1005 unimplemented).
Per service routed: pubsub 100%, logging 98%, cloudfunctions 95%, iam 88%, monitoring 82%, run 80%, apigateway 67%, cloudkms 64%, eventarc 52%, aiplatform 51% (1144 methods, the biggest block), workflows 45%, documentai 40%, discoveryengine 14%, modelarmor 13%, identitytoolkit 6%.
Caveat: GCP APIs are resolved by PATH, so APIs sharing a path shape can be answered by the wrong engine, and generic JSON catch-alls overstate coverage (logging 98% looks high). Read per-service numbers as an upper bound.
**Bug found and fixed:** `core/gcp_agentengine_core.py` crashed with an unhandled AttributeError (HTTP 500) on 62 requests that reached the engine but missed its path regex (reasoningEngines sub-resources: runtimeRevisions, sandboxEnvironmentTemplates, ...). Now a modeled 404 NOT_FOUND (core + wasm mirror). Test: `tests/conformance/test_gcp_agentengine_unmatched_path.py` (fails before, passes after). Routed 53.6% -> 56.3%.

## Known gaps
- Azure: `openai-v1-data` returned 0 operations (TypeSpec-generated layout; needs the emitted swagger path) and Azure OpenAI/Foundry are thin. Foundry agents data-plane has 42 ops, projects 29.
- GCP has a REST probe (not the real SDK). Azure has an INVENTORY only, not a probe yet.
- The AWS probe measures "routed and answered with the right wire format", not semantics.

## Run
`PYTHONPATH=. /private/tmp/ai-probe-venv13/bin/python tools/ai_probe/aws_probe.py --out <csv>` (py3.13 venv with requirements.txt + boto3/botocore==1.43.18).
