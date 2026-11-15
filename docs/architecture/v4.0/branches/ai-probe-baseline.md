# v4/ai-probe-baseline

Owner: AI enterprise session (Sudhir) - Started: 2026-11-15 - Base: origin/v4-on-main (770a9814a) - Status: Phase 0 measurement, not merged

## Purpose
Phase 0 of `docs/architecture/v4.0/AI-ENTERPRISE-REFERENCE-PLAN.md` (branch `v4/ai-enterprise-reference-plan`): replace "read from code" claims with measured ones, for all three clouds.

## What is here
- `tools/ai_probe/aws_inventory.*`, `aws_probe.py`: cherry-picked from `v4/ai-sdk-probe` (9ae54466b), now on current trunk.
- `tools/ai_probe/aws_probe_2026-11-15.csv`: fresh AWS run (1632 ops): 145 ok, 415 modeled error, 1020 unimplemented, 52 probe_error = **34.3% routed** (was 37.7% on 2026-11-14). Only S3 differs (103 -> 47 routed) because MinIO was unreachable in this run; the other 26 services are identical, so there is no real regression outside S3. Re-run S3 with MinIO up for a true number.
- `tools/ai_probe/gcp_inventory.py|csv`: 2298 REST methods from Google discovery documents (aiplatform 1144, discoveryengine 278, logging 254, iam 137, cloudkms 87, run 59, monitoring 56, identitytoolkit 50, eventarc 66, pubsub 46, documentai 42, apigateway 30, cloudfunctions 21, modelarmor 15, workflows 11, cloudtrace 2).
- `tools/ai_probe/azure_inventory.py|csv`: 1611 operations from azure-rest-api-specs (APIM 672, ML 217, Event Grid 170, Cognitive Services 146, Logic 106, ...).

## Known gaps
- Azure: `openai-v1-data` returned 0 operations (TypeSpec-generated layout; needs the emitted swagger path) and Azure OpenAI/Foundry are thin. Foundry agents data-plane has 42 ops, projects 29.
- GCP and Azure have an INVENTORY only, not a probe yet: probing needs each cloud's real SDK against the offline wire path.
- The AWS probe measures "routed and answered with the right wire format", not semantics.

## Run
`PYTHONPATH=. /private/tmp/ai-probe-venv13/bin/python tools/ai_probe/aws_probe.py --out <csv>` (py3.13 venv with requirements.txt + boto3/botocore==1.43.18).
